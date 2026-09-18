#!/usr/bin/env bash
# Firefighter Voice Responder v2.1 — answers natural-language queries from the fire service DB,
# then synthesizes the answer via ElevenLabs TTS.
#
# Usage:
#   ff_responder.sh <auth_id_or_callsign> "<question>"
# Examples:
#   ff_responder.sh auth_EL_001 "nearest hydrant"
#   ff_responder.sh auth_EL_003 "active incidents"
#   ff_responder.sh auth_EL_005 "high risk assets"
#   ff_responder.sh auth_EL_007 "water supply"
#   ff_responder.sh auth_EL_009 "false alarms"
#   ff_responder.sh auth_EL_011 "status"
set -u

ENV_FILE="$(dirname "$0")/.env"
if [[ -f "$ENV_FILE" ]]; then set -a; source "$ENV_FILE"; set +a; fi
: "${ELEVENLABS_API_KEY:?ELEVENLABS_API_KEY not set}"

IDENT="${1:-}"; PROMPT="${2:-}"
[[ -z "$IDENT" ]] && { echo "ERROR: no firefighter identity given"; exit 2; }

DB() { docker exec -e PGPASSWORD="$PGPASSWORD" postgres-db-1 psql -U tauseef -d fire_services -tA -F'|' -c "$1" 2>/dev/null; }

echo "=== 1) Authenticating firefighter: $IDENT ==="
RESULT="$(DB "SELECT ff.full_name, ff.call_sign, ff.role, fs.station_name, COALESCE(ff.voice_credential,'')
   FROM gis.firefighters ff LEFT JOIN gis.fire_stations fs ON fs.station_id=ff.station_id
   WHERE (ff.auth_id='$IDENT' OR ff.call_sign='$IDENT') AND ff.active=TRUE;")"
if [[ -z "$RESULT" ]]; then echo "AUTH FAILED: no active firefighter with id '$IDENT'."; exit 1; fi
IFS='|' read -r FULLNAME CALLSIGN ROLE STATION AUTHID VOICECRED <<< "$RESULT"
echo "  OK: $FULLNAME ($CALLSIGN), $ROLE @ $STATION"

echo "=== 2) Question: \"$PROMPT\" ==="
LOWER="$(echo "$PROMPT" | tr '[:upper:]' '[:lower:]')"

resolve_loc() {  # best known incident location (first active) as a coord-table expr
  echo "(SELECT geom FROM gis.incidents WHERE status='Active' ORDER BY reported_time DESC LIMIT 1)::geography"
}

hydrant_routing() {
  local out; out="$(DB "
    SELECT h.hydrant_number, h.flow_rate, h.status,
           round((ST_Distance((SELECT geom FROM gis.incidents WHERE status='Active' ORDER BY reported_time DESC LIMIT 1)::geography, h.geom::geography))::numeric,0)||'m'
    FROM gis.hydrants h WHERE h.status='Operational'
    ORDER BY ST_Distance((SELECT geom FROM gis.incidents WHERE status='Active' ORDER BY reported_time DESC LIMIT 1)::geography, h.geom::geography)
    LIMIT 3;")"
  if [[ -z "$out" ]]; then REPLY="No operational hydrants found."; return; fi
  REPLY="Nearest operational hydrants: $(echo "$out" | sed 's/|/ /g; s/  */ /g' | tr '\n' '; ')."
}

incident_routing() {
  local out; out="$(DB "SELECT i.incident_name||' ('||i.status||': '||COALESCE(e.risk_level,'unrated')||')'
    FROM gis.incidents i LEFT JOIN ai.incident_assessment e ON e.incident_id=i.incident_id
    WHERE i.status='Active' ORDER BY i.reported_time DESC;")"
  if [[ -z "$out" ]]; then REPLY="No active incidents right now."; return; fi
  REPLY="Active incidents: $(echo "$out" | tr '\n' '; ')."
}

asset_routing() {
  local out; out="$(DB "SELECT a.asset_name||' ('||a.asset_type||', '||a.risk_category||')'
    FROM gis.assets a WHERE a.risk_category IN ('High','HIGH','Critical') ORDER BY a.asset_type LIMIT 8;")"
  if [[ -z "$out" ]]; then REPLY="No high or critical risk assets on record."; return; fi
  REPLY="High and critical risk assets include: $(echo "$out" | tr '\n' '; ')."
}

station_routing() {
  local out; out="$(DB "SELECT station_name||' - tankers '||tankers||', personnel '||personnel FROM gis.fire_stations ORDER BY station_id;")"
  REPLY="Fire stations: $(echo "$out" | tr '\n' '; ')."
}

water_routing() {
  local out; out="$(DB "SELECT source_name||' ('||source_type||', '||COALESCE(capacity_litres::text,'n/a')||' L)' FROM gis.water_sources ORDER BY capacity_litres DESC NULLS LAST LIMIT 4;")"
  if [[ -z "$out" ]]; then REPLY="No water sources on record."; return; fi
  REPLY="Water supply: $(echo "$out" | tr '\n' '; ')."
}

falsealone_routing() {
  local out; out="$(DB "SELECT count(*) FROM gis.alarms WHERE outcome NOT ILIKE 'REAL FIRE%';")"
  REPLY="There are $out recorded false or non-fire alarms."
}

if   [[ "$LOWER" =~ hydrant ]];            then hydrant_routing
elif [[ "$LOWER" =~ (active|incident) ]];   then incident_routing
elif [[ "$LOWER" =~ (high ?risk|critical|asset) ]]; then asset_routing
elif [[ "$LOWER" =~ station ]];            then station_routing
elif [[ "$LOWER" =~ (water|supply|tank) ]]; then water_routing
elif [[ "$LOWER" =~ (false|malicious) ]];  then falsealone_routing
else REPLY="Hello Officer $FULLNAME. I can report hydrants, active incidents, high risk assets, water sources, false alarms and stations. I heard: $PROMPT."
fi
echo "  REPLY: $REPLY"

echo "=== 3) ElevenLabs TTS ==="
VOICE_ID="EXAVITQu4vr4xnSDxMaL"; OUT="/tmp/ff_${CALLSIGN}.mp3"
JSON="{\"text\": \"$REPLY\", \"model_id\": \"${ELEVENLABS_MODEL:-eleven_turbo_v2_5}\"}"
HTTP="$(curl -s -o "$OUT" -w '%{http_code}' -X POST "https://api.elevenlabs.io/v1/text-to-speech/${VOICE_ID}" \
  -H "xi-api-key: $ELEVENLABS_API_KEY" -H "Content-Type: application/json" -d "$JSON")"
if [[ "$HTTP" == "200" ]]; then echo "  SUCCESS -> $OUT ($(stat -c%s "$OUT") bytes)";
else echo "  ELEVENLABS HTTP $HTTP:"; cat "$OUT"; echo; exit 1; fi