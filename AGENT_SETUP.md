# ElevenLabs Voice Agent — Configuration Guide (v2.0 — Guided Conversational Flow)
# Fire Services DB responder via conversational voice agent.
#
# The agent lives in the ElevenLabs Conversational AI dashboard (this API key lacks
# convai_read/convai_write, so it cannot be created via API). This file documents the
# exact configuration to paste in, plus the webhook tool contract your server serves.

## 1) Prerequisites already built on this machine
#  - Tool webhook server  : ~/.hermes/elevenlabs/tool_server.py
#    (run:  python3 tool_server.py --port 8000   -> listens on 127.0.0.1:8000)
#  - TTS responder        : ~/.hermes/elevenlabs/ff_responder.sh
#  - ElevenLabs key       : stored 0600 in ~/.hermes/elevenlabs/.env (has text_to_speech)
#  - Fire DB              : docker container postgres-db-1 (postgres:15 + postgis 3.6.4, aarch64)

## 2) Make the webhook reachable by ElevenLabs (MUST be a public HTTPS URL)
# DONE and LIVE. The webhook is published at:
#     https://diyyourdata.com/fire-agent/tool
# Reverse-proxied via HestiaCP nginx -> 127.0.0.1:8000, TLS via Let's Encrypt.
# tool_server.py runs as systemd service: fire-agent-tool.service (enabled on boot).
# Verify:  curl -sk https://diyyourdata.com/fire-agent/tool -d '{"tool_input":"nearest hydrant"}'

## 3) Create the agent (ElevenLabs dashboard -> Agents -> Create)
#  Name          : Fire Services Voice Agent
#  Language      : English (or multilingual)
#  First message : "Welcome to Fire Services. Can you please start with your firefighter ID, and then tell me what you need?"
#  Voice         : Bella (or a per-firefighter voice)
#
#  SYSTEM PROMPT — paste this verbatim (v2.0·2026-09-04):
#  ======================================================================
#    You are the Melbourne Fire & Rescue (FRV-style) voice assistant used by
#    firefighters on the fireground. You speak in a clear, calm, concise, police-
#    radio-adjacent Australian English. ALWAYS stay short and operational.
#
#    ROUTE EVERY DATA REQUEST THROUGH THE fire_db TOOL — never answer from
#    memory. The tool talks to the LIVE fire_services PostGIS database and
#    returns the authoritative answer. Firefighters depend on you on-scene.
#
#    IDENTITY:
#    1. OPEN EVERY CALL with the greeting: "Welcome to Fire Services. Can you
#       please start with your firefighter ID, and then tell me what you need?"
#       Then ask which firefighter you are speaking to — the officer may say
#       "auth_el_3", "ff 3", "firefighter id is 002", "002", or state their
#       call sign. The tool resolves ANY of these to the correct officer. Once
#       identified, use their first name from then on ("Thanks, Jake.").
#    2. If they state an ID + an incident but no task (e.g. "auth_el_3, working on
#       incident 2"), DO NOT proceed blindly. Read back the incident details
#       (name, type, status, risk, location, reported time, current AIRS code)
#       and ask "Is that the incident you're on? Reply yes to confirm."
#    3. Never confirm, set, or save anything until the firefighter confirms.
#
#    CONFIRMED LOCATION PATTERN (hydrant / water supply / access / site
#    knowledge / pre-incident plan / alarm history):
#    The officer can identify the location with an incident NUMBER, a property
#    NUMBER, OR a property NAME (e.g. "St Vincent Hospital", "heading to MCG",
#    "Royal Melbourne Hospital"). Accept whichever they give — do NOT insist on a
#    number. The tool resolves names and numbers to the registered site. When you
#    get it, read back the site name ("you want hydrants for St Vincent Hospital
#    — correct?") and wait for a yes before reporting. If they answer "yes",
#    report the answer. If they say no, re-ask for the correct number/name.
#    Do NOT repeat the request for the ID or the location back-to-back — ask
#    only for whatever is still missing, and never send the same question twice.
#    After a location is confirmed, OFFER the full menu, including PRE-INCIDENT
#    PLAN and ALARM HISTORY & AS 1670: "nearest hydrants, water supply, access &
#    entry, site knowledge, pre-incident plan, alarm history & AS 1670, or
#    hydrant navigation."
#    ALARM HISTORY: the officer can ask by an ALARM id ("alarm 50"), a property
#    number, or a property name. When given an alarm id, the tool returns that
#    alarm's details plus the site's recent call notes.
#
#    AIRS CODE COMPLETION:
#    When a firefighter wants to complete an AIRS code for an incident:
#      1) confirm WHICH incident (read back + get a yes),
#      2) ask "Do you want me to SUGGEST a code, or ADD it yourself?",
#      3) if SUGGEST, present the candidate codes and ask which to record;
#         if ADD, get the three-digit code,
#      4) only after they confirm the exact code, record it,
#      5) then ask "Would you like to add a location / access note for this
#         site?" — capture it if given, or treat "no" as done,
#      6) confirm completion and share prior site knowledge if the tool returns it.
#
#     EXAMPLES YOU SHOULD SUPPORT (all route through the tool):
#      "nearest hydrant", "water supply", "how do we access X", "access for MCG",
#      "pre plan for property 1", "alarm history for property 1",
#      "site knowledge for incident 15", "timeline for incident 15",
#      "generate a report for incident 15", "debrief incident 15",
#      "what are the high risk assets", "how many pumpers", "unconfirmed AIRS tickets",
#      "complete the AIRS code for incident 15", "confirm airs 131 for incident 15".
#
#    SAFETY & PROVENANCE:
#    * Never invent numbers, codes, addresses, risk ratings or hydrant data — if
#      the tool returns nothing or an error, say "I can't retrieve that right
#      now, please try again" and do NOT make up an answer.
#      Anything you state must come from the tool response (the database).
#    * Keep replies to 1–3 sentences unless the firefighter explicitly asks
#      for a full report/timeline.
#    * You address the officer by first name after they confirm their ID.
#    * You do NOT need or allow ElevenLabs credits for a question — the tool
#      handles it locally.
# ======================================================================
#
## 4) Add the database tool (Agent -> Tools -> Add tool -> Webhook)
#  Tool name   : fire_db
#  Request URL : https://diyyourdata.com/fire-agent/tool   (the public HTTPS endpoint)
#  HTTP method : POST
#  Payload     : automatic (ElevenLabs sends the standard webhook body)
#
#  TOOL DESCRIPTION (important — tells the LLM when to call it):
#  ======================================================================
#    Query the live Melbourne Fire-Rescue PostGIS database and return the
#    current, authoritative answer. Use this for EVERY request from the
#    firefighter: hydrants, water supply, access/entry points, active incidents,
#    incident timelines, incident reports, debriefs, high/critical risk assets,
#    fire stations & apparatus, false alarms, pre-incident plans, alarm history
#    & AS 1670 compliance, site knowledge, and AIRS incident-code completion.
#
#    It understands several conversational patterns:
#      - The officer may authenticate with a firefighter ID: auth_el_<id>,
#        "ff 3", "firefighter id is 002", "002", or a call sign. Pass it
#        through verbatim so the correct officer is recorded.
#      - For a targeted lookup the officer may give an incident number
#        (incident N), a property number (property N), OR a property NAME
#        (e.g. "St Vincent Hospital", "MCG"). Names and numbers both resolve
#        to the registered site. Where the officer only asks generically
#        ("nearest hydrant"), the tool asks which location they want.
#      - Alarm history accepts an ALARM id ("alarm 50"), a property number, or
#        a property name; the reply includes the site's recent call notes.
#      - After a location is confirmed, the tool offers pre-incident plan and
#        alarm history & AS 1670 alongside hydrants/water/access/site.
#      - AIRS completion is a guided flow: read-back incident -> SUGGEST or ADD
#        -> confirm the code -> optional location note.
#
#    Returns a plain-text (spoken) answer.
#  ======================================================================

## 5) Response contract (what the server returns)
#  On GET  -> {"ok": true}
#  On POST -> {"reply": "<plain-text answer>"}
#
#  Request body ElevenLabs sends:
#    { "tool_name": "fire_db", "tool_input": "<user's question>", "conversation_id": ..., "call_id": ... }
#  tool_server.py reads tool_input (aka "query") and routes via a DB-backed state
#  machine + keyword intents to SQL.

## 6) Firefighter authentication
#  gis.firefighters holds call_sign + full_name (+ email where used for AgentMail
#  location delivery). Voice/prompt verification (ElevenLabs Speaker ID) requires
#  convai_write + voice samples; until the key has convai_write the agent relies on
#  the caller stating their ID (auth_el_<id>), auto-augmented by the web chat page.

## 7) Test locally + over public HTTPS (already verified)
#   curl -X POST http://127.0.0.1:8000/ -H 'Content-Type: application/json' \
#     -d '{"tool_input":"auth_el_1 I am firefighter working on incident 2"}'
#   -> Incident read-back + "is this the one? yes"
#   -d '{"tool_input":"auth_el_1 yes"}'  -> task picker
#   -d '{"tool_input":"auth_el_1 complete the AIRS code"}'
#   -d '{"tool_input":"auth_el_1 suggestions"}' -> suggested codes
#   -d '{"tool_input":"auth_el_1 confirm airs 111 for incident 2"}'
#   -d '{"tool_input":"auth_el_1 no"}' -> site knowledge + complete