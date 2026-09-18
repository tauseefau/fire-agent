# Fire Services Voice Agent — Natural Test Script
# Use after creating the ElevenLabs agent and attaching the fire_db webhook tool.
# Speak each tester line into the agent's test widget (or phone) and confirm the expected
# response. Expected values below are drawn from the actual fire_services DB.

## Part 1 — Identity & Greeting
# 🚒 Tester: "Hi, this is Officer Ahmad Raza, call sign FF-001 at Eastern Hill station."
#  -> Agent greets / acknowledges identity, ready to help.

## Part 2 — Core Queries

## Q1 Hydrants
# Tester: "Show me the nearest hydrants."
# Expected (live DB sample):
#   Nearest operational hydrants: RI-002 (flow 1500, 106 metres away);
#   RI-001 (1600, 505m); MCG-001 (1450, 1385m).

## Q2 Active incidents
# Tester: "What incidents are active right now?"
# Expected sample:
#   Active incidents: Richmond Substation Fire (Active, Critical); University Campus
#   Smoke (Active, High); Flinders St Vehicle Fire (Active, Critical); Port Melbourne
#   Warehouse (Active, High); Southbank Electrical Fire (Active, Low);
#   Demo Grass Fire (Active, Low).

## Q3 High-risk assets
# Tester: "Are there any high risk assets nearby?"
# Expected sample:
#   High and critical risk assets include: Southbank Aged Care Lodge (High);
#   Yarra Demolition Asbestos (Critical); CBD Data Centre UPS (High);
#   Grid Battery - Sunshine (Critical); ...

## Q4 Water supply
# Tester: "What's our water supply situation?"
# Expected sample:
#   Water supply: Yarra Pump Station Reservoir (Reservoir, 1,200,000 L);
#   Port Melbourne Open Pond (Open Water, 800,000 L);
#   Richmond Fire Supply Dam (Dam, 600,000 L); ...

## Q5 False alarms
# Tester: "How many false alarms have we had?"
# Expected: There are 13 recorded false or non-fire alarms.

## Q6 Fire stations
# Tester: "Which fire stations are on duty?"
# Expected sample:
#   Fire stations: Eastern Hill (HQ) Station 1 - tankers 3, personnel 42;
#   Richmond Station 10 - tankers 2, personnel 28; ...

## Part 3 — Edge cases
# Q7 Unknown query: "What's the weather like today?"
#   -> Agent re-prompts: handles hydrants / incidents / assets / water / alarms / stations.
# Q8 Off-topic: "Tell me a joke."
#   -> Agent redirects back to operational topics.

## Part 4 — Authentication
# Q9 "I'm Jake, FF-003 at Richmond."  -> Agent acknowledges FF-003, continues.

## Part 5 — Stress / no-data
# (Optional) "How much capacity does the Port Melbourne pond have?"
#   -> Agent answers via water-supply intent.

## Test tracker
#  # | Query                  | Data expected                          | Pass?
#  1 | Identity/greeting      | Acknowledges ID                        | []
#  2 | nearest hydrants       | Hydrant #, flow, distance              | []
#  3 | active incidents       | Names + risk level                     | []
#  4 | high risk assets       | Names + risk category                  | []
#  5 | water supply           | Sources + capacity                     | []
#  6 | false alarms           | Count                                  | []
#  7 | fire stations          | Stations + crew                        | []
#  8 | unknown query          | Graceful fallback / re-prompt          | []
#  9 | off-topic              | Redirects back to topic                | []
# 10 | auth by call sign      | Acknowledges safely                    | []

## SQL to compare live (run in container psql)
# SELECT hydrant_number, flow_rate, status FROM gis.hydrants WHERE status='Operational' LIMIT 3;
# SELECT incident_name, status FROM gis.incidents WHERE status='Active';
# SELECT count(*) FROM gis.alarms WHERE outcome NOT ILIKE 'REAL FIRE%';