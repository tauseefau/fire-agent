---
# SETUP PROMPT — give this verbatim to a fresh agent on a target system
# (Hermes, OpenCode, Claude Code, or any CLI agent with shell + web access).
# No prior context needed. It is self-contained.
---

You are a DevOps agent. Recreate the **DiYYourData Fire Services + business
stack** on this new system from two GitHub repos. Follow in order. Verify each
stage before moving on. Do not skip steps. Ask the operator only for secrets
marked `$SECRET`.

## Repositories

1. **fire-agent** — backend + voice-agent + Postgres model
   `git@github.com:tauseefau/fire-agent.git`
   - `docs/ARCHITECTURE.md` — service topology, voice-agent behaviour, restore/copy
   - `docs/SETUP-PROMPT.md` — this file
   - `db/DATA_MODEL.md` — data model + restoration procedures
   - `db/SHARED-schema.sql` — authoritative PostGIS schema dump (`gis`,`ai`,`analytics`)
   - `scripts/*.py` — three service backends
   - `systemd/*.service` — service units
   - `tool_server.py` — ElevenLabs voice-agent webhook
2. **diyyourdata-web** — business React site + gated fire showcase + nginx routing
   `git@github.com:tauseefau/diyyourdata-web.git`
   - `docs/ARCHITECTURE.md` — site, routing, signup gate, booking flow, restore

Read both `docs/ARCHITECTURE.md` files **first**. They are the source of truth.

## Target environment

- Ubuntu 24.04 LTS (arm64 or amd64), Docker + docker compose available,
  nginx or HestiaCP vhost `diyyourdata.com`, Python 3.12, git, sudo.
- Two repos cloned: `git clone git@github.com:tauseefau/fire-agent.git ./fire-agent`
  and `git clone git@github.com:tauseefau/diyyourdata-web.git ./diyyourdata-web`.

## Secrets — collect once at start, never write to files in the repos

- `$PGPASSWORD` — Postgres superuser password.
- `$PBI_PASS` — read-only Power BI user password (optional).
- `$ELEVEN_KEY` — ElevenLabs API key (voice agent only — skip if none).
- `$AGENTMAIL` — AgentMail MCP credentials (email feature — skip if none).
- `$N8N_API_KEY` — n8n API key (auto-deploy/booking — skip if none).
Use `$SECRET` literal if unavailable. Keep out of git (`.env`, `wp-config.php`
are git-ignored).

## Step 1 — Postgres data store

1. Start a postgis container exactly as in `fire-agent/db/DATA_MODEL.md` §7-A:
   image `pg15postgis:arm64` (or `postgres:15` + PostGIS extension if not
   present), container `postgres-db-1`, host 5433→5432, db `fire_services`,
   user `tauseef`, password `$PGPASSWORD`.
2. Apply schema: `docker cp fire-agent/db/SHARED-schema.sql postgres-db-1:/tmp/`
   then `psql -U tauseef -d fire_services -f /tmp/SHARED-schema.sql`.
3. Verify: `SELECT postgis_version();` → 3.x; schemas `gis`,`ai`,`analytics`,
   `topology` exist.
4. If the operator has a data dump (`fire_data.dump`), restore data per
   `DATA_MODEL.md` §7-B. Else leave schema-only (application works, empty data).

## Step 2 — Python backends (fire-agent)

1. Create venv: `python3 -m venv /opt/fire-agent-venv`; install `edge-tts`.
2. Review `systemd/*.service` — adjust `WorkingDirectory`, `ExecStart`, env path
   to `/opt/fire-agent-venv`, `/home/<user>/.hermes/...` as needed for this host.
3. Create `~/.hermes/.env` (0600) with: `PGPASSWORD=$PGPASSWORD`, and any of
   `N8N_BASE_URL`, `N8N_API_KEY`, `ELEVENLABS_API_KEY` if present.
4. Install + enable units:
   `sudo cp systemd/*.service /etc/systemd/system/` → `daemon-reload` →
   `sudo systemctl enable --now fire-agent-tool dashboard-api firis-tts`.
5. Verify each port listening: 8000, 8001, 8002. `curl localhost:8001` returns one HTTP code not 000.

## Step 3 — Website + nginx routing (diyyourdata-web)

1. Copy repo contents → webroot `public_html` (e.g. `/var/www/diyyourdata.com/public_html`).
2. Publish business site: `cp business.html index.html`.
3. Create the signup table in the site DB (WordPress MySQL or a MySQL db):
   run the `CREATE TABLE showcase_signups ...` statement from
   `diyyourdata-web/docs/ARCHITECTURE.md` §4/§6.
4. Install nginx include:
   `sudo cp diyyourdata-web/nginx/nginx.ssl.conf_fire /etc/nginx/conf.d/`
   (or HestiaCP: `/home/<user>/conf/web/diyyourdata.com/nginx.ssl.conf_fire`).
   Tune `proxy_pass` hosts:8000/8001/8002 to localhost.
5. Ensure `showcase-gate.php`/`showcase-auth.php` read DB constants from
   `wp-config.php` (or adjust their `require` + PDO DSN for this host).
6. Reload: `sudo nginx -t && sudo nginx -s reload` (or Hestia `systemctl reload nginx`).

## Step 4 — Booking → Google Calendar (optional, requires n8n)

- If `$N8N_API_KEY` provided: recreate the n8n webhook workflow
  `hermes-booking-google-calendar` (see `diyyourdata-web/docs/ARCHITECTURE.md`
  §3) that parses `{name,email,service,date,time,message}` and creates a Google
  Calendar event. Authorise Google creds in n8n UI.

## Step 5 — Verification (all must pass)

- `curl -s -o /dev/null -w "%{http_code}" https://diyyourdata.com/` → 200, body
  contains "diyyourdata AI Automation".
- `/fire/` without cookie → 302/redirect to `showcase-gate.php`.
- `showcase-gate.php` renders CAPTCHA + signup fields; submitting with correct
  CAPTCHA inserts a row and sets `dsgx_auth` cookie; `/fire/` then → 200.
- Ports 8000/8001/8002 listening.
- `docker exec postgres-db-1 psql ... -c "select 1"` returns 1.
- `npx`-free sanity: `grep -q type="text/babel" index.html`.

## Rules

- Read the two `ARCHITECTURE.md` files before touching any YAML/PHP/Python.
- Never commit secrets. `.env` and `wp-config.php` stay git-ignored.
- Ports / container name / db name are fixed by convention; change only if the
  target host conflicts.
- If a step fails, fix the cause, don't paper over; report the exact error line.

Finish by printing a short deployment report: services running, ports, DB
schema applied, nginx routes live, gate verified, and any skipped optional
features (ElevenLabs, n8n, AgentMail).