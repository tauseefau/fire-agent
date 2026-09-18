# fire-agent — Postgres Data Model & Restoration

This document is the machine-readable contract an AI agent needs to **restore or
copy** the `fire_services` PostGIS data store, and to reason about the data
model. The authoritative schema is committed at `db/SHARED-schema.sql`
(a `pg_dump -s` of schemas `gis`, `ai`, `analytics`).

---

## 1. Connection

| Item | Value |
|---|---|
| Container | `postgres-db-1` |
| Image | `pg15postgis:arm64` (PostgreSQL 15.19 + PostGIS 3.6.4) |
| Host port | 5433 → container 5432 |
| Database | `fire_services` |
| Superuser | `tauseef` |
| Read-only (Power BI) | `powerbi_ro` (scram) |
| Password source | `~/.hermes/.env` → `PGPASSWORD` (runtime, never committed) |
| Spatial SRID | **4326** everywhere (lat/lon), `geometry(Point,4326)` |

All internal tools call Postgres via `docker exec ... psql -U tauseef -d fire_services`.

---

## 2. Schemas

- **`gis`** — operational fire-services domain (25 tables + 9 read views).
- **`ai`** — AI assessments.
- **`analytics`** — Power BI / NERIS analytical tables.

---

## 3. Data model — `gis` tables

| Table | PK | Foreign / link | Notes |
|---|---|---|---|
| `firefighters` | `firefighter_id` | `station_id` → `fire_stations` | auth by `auth_id`/`call_sign`, has `voice_credential`, `email`, `phone`, `active` |
| `fire_stations` | `station_id` | — | `geom` point, `tankers`, `personnel` |
| `properties` | `property_id` | — | master registry; `aliases`, `construction_type`, `occupancy_type`, `sprinkler_coverage` |
| `incidents` | `incident_id` | `firefighter_id`, `airs_code` | status, `geom`, AIRS suggestion fields |
| `assets` | `asset_id` | — | `asset_type` ('Sprinkler'), `capacity_litres`, `geom` |
| `water_sources` | `water_source_id` | — | `source_type` ('Water Tank' preferred), `capacity_litres`, `geom` |
| `hydrants` | `hydrant_id` | — | `flow_rate`, `status`, `geom` |
| `alarms` | `alarm_id` | `property_id`, `alarm_code` | `geom` |
| `alarm_codes` | `alarm_code` | — | `as1670_category`, `zone_type`, `priority` |
| `airs_codes` | `airs_code` | — | `keywords[]`, `nfirs_equivalent`, `priority` |
| `call_notes` | `note_id` | `property_id`, `firefighter_id` | firefighter property notes |
| `conversation_log` | `log_id` | `firefighter_id`, `property_id` | every voice-agent Q&A (600+ rows) |
| `dispatch_log` | `dispatch_id` | `incident_id`, `apparatus_id` | full unit dispatch timeline |
| `apparatus` | `apparatus_id` | `station_id` | `call_sign`, capacities, crew, `equipment[]` |
| `property_risks` | `risk_id` | `property_id` | risk types/levels |
| `incident_reports` | `report_id` | `incident_id`, `generated_by` | `content_json`, `content_text` |
| `post_incident_surveys` | `survey_id` | `firefighter_id`, `incident_id`, `property_id` | rated survey (★1-5 fields) |
| `agency_notifications` | `notification_id` | `incident_id` | agency contact log |
| `agent_state` | `firefighter_id` | — | voice-agent contextual state (`context jsonb`) |
| `standard_operating_procedures` | `sop_id` | — | `incident_types[]`, `keywords[]` |
| `weather_observations` | `obs_id` | — | district FDR data |

**Key relationships (graph):**
```
fire_stations 1──* firefighters
fire_stations 1──* apparatus
properties    1──* incidents        (via firefighter/geom, logical)
properties    1──* call_notes
properties    1──* property_risks
properties    1──* alarms ═ alarm_codes
incidents     1──* dispatch_log *── apparatus
incidents     1──* incident_reports
incidents     1──* agency_notifications
incidents     1──* conversation_log
firefighters  1──* conversation_log
incidents     1──* post_incident_surveys
```

## 4. `gis` views (web/Power-BI friendly)

`v_incidents`, `v_fire_stations`, `v_hydrants`, `v_water_sources`, `v_assets`,
`v_alarms`→`v_alarm_analysis`, `v_property_risks`, `v_call_notes`,
`v_conversation_log`. Each exposes `lat`/`lon` numbers plus joined names/
call-signs for easy charting. (Note: schema dump calls the alarm/jurisdiction
view `v_incidents` with joined AIRS fields; confirm exact names from
`SHARED-schema.sql`.)

## 5. `analytics` (NERIS / Power BI)

| Table | PK | Purpose |
|---|---|---|
| `incidents` | `incident_neris_id` | NERIS incident reference + nearest station |
| `fire_departments` | `fd_neris_id` | FD reference (1 row) |
| `stations` | `station_id` | station capability/staffing |
| `dispatch` | `dispatch_internal_id` | response-time analytics |

## 6. `ai` table

`incident_assessment` — `assessment_id`, `incident_id`, `risk_level`,
`exposed_assets`, `recommendation`, `assessment_time`.

---

## 7. Restore / copy procedures (AI-agent stepwise)

### A. Restore schema on a fresh container
```bash
# 1. start offline PostGIS container (image already present)
docker run -d --name postgres-db-1 -p 5433:5432 \
  -e POSTGRES_USER=tauseef -e POSTGRES_PASSWORD="$PGPASSWORD" \
  -e POSTGRES_DB=fire_services -v pgdata:/var/lib/postgresql/data \
  pg15postgis:arm64
# 2. apply schema
docker cp db/SHARED-schema.sql postgres-db-1:/tmp/schema.sql
docker exec -e PGPASSWORD="$PGPASSWORD" postgres-db-1 \
  psql -U tauseef -d fire_services -f /tmp/schema.sql
# 3. recreate read-only role (security) for Power BI
docker exec -e PGPASSWORD="$PGPASSWORD" postgres-db-1 \
  psql -U tauseef -d fire_services -c \
  "CREATE ROLE powerbi_ro LOGIN PASSWORD '$PBI_PASS'; GRANT USAGE ON SCHEMA gis TO powerbi_ro; GRANT SELECT ON ALL TABLES IN SCHEMA gis TO powerbi_ro; ..."
```

### B. Copy data between instances
```bash
# dump (data only, gis/ai/analytics)
docker exec -e PGPASSWORD="$PGPASSWORD" postgres-db-1 \
  pg_dump -U tauseef -d fire_services \
  -n gis -n ai -n analytics --data-only -Fc -f /tmp/fire_data.dump
docker cp postgres-db-1:/tmp/fire_data.dump ./fire_data.dump
# restore into target
docker cp ./fire_data.dump target-db:/tmp/fire_data.dump
docker exec -e PGPASSWORD="$PGPASSWORD" target-db \
  pg_restore -U tauseef -d fire_services /tmp/fire_data.dump
```

### C. Golden rules
- **Disable triggers / FK noise** not needed — data dump preserves ordering; use
  `--data-only` + `pg_restore` (handles FK) rather than raw SQL COPY.
- **Never commit** `PGPASSWORD`, connection strings, or `.env` to git.
- Preserve `gis.conversation_log` and `gis.call_notes` on copy — they are the
  audit + context the agent depends on.
- SRID 4326 must match on the copy; verify with
  `SELECT Find_SRID('gis','incidents','geom');`.

## 8. Verification checklist

- `SELECT postgis_version();` → `3.6 USE_GEOS...`
- `SHOW SCHEMAS` contains `gis`, `ai`, `analytics`, `topology`.
- `gis.v_incidents` returns rows and `lat`/`lon` are non-null.
- Counts (reference): incidents 38, conversations 647, properties 46, hydrants
  34, assets 65, water_sources 12, firefighters 12, apparatus 23.
- `powerbi_ro` login works against host port 5433.