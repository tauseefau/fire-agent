#!/usr/bin/env python3
"""Hourly data enrichment for fire_services using docker exec psql."""
import os
import random
import subprocess

PGPASSWORD = os.environ.get('PGPASSWORD') or os.environ.get('PGPASS', '')

def psql(sql, echo=True):
    cmd = ['docker', 'exec', '-e', f'PGPASSWORD={PGPASSWORD}', 
           'postgres-db-1', 'psql', '-U', 'tauseef', '-d', 'fire_services', '-c', sql]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if echo:
        if result.stdout.strip():
            print(result.stdout.strip())
        if result.returncode != 0 and result.stderr.strip():
            print(f"stderr: {result.stderr.strip()}")
    return result

def rand_incident():
    return (
        f"DO $$ "
        f"DECLARE "
        f"  v_property_id int; "
        f"  v_ff_id int; "
        f"  v_airs_code text; "
        f"  v_comments text[] := ARRAY['Initial attack successful.', 'Sprinkler contained.', 'Under investigation.', 'Multi-agency response.']; "
        f"  v_incident_id int; "
        f"BEGIN "
        f"  SELECT property_id INTO v_property_id FROM gis.properties ORDER BY random() LIMIT 1; "
        f"  SELECT firefighter_id INTO v_ff_id FROM gis.firefighters WHERE active = TRUE ORDER BY random() LIMIT 1; "
        f"  v_airs_code := CASE WHEN random() > 0.5 THEN "
        f"    (SELECT airs_code FROM gis.airs_codes ORDER BY random() LIMIT 1) "
        f"    ELSE NULL END; "
        f"  "
        f"  INSERT INTO gis.incidents (incident_name, incident_type, status, reported_time, "
        f"    geom, firefighter_id, airs_code, "
        f"    airs_confirmed_by, airs_confirmed_at, comment) "
        f"  VALUES ('Structure Fire - Collins St {random.randint(1,500)}', "
        f"'Structure Fire', '{random.choice(['Active','Contained','Controlled','Extinguished','Under Investigation'])}', "
        f"CURRENT_TIMESTAMP - (random() * interval '48 hours'), "
        f"(SELECT geom FROM gis.properties ORDER BY random() LIMIT 1), "
        f"v_ff_id, v_airs_code, "
        f"CASE WHEN v_airs_code IS NOT NULL AND random() > 0.3 THEN v_ff_id ELSE NULL END, "
        f"CASE WHEN v_airs_code IS NOT NULL AND random() > 0.3 THEN CURRENT_TIMESTAMP + (floor(random()*210+30)||' minutes')::interval ELSE NULL END, "
        f"v_comments[floor(random()*4+1)]) "
        f"RETURNING incident_id INTO v_incident_id; "
        f" "
        f"  /* Add 1-4 dispatch entries */ "
        f"  FOR j IN 1..floor(random()*4+1) LOOP "
        f"  DECLARE "
        f"    v_dispensed timestamp := CURRENT_TIMESTAMP - (random() * interval '48 hours') + (floor(random()*5)||' minutes')::interval; "
        f"    v_arrived timestamp := v_dispensed + (floor(random()*12+3)||' minutes')::interval; "
        f"    v_cleared timestamp := CASE WHEN random() > 0.2 THEN v_arrived + (floor(random()*150+30)||' minutes')::interval ELSE NULL END; "
        f"    v_call_sign text := (ARRAY['P1','P2','P3','P4','P5','P6','MP1','LP1','UP1','L1','L2','T1','T2','R1','R2','H1','FB1','C1'])[floor(random()*18+1)]; "
        f"    v_app_type text := CASE v_call_sign "
        f"      WHEN 'P1' THEN 'Heavy Pumper (P)' WHEN 'P2' THEN 'Heavy Pumper (P)' WHEN 'P3' THEN 'Heavy Pumper (P)' "
        f"      WHEN 'P4' THEN 'Heavy Pumper (P)' WHEN 'P5' THEN 'Heavy Pumper (P)' WHEN 'P6' THEN 'Heavy Pumper (P)' "
        f"      WHEN 'MP1' THEN 'Medium Pumper (MP)' WHEN 'LP1' THEN 'Light Pumper (LP)' WHEN 'UP1' THEN 'Urban Pump (UP)' "
        f"      WHEN 'L1' THEN 'Aerial Ladder (L)' WHEN 'L2' THEN 'Aerial Platform (L)' "
        f"      WHEN 'T1' THEN 'Tanker (T)' WHEN 'T2' THEN 'Tanker (T)' "
        f"      WHEN 'R1' THEN 'Heavy Rescue (R)' WHEN 'R2' THEN 'Rescue (R)' "
        f"      WHEN 'H1' THEN 'Hazmat Unit (H)' WHEN 'FB1' THEN 'Fire Boat (FB)' ELSE 'Command Vehicle (C)' END; "
        f"    v_station text := CASE v_call_sign "
        f"      WHEN 'P1' THEN 'Eastern Hill (HQ) Station 1' WHEN 'P2' THEN 'Eastern Hill (HQ) Station 1' WHEN 'P3' THEN 'Eastern Hill (HQ) Station 1' "
        f"      WHEN 'P4' THEN 'Richmond Station 10' WHEN 'P5' THEN 'Carlton Station 3' WHEN 'P6' THEN 'South Melbourne Station 38' "
        f"      WHEN 'MP1' THEN 'Richmond Station 10' WHEN 'LP1' THEN 'Carlton Station 3' WHEN 'UP1' THEN 'Port Melbourne Station 39' "
        f"      WHEN 'L1' THEN 'Eastern Hill (HQ) Station 1' WHEN 'L2' THEN 'Richmond Station 10' "
        f"      WHEN 'T1' THEN 'Port Melbourne Station 39' WHEN 'T2' THEN 'Carlton Station 3' "
        f"      WHEN 'R1' THEN 'Eastern Hill (HQ) Station 1' WHEN 'R2' THEN 'South Melbourne Station 38' "
        f"      WHEN 'H1' THEN 'Richmond Station 10' WHEN 'FB1' THEN 'Port Melbourne Station 39' ELSE 'Eastern Hill (HQ) Station 1' END; "
        f"    v_role text := (ARRAY['First Due - Attack','Ventilation/Rescue','RIT','Water Supply','Foam','Hazmat','Command','Lighting'])[floor(random()*8+1)]; "
        f"""
        v_turnout timestamp := v_dispensed + interval '1 minute';
        v_enroute timestamp := v_dispensed + interval '1 min 30 sec';
        v_on_scene timestamp := v_arrived;
        v_return timestamp := v_cleared;
        v_in_station timestamp := COALESCE(v_cleared, v_arrived) + interval '12 minutes';
        BEGIN
        INSERT INTO gis.dispatch_log (incident_id, apparatus_call_sign, apparatus_type, station_name,
          dispatched_at, turned_out_at, enroute_at, on_scene_at, return_station_at, in_station_at, arrived_at, cleared_at, notes)
        VALUES (v_incident_id, v_call_sign, v_app_type, v_station, v_dispensed, v_turnout, v_enroute, v_on_scene,
          v_return, v_in_station, v_arrived, v_cleared,
          (ARRAY[NULL,'Level 2 fire','Hazmat containment','Search and rescue','Water supply established'])[floor(random()*5+1)]);
        END; """
        f"  END LOOP; "
        f" "
        f"  /* Add 1-4 conversation logs */ "
        f"  FOR j IN 1..floor(random()*4+1) LOOP "
        f"  INSERT INTO gis.conversation_log (firefighter_id, property_id, question, answer, created_at) "
        f"  VALUES (v_ff_id, v_property_id, "
        f"    (ARRAY['airs for incident '||v_incident_id, 'hydrant near incident '||v_incident_id, 'pre plan for property '||v_property_id, "
        f"     'timeline for incident '||v_incident_id, 'alarm history for property '||v_property_id, "
        f"     'water sources near incident '||v_incident_id])[floor(random()*6+1)], "
        f"    'Suggested AIRS code: ' || (SELECT airs_code FROM gis.airs_codes ORDER BY random() LIMIT 1), "
        f"    CURRENT_TIMESTAMP - (random() * interval '120 hours') + (floor(random()*115+5)||' minutes')::interval); "
        f"  END LOOP; "
        f"END $$;"
    )

def main():
    print(f"\n=== Fire Services Data Enrichment - {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===\n")
    
    total = 0
    for _ in range(random.randint(0, 2)):
        if random.random() > 0.3:  # 70% chance to add incidents
            sql = rand_incident()
            result = psql(sql, echo=False)
            # Check if successful by looking at stderr
            if result.returncode == 0 and 'ERROR' not in (result.stderr or ''):
                total += 1
                print("  ✓ Added incident")
            else:
                print(f"  ✗ Failed: {result.stderr[:100] if result.stderr else 'unknown'}")
    
    # Add alarms
    for _ in range(random.randint(2, 4)):
        sql = f"DO $$ DECLARE v_property_id int; BEGIN SELECT property_id INTO v_property_id FROM gis.properties ORDER BY random() LIMIT 1; INSERT INTO gis.alarms (property_id, alarm_type, outcome, alarm_code, alarm_date) VALUES (v_property_id, "
        # NOTE: no quotes around the array subscriptions so plpgsql EVALUATES them
        sql += f"(ARRAY['Automatic - Smoke Detector','Automatic - Heat Detector','Manual Pull','Sprinkler Flow','Gas Detector','Flame Detector'])[floor(random()*6+1)], "
        sql += f"(ARRAY['REAL FIRE - Structure','REAL FIRE - Vehicle','REAL FIRE - Vegetation','FALSE - Faulty detector','FALSE - Dust/steam','FALSE - Cooking fumes','MALICIOUS - Hoax','MALICIOUS - Vandalism'])[floor(random()*8+1)], "
        sql += f"(ARRAY['A1','A2','A3','A4','A5','B1','B2','B3','B4','C1','C2','C3','D1','D2','D3','D4','E1','E2','E3','F1','F2','F3','F4','H1','H2','M1','V1'])[floor(random()*25+1)], "
        sql += f"now() - (random() * interval '72 hours')); END $$;"
        result = psql(sql, echo=False)
        if result.returncode == 0 and 'ERROR' not in (result.stderr or ''):
            total += 1
            print("  ✓ Added alarm")
        else:
            print(f"  ✗ alarm failed: {result.stderr[:120] if result.stderr else 'unknown'}")
    
    # Add call notes
    for _ in range(random.randint(1, 3)):
        sql = f"DO $$ DECLARE v_property_id int; v_ff_id int; BEGIN SELECT property_id INTO v_property_id FROM gis.properties ORDER BY random() LIMIT 1; SELECT firefighter_id INTO v_ff_id FROM gis.firefighters WHERE active = TRUE ORDER BY random() LIMIT 1; "
        sql += f"INSERT INTO gis.call_notes (property_id, firefighter_id, note_text, created_at) VALUES (v_property_id, v_ff_id, "
        sql += f"'(ARRAY['Hydrant H-' || floor(random()*9000+1000) || ' has reduced flow, reported to water corp.', "
        sql += f"'Building ' || v_property_id || ' has new tenant on level ' || floor(random()*20+1) || ', updated occupancy.', "
        sql += f"'Access via ' || (ARRAY['Gate 1','Gate 2','Gate 3','Gate 4','Gate 5'])[floor(random()*5+1)] || ' gate restricted after hours, use ' || (ARRAY['Gate 2','Gate 3','Service Rd','Rear Access'])[floor(random()*4+1)] || ' instead.', "
        sql += f"'Sprinkler system at ' || v_property_id || ' undergoing maintenance until ' || to_char(now() + interval '1 month', 'DD Mon YYYY'), "
        sql += f"'New hazmat storage in basement ' || v_property_id || ', update pre-plan.', "
        sql += f"'Fire lift at ' || v_property_id || ' out of service, use stairs only.', "
        sql += f"'Roof access at ' || v_property_id || ' via ladder only, no hatch.', "
        sql += f"'Gas isolation valve at ' || v_property_id || ' located in plant room B' || floor(random()*5+1) || '.'])[floor(random()*8+1)], "
        sql += f"CURRENT_TIMESTAMP - (random() * interval '168 hours')); END $$;"
        result = psql(sql, echo=False)
        if result.returncode == 0 and 'ERROR' not in (result.stderr or ''):
            total += 1
            print("  ✓ Added call note")
    
    print(f"\n=== Total records added this run: {total} ===\n")

if __name__ == '__main__':
    main()