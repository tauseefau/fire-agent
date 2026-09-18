#!/usr/bin/env python3
"""
ElevenLabs Voice Agent + Firefighter Web UI -> Fire Services DB backend.

Serves two roles:
  1) ElevenLabs "webhook tool" contract: the voice agent POSTs a question, we run
     SQL against the fire_services PostGIS DB and return the spoken answer.
     Each Q&A is also logged to gis.conversation_log (so firefighters keep a written
     record of every voice call).
  2) A small REST API for the firefighter web page:
      GET  /property/<id>              -> property + past incidents + alarms + notes
      GET  /property?name=<query>      -> search properties by name/type
      GET  /property/<id>/notes        -> notes for a property
      POST /property/<id>/note         -> add a note  {note_text, firefighter_id?}
      POST /conversation               -> manually record a Q&A {question, answer,
                                           firefighter_id?, property_id?}

Run (systemd: fire-agent-tool.service):
  python3 tool_server.py [--port 8000]
"""
import argparse
import json
import os
import re
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
import urllib.parse
import urllib.request
import urllib.error
import subprocess

DB_USER = "tauseef"
DB_NAME = "fire_services"
CONTAINER = "postgres-db-1"
DB_PASS = os.environ.get("PGPASSWORD") or os.environ.get("PGPASS", "")


def run_sql(sql: str, params: dict = None) -> str:
    """Execute SQL via docker exec. params may be used for simple-safe interpolation."""
    if params:
        for k, v in params.items():
            v = str(v).replace("'", "''")
            sql = sql.replace(f"__{k}__", f"'{v}'")
    try:
        res = subprocess.run(
            ["docker", "exec", "-e", f"PGPASSWORD={DB_PASS}", CONTAINER,
             "psql", "-U", DB_USER, "-d", DB_NAME, "-tA", "-F", "|", "-c", sql],
            capture_output=True, text=True, timeout=30,
        )
    except Exception as e:  # noqa: BLE001
        return f"DB error: {e}"
    if res.returncode != 0:
        return f"DB error: {res.stderr.strip()}"
    return res.stdout.strip()


def rows_as_text(sql: str) -> list:
    """Return list of row strings (empty list on no rows)."""
    out = run_sql(sql)
    if not out or out.startswith("DB error"):
        return []
    return [r for r in out.split("\n") if r]


# ----------------------------------------------------------------------------
# AIRS Code Suggestion Logic
# ----------------------------------------------------------------------------
def suggest_airs_code(incident_id: int, firefighter_id: int = None) -> str:
    """Analyze incident notes/comments and conversation history to suggest AIRS code."""
    # Get incident details
    inc = rows_as_text(f"""
        SELECT i.incident_id, i.incident_name, i.incident_type, i.status, i.comment,
               COALESCE(e.risk_level,'unrated') AS risk_level,
               ff.call_sign AS firefighter_call_sign,
               ff.full_name AS firefighter_name
        FROM gis.incidents i
        LEFT JOIN ai.incident_assessment e ON e.incident_id = i.incident_id
        LEFT JOIN gis.firefighters ff ON ff.firefighter_id = i.firefighter_id
        WHERE i.incident_id = {incident_id};
    """)
    if not inc:
        return f"Incident {incident_id} not found."
    inc_id, name, itype, status, comment, risk_level, ff_call, ff_name = inc[0].split('|')
    
    # Get conversation history for this incident
    conv = rows_as_text(f"""
        SELECT question, answer, to_char(created_at,'DD Mon HH24:MI')
        FROM gis.conversation_log
        WHERE question ILIKE '%{name.replace("'", "")}%' 
           OR question ILIKE '%incident {incident_id}%'
           OR question ILIKE '%{itype.replace("'", "")}%'
        ORDER BY created_at DESC LIMIT 10;
    """)
    
    # Combine all text for keyword matching
    all_text = f"{name} {itype} {comment or ''} {risk_level}"
    for row in conv:
        parts = row.split('|')
        if len(parts) >= 2:
            all_text += f" {parts[0]} {parts[1]}"
    all_text = all_text.lower()
    
    # Score AIRS codes by keyword matches
    scored = rows_as_text("""
        SELECT airs_code, airs_category, airs_subcategory, description, priority,
               array_to_string(keywords, ',') as kw_str
        FROM gis.airs_codes
        ORDER BY priority, airs_code;
    """)
    
    best_matches = []
    for row in scored:
        parts = row.split('|')
        if len(parts) < 6:
            continue
        code, cat, subcat, desc, priority, kw_str = parts
        keywords = [k.strip() for k in kw_str.split(',')] if kw_str else []
        score = sum(1 for kw in keywords if kw.lower() in all_text)
        if score > 0:
            best_matches.append((score, int(priority), code, cat, subcat, desc))
    
    best_matches.sort(key=lambda x: (-x[0], x[1]))
    
    if not best_matches:
        return (f"Incident {incident_id}: {name} ({itype}, {status}). "
                f"No clear AIRS match found from notes. Consider manual selection.")
    
    # Top 3 suggestions
    suggestions = []
    for score, priority, code, cat, subcat, desc in best_matches[:3]:
        reason = f"Matched keywords in incident notes/conversation (score: {score})"
        suggestions.append(f"{code} - {desc} [{cat}/{subcat}] - {reason}")
    
    # Store top suggestion in incident for review
    top_code = best_matches[0][2]
    reason = f"Matched keywords in incident notes/conversation (score: {best_matches[0][0]})"
    run_sql(f"""
        UPDATE gis.incidents SET
          airs_suggested_code = '{top_code}',
          airs_suggestion_reason = '{reason.replace("'", "''")}'
        WHERE incident_id = {incident_id};
    """)
    
    lines = [
        f"Incident {incident_id}: {name} ({itype}, {status})",
        f"Firefighter: {ff_name} ({ff_call})",
        f"Risk level: {risk_level}",
        f"Comment: {comment or 'none'}",
        "",
        "Suggested AIRS codes:"
    ] + suggestions + [
        "",
        f"Top suggestion ({top_code}) stored for review. "
        f"Confirm with 'confirm airs {top_code} for incident {incident_id}' or choose another."
    ]
    return "\n".join(lines)


def confirm_airs_code(incident_id: int, airs_code: str, firefighter_id: int) -> str:
    """Confirm/lock in the AIRS code for an incident."""
    # Validate code exists
    val = rows_as_text(f"SELECT airs_code FROM gis.airs_codes WHERE airs_code = '{airs_code}';")
    if not val:
        return f"Invalid AIRS code: {airs_code}"
    
    run_sql(f"""
        UPDATE gis.incidents SET
          airs_code = '{airs_code}',
          airs_confirmed_by = {firefighter_id},
          airs_confirmed_at = NOW()
        WHERE incident_id = {incident_id};
    """)
    
    # Get description for confirmation
    desc = rows_as_text(f"SELECT description FROM gis.airs_codes WHERE airs_code = '{airs_code}';")
    desc_text = desc[0] if desc else airs_code
    
    return f"AIRS code {airs_code} ({desc_text}) confirmed for incident {incident_id} by firefighter {firefighter_id}."


def incident_nearest_property(incident_id: int):
    """Return (property_id, property_name) nearest to an incident's location,
    or (None, None) if the incident has no geometry."""
    rows = rows_as_text(f"""
        SELECT p.property_id, p.property_name
        FROM gis.incidents i
        JOIN gis.properties p
          ON ST_DWithin(i.geom::geography, p.geom::geography, 2000)
        WHERE i.incident_id = {int(incident_id)}
        ORDER BY ST_Distance(i.geom::geography, p.geom::geography)
        LIMIT 1;
    """)
    if not rows:
        return None, None
    pid, name = rows[0].split("|", 1)
    return int(pid), name


def add_location_note(incident_id: int, note_text: str, firefighter_id: int = None) -> str:
    """Attach a location/access note to the property nearest an incident, so
    it's available to future crews. Returns a confirmation line."""
    if not note_text or not note_text.strip():
        return "No note text was captured."
    pid, name = incident_nearest_property(incident_id)
    if pid is None:
        return "Could not resolve a property near that incident to attach the note to."
    ff = f"{firefighter_id}" if firefighter_id else "NULL"
    safe = note_text.replace("'", "''")
    run_sql(f"""
        INSERT INTO gis.call_notes (property_id, firefighter_id, note_text)
        VALUES ({pid}, {ff}, '{safe}');
    """)
    return f"Location note saved against {name} (property {pid}) for future crews."


def site_location_brief(incident_id: int) -> str:
    """Return prior call-notes + recent alarm history for the site nearest an
    incident, so a crew sees what previous firefighters captured."""
    pid, name = incident_nearest_property(incident_id)
    if pid is None:
        return "Unable to find a registered site near that incident."
    notes = rows_as_text(f"""
        SELECT COALESCE(ff.call_sign,'FF') || ' (' || to_char(cn.created_at,'DD Mon') ||
               '): ' || cn.note_text
        FROM gis.call_notes cn
        LEFT JOIN gis.firefighters ff ON ff.firefighter_id = cn.firefighter_id
        WHERE cn.property_id = {pid}
        ORDER BY cn.created_at DESC LIMIT 5;
    """)
    alarms = rows_as_text(f"""
        SELECT a.alarm_type || ' - ' || a.outcome || ' (' ||
               to_char(a.alarm_date,'DD Mon HH24:MI') || ')'
        FROM gis.alarms a
        WHERE a.property_id = {pid}
        ORDER BY a.alarm_date DESC LIMIT 5;
    """)
    lines = [f"Site knowledge for {name} (property {pid}):"]
    lines.append(" Previous notes:")
    lines += [f"   - {n}" for n in notes] if notes else ["   - none"]
    lines.append(" Recent alarms:")
    lines += [f"   - {a}" for a in alarms] if alarms else ["   - none"]
    return "\n".join(lines)


def get_firefighter_name(ff_id):
    """Return (full_name, first_name) for a firefighter id, or None if unknown/idle."""
    try:
        rows = rows_as_text(f"SELECT full_name FROM gis.firefighters WHERE firefighter_id={int(ff_id)} AND active=TRUE;")
    except (TypeError, ValueError):
        return None
    if not rows or not rows[0]:
        return None
    full = rows[0].strip()
    first = full.split(" ")[0] if " " in full else full
    return full, first


# ----------------------------------------------------------------------------
# Guided conversational flow (state machine) — wraps ALL use cases:
#   1) ask firefighter ID -> 2) ask reason for the call -> 3) route to use case
#   4) confirm details -> 5) propose/suggest or direct-add -> 6) add location notes
#   7) confirm & complete. State persists per-firefighter in gis.agent_state.
# ----------------------------------------------------------------------------
import json as _json

def load_agent_state(ff_id):
    """Return {step, context} for a firefighter, or the default idle state."""
    if not ff_id:
        return {"step": "idle", "context": {}}
    rows = rows_as_text(
        f"SELECT step, context::text FROM gis.agent_state WHERE firefighter_id={int(ff_id)}")
    if not rows or "|" not in rows[0]:
        return {"step": "idle", "context": {}}
    step, ctx = rows[0].split("|", 1)
    try:
        context = _json.loads(ctx)
    except Exception:
        context = {}
    if not isinstance(context, dict):
        context = {}
    return {"step": step, "context": context}


def save_agent_state(ff_id, step, context=None):
    ctx = _json.dumps(context or {})
    run_sql(f"""INSERT INTO gis.agent_state (firefighter_id, step, context, updated_at)
               VALUES ({int(ff_id)}, '{step}', '{ctx.replace("'","''")}', now())
               ON CONFLICT (firefighter_id) DO UPDATE SET
                 step=EXCLUDED.step, context=EXCLUDED.context, updated_at=now()""")


def clear_agent_state(ff_id):
    if ff_id:
        run_sql(f"DELETE FROM gis.agent_state WHERE firefighter_id={int(ff_id)}")


# Keywords that signal the firefighter wants to "complete / set / add" an AIRS code
_AIRS_ACTION = ("complete airs", "set airs", "add airs", "finish airs", "do the airs",
                "do airs", "complete the airs code", "add the airs code", "airs code",
                "complete incident", "end incident", "close incident")


def _detect_use_case(body):
    """Return a use-case id string for a stated reason, or None if generic."""
    b = body.lower()
    airs = any(w in b for w in _AIRS_ACTION) or (
        "confirm airs" in b or
        "airs" in b and ("incident" in b or "code" in b))
    if airs:
        return "airs"
    if "unconfirmed" in b or "open airs" in b:
        return "airs"
    if any(w in b for w in ("hydrant",)): return "hydrant"
    if any(w in b for w in ("pre plan", "pre-plan", "pre incident plan", "pre-incident plan", "preincident",
                               "building info", "property details", "site plan", "floor plan")):
        return "preplan"
    if any(w in b for w in ("access", "entry point", "gate", "entrance", "how we get in", "quick access")):
        return "access"
    if any(w in b for w in ("alarm history", "alert history", "compliance", "as 1670", "as1670", "alarm hist")):
        return "alarms"
    if re.search(r"\balarm\s*#?\s*\d+", b):
        return "alarms"
    if any(w in b for w in ("timeline", "chronology", "what happened")):
        return "timeline"
    if any(w in b for w in ("generate report", "generate a report", "create report", "create a report",
                                "afirs report", "nfirs report", "incident report", "write a report",
                                "make a report", "produce a report", "report for incident")):
        return "report"
    if any(w in b for w in ("debrief", "lessons learned", "after action")):
        return "debrief"
    if any(w in b for w in ("high risk", "critical asset", "asset")):
        return "assets"
    if any(w in b for w in ("station", "apparatus", "pumper", "tanker", "aerial", "units at", "fire station")):
        return "stations"
    if any(w in b for w in ("water", "supply")):
        return "water"
    if any(w in b for w in ("site knowledge", "site info", "what do we know", "site", "previous notes", "site brief")):
        return "site"
    if any(w in b for w in ("false alarm", "malicious", "repeat offender", "offender")):
        return "falsealarms"
    if any(w in b for w in ("active incident", "what is on", "current incidents")):
        return "active"
    if any(w in b for w in ("note", "notes")) and ("property" in b or "location" in b or "site" in b):
        return "notes"
    return None


def _incident_readback(incident_id):
    """Return a read-back of an incident's details for verification."""
    inc = rows_as_text(f"""
        SELECT i.incident_name, COALESCE(i.incident_type,''), COALESCE(i.status,''),
               COALESCE(e.risk_level,'unrated'),
               COALESCE(to_char(i.reported_time,'YYYY-MM-DD HH24:MI'),''),
               COALESCE(i.comment,'')
        FROM gis.incidents i
        LEFT JOIN ai.incident_assessment e ON e.incident_id = i.incident_id
        WHERE i.incident_id = {int(incident_id)}
    """)
    if not inc:
        return None
    fields = inc[0].split('|', 5)
    while len(fields) < 6:
        fields.append('')
    name, itype, status, risk, reported, comment = fields
    pid, prop_name = incident_nearest_property(int(incident_id))
    location = prop_name or "No registered site within 2km"
    return (f"Incident {int(incident_id)} — {name}\n"
            f"  Type: {itype} | Status: {status} | Risk: {risk}\n"
            f"  Location: {location}\n"
            f"  Reported: {reported}\n"
            f"  Comment: {comment or 'none'}")


def _handle_verify_incident(body, ff_id, state):
    """Incident verification step: read back details, ask to confirm/choose a task."""
    ctx = state.get("context", {})
    first = (_ff_display(ff_id).split(" ")[0])
    b = body.strip().lower()

    # If we already know the incident and they're just confirming it's right
    iid = ctx.get("incident_id")
    if not iid:
        iid = _extract_incident(body)
        if not iid:
            return (f"Which incident are you working on, {first}? "
                    f"Please give the incident number, or say 'none' if it's a new job.")
        ctx["incident_id"] = iid

    # Check current incident + existing AIRS state
    inc = rows_as_text(f"SELECT airs_code FROM gis.incidents WHERE incident_id={int(iid)}")
    current_airs = inc[0].split('|')[0] if inc and inc[0] else None

    # If they've confirmed the incident (yes/confirmed/correct) OR just want to proceed
    confirmed = any(w in b for w in ("yes", "correct", "confirmed", "right", "that's the one",
                                     "that is the one", "yes it is", "proceed", "continue", "go ahead"))
    if confirmed:
        ctx["incident_id"] = iid
        save_agent_state(ff_id, "choose_task", ctx)
        extra = ""
        if current_airs:
            extra = f" (Note: incident {iid} already has AIRS code {current_airs} recorded.)"
        return (f"Great, {first}. Incident {iid} confirmed. What would you like to do? "
                f"You can complete the AIRS code{extra}, view the timeline, add a note, "
                f"or ask for site knowledge.")

    # First time identifying with just an incident number -> read back + verify
    if not confirmed and not ctx.get("asked_readback"):
        ctx["asked_readback"] = True
        ctx["incident_id"] = iid
        save_agent_state(ff_id, "verify_incident", ctx)
        readback = _incident_readback(iid)
        if not readback:
            return f"Incident {iid} not found, {first}. Please check the number."
        return (f"Hi {first}, before we proceed: is this the incident you're working on? "
                f"\n\n{readback}\n\n"
                f"Reply 'yes' to confirm, or give me the correct incident number.")

    # Asked already and they gave a different incident number
    auto_iid = _extract_incident(body)
    if auto_iid and not confirmed:
        ctx["incident_id"] = auto_iid
        ctx["asked_readback"] = True
        save_agent_state(ff_id, "verify_incident", ctx)
        readback = _incident_readback(auto_iid)
        if not readback:
            return f"Incident {auto_iid} not found, {first}."
        return (f"OK, checking incident {auto_iid}. "
                f"\n\n{readback}\n\n"
                f"Reply 'yes' to confirm this is the right one.")

    return (f"Please confirm whether incident {iid} is correct, {first}, "
            f"or tell me the correct incident number.")


def _handle_choose_task(body, ff_id, state):
    """After an incident is confirmed, route to the chosen task (AIRS completion,
    timeline, note, site knowledge, etc.)."""
    ctx = state.get("context", {})
    first = (_ff_display(ff_id).split(" ")[0])
    b = body.strip().lower()
    iid = ctx.get("incident_id")

    # AIRS completion chosen
    if any(w in b for w in ("airs", "code", "complete", "suggest", "confirm airs")):
        if not iid:
            m = _extract_incident(b)
            if m:
                iid = m
            else:
                return (f"Which incident is the AIRS code for, {first}?")
        ctx["incident_id"] = iid
        save_agent_state(ff_id, "airs_type", ctx)
        return (f"Incident {iid}. Do you want me to SUGGEST an AIRS code, "
                f"or would you like to ADD the AIRS code yourself?")

    # They said "add note" / "location note"
    if any(w in b for w in ("note", "add a note", "location note", "access note")):
        return (f"Sure {first}, what would you like the note to say for incident {iid}? "
                f"Just tell me the note text.")

    # Site knowledge
    if any(w in b for w in ("site knowledge", "site info", "what do we know", "history",
                            "previous notes", "site")):
        return site_location_brief(int(iid)) if iid else "No incident selected yet."

    # Timeline
    if any(w in b for w in ("timeline", "chronology", "what happened")):
        return get_incident_timeline(f"incident {iid}", ff_id) if iid else "No incident selected yet."

    # Pre-incident plan for nearest site
    if any(w in b for w in ("pre plan", "pre-plan", "preincident", "building info")):
        pid, pname = incident_nearest_property(int(iid)) if iid else (None, None)
        return get_pre_incident_plan(f"property {pid}", ff_id) if pid else "Could not resolve a site near that incident."

    # Alarm history for nearest site
    if any(w in b for w in ("alarm", "as 1670", "as1670", "compliance")):
        pid, pname = incident_nearest_property(int(iid)) if iid else (None, None)
        return get_alarm_history(f"property {pid}", ff_id) if pid else "Could not resolve a site near that incident."

    # Default: recap and re-offer
    return (f"OK {first}. For incident {iid}, I can: complete the AIRS code (I'll "
            f"suggest or you can add one), show the timeline, pre-incident plan, "
            f"alarm history & AS 1670, add a location note, or give site knowledge. "
            f"What would you like?")


def _hydrants_near_incident(incident_id):
    """Return the 3 operational hydrants nearest to a specific incident."""
    rows = rows_as_text(f"""
        SELECT h.hydrant_number || ' (flow ' || h.flow_rate ||
               ', ' || h.status || ', coordinates: lat ' ||
               round(ST_Y(h.geom)::numeric,5) || ', lon ' ||
               round(ST_X(h.geom)::numeric,5) || ', ' ||
               round(ST_Distance(
                   (SELECT geom FROM gis.incidents WHERE incident_id={int(incident_id)})::geography,
                   h.geom::geography))::text || ' metres away)'
        FROM gis.hydrants h WHERE h.status='Operational'
        ORDER BY ST_Distance(
            (SELECT geom FROM gis.incidents WHERE incident_id={int(incident_id)})::geography,
            h.geom::geography)
        LIMIT 3;
    """)
    if not rows:
        return "No operational hydrants found."
    return "Nearest operational hydrants: " + "; ".join(rows) + "."


def _hydrants_near_property(property_id):
    """Return the 3 operational hydrants nearest to a property."""
    rows = rows_as_text(f"""
        SELECT h.hydrant_number || ' (flow ' || h.flow_rate ||
               ', ' || h.status || ')'
        FROM gis.hydrants h
        WHERE h.status='Operational'
        ORDER BY ST_Distance(
            (SELECT geom FROM gis.properties WHERE property_id={int(property_id)})::geography,
            h.geom::geography)
        LIMIT 3;
    """)
    if not rows:
        return "No operational hydrants found."
    return "Nearest hydrants: " + "; ".join(rows) + "."


def _handle_hydrant_branch(body, ff_id, state):
    """Guided nearest-hydrant flow: ask for incident/property, resolve the property,
    confirm the location with the firefighter, then provide hydrants."""
    ctx = state.get("context", {})
    step = state.get("step")
    first = (_ff_display(ff_id).split(" ")[0])

    if step in ("idle", "await_reason", "hydrant_ask"):
        # Try to find an incident number, property number, OR property name in the message
        iid = _extract_incident(body)
        pid = re.search(r"property\s+(\d+)", body)

        # If they gave BOTH an incident number -> resolve its property
        if iid:
            prop = incident_nearest_property(int(iid))
            ctx["incident_id"] = iid
            if prop[0]:
                ctx["property_id"] = prop[0]
                ctx["property_name"] = prop[1]
                save_agent_state(ff_id, "hydrant_confirm", ctx)
                return (f"OK {first}, you're working on incident {iid} at {prop[1]}. "
                        f"Confirm that's the location for the hydrant lookup? "
                        f"Say 'yes' to continue.")
            save_agent_state(ff_id, "hydrant_confirm", ctx)
            return (f"OK {first}, incident {iid}. I couldn't find a registered site within "
                    f"2km. Should I still show the nearest operational hydrants? Say 'yes' to continue.")
        # If they gave a property number
        if pid:
            pipe = rows_as_text(f"SELECT property_name FROM gis.properties WHERE property_id={int(pid.group(1))}")
            pname = pipe[0] if pipe else f"property {pid.group(1)}"
            ctx["property_id"] = int(pid.group(1))
            ctx["property_name"] = pname
            save_agent_state(ff_id, "hydrant_confirm", ctx)
            return (f"OK {first}, you want hydrants for {pname}. "
                    f"Confirm that's the location? Say 'yes' to continue.")
        # If they gave a property NAME (e.g. "St Vincent Hospital", "heading to MCG")
        try:
            npid, npname = _resolve_property_from_name(body)
        except Exception:
            npid, npname = None, None
        if npid:
            ctx["property_id"] = npid
            ctx["property_name"] = npname
            save_agent_state(ff_id, "hydrant_confirm", ctx)
            return (f"OK {first}, you want hydrants for {npname}. "
                    f"Confirm that's the location? Say 'yes' to continue.")
        # No incident/property yet -> ask
        save_agent_state(ff_id, "hydrant_ask", {})
        return (f"Sure {first}. Which incident or property are you at? "
                f"Give me the incident number (e.g. incident 2), a property number, "
                f"or a property name (e.g. St Vincent Hospital).")

    if step == "hydrant_confirm":
        confirmed = any(w in body.lower() for w in ("yes", "yep", "correct", "confirmed", "right", "that's it", "yeah"))
        if confirmed:
            iid = ctx.get("incident_id")
            pid = ctx.get("property_id")
            if iid:
                clear_agent_state(ff_id)
                return _hydrants_near_incident(int(iid))
            if pid:
                clear_agent_state(ff_id)
                return _hydrants_near_property(int(pid))
        # Switched to a different incident/property
        iid = _extract_incident(body)
        pid = re.search(r"property\s+(\d+)", body)
        if iid or pid:
            return _handle_hydrant_branch(body, ff_id, {"step": "hydrant_ask", "context": {}})
        # Corrector: a property name was given
        try:
            cpid, cpname = _resolve_property_from_name(body)
        except Exception:
            cpid, cpname = None, None
        if cpid:
            return _handle_hydrant_branch(body, ff_id, {"step": "hydrant_ask", "context": {}})
        return (f"OK {first}, I'll show hydrants for {ctx.get('property_name','that location')}. "
                f"Say 'yes' to confirm, or give me the correct incident/property number or name.")

    return None


def _waters_near_incident(incident_id):
    """Return the 4 water sources nearest to a specific incident."""
    rows = rows_as_text(f"""
        SELECT source_name || ' (' || source_type || ', ' ||
               COALESCE(capacity_litres::text,'n/a') || ' L, ' ||
               round(ST_Distance(
                   (SELECT geom FROM gis.incidents WHERE incident_id={int(incident_id)})::geography,
                   geom::geography))::text || ' m)'
        FROM gis.water_sources
        ORDER BY ST_Distance(
            (SELECT geom FROM gis.incidents WHERE incident_id={int(incident_id)})::geography,
            geom::geography)
        LIMIT 4;
    """)
    if not rows:
        return "No water sources near that incident."
    return "Nearest water supply: " + "; ".join(rows) + "."


def _waters_near_property(property_id):
    """Return the 4 water sources nearest to a property."""
    rows = rows_as_text(f"""
        SELECT source_name || ' (' || source_type || ', ' ||
               COALESCE(capacity_litres::text,'n/a') || ' L, ' ||
               round(ST_Distance(
                   (SELECT geom FROM gis.properties WHERE property_id={int(property_id)})::geography,
                   geom::geography))::text || ' m)'
        FROM gis.water_sources
        ORDER BY ST_Distance(
            (SELECT geom FROM gis.properties WHERE property_id={int(property_id)})::geography,
            geom::geography)
        LIMIT 4;
    """)
    if not rows:
        return "No water sources found near that property."
    return "Nearest water supply: " + "; ".join(rows) + "."


def _access_for_incident(incident_id):
    """Access brief for a specific incident's nearest property."""
    pid, name = incident_nearest_property(int(incident_id))
    if pid is None:
        return "Unable to resolve a property near that incident."
    return get_access_info(f"access for property {pid}")


def _access_for_property(property_id):
    return get_access_info(f"access for property {property_id}")


def _site_knowledge_for_facility(property_id):
    """Prior call-notes + alarm history for a specific property id."""
    rows = rows_as_text(f"""
        SELECT property_name FROM gis.properties WHERE property_id={int(property_id)}
    """)
    if not rows:
        return f"Property {property_id} not found."
    name = rows[0]
    notes = rows_as_text(f"""
        SELECT COALESCE(ff.call_sign,'FF') || ' (' || to_char(cn.created_at,'DD Mon') ||
               '): ' || cn.note_text
        FROM gis.call_notes cn
        LEFT JOIN gis.firefighters ff ON ff.firefighter_id = cn.firefighter_id
        WHERE cn.property_id = {int(property_id)}
        ORDER BY cn.created_at DESC LIMIT 5;
    """)
    alarms = rows_as_text(f"""
        SELECT a.alarm_type || ' - ' || a.outcome || ' (' ||
               to_char(a.alarm_date,'DD Mon HH24:MI') || ')'
        FROM gis.alarms a
        WHERE a.property_id = {int(property_id)}
        ORDER BY a.alarm_date DESC LIMIT 5;
    """)
    lines = [f"Site knowledge for {name} (property {int(property_id)}):"]
    lines.append(" Previous notes:")
    lines += [f"   - {n}" for n in notes] if notes else ["   - none"]
    lines.append(" Recent alarms:")
    lines += [f"   - {a}" for a in alarms] if alarms else ["   - none"]
    return "\n".join(lines)


def _site_knowledge_for_incident(incident_id):
    return site_location_brief(int(incident_id))


def _resolve_location(body):
    """Resolve an incident or property id/name from a message.
    Returns (ctx_dict, name)."""
    ctx = {}
    iid = _extract_incident(body)
    mpid = re.search(r"property\s+(\d+)", body)
    name = None
    if iid:
        ctx["incident_id"] = iid
        prop = incident_nearest_property(int(iid))
        if prop[0]:
            ctx["property_id"] = prop[0]
            ctx["property_name"] = prop[1]
            name = prop[1]
        else:
            name = f"incident {iid}"
    elif mpid:
        ctx["property_id"] = int(mpid.group(1))
        p = rows_as_text(f"SELECT property_name FROM gis.properties WHERE property_id={int(mpid.group(1))}")
        ctx["property_name"] = p[0] if p else f"property {mpid.group(1)}"
        name = ctx["property_name"]
    else:
        # Property NAME resolution (e.g. "St Vincent Hospital", "heading to MCG")
        try:
            pid, pname = _resolve_property_from_name(body)
        except Exception:
            pid, pname = None, None
        if pid:
            ctx["property_id"] = pid
            ctx["property_name"] = pname
            name = pname
    return ctx, name


def _handle_facility_location_body(body, ff_id, state, kind):
    """Generalized location-confirmation flow for water/access/site.
    kind: 'water' | 'access' | 'site'"""
    ctx = state.get("context", {})
    step = state.get("step") or "idle"
    first = (_ff_display(ff_id).split(" ")[0])

    if step in ("idle", "await_reason", f"{kind}_ask"):
        resolved, name = _resolve_location(body)
        if resolved:
            ctx.update(resolved)
            ctx["property_name"] = name
            save_agent_state(ff_id, f"{kind}_confirm", ctx)
            label = ctx.get("property_name") or "that location"
            return (f"OK {first}, you want {kind} info for {label}. "
                    f"Confirm that's the location? Say 'yes' to continue.")
        save_agent_state(ff_id, f"{kind}_ask", {})
        return (f"Sure {first}. Which incident or property is that for? "
                f"Give me the incident number (e.g. incident 2) or a property number.")

    if step == f"{kind}_confirm":
        confirmed = any(w in body.lower() for w in ("yes", "yep", "correct", "confirmed", "right", "that's it", "yeah"))
        iid = ctx.get("incident_id")
        pid = ctx.get("property_id")
        if confirmed:
            clear_agent_state(ff_id)
            if kind == "water":
                return _waters_near_incident(int(iid)) if iid else _waters_near_property(int(pid))
            if kind == "access":
                return _access_for_incident(int(iid)) if iid else _access_for_property(int(pid))
            if kind == "site":
                return _site_knowledge_for_incident(int(iid)) if iid else _site_knowledge_for_facility(int(pid))
            if kind == "preplan":
                return get_pre_incident_plan(f"property {pid}", ff_id) if pid else get_pre_incident_plan(f"incident {iid}", ff_id)
            if kind == "alarms":
                return get_alarm_history(f"property {pid}", ff_id) if pid else "Please specify a property for alarm history."
        # changed location
        resolved, name = _resolve_location(body)
        if resolved:
            return _handle_location_confirmation(body, ff_id, {"step": f"{kind}_ask", "context": {}}, kind)
        return (f"OK {first}, I'll show {kind} for {ctx.get('property_name','that location')}. "
                f"Say 'yes' to confirm, or give me a different incident/property number.")

    return None


def _handle_location_confirmation(body, ff_id, state, kind):
    """Entry point for water/access/site guided confirmation."""
    return _handle_facility_location_body(body, ff_id, state, kind)


def _ff_display(ff_id):
    nm = get_firefighter_name(ff_id)
    if nm:
        return f"{nm[0]}"
    return f"Firefighter {ff_id}"


def _extract_incident(body):
    m = re.search(r"incident\s+(\d+)", body, re.I)
    if m:
        return int(m.group(1))
    m = re.search(r"#(\d+)", body)
    return int(m.group(1)) if m else None


def _normalize_name(s):
    """Lowercase, strip punctuation so 'St. Vincent Hospital' == 'St Vincent Hospital'."""
    return re.sub(r"[^a-z0-9 ]", " ", (s or "").lower()).strip()


def _resolve_property_from_name(body):
    """Try to match a known property NAME mentioned in the message.
    Returns (property_id, property_name) or (None, None).
    Matches full normalized name OR a distinctive multi-word token (e.g. 'vincent hospital')."""
    props = rows_as_text("SELECT property_id, property_name FROM gis.properties")
    if not props:
        return None, None
    bl = _normalize_name(body)
    # First: exact whole-name containment
    for r in props:
        try:
            pid_s, name = r.split("|", 1)
        except ValueError:
            continue
        nl = _normalize_name(name)
        if nl and nl in bl:
            return int(pid_s), name
    # Second: distinctive 2+ word sub-phrase of the property name present in the message
    best = None
    for r in props:
        try:
            pid_s, name = r.split("|", 1)
        except ValueError:
            continue
        words = [w for w in _normalize_name(name).split() if len(w) > 2]
        # try progressive window of 2+ words
        for i in range(len(words)):
            for j in range(i + 2, len(words) + 1):
                phrase = " ".join(words[i:j])
                if phrase in bl:
                    if best is None or len(phrase) > len(best[1]):
                        best = (int(pid_s), name, len(phrase))
    if best:
        return best[0], best[1]
    # Third: fuzzy typo-tolerant match — each significant word of the property
    # name fuzzy-matches a word in the message (e.g. "vincet"→"vincent", "hosital"→"hospital").
    import difflib
    bl_words = bl.split()
    fuzz_best = None
    for r in props:
        try:
            pid_s, name = r.split("|", 1)
        except ValueError:
            continue
        words = [w for w in _normalize_name(name).split() if len(w) > 2]
        if not words:
            continue
        matched_len = 0
        total_len = sum(len(w) for w in words)
        for pw in words:
            # find the best body word for this property word
            for bw in bl_words:
                if len(bw) < 4:
                    continue
                if difflib.SequenceMatcher(None, pw, bw).ratio() >= 0.72:
                    matched_len += len(pw)
                    break
        if total_len and matched_len / total_len >= 0.55:
            score = matched_len / total_len
            if fuzz_best is None or score > fuzz_best[2]:
                fuzz_best = (int(pid_s), name, score)
    if fuzz_best:
        return fuzz_best[0], fuzz_best[1]
    return None, None


def _extract_firefighter(body):
    """Parse a firefighter id from natural language.
    Returns firefighter_id (int) or None.
    Recognises: auth_el_<id>, 'firefighter 002', 'ff 002', 'my id is 002',
    'id 002', call sign 'FF-002', or a bare 1-3 digit id when identity words present."""
    t = body or ""
    m = re.search(r"auth_el_?(\d+)", t, re.I)
    if m:
        return int(m.group(1))
    # identity-word anchored ids: 'my firefighter id is 002', 'id is 002', 'id: 2'
    for pat in (
        r"(?:firefighter|ff)\s*(?:id)?\s*(?:is|#|:)?\s*(\d{1,3})\b",
        r"\bid\s*(?:is|#|:|=)\s*(\d{1,3})\b",
        r"\b(?:my|id)\s+(\d{1,3})\b",
        r"\bff[- ]?(\d{1,3})\b",
        r"^\s*(?:ok\s+)?(\d{3})\b",
        r"\bzero*(\d{1,3})\s*(?:reporting|here|on\s+duty|heading|working)\b",
    ):
        m = re.search(pat, t, re.I)
        if m:
            return int(m.group(1))
    return None



def _default_reply_intro() -> str:
    return ("I can help with: AIRS incident codes, pre-incident plans, hydrants, "
            "access & entry points, alarm history & AS 1670, incident timelines, reports, "
            "debriefs, high-risk assets, stations & apparatus, water supply, false alarms, "
            "and property notes.")


def _handle_airs_branch(body, ff_id, state):
    """The guided AIRS completion flow (states airs_type / airs_confirm / airs_note)."""
    ctx = state.get("context", {})
    step = state.get("step")
    first = (_ff_display(ff_id).split(" ")[0])

    # 'idle' and 'await_reason' both mean: we know they want an AIRS code.
    if step in ("idle", "await_reason"):
        # They just said they want to complete an AIRS code — need the incident
        iid = _extract_incident(body)
        if not iid:
            save_agent_state(ff_id, "airs_type", {"phase": "need_incident"})
            return (f"Got it, {first}. Which incident is the AIRS code for? "
                    f"Please give the incident number (e.g. incident 2).")
        ctx["incident_id"] = iid
        save_agent_state(ff_id, "airs_type", ctx)
        return (f"Incident {iid} noted. Do you want me to SUGGEST an AIRS code, "
                f"or would you like to ADD the AIRS code yourself?")

    if step == "airs_type":
        phase = ctx.get("phase")
        # If we were waiting for the incident number
        if phase == "need_incident":
            iid = _extract_incident(body)
            if not iid:
                return (f"I still need the incident number, {first}. "
                        f"Which incident is the AIRS code for?")
            ctx["incident_id"] = iid
            ctx.pop("phase", None)  # clear the phase so we don't re-ask for incident
            save_agent_state(ff_id, "airs_type", ctx)
            return (f"Incident {iid} noted. Do you want me to SUGGEST an AIRS code, "
                    f"or would you like to ADD the AIRS code yourself?")
        # They choose suggest / add
        if any(w in body for w in ("suggest", "recommend", "propose", "what do you think",
                                   "your suggestion", "suggestion", "option")):
            iid = ctx.get("incident_id")
            sug = suggest_airs_code(iid, ff_id)
            save_agent_state(ff_id, "airs_confirm", {"incident_id": iid})
            return (f"Here are my suggestions for incident {iid}. {sug}\n\n"
                    f"Which code would you like me to record? Say 'confirm <code> for incident {iid}', "
                    f"or just tell me the code number.")
        if any(w in body for w in ("add", "record", "set", "enter", "put", "confirm", "use")):
            # They want to add a specific code — find the number
            code = re.search(r"\b(1[0-9]{2}|2[0-9]{2}|3[0-9]{2}|4[0-9]{2}|5[0-9]{2}|6[0-9]{2})\b", body)
            iid = ctx.get("incident_id")
            if code and iid:
                return (_handle_airs_confirm(f"confirm airs {code.group(1)} for incident {iid}",
                                             ff_id, {"step": "airs_confirm",
                                                     "context": {"incident_id": iid}}))
            if iid:
                save_agent_state(ff_id, "airs_confirm", {"incident_id": iid})
                return (f"OK {first}, what is the AIRS code you want to add for incident {iid}? "
                        f"Just tell me the three-digit code number.")
            return (f"Which incident is that for, {first}? Please give the incident number.")
        # else unknown
        return (f"Would you like me to SUGGEST an AIRS code, or ADD one yourself, {first}?")

    if step == "airs_confirm":
        return _handle_airs_confirm(body, ff_id, state)

    if step == "airs_note":
        return _handle_airs_note(body, ff_id, state)

    return None


def _handle_airs_confirm(body, ff_id, state):
    ctx = state.get("context", {})
    iid = ctx.get("incident_id")
    first = (_ff_display(ff_id).split(" ")[0])
    # Find the code number to record
    code = re.search(r"\b(1[0-9]{2}|2[0-9]{2}|3[0-9]{2}|4[0-9]{2}|5[0-9]{2}|6[0-9]{2})\b", body)
    if not code or not iid:
        save_agent_state(ff_id, "airs_note", {"incident_id": iid})
        return (f"I wasn't able to read a clear AIRS code, {first}. Please repeat the "
                f"three-digit code, or say 'skip' to move to notes.")
    c = code.group(1)
    result = confirm_airs_code(int(iid), c, int(ff_id))
    ctx["code"] = c
    save_agent_state(ff_id, "airs_note", ctx)
    return (f"{result} Last step: would you like to add a location / access note "
            f"for this property, {first}? Say the note, or 'no' to finish.")


def _handle_airs_note(body, ff_id, state):
    ctx = state.get("context", {})
    iid = ctx.get("incident_id")
    code = ctx.get("code")
    first = (_ff_display(ff_id).split(" ")[0])
    b = body.strip().lower()
    if not b or b in ("no", "nope", "none", "skip", "not now", "nothing"):
        clear_agent_state(ff_id)
        brief = site_location_brief(int(iid)) if iid else ""
        return (f"All set, {first}. AIRS code {code if code else ''} is recorded. "
                f"No note added. {brief}".strip() + "\n\nTask complete. Anything else, call me anytime.")
    # Otherwise treat as a note to save
    note = re.sub(r"\s*(auth_el_\d+)\s*$", "", body).strip()
    if note:
        saved = add_location_note(int(iid), note, int(ff_id))
        brief = site_location_brief(int(iid)) if iid else ""
        clear_agent_state(ff_id)
        return f"{saved}\n\n{brief}\n\nTask complete. Anything else, {first}?"
    clear_agent_state(ff_id)
    return f"Task complete, {first}. Anything else?"


def run_guided_flow(question, ff_id):
    """Top-level guided conversational dispatcher. Returns a reply string, or
    None to fall through to the one-shot handlers in answer()."""
    if ff_id is None:
        # No identity yet — only ask for ID if the query is truly generic
        # (nothing actionable detected). Otherwise fall through to one-shot handlers.
        m = re.search(r"auth_el_(\d+)", question, re.I)
        detected = _detect_use_case(question.lower())
        _generic = ("info" in question.lower() or "help" in question.lower()
                    or "what can you" in question.lower() or "start over" in question.lower())
        if not m and detected is None and not _generic:
            return ("Please identify yourself with your firefighter ID so I know who "
                    "I'm helping — for example, say 'auth_el_3'.")
        return None

    state = load_agent_state(ff_id)
    step = state.get("step")
    body = re.sub(r"\s*auth_el_\d+\s*", " ", question).strip()

    # ---- Fresh-intent override ----
    # If we're mid-flow for one task (e.g. preplan_confirm) and the firefighter
    # now states a DIFFERENT, self-contained use case (e.g. "alarm history"),
    # abandon the stale state and start that new task cleanly instead of
    # continuing the old confirm loop.
    _KIND_OF_STEP = {
        "hydrant_ask": "hydrant", "hydrant_confirm": "hydrant",
        "water_ask": "water", "water_confirm": "water",
        "access_ask": "access", "access_confirm": "access",
        "site_ask": "site", "site_confirm": "site",
        "preplan_ask": "preplan", "preplan_confirm": "preplan",
        "alarms_ask": "alarms", "alarms_confirm": "alarms",
        "airs_type": "airs", "airs_confirm": "airs", "airs_note": "airs",
    }
    cur_kind = _KIND_OF_STEP.get(step)
    uc_new = _detect_use_case(body)
    if cur_kind and uc_new and uc_new != cur_kind:
        # Distinct new intent (ignoring a pure "yes" confirm / generic words which
        # map to uc_new=None). Reset and re-enter fresh-start below.
        clear_agent_state(ff_id)
        state = {"step": "idle", "context": {}}
        step = state.get("step")

    # Continue an in-progress guided flow first
    if step == "await_reason":
        uc = _detect_use_case(body)
        if uc == "airs":
            return _handle_airs_branch(body, ff_id, state)
        if uc == "hydrant":
            return _handle_hydrant_branch(body, ff_id, state)
        if uc in ("water", "access", "site", "preplan", "alarms"):
            return _handle_location_confirmation(body, ff_id, state, uc)
        if uc:
            # Non-AIRS use case stated as the reason — fall through so the
            # specific one-shot handler answers, but remember the intent.
            return None
        return (f"Thanks. What's the reason for your call, {_ff_display(ff_id).split(' ')[0]}? "
                f"{_default_reply_intro()}")

    if step in ("airs_type", "airs_confirm", "airs_note"):
        return _handle_airs_branch(body, ff_id, state)

    if step in ("hydrant_ask", "hydrant_confirm"):
        return _handle_hydrant_branch(body, ff_id, state)

    if step in ("water_ask", "water_confirm", "access_ask", "access_confirm",
                "site_ask", "site_confirm", "preplan_ask", "preplan_confirm",
                "alarms_ask", "alarms_confirm"):
        _kind = step.split("_")[0]
        return _handle_location_confirmation(body, ff_id, state, _kind)

    # A location was given but no task chosen yet — the firefighter can now pick one.
    if step == "location_pending":
        uc = _detect_use_case(body)
        # carry forward the resolved location into whichever task they choose
        pending_ctx = state.get("context", {})
        if uc == "hydrant" and pending_ctx.get("property_id"):
            save_agent_state(ff_id, "hydrant_confirm", pending_ctx)
            return (f"OK {_ff_display(ff_id).split(' ')[0]}, you want hydrants for "
                    f"{pending_ctx.get('property_name','that property')}. "
                    f"Confirm that's the location? Say 'yes' to continue.")
        if uc == "hydrant":
            return _handle_hydrant_branch(body, ff_id, {"step": "hydrant_ask", "context": pending_ctx})
        if uc in ("water", "access", "site", "preplan", "alarms") and pending_ctx.get("property_id"):
            save_agent_state(ff_id, f"{uc}_confirm", pending_ctx)
            return (f"OK {_ff_display(ff_id).split(' ')[0]}, you want {uc} for "
                    f"{pending_ctx.get('property_name','that property')}. "
                    f"Confirm that's the location? Say 'yes' to continue.")
        if uc in ("water", "access", "site", "preplan", "alarms"):
            return _handle_location_confirmation(body, ff_id, {"step": f"{uc}_ask", "context": pending_ctx}, uc)
        # confirm / generic -> default to hydrants at the pending location
        if any(w in body.lower() for w in ("yes", "yeah", "hydrant", "water", "ok")):
            pid = pending_ctx.get("property_id")
            if pid:
                return _hydrants_near_property(int(pid))
            iid = pending_ctx.get("incident_id")
            if iid:
                return _hydrants_near_incident(int(iid))
        return (f"At {pending_ctx.get('property_name','that location')}, I can give you "
                f"nearest hydrants, water supply, access & entry, site knowledge, "
                f"pre-incident plan, alarm history & AS 1670 compliance, or hydrant navigation. "
                f"Which would you like, "
                f"{_ff_display(ff_id).split(' ')[0]}?")

    if step == "verify_incident":
        return _handle_verify_incident(body, ff_id, state)

    if step == "choose_task":
        return _handle_choose_task(body, ff_id, state)

    # Fresh start: identify + reason
    # Gate: enter guided flow if the message carries the identity token, OR the
    # identity was resolved naturally (ff_id is not None here) and there's an
    # actionable location/use-case to guide on. Either way, since answer() only
    # calls us with a validated ff_id, guide whenever we recognise intent.
    has_ident = bool(re.search(r"auth_el_?\d*", question, re.I)) or ff_id is not None
    if has_ident:
        uc = _detect_use_case(body)
        # Identified + gave an incident number but no specific task keyword:
        # verify the incident first (the guided flow you asked for).
        iid_present = _extract_incident(body) is not None
        if uc is None and iid_present and any(w in body for w in
                ("working", "on incident", "my incident", "responding", "assigned", "at incident")):
            return _handle_verify_incident(body, ff_id, {"step": "verify_incident", "context": {}})
        if uc == "hydrant":
            return _handle_hydrant_branch(body, ff_id, state)
        # Direct alarm-by-id fast-path: a bare "alarm 50" / "alarm #50" should
        # answer immediately (with the site's notes) without asking for a location.
        _aid = re.search(r"\balarm\s*#?\s*(\d+)", body, re.I)
        if uc == "alarms" and _aid:
            return get_alarm_history(f"alarm {_aid.group(1)}", ff_id)
        # Report / debrief: fall through to the one-shot handlers (no location prompt).
        if uc in ("report", "debrief", "timeline", "active", "falsealarms", "assets", "stations", "notes"):
            return None
        if uc in ("water", "access", "site", "preplan", "alarms"):
            return _handle_location_confirmation(body, ff_id, state, uc)
        # Identified + resolved a location (property name or incident) but no
        # explicit task keyword yet -> carry the location and ask what they need
        # there, instead of looping for a bare reason.
        if uc is None:
            resolved, loc_name = _resolve_location(body)
            if resolved and loc_name:
                ctx = dict(resolved)
                save_agent_state(ff_id, "location_pending", ctx)
                return (f"Thanks {_ff_display(ff_id).split(' ')[0]}, you're at {loc_name}. "
                        f"What do you need there — nearest hydrants, water supply, "
                        f"access & entry, site knowledge, pre-incident plan, "
                        f"alarm history & AS 1670, or hydrant navigation?")
            save_agent_state(ff_id, "await_reason", {})
            return (f"Hello {_ff_display(ff_id)}. What's the reason for your call today? "
                    f"{_default_reply_intro()}")
        if uc == "airs":
            return _handle_airs_branch(body, ff_id, state)
        return None

    return None


# ----------------------------------------------------------------------------
# Voice answer generation (ElevenLabs webhook)
# ----------------------------------------------------------------------------
def answer(question: str) -> str:
    q = question.lower()

    # Firefighter identity
    ff_id = None
    if "auth_" in q:
        m = re.search(r"auth_el_(\d+)", q, re.I)
        if m:
            ff_id = m.group(1)
    if ff_id is None:
        # Natural-language identity: "My firefighter ID is 002", "ff 3", "id 002"
        _ffid = _extract_firefighter(question)
        if _ffid:
            # validate it maps to a real active firefighter
            if get_firefighter_name(_ffid) is not None:
                ff_id = str(_ffid)
    if ff_id is None:
        # Recovery: mid-guided-flow the firefighter may not repeat their ID.
        strows = rows_as_text(
            "SELECT firefighter_id FROM gis.agent_state "
            "ORDER BY updated_at DESC LIMIT 1")
        if strows and strows[0].strip().isdigit():
            ff_id = strows[0].strip()

    # Guided conversational flow (stateful, wraps all use cases)
    _guided = run_guided_flow(question, ff_id)
    if _guided is not None:
        return _guided

    # Property notes intent: "notes for property <name or id>"
    if "notes" in q and ("property" in q or "call" in q or q.strip().startswith("notes")):
        pid = None
        m = re.search(r"property\s+(\d+)", q)
        if m:
            pid = m.group(1)
        else:
            m2 = re.search(r"(\d{2,})", q)
            if m2:
                pid = m2.group(1)
        if pid:
            rows = rows_as_text(f"""
                SELECT 'Note by ' || COALESCE(ff.call_sign,'') || ' (' ||
                       to_char(cn.created_at,'DD Mon') || '): ' || cn.note_text
                FROM gis.call_notes cn
                LEFT JOIN gis.firefighters ff ON ff.firefighter_id = cn.firefighter_id
                WHERE cn.property_id = {pid}
                ORDER BY cn.created_at DESC;
            """)
            if rows:
                return "Previous notes for this property: " + " ".join(rows) + "."
            return f"No previous notes found for property {pid}."
        return "Please tell me the property number you want notes for."

    if "confirm airs" in q:
        m = re.search(r"confirm airs\s+(\w+)\s+for\s+incident\s+(\d+)", q)
        if m and ff_id:
            airs_code, incident_id = m.group(1).upper(), int(m.group(2))
            base = confirm_airs_code(incident_id, airs_code, int(ff_id))
            # Capture quick-access/location info the firefighter adds at
            # completion, then share what prior crews captured.
            extra = re.search(r"(?:with note|note:|access info|location info|quick access)\s*[:.]?\s*(.+)$", q, re.I)
            parts = []
            if extra and extra.group(1).strip():
                note = extra.group(1).strip().rstrip(".")
                note = re.sub(r"\s*(auth_el_\d+)\s*$", "", note)
                if note:
                    parts.append(add_location_note(incident_id, note, int(ff_id)))
            brief = site_location_brief(incident_id)
            parts.append(brief)
            return base + "\n\n" + "\n".join(parts)
        return "Use format: 'confirm airs 111 for incident 15' (include your auth_el_<id>)."

    # Save a location/access note against an incident's site: "note for incident 15: ..."
    if (q.startswith("note for incident") or q.startswith("add note for incident")
        or q.startswith("save note for incident") or "note for incident" in q
        or "save a location note" in q):
        m = re.search(r"(?:for|on)\s+incident\s+(\d+)\s*[:,]?\s*(.+)$", q)
        if m:
            incident_id, note = int(m.group(1)), m.group(2).strip()
            note = re.sub(r"\s*(auth_el_\d+)\s*$", "", note)
            if not note:
                return f"Tell me what to save. e.g. 'note for incident {incident_id}: hydrant access via Brunton Ave'."
            result = add_location_note(incident_id, note, int(ff_id) if ff_id else None)
            return result + "\n\n" + site_location_brief(incident_id)
        return "To save a location note, say 'note for incident 15: <your access detail>'."

    # Site knowledge (prior call-notes + alarms) for an incident location
    if any(w in q for w in ("site info for incident", "site knowledge", "location info for incident", "notes for incident", "previous notes for incident", "what do we know about incident")):
        m = re.search(r"incident\s+(\d+|\w+)", q)
        if m:
            iid = m.group(1)
            if iid.isdigit():
                return site_location_brief(int(iid))
            return "Please give the incident number, e.g. 'site info for incident 15'."


    # Unconfirmed AIRS tickets: incidents without a confirmed AIRS code
    if "unconfirmed" in q and ("airs" in q or "ticket" in q or "incident" in q):
        rows = rows_as_text("""
            SELECT
                i.incident_id,
                i.incident_name,
                to_char(i.reported_time,'HH24:MI') AS reported,
                COALESCE(i.airs_suggested_code, i.airs_code, '') AS code,
                COALESCE(i.airs_suggestion_reason, '') AS reason
            FROM gis.incidents i
            WHERE (i.airs_code IS NULL OR i.airs_code = '')
            ORDER BY i.reported_time DESC
            LIMIT 10
        """)
        if not rows:
            return "All known incidents have confirmed AIRS codes."
        lines = ["Open AIRS tickets (incidents without confirmed AIRS code):"]
        for r in rows:
            p = r.split('|')
            if len(p) >= 5:
                lines.append(f"  Incident {p[0]}: {p[1]} (reported {p[2]}) — suggested code {p[3]} ({p[4]})")
        return "\n".join(lines)

    if "hydrant" in q:
        rows = rows_as_text("""
            SELECT h.hydrant_number || ' (flow ' || h.flow_rate ||
                   ', ' || h.status || ', coordinates: lat ' ||
                   round(ST_Y(h.geom)::numeric,5) || ', lon ' ||
                   round(ST_X(h.geom)::numeric,5) || ', ' ||
                   round(ST_Distance(
                       (SELECT geom FROM gis.incidents WHERE status='Active'
                        ORDER BY reported_time DESC LIMIT 1)::geography,
                       h.geom::geography))::text || ' metres away)'
            FROM gis.hydrants h WHERE h.status='Operational'
            ORDER BY ST_Distance(
                (SELECT geom FROM gis.incidents WHERE status='Active'
                 ORDER BY reported_time DESC LIMIT 1)::geography, h.geom::geography)
            LIMIT 3;
        """)
        if not rows:
            return "No operational hydrants found."
        return "Nearest operational hydrants: " + "; ".join(rows) + "."

    # AIRS incident code suggestion: "airs for incident 15"
    if any(w in q for w in ("airs", "air code", "incident code", "complete incident")):
        m = re.search(r"incident\s+(\d+)", q)
        if not m:
            m = re.search(r"#(\d+)", q)
        if not m:
            # Also match "airs 15" or "air code 15"
            m = re.search(r"(?:airs|air code|incident code|complete incident)\s+(\d+)", q)
        if m:
            incident_id = int(m.group(1))
            return suggest_airs_code(incident_id, ff_id)
        return "Please specify the incident number (e.g., 'airs for incident 15')."

    # 3. Pre-Incident Plan Lookup: "pre plan for property MCG" or "building info for property 15"
    if any(w in q for w in ("pre plan", "pre-plan", "pre incident plan", "pre-incident plan", "preincident",
                            "building info", "property details", "site plan", "floor plan")):
        return get_pre_incident_plan(q, ff_id)

    # Quick-access intent: "how do we get access to X", "access for<property>",
    # "entry points for <name>", "vehicle access to <property>". Returns the
    # fast on-scene access brief for an incident location.
    if any(w in q for w in ("access", "get access", "entry point", "entry", "how do we get in", "vehicle access", "quick access", "gate", "entrance")):
        return get_access_info(q)

    # 4. Alarm History & Compliance: "alarm history for property 15" / "compliance for Royal Melbourne Hospital" / "alarm 50"
    if any(w in q for w in ("alarm history", "compliance", "as 1670", "as1670")) or re.search(r"\balarm\s*#?\s*\d+", q):
        return get_alarm_history(q, ff_id)

    # 6. Incident Timeline: "timeline for incident 15" or "chronology incident 15"
    if any(w in q for w in ("timeline", "chronology", "what happened", "sequence")):
        return get_incident_timeline(q, ff_id)

    # 9. Generate Report: "generate report for incident 15", "I need to generate a report", "AFIRS report incident 15"
    if any(w in q for w in ("generate report", "generate a report", "create report", "create a report",
                            "afirs report", "nfirs report", "incident report", "write a report",
                            "make a report", "produce a report", "report for incident")):
        return generate_incident_report(q, ff_id)

    # 10. Debrief Mode: "debrief incident 15" or "lessons learned incident 15" or "after action incident 15"
    if any(w in q for w in ("debrief", "lessons learned", "after action", "after-action", "review incident")):
        return debrief_incident(q, ff_id)

    if any(w in q for w in ("active", "incident", "incidents")):
        rows = rows_as_text("""
            SELECT i.incident_name || ' (' || i.status || ', ' ||
                   COALESCE(e.risk_level,'unrated') || ')'
            FROM gis.incidents i
            LEFT JOIN ai.incident_assessment e ON e.incident_id = i.incident_id
            WHERE i.status='Active' ORDER BY i.reported_time DESC;
        """)
        if not rows:
            return "No active incidents right now."
        return "Active incidents: " + "; ".join(rows) + "."

    # High-risk / critical assets
    if any(w in q for w in ("high risk", "critical", "asset")):
        rows = rows_as_text("""
            SELECT a.asset_name || ' (' || a.asset_type || ', ' || a.risk_category || ')'
            FROM gis.assets a
            WHERE a.risk_category IN ('High','HIGH','Critical')
            ORDER BY a.asset_type LIMIT 8;
        """)
        if not rows:
            return "No high or critical risk assets on record."
        return "High and critical risk assets include: " + "; ".join(rows) + "."

    # False / malicious alarms + repeat offenders
    if any(w in q for w in ("false", "malicious", "offender", "repeat")):
        n_rows = rows_as_text("""
            SELECT count(*) FROM gis.alarms WHERE outcome NOT ILIKE 'REAL FIRE%';
        """)
        n = n_rows[0] if n_rows else "0"
        offenders = rows_as_text("""
            SELECT p.property_name || ' (' || count(a.alarm_id) || ' false alarms)'
            FROM gis.alarms a JOIN gis.properties p ON p.property_id=a.property_id
            WHERE a.outcome NOT ILIKE 'REAL FIRE%'
            GROUP BY p.property_name
            ORDER BY count(a.alarm_id) DESC, p.property_name
            LIMIT 5;
        """)
        base = f"There are {n} recorded false or non-fire alarms."
        if offenders and ("offender" in q or "repeat" in q or "who" in q or "where" in q):
            base += " Most frequent: " + "; ".join(offenders) + "."
        return base

    # Stations & apparatus: "units at station 3", "pumpers at Eastern Hill",
    # "what apparatus at station 2", "list fire stations", "how many pumpers".
    # NOTE: runs before the water guard so phrases like "how many tankers"
    # are treated as apparatus, not water tanks.
    if any(w in q for w in ("station", "stations", "units at", "apparatus", "pumper", "pumpers", "aerial", "tanker", "tankers", "rescue", "hazmat", "command", "what units", "fleet", "fire station")):
        return get_station_apparatus(q)

    # Water sources / water supply
    if any(w in q for w in ("water", "supply", "tank")):
        rows = rows_as_text("""
            SELECT source_name || ' (' || source_type || ', ' ||
                   COALESCE(capacity_litres::text,'n/a') || ' L)'
            FROM gis.water_sources ORDER BY capacity_litres DESC NULLS LAST LIMIT 4;
        """)
        if not rows:
            return "No water sources on record."
        return "Water supply: " + "; ".join(rows) + "."

    # Stations & apparatus (shadow-safe water guard was moved above)

    return ("I can report hydrants, active incidents, high risk assets, water sources, "
            "false alarms, fire stations, unit/apparatus at a station, previous notes for a property, "
            "suggest AIRS codes, pre-incident plans, alarm history, incident timelines, "
            "generate reports, and debrief incidents. "
            f"Please ask about one of those. I heard: {question}")


def get_station_apparatus(q: str) -> str:
    """Answer station / apparatus queries: list stations, units at a station,
    or apparatus of a given type (e.g. pumpers, tankers)."""
    ql = q.lower()
    # Try to resolve a specific station by number or name substring
    station_filter = ""
    m = re.search(r"station?s?\s*(?:#|number\s*)?(\d+)", ql)
    if not m:
        m = re.search(r"at\s+(.+?)(?:\?|$)", ql)
        if m:
            cand = m.group(1).strip()
            if not any(x in cand for x in ("unit", "incident", "property", "hydrant")):
                station_filter = cand
    if m and station_filter == "" and re.search(r"station", ql):
        num = m.group(1)
        if re.search(r"(station\s*#?"+num+r"\b|#\s*"+num+r"\b|station\s+"+num+r"\b)", ql):
            station_filter = num

    def esc(s): return s.replace("'", "''")

    # A specific station was requested: show its apparatus
    if station_filter:
        where = f"fs.station_id = {esc(station_filter)}" if station_filter.isdigit() else \
                f"fs.station_name ILIKE '%{esc(station_filter)}%'"
        rows = rows_as_text(f"""
            SELECT fs.station_name, a.call_sign, a.apparatus_type,
                   COALESCE(a.water_capacity_l::text,'0') || 'L / ' ||
                   COALESCE(a.pump_capacity_lpm::text,'0') || 'Lpm'
            FROM gis.apparatus a
            JOIN gis.fire_stations fs ON fs.station_id = a.station_id
            WHERE {where}
            ORDER BY a.apparatus_type, a.call_sign;
        """)
        if not rows:
            rows2 = rows_as_text(f"SELECT station_name FROM gis.fire_stations WHERE {where}")
            name = rows2[0] if rows2 else station_filter
            return f"Station '{name}' has no units assigned."
        lines = [f"Units at {rows[0].split('|')[0]}:"]
        for r in rows:
            p = r.split("|")
            lines.append(f"  {p[1]} - {p[2]} ({p[3]})")
        return "\n".join(lines)

    # 'how many pumpers' / by-type query
    type_map = {
        "pumper": "Pumper", "pump": "Pumper", "pumpers": "Pumper",
        "aerial": "Aerial", "aerial": "Aerial", "tanker": "Tanker", "tankers": "Tanker",
        "rescue": "Rescue", "rescues": "Rescue", "hazmat": "Hazmat", "command": "Command",
    }
    for kw, label in type_map.items():
        if kw in ql and any(w in ql for w in ("how many", "count", "list", "all", "number")):
            rows = rows_as_text(f"""
                SELECT a.call_sign, a.apparatus_type, fs.station_name
                FROM gis.apparatus a JOIN gis.fire_stations fs ON fs.station_id=a.station_id
                WHERE a.apparatus_type ILIKE '%{label}%' ORDER BY a.call_sign;
            """)
            if rows:
                return f"{len(rows)} {label} unit(s): " + "; ".join(
                    f"{r.split('|')[0]} at {r.split('|')[2]}" for r in rows) + "."
            return f"No {label} units found."

    # Generic station + apparatus roster
    rows = rows_as_text("""
        SELECT fs.station_name,
               (SELECT count(*) FROM gis.apparatus a WHERE a.station_id=fs.station_id),
               string_agg(a.call_sign, ',' ORDER BY a.call_sign)
        FROM gis.fire_stations fs
        LEFT JOIN gis.apparatus a ON a.station_id=fs.station_id
        GROUP BY fs.station_id, fs.station_name
        ORDER BY fs.station_id;
    """)
    if not rows:
        return "No fire stations on record."
    lines = ["Fire stations and their units:"]
    for r in rows:
        p = r.split("|")
        units = p[2] if len(p) > 2 and p[2] else "no units"
        lines.append(f"  {p[0]}: {p[1]} unit(s) - {units}")
    return "\n".join(lines)


def get_access_info(q: str) -> str:
    """Quick on-scene access brief for a property/location (the firefighter's
    'how do we get in' reference). Returns entry points, vehicle access,
    nearest hydrant and hazards in a short, spoken, on-call response."""
    ql = q.lower()
    pid = None
    name_query = None
    m = re.search(r"property\s+(\d+)", ql)
    if m:
        pid = m.group(1)
    elif re.search(r"(?:#|id)\s*(\d+)", ql):
        pid = re.search(r"(?:#|id)\s*(\d+)", ql).group(1)
    else:
        m2 = re.search(r"(?:for|to|at|into|of)\s+(.+?)(?:\?|$)", ql)
        if m2:
            cand = m2.group(1).strip()
            cand = re.sub(r"\s+(gate|entrance|access|entry|qvm|mcg|st|street|station|bldg|building)$", "", cand)
            cand = re.sub(r"\b(access\s+(to|for)|entry\s+to\s+)\b", "", cand)
            if cand and len(cand) > 1:
                name_query = cand
    def esc(s): return s.replace("'", "''")

    where = ""
    # By property id
    if pid:
        # check the id exists; if not, give a useful message
        exists = rows_as_text(f"SELECT property_name FROM gis.properties WHERE property_id={esc(pid)}")
        if not exists:
            landmarks = rows_as_text("""
                SELECT property_name FROM gis.properties
                WHERE property_id BETWEEN 1 AND 100
                ORDER BY property_name LIMIT 12;
            """)
            pick = "; ".join(landmarks) if landmarks else ""
            return (f"Property {pid} not found. Ask by name instead, e.g. 'access for MCG'. "
                    f"Key locations include: {pick}.")
        name_query = exists[0]  # use its exact name to fetch full row
        where = f"property_id = {esc(pid)}"
    elif name_query:
        # match name OR alias; prefer an exact/landmark primary over duplicates
        where = (f"(property_name ILIKE '%{esc(name_query)}%' "
                 f"OR aliases ILIKE '%{esc(name_query)}%')")
    else:
        return "Please tell me which location or property you need access to (e.g. 'access for MCG')."

    # Prefer (1) alias/exact-name primary, (2) Landmark/top-9 showcase, (3) lowest id
    rows = rows_as_text(f"""
        SELECT property_id, property_name, COALESCE(access_notes,''),
               COALESCE(hazards,'')
        FROM gis.properties
        WHERE {where}
        ORDER BY (aliases ILIKE '%{esc(name_query)}%' OR property_name ILIKE '%{esc(name_query)}%') DESC,
                 CASE WHEN property_id BETWEEN 1 AND 100 THEN 0 ELSE 1 END,
                 property_id
        LIMIT 1;
    """)
    if not rows:
        return f"No property found matching '{name_query}'. Try 'pre plan for <property name>'."
    pid_, name, access, hazards = rows[0].split("|", 3)

    hyd = rows_as_text(f"""
        SELECT h.hydrant_number || ' (' || h.flow_rate || ' L/s, ' ||
               round(ST_Distance(h.geom::geography, p.geom::geography))::text || ' m)'
        FROM gis.hydrants h, gis.properties p
        WHERE p.property_id = {pid_} AND h.status='Operational'
        ORDER BY ST_Distance(h.geom::geography, p.geom::geography) LIMIT 1;
    """)

    lines = [
        f"ACCESS FOR {name} (Property #{pid_}):",
        f"  {access if access else 'No access notes recorded.'}",
        f"  Nearest hydrant: {hyd[0] if hyd else 'none within range'}",
        f"  Hazards: {hazards if hazards else 'none recorded'}",
        "",
        "For the full building layout, occupancy and alarm details ask 'pre plan for this property'."
    ]
    return "\n".join(lines)


def log_conversation(question, answer_text, firefighter_id=None, property_id=None):
    """Persist a voice Q&A to gis.conversation_log."""
    params = {}
    if firefighter_id:
        params["ff"] = firefighter_id
    if property_id:
        params["prop"] = property_id
    sql = ("INSERT INTO gis.conversation_log (firefighter_id, property_id, question, answer) "
           f"VALUES ({params.get('ff','NULL')}, {params.get('prop','NULL')}, "
           f"__q__, __a__);")
    sql = sql.replace("__q__", "'" + question.replace("'", "''") + "'")
    sql = sql.replace("__a__", "'" + answer_text.replace("'", "''") + "'")
    run_sql(sql)


# ----------------------------------------------------------------------------
# 3. Pre-Incident Plan Lookup
# ----------------------------------------------------------------------------
def get_pre_incident_plan(q: str, ff_id: str = None) -> str:
    """Get comprehensive pre-incident plan for a property."""
    import re
    m = re.search(r"property\s+(\d+)", q)
    if not m:
        m = re.search(r"(\d{2,})", q)
    if not m:
        # Try to match by name
        m = re.search(r"(?:for|at)\s+([a-zA-Z\s]+)", q)
        if m:
            name_query = m.group(1).strip()
            rows = rows_as_text(f"""
                SELECT property_id FROM gis.properties
                WHERE property_name ILIKE '%{name_query.replace("'", "''")}%'
                LIMIT 1;
            """)
            if rows:
                m = type('obj', (object,), {'group': lambda self, x: rows[0].split('|')[0]})()
    
    if m:
        pid = m.group(1) if hasattr(m, 'group') else m
        # Get property details
        prop = rows_as_text(f"""
            SELECT property_id, property_name, property_type,
                   construction_type, occupancy_type, floors, floor_area_sqm,
                   sprinkler_coverage, alarm_system, access_notes, hazards
            FROM gis.properties WHERE property_id = {pid};
        """)
        if not prop:
            return f"Property {pid} not found."
        
        parts = prop[0].split('|')
        pid, name, ptype, construction, occupancy, floors, area, sprinkler, alarm, access, hazards = parts
        
        # Get nearby hydrants
        hydrants = rows_as_text(f"""
            SELECT h.hydrant_number || ' (' || h.flow_rate || ' L/s, ' ||
                   round(ST_Distance(h.geom::geography, p.geom::geography))::text || 'm)'
            FROM gis.hydrants h, gis.properties p
            WHERE p.property_id = {pid} AND h.status = 'Operational'
            ORDER BY ST_Distance(h.geom::geography, p.geom::geography)
            LIMIT 5;
        """)
        
        # Get alarm history
        alarms = rows_as_text(f"""
            SELECT a.alarm_type || ' ' || a.outcome || ' (' ||
                   to_char(a.alarm_date, 'DD Mon YYYY') || ')'
            FROM gis.alarms a
            WHERE a.property_id = {pid}
            ORDER BY a.alarm_date DESC LIMIT 10;
        """)
        
        # Get call notes
        notes = rows_as_text(f"""
            SELECT cn.note_text || ' - ' || COALESCE(ff.call_sign, 'FF') || ' (' ||
                   to_char(cn.created_at, 'DD Mon YYYY') || ')'
            FROM gis.call_notes cn
            LEFT JOIN gis.firefighters ff ON ff.firefighter_id = cn.firefighter_id
            WHERE cn.property_id = {pid}
            ORDER BY cn.created_at DESC LIMIT 5;
        """)
        
        # Get nearest station
        station = rows_as_text(f"""
            SELECT fs.station_name || ' (' ||
                   round(ST_Distance(fs.geom::geography, p.geom::geography)/1000, 1) || 'km)'
            FROM gis.fire_stations fs, gis.properties p
            WHERE p.property_id = {pid}
            ORDER BY ST_Distance(fs.geom::geography, p.geom::geography)
            LIMIT 1;
        """)
        
        lines = [
            f"PRE-INCIDENT PLAN: {name} (Property #{pid})",
            f"Type: {ptype or 'Unknown'}",
            f"Construction: {construction or 'N/A'} | Occupancy: {occupancy or 'N/A'}",
            f"Floors: {floors or 'N/A'} | Area: {area or 'N/A'} sqm",
            f"Sprinklers: {sprinkler or 'N/A'} | Alarm System: {alarm or 'N/A'}",
            f"Nearest Station: {station[0] if station else 'Unknown'}",
            "",
            "HYDRANTS (nearest 5):"
        ] + (hydrants if hydrants else ["  None found within range"]) + [
            "",
            "ALARM HISTORY (last 10):"
        ] + (alarms if alarms else ["  No alarms recorded"]) + [
            "",
            "PREVIOUS NOTES:"
        ] + (notes if notes else ["  No previous notes"]) + [
            "",
            f"ACCESS NOTES: {access or 'None recorded'}",
            f"HAZARDS: {hazards or 'None recorded'}"
        ]
        return "\n".join(lines)
    
    return "Please specify a property number or name (e.g., 'pre plan for property 15' or 'pre plan for MCG')."


# ----------------------------------------------------------------------------
# 4. Alarm History & AS 1670 Compliance
# ----------------------------------------------------------------------------
def get_alarm_history(q: str, ff_id: str = None) -> str:
    """Get alarm history and AS 1670 compliance for a property.
    Accepts an alarm ID (resolves to its site + notes), a property number, or a
    property name. Always includes recent call notes for the site."""
    import re
    pid = None
    aid = None
    # Explicit alarm id
    m = re.search(r"(?:alarm\s*(?:id|#)?\s*)(\d+)", q, re.I)
    if m:
        aid = int(m.group(1))
    m = re.search(r"property\s+(\d+)", q)
    if m and pid is None:
        pid = int(m.group(1))
    if pid is None and aid is None:
        # By name
        m = re.search(r"(?:for|at)\s+([a-zA-Z]+(?:[\s-][a-zA-Z]+)*)", q)
        if m:
            name_query = m.group(1).strip()
            rows = rows_as_text(f"""SELECT property_id FROM gis.properties
                WHERE property_name ILIKE '%{name_query.replace("'", "''")}%' LIMIT 1;""")
            if rows:
                pid = int(rows[0].split('|')[0])
    if pid is None and aid is None:
        # Bare number ambiguous — check alarm id first, then property id
        m = re.search(r"(\d+)", q)
        if m:
            candidate = int(m.group(1))
            arow = rows_as_text(f"SELECT property_id FROM gis.alarms WHERE alarm_id = {candidate} LIMIT 1;")
            if arow:
                aid = candidate
            else:
                pid = candidate

    if aid:
        arows = rows_as_text(f"""SELECT a.alarm_id, a.alarm_type, COALESCE(a.outcome,''),
            COALESCE(a.alarm_code,''), to_char(a.alarm_date,'DD Mon YYYY HH24:MI'),
            COALESCE(a.property_id::text,''), COALESCE(p.property_name,'')
            FROM gis.alarms a LEFT JOIN gis.properties p ON p.property_id=a.property_id
            WHERE a.alarm_id = {aid};""")
        if not arows:
            return f"Alarm #{aid} not found."
        p = arows[0].split('|')
        al_id, al_type, al_out, al_code, al_date, a_pid, a_pname = (p + ['']*7)[:7]
        lines = [f"ALARM #{al_id} — {al_type}",
                 f"Outcome: {al_out} | Code: {al_code or '—'} | When: {al_date}",
                 f"Site: {a_pname or 'Unknown'}{' (property '+a_pid+')' if a_pid else ''}"]
        if a_pid and a_pid.isdigit():
            notes = rows_as_text(f"""SELECT cn.note_text || ' — ' || COALESCE(ff.call_sign,'FF')
                || ' (' || to_char(cn.created_at,'DD Mon') || ')'
                FROM gis.call_notes cn LEFT JOIN gis.firefighters ff ON ff.firefighter_id=cn.firefighter_id
                WHERE cn.property_id = {int(a_pid)} ORDER BY cn.created_at DESC LIMIT 5;""")
            lines.append("")
            lines.append("CALL NOTES FOR THIS SITE:")
            lines += notes if notes else ["  None on record"]
        return "\n".join(lines)

    if pid is None:
        return "Please specify a property or alarm (e.g., 'alarm history for property 15', 'alarm 50', or 'alarm history for Royal Melbourne Hospital')."

    total = rows_as_text(f"SELECT count(*) FROM gis.alarms WHERE property_id = {pid};")
    total_count = total[0] if total else "0"

    outcomes = rows_as_text(f"""SELECT outcome, count(*) FROM gis.alarms
        WHERE property_id = {pid} GROUP BY outcome ORDER BY count(*) DESC;""")

    categories = rows_as_text(f"""SELECT ac.as1670_category, ac.detection_method, count(*)
        FROM gis.alarms a LEFT JOIN gis.alarm_codes ac ON ac.alarm_code = a.alarm_code
        WHERE a.property_id = {pid} GROUP BY ac.as1670_category, ac.detection_method
        ORDER BY count(*) DESC;""")

    recent = rows_as_text(f"""SELECT a.alarm_type || ' | ' || a.outcome || ' | ' ||
        COALESCE(ac.alarm_code || ' (' || ac.detection_method || ')', 'No code') || ' | ' ||
        to_char(a.alarm_date, 'DD Mon YYYY HH24:MI')
        FROM gis.alarms a LEFT JOIN gis.alarm_codes ac ON ac.alarm_code = a.alarm_code
        WHERE a.property_id = {pid} ORDER BY a.alarm_date DESC LIMIT 15;""")

    notes = rows_as_text(f"""SELECT cn.note_text || ' — ' || COALESCE(ff.call_sign,'FF')
        || ' (' || to_char(cn.created_at,'DD Mon') || ')'
        FROM gis.call_notes cn LEFT JOIN gis.firefighters ff ON ff.firefighter_id=cn.firefighter_id
        WHERE cn.property_id = {pid} ORDER BY cn.created_at DESC LIMIT 5;""")

    false_count = rows_as_text(f"""SELECT count(*) FROM gis.alarms
        WHERE property_id = {pid} AND outcome NOT ILIKE 'REAL FIRE%';""")
    false_rate = f"{int(false_count[0]) / max(int(total_count), 1) * 100:.0f}%" if false_count else "0%"

    prop = rows_as_text(f"SELECT property_name FROM gis.properties WHERE property_id = {pid};")
    pname = prop[0] if prop else f"Property {pid}"

    lines = [
        f"ALARM HISTORY & AS 1670 COMPLIANCE: {pname}",
        f"Total Alarms: {total_count} | False/Non-Fire Rate: {false_rate}",
        "",
        "BY OUTCOME:"
    ] + (outcomes if outcomes else ["  None"]) + [
        "",
        "BY AS 1670 CATEGORY (Detection Method):"
    ] + (categories if categories else ["  No alarm codes assigned"]) + [
        "",
        "RECENT ALARMS (last 15):"
    ] + (recent if recent else ["  None"]) + [
        "",
        "CALL NOTES:"
    ] + (notes if notes else ["  None on record"])

    if int(total_count) > 0 and int(false_count[0]) > 3:
        lines.append(f"\n⚠️ COMPLIANCE FLAG: {false_count[0]} false alarms - recommend AS 1670 system review.")

    return "\n".join(lines)


# ----------------------------------------------------------------------------
# 6. Incident Timeline Reconstruction
# ----------------------------------------------------------------------------
def get_incident_timeline(q: str, ff_id: str = None) -> str:
    """Reconstruct incident timeline from dispatch, alarms, and voice logs."""
    import re
    m = re.search(r"incident\s+(\d+)", q)
    if not m:
        m = re.search(r"#(\d+)", q)
    if not m:
        m = re.search(r"(\d{2,})", q)
    
    if m:
        iid = m.group(1)
        
        # Incident basics
        inc = rows_as_text(f"""
            SELECT incident_name, incident_type, status, reported_time,
                   to_char(reported_time, 'DD Mon YYYY HH24:MI')
            FROM gis.incidents WHERE incident_id = {iid};
        """)
        if not inc:
            return f"Incident {iid} not found."
        
        name, itype, status, rtime, rtime_str = inc[0].split('|')
        
        # Dispatch log
        dispatch = rows_as_text(f"""
            SELECT apparatus_call_sign || ' (' || apparatus_type || ') | ' ||
                   role || ' | Dispatched: ' || to_char(dispatched_at, 'HH24:MI') ||
                   ' | Arrived: ' || COALESCE(to_char(arrived_at, 'HH24:MI'), '—') ||
                   ' | Cleared: ' || COALESCE(to_char(cleared_at, 'HH24:MI'), '—') ||
                   CASE WHEN notes IS NOT NULL THEN ' | ' || notes ELSE '' END
            FROM gis.dispatch_log
            WHERE incident_id = {iid}
            ORDER BY dispatched_at;
        """)
        
        # Alarm activations
        alarms = rows_as_text(f"""
            SELECT 'ALARM: ' || alarm_type || ' (' || outcome || ') | ' ||
                   to_char(alarm_date, 'HH24:MI') || ' | ' ||
                   COALESCE(ac.detection_method || ' [' || ac.alarm_code || ']', 'No code')
            FROM gis.alarms a
            LEFT JOIN gis.alarm_codes ac ON ac.alarm_code = a.alarm_code
            WHERE a.property_id IN (
                SELECT property_id FROM gis.properties
                WHERE ST_DWithin(geom::geography,
                    (SELECT geom FROM gis.incidents WHERE incident_id = {iid})::geography, 500)
            )
            ORDER BY a.alarm_date;
        """)
        
        # Voice conversation log
        voice = rows_as_text(f"""
            SELECT to_char(created_at, 'HH24:MI') || ' | ' ||
                   COALESCE(ff.call_sign || ': ', '') ||
                   question || ' → ' || substr(answer, 1, 80) || '...'
            FROM gis.conversation_log cl
            LEFT JOIN gis.firefighters ff ON ff.firefighter_id = cl.firefighter_id
            WHERE cl.question ILIKE '%{name.replace("'", "")}%'
               OR cl.question ILIKE '%incident {iid}%'
            ORDER BY cl.created_at;
        """)
        
        # AIRS code
        airs = rows_as_text(f"""
            SELECT airs_code, airs_confirmed_by, airs_confirmed_at
            FROM gis.incidents WHERE incident_id = {iid};
        """)
        
        lines = [
            f"INCIDENT TIMELINE: {name} (Incident #{iid})",
            f"Type: {itype} | Status: {status} | Reported: {rtime_str}",
            ""
        ]
        
        if dispatch:
            lines.append("DISPATCH LOG:")
            lines.extend(["  " + d for d in dispatch])
            lines.append("")
        
        if alarms:
            lines.append("ALARM ACTIVATIONS:")
            lines.extend(["  " + a for a in alarms])
            lines.append("")
        
        if voice:
            lines.append("VOICE COMMUNICATIONS:")
            lines.extend(["  " + v for v in voice])
            lines.append("")
        
        if airs and airs[0].split('|')[0]:
            airs_parts = airs[0].split('|')
            lines.append(f"AIRS CODE: {airs_parts[0]} (confirmed by FF#{airs_parts[1]} at {airs_parts[2]})")
        else:
            lines.append("AIRS CODE: Not yet confirmed")
        
        return "\n".join(lines)
    
    return "Please specify an incident number (e.g., 'timeline for incident 15')."


# ----------------------------------------------------------------------------
# 9. Generate Incident Report (AFIRS/NFIRS)
# ----------------------------------------------------------------------------
def generate_incident_report(q: str, ff_id: str = None) -> str:
    """Generate AFIRS/NFIRS incident report."""
    import re
    m = re.search(r"incident\s+(\d+)", q)
    if not m:
        m = re.search(r"#(\d+)", q)
    if not m:
        m = re.search(r"(\d{2,})", q)
    
    if m:
        iid = m.group(1)
        
        inc = rows_as_text(f"""
            SELECT i.incident_id, i.incident_name, i.incident_type, i.status,
                   i.reported_time, i.comment, i.airs_code,
                   ff.full_name AS ff_name, ff.call_sign AS ff_call,
                   ac.airs_category, ac.airs_subcategory, ac.description AS airs_desc,
                   ac.nfirs_equivalent
            FROM gis.incidents i
            LEFT JOIN gis.firefighters ff ON ff.firefighter_id = i.firefighter_id
            LEFT JOIN gis.airs_codes ac ON ac.airs_code = i.airs_code
            WHERE i.incident_id = {iid};
        """)
        if not inc:
            return f"Incident {iid} not found."
        
        parts = inc[0].split('|')
        (incident_id, name, itype, status, reported_time, comment, airs_code,
         ff_name, ff_call, airs_cat, airs_subcat, airs_desc, nfirs) = parts
        
        # Dispatch resources
        dispatch = rows_as_text(f"""
            SELECT apparatus_call_sign || ' (' || apparatus_type || ') - ' || role
            FROM gis.dispatch_log WHERE incident_id = {iid} ORDER BY dispatched_at;
        """)
        
        # Agency notifications
        agencies = rows_as_text(f"""
            SELECT agency || ' (Ref: ' || reference_number || ') - ' || status
            FROM gis.agency_notifications WHERE incident_id = {iid};
        """)
        
        # Determine report type
        report_type = "AFIRS"
        if "nfirs" in q.lower():
            report_type = "NFIRS"
        elif "internal" in q.lower():
            report_type = "Internal"
        
        # Save report to DB
        import json
        report_data = {
            "incident_id": incident_id,
            "incident_name": name,
            "incident_type": itype,
            "status": status,
            "reported_time": reported_time,
            "airs_code": airs_code,
            "airs_category": airs_cat,
            "airs_subcategory": airs_subcat,
            "airs_description": airs_desc,
            "nfirs_equivalent": nfirs,
            "reporting_firefighter": f"{ff_name} ({ff_call})",
            "comment": comment,
            "resources": dispatch if dispatch else [],
            "agencies_notified": agencies if agencies else [],
            "report_type": report_type
        }
        
        generator_id = int(ff_id) if ff_id else 1
        run_sql(f"""
            INSERT INTO gis.incident_reports (incident_id, report_type, content_json, content_text, generated_by, status)
            VALUES ({iid}, '{report_type}', '{json.dumps(report_data).replace("'", "''")}', 
                    'Generated via voice agent', {generator_id}, 'Generated')
            ON CONFLICT DO NOTHING;
        """)
        
        lines = [
            f"{report_type} INCIDENT REPORT — {name}",
            "=" * 50,
            f"Incident ID: {incident_id}",
            f"Incident Name: {name}",
            f"Type: {itype}",
            f"Status: {status}",
            f"Date/Time: {reported_time}",
            f"Reporting Officer: {ff_name} ({ff_call})",
            f"Report Type: {report_type}",
            "",
            "AIRS CLASSIFICATION:",
            f"  Code: {airs_code or 'Not assigned'}",
            f"  Category: {airs_cat or 'N/A'} / {airs_subcat or 'N/A'}",
            f"  Description: {airs_desc or 'N/A'}",
            f"  NFIRS Equivalent: {nfirs or 'N/A'}",
            "",
            "NARRATIVE:",
            f"  {comment or 'No narrative recorded'}",
            "",
            "RESOURCES DISPATCHED:"
        ] + (["  " + d for d in dispatch] if dispatch else ["  None recorded"]) + [
            "",
            "AGENCIES NOTIFIED:"
        ] + (["  " + a for a in agencies] if agencies else ["  None recorded"]) + [
            "",
            f"Report saved to database. Reference: {report_type}-{iid}-{reported_time[:10].replace('-', '')}"
        ]
        
        return "\n".join(lines)
    
    return "Please specify an incident number (e.g., 'generate report for incident 15')."


# ----------------------------------------------------------------------------
# 10. Debrief Mode / After Action Review
# ----------------------------------------------------------------------------
def debrief_incident(q: str, ff_id: str = None) -> str:
    """Generate after-action debrief with SOP compliance check."""
    import re
    m = re.search(r"incident\s+(\d+)", q)
    if not m:
        m = re.search(r"#(\d+)", q)
    if not m:
        m = re.search(r"(\d{2,})", q)
    
    if m:
        iid = m.group(1)
        
        inc = rows_as_text(f"""
            SELECT incident_name, incident_type, status, reported_time, comment, airs_code
            FROM gis.incidents WHERE incident_id = {iid};
        """)
        if not inc:
            return f"Incident {iid} not found."
        
        name, itype, status, rtime, comment, airs_code = inc[0].split('|')
        
        # Dispatch timeline
        dispatch = rows_as_text(f"""
            SELECT apparatus_call_sign || ' | ' || role || ' | ' ||
                   to_char(dispatched_at, 'HH24:MI') || ' → ' ||
                   COALESCE(to_char(arrived_at, 'HH24:MI'), 'pending')
            FROM gis.dispatch_log WHERE incident_id = {iid} ORDER BY dispatched_at;
        """)
        
        # Response times
        if dispatch:
            first_arrival = rows_as_text(f"""
                SELECT min(arrived_at) FROM gis.dispatch_log 
                WHERE incident_id = {iid} AND arrived_at IS NOT NULL;
            """)
            if first_arrival and first_arrival[0]:
                from datetime import datetime
                reported = datetime.fromisoformat(rtime.replace(' ', 'T'))
                arrived = datetime.fromisoformat(first_arrival[0].replace(' ', 'T'))
                response_min = int((arrived - reported).total_seconds() / 60)
            else:
                response_min = None
        else:
            response_min = None
        
        # Voice decisions
        voice = rows_as_text(f"""
            SELECT to_char(created_at, 'HH24:MI') || ' | ' ||
                   COALESCE(ff.call_sign, 'FF') || ': ' || question
            FROM gis.conversation_log cl
            LEFT JOIN gis.firefighters ff ON ff.firefighter_id = cl.firefighter_id
            WHERE cl.question ILIKE '%{name.replace("'", "")}%'
               OR cl.question ILIKE '%incident {iid}%'
            ORDER BY cl.created_at;
        """)
        
        # Relevant SOPs
        sop_matches = rows_as_text(f"""
            SELECT sop_number, title, content
            FROM gis.standard_operating_procedures
            WHERE '{itype}' = ANY(incident_types)
               OR EXISTS (
                   SELECT 1 FROM unnest(keywords) kw 
                   WHERE '{name.lower()}' ILIKE '%' || kw || '%'
                      OR '{comment.lower()}' ILIKE '%' || kw || '%'
               )
            ORDER BY sop_number;
        """)
        
        lines = [
            f"AFTER-ACTION DEBRIEF: {name} (Incident #{iid})",
            "=" * 55,
            f"Type: {itype} | Status: {status} | AIRS: {airs_code or 'Unassigned'}",
            f"Response Time: {f'{response_min} min' if response_min else 'Not recorded'}",
            "",
            "RESOURCE TIMELINE:"
        ] + (["  " + d for d in dispatch] if dispatch else ["  No dispatch log"]) + [
            "",
            "KEY VOICE DECISIONS/QUERIES:"
        ] + (["  " + v for v in voice] if voice else ["  No voice log entries"]) + [
            "",
            "SOP COMPLIANCE CHECK:"
        ]
        
        if sop_matches:
            for sop in sop_matches:
                parts = sop.split('|', 2)
                if len(parts) >= 3:
                    lines.append(f"  ✓ {parts[0]}: {parts[1]}")
                    lines.append(f"    Key guidance: {parts[2][:100]}...")
        else:
            lines.append("  No specific SOPs matched for this incident type")
        
        # Lessons learned prompt
        lines.extend([
            "",
            "DEBRIEF QUESTIONS FOR REVIEW:",
            "  1. Was initial size-up accurate? (360° completed?)",
            "  2. Water supply established per SOP 4.1? (Forward lay / tanker shuttle)",
            "  3. Search & rescue: Primary/Secondary completed? (SOP 5.1)",
            "  4. Ventilation coordinated with attack? (Horizontal vs Vertical)",
            "  5. RIT established and staged? (SOP 1.1)",
            "  6. Communications: Any breakdowns? (Fireground channels)",
            "  7. Safety: Any near-misses or injuries?",
            "  8. Resource allocation: Adequate? Escalation timely? (SOP 6.1)",
            "  9. Multi-agency coordination effective?",
            "  10. Documentation: AIRS code confirmed? Report generated?",
            "",
            "Save debrief? Say 'save debrief for incident " + iid + "' to store."
        ])
        
        return "\n".join(lines)
    
    return "Please specify an incident number (e.g., 'debrief incident 15')."


# ----------------------------------------------------------------------------
# Twilio SMS — send a firefighter's GPS coordinates to dispatch
# ----------------------------------------------------------------------------
_twilio = None

def _load_twilio():
    """Load Twilio creds from ~/.hermes/twilio/.env (cached)."""
    global _twilio
    if _twilio is not None:
        return _twilio
    cfg = {}
    path = os.path.expanduser("~/.hermes/twilio/.env")
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    cfg[k.strip()] = v.strip()
    except FileNotFoundError:
        cfg = {}
    _twilio = cfg
    return cfg


def send_sms(body: str) -> dict:
    """Send an SMS via Twilio. Returns {'ok': True, ...} or {'ok': False, 'error': msg}."""
    cfg = _load_twilio()
    acct = cfg.get("TWILIO_ACCOUNT_SID", "")
    token = cfg.get("TWILIO_AUTH_TOKEN", "")
    to = cfg.get("TWILIO_TO_VERIFIED", "")
    fr = cfg.get("TWILIO_FROM_NUMBER", "")
    if not (acct and token and to and fr):
        return {"ok": False, "error": "Twilio not fully configured in ~/.hermes/twilio/.env"}
    data = f"To={to}&From={fr}&Body={urllib.parse.quote(body)}".encode()
    req = urllib.request.Request(
        f"https://api.twilio.com/2010-04-01/Accounts/{acct}/Messages.json",
        data=data, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    import base64
    auth = "Basic " + base64.b64encode(f"{acct}:{token}".encode()).decode()
    req.add_header("Authorization", auth)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            resp = json.loads(r.read().decode())
            return {"ok": True, "sid": resp.get("sid"), "status": resp.get("status")}
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read().decode())
            return {"ok": False, "error": err.get("message", str(e))}
        except Exception:
            return {"ok": False, "error": f"HTTP {e.code}"}


def parse_coordinates(text: str):
    """Pull a (lat, lon) pair from free text. Accepts:
      - '37.8089, 144.9754' (comma/slash/space separated)
      - 'latitude -37.8145 longitude 144.9632'
      - 'lat 37.8 lon 144.9'
    Returns (lat, lon) or None."""
    # Pattern 1: latitude/longitude labels (possibly abbreviated)
    m = re.search(r"lat(?:itude)?\s*[=:]?\s*([-+]?\d{1,3}\.\d+).{0,8}?lon(?:gitude)?\s*[=:]?\s*([-+]?\d{1,3}\.\d+)", text, re.I)
    if m:
        lat, lon = float(m.group(1)), float(m.group(2))
        if -90 <= lat <= 90 and -180 <= lon <= 180:
            return (lat, lon)
    # Pattern 2: two numbers separated by comma/slash/whitespace
    for m in re.finditer(r"([-+]?\d{1,3}\.\d+)\s*[,/\\]\s*([-+]?\d{1,3}\.\d+)", text):
        lat, lon = float(m.group(1)), float(m.group(2))
        if -90 <= lat <= 90 and -180 <= lon <= 180:
            return (lat, lon)
    return None


def repl_link(escaped_html):
    """Turn http(s) URLs inside an already-HTML-escaped string into clickable <a> links."""
    return re.sub(
        r"(https?://[^\s<>\"']+)",
        lambda m: f'<a href="{m.group(1)}" style="color:#1a73e8;font-weight:bold">{m.group(1)}</a>',
        escaped_html,
    )


def send_agentmail(to, subject, text, html=None) -> dict:
    """Send email via AgentMail. Returns {'ok': True, 'id': ...} or {'ok': False, 'error': msg}.
    Uses the inbox + key from ~/.hermes/twilio/agentmail.env (or Hermes config's key).
    If html is provided it is sent alongside text so hyperlinks render clickable."""
    cfg = os.path.expanduser("~/.hermes/twilio/agentmail.env")
    inbox = ""
    key = os.environ.get("AGENTMAIL_API_KEY", "")
    if os.path.exists(cfg):
        with open(cfg) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    if k.strip() == "AGENTMAIL_INBOX":
                        inbox = v.strip()
                    if k.strip() == "AGENTMAIL_API_KEY":
                        key = v.strip()
    if not inbox:
        # fall back to reading from Hermes config
        try:
            with open(os.path.expanduser("~/.hermes/config.yaml")) as f:
                txt = f.read()
            m = re.search(r"AGENTMAIL_API_KEY:\s*[\"']([^\"']+)", txt)
            if m:
                key = m.group(1)
        except Exception:
            pass
        inbox = "mohammad-9483@agentmail.to"  # discovered default
    if not key:
        return {"ok": False, "error": "AgentMail key not configured"}
    data = {"to": to, "subject": subject, "text": text}
    if html:
        data["html"] = html
    payload = json.dumps(data).encode()
    req = urllib.request.Request(
        f"https://api.agentmail.to/v0/inboxes/{urllib.parse.quote(inbox)}/messages/send",
        data=payload, method="POST",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            resp = json.loads(r.read().decode())
            return {"ok": True, "message_id": resp.get("message_id"), "thread_id": resp.get("thread_id")}
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read().decode())
            return {"ok": False, "error": err.get("message", str(e))}
        except Exception:
            return {"ok": False, "error": f"HTTP {e.code}"}


def handle_location_intent(question: str, ff_email: str = None) -> str:
    """When a firefighter asks to send/email a location (hydrant, station, etc.),
    look up the coordinates and EMAIL them a Google Maps navigation link.
    Simple — no asking for their GPS, no confirmation dance.
    Returns the spoken reply."""
    ql = (question or "").lower()

    # Figure out which resource they want coordinates for
    if "hydrant" in ql:
        rows = rows_as_text("""
            SELECT h.hydrant_number, round(ST_Y(h.geom)::numeric,6),
                   round(ST_X(h.geom)::numeric,6)
            FROM gis.hydrants h WHERE h.status='Operational'
            ORDER BY ST_Distance(
                (SELECT geom FROM gis.incidents WHERE status='Active'
                 ORDER BY reported_time DESC LIMIT 1)::geography, h.geom::geography)
            LIMIT 1;
        """)
        if not rows:
            return "I could not find an operational hydrant to send."
        num, lat, lon = rows[0].split("|")
        label = f"Hydrant {num}"
    elif "sprinkler" in ql or "sprinklers" in ql:
        # Sprinkler systems are stored in gis.assets (type 'Sprinkler') with capacity.
        # If a property name/site is mentioned, target that site's sprinkler.
        _prop_pid, _prop_name = _resolve_property_from_name(question)
        if _prop_pid:
            rows = rows_as_text(f"""
                SELECT a.asset_name, round(ST_Y(a.geom)::numeric,6), round(ST_X(a.geom)::numeric,6),
                       COALESCE(a.capacity_litres::text,'')
                FROM gis.assets a
                WHERE a.asset_type ILIKE 'sprinkler'
                  AND a.geom = (SELECT geom FROM gis.properties WHERE property_id={_prop_pid})
                ORDER BY a.asset_name LIMIT 1;
            """)
            # fallback: match by the property's dominant token in the asset name
            if not rows:
                _tok = (_prop_name or "").lower().split()
                rows = rows_as_text(f"""
                    SELECT a.asset_name, round(ST_Y(a.geom)::numeric,6), round(ST_X(a.geom)::numeric,6),
                           COALESCE(a.capacity_litres::text,'')
                    FROM gis.assets a
                    WHERE a.asset_type ILIKE 'sprinkler'
                      AND a.asset_name ILIKE '%{_tok[0]}%' ORDER BY a.asset_name LIMIT 1;
                """) if _tok else []
        else:
            rows = rows_as_text("""
                SELECT a.asset_name,
                       round(ST_Y(a.geom)::numeric,6), round(ST_X(a.geom)::numeric,6),
                       COALESCE(a.capacity_litres::text,'')
                FROM gis.assets a
                WHERE a.asset_type ILIKE 'sprinkler'
                ORDER BY a.asset_name LIMIT 1;
            """)
        if not rows:
            return "I could not find a sprinkler system to send."
        name, lat, lon, cap = rows[0].split("|")
        cap_txt = f" ({int(cap):,} L)" if cap and cap.isdigit() else ""
        label = f"{name}{cap_txt}"
    elif "station" in ql:
        rows = rows_as_text("""
            SELECT station_name, round(ST_Y(geom)::numeric,6), round(ST_X(geom)::numeric,6)
            FROM gis.fire_stations ORDER BY station_id LIMIT 1;
        """)
        if not rows:
            return "I could not find a station to send."
        label, lat, lon = rows[0].split("|")
        label = f"Fire Station {label}"
    elif "water" in ql or "tank" in ql:
        # If they said "tank", prefer a Water Tank source; otherwise nearest source.
        _tank_q = " AND source_type ILIKE '%tank%' " if "tank" in ql else ""
        rows = rows_as_text(f"""
            SELECT COALESCE(source_name,'Water source'), round(ST_Y(geom)::numeric,6),
                   round(ST_X(geom)::numeric,6)
            FROM gis.water_sources
            WHERE TRUE {_tank_q}
            ORDER BY capacity_litres DESC NULLS LAST LIMIT 1;
        """)
        if not rows:
            return "I could not find a water source to send."
        label, lat, lon = rows[0].split("|")
        label = f"Water Source {label}"
    else:
        # generic: nearest active incident location
        rows = rows_as_text("""
            SELECT incident_name, round(ST_Y(geom)::numeric,6), round(ST_X(geom)::numeric,6)
            FROM gis.incidents WHERE status='Active'
            ORDER BY reported_time DESC LIMIT 1;
        """)
        if not rows:
            return "I could not find a location to send."
        label, lat, lon = rows[0].split("|")
        label = f"Incident {label}"

    lat, lon = float(lat), float(lon)
    to = ff_email or "Tauseefau@live.com"
    maps = f"https://www.google.com/maps/dir/?api=1&destination={lat},{lon}"
    body = (f"FIRE DISPATCH - {label}\n"
            f"Coordinates: {lat:.6f}, {lon:.6f}\n"
            f"Open in navigation: {maps}\n"
            f"(Sent by fire service voice agent)")
    # HTML body so the Google Maps link is a real clickable hyperlink.
    esc_label = label.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    html_body = (
        "<div style=\"font-family:Arial,Helvetica,sans-serif;font-size:14px;line-height:1.6\">"
        f"<p style=\"margin:0 0 12px\"><b style=\"font-size:16px\">🚒 FIRE DISPATCH — {esc_label}</b></p>"
        f"<p style=\"margin:0 0 6px\">📍 Coordinates: <b>{lat:.6f}, {lon:.6f}</b></p>"
        f"<p style=\"margin:0 0 14px\">🗺️ Open in navigation: "
        f"<a href=\"{maps}\" style=\"color:#1a73e8;font-weight:bold\">{maps}</a></p>"
        "<p style=\"margin:0;color:#555;font-size:12px\">(Sent by fire service voice agent)</p>"
        "</div>"
    )
    res = send_agentmail(to, f"Fire dispatch - {label} location", body, html_body)
    if res.get("ok"):
        return (f"I have emailed you the location of {label}. "
                f"Coordinates: {lat:.5f}, {lon:.5f}. Open your email for the navigation link.")
    return (f"I could not send the email right now: {res.get('error')}. "
            f"The location of {label} is lat {lat:.5f}, lon {lon:.5f}.")


# ----------------------------------------------------------------------------
# HTTP handler — routes both webhook and property REST API
# ----------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    def _json(self, obj, code=200):
        payload = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        u = urlparse(self.path)
        path = u.path

        if path == "/":
            return self._json({"ok": True, "service": "fire-db-webhook"})

        # Property search: /property?name=X
        if path == "/property" or path == "/property/":
            qs = parse_qs(u.query)
            name = qs.get("name", [""])[0].strip()
            if not name:
                return self._json({"error": "provide ?name= to search"}, 400)
            rows = rows_as_text(f"""
                SELECT property_id || '|' || property_name || '|' || property_type
                FROM gis.properties
                WHERE property_name ILIKE '%{name.replace("'", "")}%'
                   OR property_type ILIKE '%{name.replace("'", "")}%'
                   OR CAST(property_id AS text) = '{name.replace("'", "")}'
                ORDER BY property_id LIMIT 20;
            """)
            items = [r.split("|") for r in rows]
            return self._json({"results": [
                {"property_id": int(a), "name": b, "type": c} for a, b, c in items
            ]})

        # Property detail: /property/<id>
        if path.startswith("/property/"):
            parts = path.strip("/").split("/")  # property, <id>, [notes]
            pid = parts[1] if len(parts) > 1 else ""
            if not pid.isdigit():
                return self._json({"error": "bad property id"}, 400)
            # notes-only route
            if len(parts) >= 3 and parts[2] == "notes":
                rows = rows_as_text(f"""
                    SELECT cn.note_id || '|' || COALESCE(ff.full_name,'-') || '|' ||
                           COALESCE(ff.call_sign,'-') || '|' ||
                           to_char(cn.created_at,'YYYY-MM-DD HH24:MI') || '|' || cn.note_text
                    FROM gis.call_notes cn
                    LEFT JOIN gis.firefighters ff ON ff.firefighter_id = cn.firefighter_id
                    WHERE cn.property_id = {pid} ORDER BY cn.created_at DESC;
                """)
                notes = [r.split("|") for r in rows]
                return self._json({"notes": [
                    {"note_id": int(n[0]), "firefighter": n[1], "call_sign": n[2],
                     "created_at": n[3], "text": n[4]} for n in notes
                ]})

            prop = rows_as_text(f"""
                SELECT property_id || '|' || property_name || '|' || property_type ||
                       '|' || ST_AsText(geom)
                FROM gis.properties WHERE property_id = {pid};
            """)
            if not prop:
                return self._json({"error": "property not found"}, 404)
            pid2, name, ptype, geom = prop[0].split("|", 3)

            incidents = rows_as_text(f"""
                SELECT incident_name || '|' || incident_type || '|' || status ||
                       '|' || to_char(reported_time,'YYYY-MM-DD HH24:MI')
                FROM gis.incidents WHERE ST_DWithin(
                    geom::geography, (SELECT geom FROM gis.properties WHERE property_id={pid})::geography, 1000);
            """)
            alarms = rows_as_text(f"""
                SELECT alarm_type || '|' || outcome || '|' ||
                       to_char(alarm_date,'YYYY-MM-DD HH24:MI')
                FROM gis.alarms WHERE property_id = {pid} ORDER BY alarm_date DESC;
            """)
            notes = rows_as_text(f"""
                SELECT COALESCE(ff.call_sign,'-') || '|' ||
                       to_char(cn.created_at,'YYYY-MM-DD HH24:MI') || '|' || cn.note_text
                FROM gis.call_notes cn
                LEFT JOIN gis.firefighters ff ON ff.firefighter_id = cn.firefighter_id
                WHERE cn.property_id = {pid} ORDER BY cn.created_at DESC;
            """)
            return self._json({
                "property": {"property_id": int(pid2), "name": name, "type": ptype, "geom": geom},
                "incidents_nearby": [r.split("|") for r in incidents],
                "alarms": [r.split("|") for r in alarms],
                "notes": [r.split("|") for r in notes],
            })

        # Incident detail: /incident/<id>
        if path.startswith("/incident/"):
            parts = path.strip("/").split("/")
            iid = parts[1] if len(parts) > 1 else ""
            if not iid.isdigit():
                return self._json({"error": "bad incident id"}, 400)
            inc = rows_as_text(f"""
                SELECT i.incident_id || '|' || COALESCE(i.incident_name,'Incident #'||i.incident_id) || '|' ||
                       COALESCE(i.incident_type,'') || '|' || COALESCE(i.status,'') || '|' ||
                       COALESCE(to_char(i.reported_time,'YYYY-MM-DD HH24:MI'),'') || '|' ||
                       COALESCE(i.airs_code,'') || '|' || COALESCE(i.comment,'') || '|' ||
                       COALESCE(round(ST_Y(i.geom)::numeric,6)::text,'') || '|' ||
                       COALESCE(round(ST_X(i.geom)::numeric,6)::text,'') || '|' ||
                       COALESCE(ff.full_name,'') || '|' || COALESCE(ff.call_sign,'') || '|' ||
                       COALESCE(to_char(i.airs_confirmed_at,'YYYY-MM-DD HH24:MI'),'') || '|' ||
                       COALESCE(i.airs_confirmed_by::text,'')
                FROM gis.incidents i
                LEFT JOIN gis.firefighters ff ON ff.firefighter_id = i.firefighter_id
                WHERE i.incident_id = {iid};
            """)
            if not inc:
                return self._json({"error": "incident not found"}, 404)
            p = inc[0].split("|")
            info = {
                "incident_id": int(p[0]), "name": p[1], "type": p[2], "status": p[3],
                "reported": p[4], "airs_code": p[5], "comment": p[6],
                "lat": p[7] or None, "lon": p[8] or None,
                "firefighter": p[9], "call_sign": p[10],
                "airs_confirmed_at": p[11], "airs_confirmed_by": p[12] or None,
            }
            # nearest property
            nearprop = rows_as_text(f"""
                SELECT p.property_id || '|' || COALESCE(p.property_name,'') || '|' ||
                       COALESCE(p.property_type,'') || '|' ||
                       round(ST_Distance(p.geom::geography, (SELECT geom FROM gis.incidents WHERE incident_id={iid})::geography)::numeric,0)::text
                FROM gis.properties p
                WHERE ST_DWithin(p.geom::geography, (SELECT geom FROM gis.incidents WHERE incident_id={iid})::geography, 1000)
                ORDER BY ST_Distance(p.geom::geography, (SELECT geom FROM gis.incidents WHERE incident_id={iid})::geography)
                LIMIT 1;
            """)
            nearest_property = None
            if nearprop:
                q = nearprop[0].split("|")
                nearest_property = {"property_id": int(q[0]), "name": q[1], "type": q[2], "dist_m": int(q[3] or -1)}
            disp = rows_as_text(f"""
                SELECT COALESCE(d.apparatus_call_sign,'') || '|' || COALESCE(d.apparatus_type,'') || '|' ||
                       COALESCE(d.station_name,'') || '|' || COALESCE(d.role,'') || '|' ||
                       COALESCE(to_char(d.dispatched_at,'YYYY-MM-DD HH24:MI'),'') || '|' ||
                       COALESCE(to_char(d.arrived_at,'YYYY-MM-DD HH24:MI'),'') || '|' ||
                       COALESCE(to_char(d.cleared_at,'YYYY-MM-DD HH24:MI'),'') || '|' ||
                       COALESCE(d.notes,'')
                FROM gis.dispatch_log d WHERE d.incident_id = {iid} ORDER BY d.dispatched_at;
            """)
            dispatch = []
            for r in disp:
                q = r.split("|")
                if len(q) >= 8:
                    dispatch.append({"call_sign": q[0], "type": q[1], "station": q[2], "role": q[3],
                                     "dispatched": q[4], "arrived": q[5], "cleared": q[6], "notes": q[7]})
            return self._json({"incident": info, "nearest_property": nearest_property, "dispatch": dispatch})

        return self._json({"error": "not found"}, 404)

    def do_POST(self):
        u = urlparse(self.path)
        path = u.path
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) or b"{}"
        try:
            body = json.loads(raw)
        except Exception:
            body = {}

        # Generic email-send: chat can email any data result to any address.
        if path in ("/email", "/send-email", "/api/email"):
            to = str(body.get("to") or body.get("email") or "").strip()
            subject = str(body.get("subject") or "Fire Services Dispatch data").strip()
            text = str(body.get("text") or body.get("body") or "").strip()
            if not to or "@" not in to or not text:
                return self._json({"error": "to and text are required"}, 400)
            # Build a clickable-HTML body: auto-link any http(s) URLs in the text.
            esc = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            html = ("<div style='font-family:Arial,Helvetica,sans-serif;font-size:14px;line-height:1.6'>"
                    + repl_link(esc) + "</div>")
            res = send_agentmail(to, subject, text, html)
            if res.get("ok"):
                return self._json({"ok": True, "message_id": res.get("message_id"),
                                   "message": f"Email sent to {to}"})
            return self._json({"ok": False, "error": res.get("error")}, 500)

        # ElevenLabs webhook tool
        if path in ("/", "/tool", "/fire-agent/tool") or body.get("tool_name"):
            tool_input = str(body.get("tool_input") or body.get("query") or "")
            # try simple extraction of firefighter id for logging
            ff_id = None
            pid = None
            q = tool_input.lower()
            m = re.search(r"auth_el_(\d+)", q, re.I)
            if m:
                ff_id = m.group(1)
            elif not ff_id:
                # Recovery: a firefighter mid-guided-flow may not repeat their ID.
                # If someone has an active agent_state, assume it's the same caller.
                strows = rows_as_text(
                    "SELECT firefighter_id FROM gis.agent_state "
                    "ORDER BY updated_at DESC LIMIT 1")
                if strows and strows[0].strip().isdigit():
                    ff_id = strows[0].strip()
            m2 = re.search(r"property\s+(\d+)", q)
            if m2:
                pid = m2.group(1)
            # Look up the firefighter's email for delivery (if they identified)
            ff_email = None
            if ff_id:
                em = rows_as_text(f"SELECT email FROM gis.firefighters WHERE firefighter_id={ff_id} AND active=TRUE;")
                if em:
                    ff_email = em[0]
            # Location intent: firefighter asks to EMAIL/SEND coordinates of a
            # location (hydrant, station, etc.) for navigation. Simple; emails it.
            wants_email = any(w in q.split() for w in ("email", "send", "navigate", "navigation", "map", "nav"))
            is_location_q = any(w in q for w in ("hydrant", "hydrants", "sprinkler", "sprinklers",
                                                 "location", "station", "water", "tank", "tanks",
                                                 "gps", "coordinate", "coordinates", "source", "sources"))
            if wants_email and is_location_q:
                reply_text = handle_location_intent(tool_input, ff_email)
                log_conversation(tool_input, reply_text, ff_id, pid)
                return self._json({"reply": reply_text})
            reply_text = answer(tool_input)
            # Identity confirmation: a bare firefighter id (no real question)
            # is treated as a call-in/identification, so confirm the name.
            if ff_id:
                nm = get_firefighter_name(ff_id)
                if nm:
                    full, first = nm
                    rest = re.sub(r"\s*auth_el_\d+\s*", " ", q).strip()
                    if not rest:
                        reply_text = (f"Am I speaking to firefighter {full}? "
                                      f"Please confirm, or tell me what you need, {first}.")
                    else:
                        # Only prefix the caller's name if the reply doesn't already
                        # address them (the guided flow already says e.g. 'OK Sarah').
                        if first not in reply_text:
                            reply_text = f"Thank you, {first}. {reply_text.strip()}"
            log_conversation(tool_input, reply_text, ff_id, pid)
            return self._json({"reply": reply_text})

        if path.startswith("/property/"):
            parts = path.strip("/").split("/")
            pid = parts[1] if len(parts) > 1 else ""
            if not pid.isdigit():
                return self._json({"error": "bad property id"}, 400)
            action = parts[2] if len(parts) > 2 else ""
            if action == "note":
                text = str(body.get("note_text") or "").strip()
                if not text:
                    return self._json({"error": "note_text required"}, 400)
                ff = body.get("firefighter_id")
                if ff is not None and str(ff).isdigit():
                    ffval = str(ff)
                else:
                    ffval = "NULL"
                run_sql(f"""
                    INSERT INTO gis.call_notes (property_id, firefighter_id, note_text)
                    VALUES ({pid}, {ffval}, __t__);
                """.replace("__t__", "'" + text.replace("'", "''") + "'"))
                return self._json({"ok": True, "message": "note added"})
            return self._json({"error": "unknown action"}, 400)

        if path == "/conversation":
            question = str(body.get("question") or "")
            answer_text = str(body.get("answer") or "")
            ff = body.get("firefighter_id")
            pid = body.get("property_id")
            if not question:
                return self._json({"error": "question required"}, 400)
            log_conversation(question, answer_text, ff if ff else None, pid if pid else None)
            return self._json({"ok": True, "message": "logged"})

        return self._json({"error": "not found"}, 404)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--host", default="127.0.0.1")
    args = p.parse_args()
    print(f"Fire DB backend listening on http://{args.host}:{args.port}", flush=True)
    HTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()