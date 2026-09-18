# fire-agent

Fire Rescue Victoria-style voice agent + backend services for the diyyourdata
fire-services showcase.

## Components

- `tool_server.py` — ElevenLabs voice-agent webhook server (:8000), AI
  incident/response handling, AgentMail email delivery.
- `AGENT_SETUP.md` — voice-agent prompt + tool descriptions v2.1.
- `TEST_SCRIPT.md` — manual test script for the agent.
- `ff_responder.sh` — helper responder script.
- `scripts/`
  - `dashboard_api.py` — analytics/map/survey/ArcGIS proxy API server (:8001).
  - `firis_tts_server.py` — local Edge-TTS HTTP server (:8002).
  - `enrich_fire_data.py` — incident data enrichment job.
  - `populate_dispatch.py` — populate `gis.dispatch_log`.
  - `n8n.py` — Hermes CLI for the n8n REST API.
- `systemd/` — unit files for the three services.

## Runtime dependencies

- PostGIS `fire_services` DB in Docker `postgres-db-1` (port 5433).
- Secrets from `~/.hermes/.env` (e.g. `N8N_API_KEY`, `PGPASSWORD`). Repo holds
  no credentials; all values are read from environment at runtime.

## Install

```bash
cp systemd/*.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now dashboard-api fire-agent-tool firis-tts
```