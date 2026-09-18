# fire-agent — Architecture & Restoration Guide

Complete design document for an AI agent to **recreate, restore, or copy** the
DiYYourData Fire Services voice-agent + backend stack from this repository.

---

## 1. System overview

The fire-agent is the backend + ElevenLabs voice-agent orchestration layer behind
the **di.your-data.com fire-services showcase**. It is the domain engine: it knows
every incident, station, hydrant, asset, firefighter, SOP, alarm, and conversation
in Melbourne's simulated FRV brigade, and lets both a **voice agent** (ElevenLabs
webhook) and the **web dashboard** query and mutate that domain.

Three long-running services (systemd) on a single Oracle free VM (Ubuntu 24.04
arm64):

| Unit | Script | Port | Role |
|---|---|---|---|
| `fire-agent-tool.service` | `tool_server.py` | **8000** | ElevenLabs voice-agent webhook + REST domain API |
| `dashboard-api.service` | `dashboard_api.py` | **8001** | Analytics / map / survey / ArcGIS-proxy API for web |
| `firis-tts.service` | `firis_tts_server.py` | **8002** | Local Edge-TTS HTTP audio endpoint |

All three read secrets from `~/.hermes/.env` at runtime (never committed).

---

## 2. Service topology

```
                    ┌──────────────────────────────────────────────┐
                    │         Oracle VM (168.138.14.148)           │
                    │                                              │
  ElevenLabs ──────▶│  :8000  fire-agent-tool (tool_server.py)     │
  voice call        │         · webhook /elevenlabs                │
                    │         · REST  /agent, /incident, ...       │
                    │                                              │
  Web browsers ────▶│  :8001  dashboard-api (dashboard_api.py)     │
  diyyourdata.com   │         · /api/map /api/nearby /api/surveys   │
  (nginx proxy)     │         · /timeline/api/* ArcGIS proxy       │
                    │                                              │
  Firis chat page ─▶│  :8002  firis-tts (firis_tts_server.py)      │
                    │         · /tts  → Edge-TTS MP3              │
                    │                                              │
                    │        Docker: postgres-db-1  (:5433 → 5432) │
                    │        fire_services DB (PostGIS 3.6.4)      │
                    └──────────────────────────────────────────────┘
```

- **Nginx** (HestiaCP) terminates TLS for `diyyourdata.com` and proxies:
  - `/fire-agent/tool` → `127.0.0.1:8000`
  - `/timeline/api/*`  → `127.0.0.1:8001`
  - `/firis-tts/*`     → `127.0.0.1:8002`
  via the custom include `nginx.ssl.conf_fire` (lives in the `diyyourdata-web`
  repo, survives HestiaCP rebuilds).
- **Postgres** runs in Docker, host port 5433 mapped to container 5432,
  database `fire_services`, superuser `tauseef`.

---

## 3. Voice agent behaviour (tool_server.py)

`tool_server.py` (~123 KB) is the heart. It implements a **guided,
confirm-driven** dialogue exactly matching the AIRS / incident-completion
pattern:

1. Agent greets / authenticates a firefighter by `auth_id` / `call_sign`
   (`firefighters` table).
2. **Asks + verifies incident + location** — reads details back.
3. Gets an **explicit confirm** before acting.
4. Performs the action (dispatch, AIRS code suggestion, property lookup,
   pre-incident plan, alarm history, weather, etc.).
5. Announces completion.

Key internal helpers (assist LLM tooling):
- `_resolve_property_from_name` — fuzzy property-name → `properties` row.
- `_detect_use_case` — classifies the utterance into a supported handler.
- `_handle_choose_task` — multi-step task orchestration.
- `get_alarm_history`, `get_pre_incident_plan`, `suggest_airs_code`,
  `get_incident_timeline`, `debrief_incident`, `generate_incident_report`.
- `handle_location_intent` + `send_agentmail` — emails a clickable Google-Maps
  navigation link to the firefighter's email (hydrant / station / water /
  sprinkler / incident). Uses the **AgentMail** MCP inbox
  (`mohammad-9483@agentmail.to`).
- `location_pending` context tracking to resolve follow-up location queries.

The prompt + tool descriptions are versioned in `AGENT_SETUP.md` (v2.1).

Every Q&A the voice agent handles is logged to `gis.conversation_log`.

---

## 4. Authentication & data input

- Firefighter auth by `firefighters.auth_id` / `call_sign` (`voice_credential`).
- **No secrets** in repo. Runtime values injected from env:
  - `PGPASSWORD` / `PGPASS` — Postgres password
  - `N8N_API_KEY`, `N8N_BASE_URL` — n8n automation CLI
  - ElevenLabs key (in `~/.hermes/elevenlabs/.env`)
  - AgentMail credentials (`~/.hermes/twilio/agentmail.env`)

---

## 5. Dependencies

- **Python 3.12** + `edge-tts` (in `~/.hermes/tts-venv`).
- **Docker** running `postgres-db-1` (`pg15postgis:arm64` image), PostGIS 3.6.4.
- **systemd** units in `systemd/` (copy to `/etc/systemd/system/`).
- **Nginx / HestiaCP** TLS + reverse proxy.
- Outbound: ElevenLabs webhook, AgentMail (via MCP), optional n8n.
  The VM itself has **no** store-internet to the Postgres container image.

---

## 6. Systemd service reference

`systemd/fire-agent-tool.service` — restart policy, ExecStart path, env source.
Review each unit before deploy; update the working directory + env file paths to
match the host (`/home/ubuntu/.hermes/elevenlabs/`, `/home/ubuntu/.hermes/scripts/`).

---

## 7. Restoration / copy — stepwise for an AI agent

Given this repo + a fresh Ubuntu host with Docker:

1. **Provision Postgres**
   ```bash
   docker run -d --name postgres-db-1 -p 5433:5432 \
     -e POSTGRES_USER=tauseef -e POSTGRES_PASSWORD="$PGPASSWORD" \
     -e POSTGRES_DB=fire_services \
     -v pgdata:/var/lib/postgresql/data \
     pg15postgis:arm64
   ```
2. **Apply schema** — see `db/SHARED-schema.sql` (dump of `gis`, `ai`,
   `analytics`) committed in this repo. Apply with:
   ```bash
   docker exec -e PGPASSWORD="$PGPASSWORD" postgres-db-1 \
     psql -U tauseef -d fire_services -f /path/to/SHARED-schema.sql
   ```
   (uploads via `docker cp`).
3. **Seed reference data** (optional, if restoring demo data) — restore from a
   `pg_dump` of the source DB (see `db/` notes).
4. **Install Python deps** incl. `edge-tts` in a venv.
5. **Install systemd units** → `daemon-reload` → `enable --now`.
6. **Recreate `~/.hermes/.env`** with the same secret keys (not committed).
7. **Wire AgentMail** MCP credentials.
8. **Verify**: `curl localhost:8000/health`, query a known incident id,
   call the ElevenLabs webhook with a test phrase.

Copying to a **second stack**: clone this repo, change `CONTAINER`, port,
DB name in the scripts, and re-run the same steps.

---

## 8. Operational notes / pitfalls

- The Postgres container runs **offline** (no net) on `pg15postgis:arm64`;
  do not rebuild it from `postgres:15` without PostGIS, tables use geometry.
- Geometry is **SRID 4326** everywhere; web layer exposes `lat`/`lon`
  via the `gis.v_*` views.
- `gis.conversation_log` grows fast (600+ rows) — it is the audit trace the
  agent and dashboard rely on; preserve it on copy.