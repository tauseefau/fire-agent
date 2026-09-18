#!/usr/bin/env python3
"""n8n REST API CLI for Hermes — create/list/update/delete/run workflows.

Reads N8N_BASE_URL + N8N_API_KEY from ~/.hermes/.env (or config.yaml).

Usage:
  n8n.py workflows list
  n8n.py workflows get <id>
  n8n.py workflows create --name "My Flow" --nodes <json> [--connections <json>] [--active true|false]
  n8n.py workflows create-simple --name "X" --node-type n8n-nodes-base.webhook --url-path path --method POST
  n8n.py workflows update <id> --name "..." [--active true|false]
  n8n.py workflows delete <id>
  n8n.py workflows activate <id> | deactivate <id>
  n8n.py executions list   (recent executions)
  n8n.py executions run <workflowId>
  n8n.py tags list
"""
import argparse
import json
import os
import re
import sys
import urllib.request
import urllib.error

BASE = os.environ.get("N8N_BASE_URL", "https://n8n.diyyourdata.com/")
KEY = os.environ.get("N8N_API_KEY", "")
if not KEY:
    # fall back to config.yaml / .env
    try:
        for line in open(os.path.expanduser("~/.hermes/.env")):
            if line.startswith("N8N_API_KEY="):
                KEY = line.split("=", 1)[1].strip()
    except Exception:
        pass
if not KEY:
    try:
        txt = open(os.path.expanduser("~/.hermes/config.yaml")).read()
        m = re.search(r"N8N_API_KEY:\s*[\"']([^\"']+)", txt)
        if m:
            KEY = m.group(1)
        m = re.search(r"N8N_BASE_URL:\s*[\"']([^\"']+)", txt)
        if m:
            BASE = m.group(1)
    except Exception:
        pass


def _req(method, path, body=None):
    url = BASE.rstrip("/") + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("X-N8N-API-KEY", KEY)
    req.add_header("Content-Type", "application/json")
    # Cloudflare (n8n is behind CF) blocks empty / generic UA signatures.
    req.add_header("User-Agent",
                   "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        err = e.read().decode()
        sys.stderr.write("HTTP %d: %s\n" % (e.code, err[:400]))
        sys.exit(1)


def _out(obj):
    print(json.dumps(obj, indent=2, default=str))


def _deref_creds(nodes):
    """Replace any {{$credential(...)}} references with empty placeholders (no-op safety)."""
    return nodes


def simple_flow(name, node_type, url_path=None, method="POST", webhook_id=None, trigger=True):
    """Build a minimal workflow JSON with an optional trigger + one node."""
    nodes = []
    if trigger:
        nodes.append({
            "parameters": {},
            "id": "trigger-1", "name": "When triggered",
            "type": "n8n-nodes-base.manualTrigger",
            "typeVersion": 1, "position": [0, 0],
        })
    params = {}
    if url_path:
        params["path"] = url_path
        params["method"] = method
        if webhook_id:
            params["webhookId"] = webhook_id
    nodes.append({
        "parameters": params,
        "id": "node-1", "name": name,
        "type": node_type, "typeVersion": 1, "position": [220, 0],
    })
    if trigger:
        connections = {"When triggered": {"main": [[{"node": name, "type": "main", "index": 0}]]}}
    else:
        connections = {}
    return {"name": name, "nodes": nodes, "connections": connections, "active": False,
            "settings": {"executionOrder": "v1"}}


def main():
    ap = argparse.ArgumentParser(description="n8n REST API CLI for Hermes")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("workflows")
    wsp = p.add_subparsers(dest="action", required=True)
    wsp.add_parser("list")
    g = wsp.add_parser("get"); g.add_argument("id")
    c = wsp.add_parser("create"); c.add_argument("--name"); c.add_argument("--nodes"); c.add_argument("--connections"); c.add_argument("--active"); c.add_argument("--file")
    s = wsp.add_parser("create-simple"); s.add_argument("--name"); s.add_argument("--node-type", default="n8n-nodes-base.set"); s.add_argument("--url-path"); s.add_argument("--method", default="POST"); s.add_argument("--webhook-id")
    u = wsp.add_parser("update"); u.add_argument("id"); u.add_argument("--name"); u.add_argument("--active"); u.add_argument("--nodes")
    d = wsp.add_parser("delete"); d.add_argument("id")
    a = wsp.add_parser("activate"); a.add_argument("id")
    de = wsp.add_parser("deactivate"); de.add_argument("id")
    e = sub.add_parser("executions")
    eep = e.add_subparsers(dest="action", required=True)
    eep.add_parser("list")
    r = eep.add_parser("run"); r.add_argument("workflowId"); r.add_argument("--data", default="{}")
    tsub = sub.add_parser("tags"); t = tsub.add_subparsers(dest="action"); t.add_parser("list")
    csub = sub.add_parser("credentials"); c = csub.add_subparsers(dest="action"); c.add_parser("list")

    args = ap.parse_args()
    cmd = args.cmd

    if cmd == "workflows":
        a = args.action
        if a == "list":
            _out(_req("GET", "/api/v1/workflows?limit=50"))
        elif a == "get":
            _out(_req("GET", f"/api/v1/workflows/{args.id}"))
        elif a == "create":
            if args.file:
                wf = json.load(open(args.file))
                if args.name: wf["name"] = args.name
                wf.pop("active", None)  # active is read-only on create; set via activate
                wf["settings"] = wf.get("settings") or {"executionOrder": "v1"}
                _out(_req("POST", "/api/v1/workflows", wf))
            else:
                nodes = json.loads(args.nodes or "[]")
                conns = json.loads(args.connections or "{}")
                wf = {"name": args.name or "New Workflow", "nodes": _deref_creds(nodes),
                      "connections": conns, "settings": {"executionOrder": "v1"}}
                if args.active and args.active.lower() == "true":
                    wf["active"] = True
                _out(_req("POST", "/api/v1/workflows", wf))
        elif a == "create-simple":
            wf = simple_flow(args.name, args.node_type, args.url_path, args.method, args.webhook_id)
            _out(_req("POST", "/api/v1/workflows", wf))
        elif a == "update":
            body = {}
            if args.name: body["name"] = args.name
            if args.active is not None: body["active"] = args.active.lower() == "true"
            if args.nodes: body["nodes"] = _deref_creds(json.loads(args.nodes))
            body["settings"] = {"executionOrder": "v1"}
            _out(_req("PATCH", f"/api/v1/workflows/{args.id}", body))
        elif a == "delete":
            _out(_req("DELETE", f"/api/v1/workflows/{args.id}"))
        elif a == "activate":
            _out(_req("POST", f"/api/v1/workflows/{args.id}/activate"))
        elif a == "deactivate":
            _out(_req("POST", f"/api/v1/workflows/{args.id}/deactivate"))
    elif cmd == "executions":
        a = args.action
        if a == "list":
            _out(_req("GET", "/api/v1/executions?limit=20"))
        elif a == "run":
            _out(_req("POST", f"/api/v1/workflows/{args.workflowId}/run", json.loads(args.data)))
    elif cmd == "tags":
        if args.action == "list":
            _out(_req("GET", "/api/v1/tags"))
    elif cmd == "credentials":
        if args.action == "list":
            _out(_req("GET", "/api/v1/credentials"))


if __name__ == "__main__":
    main()