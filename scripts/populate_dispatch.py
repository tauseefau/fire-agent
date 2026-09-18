#!/usr/bin/env python3
"""Populate gis.dispatch_log for ALL incidents with realistic Melbourne FRV unit assignments."""
import subprocess
import os

PG = os.environ.get("PGPASSWORD") or os.environ.get("PGPASS", "")
CONTAINER = "postgres-db-1"

def psql(sql, echo=True):
    r = subprocess.run(["docker","exec","-e",f"PGPASSWORD={PG}",CONTAINER,
                        "psql","-U","tauseef","-d","fire_services","-tA","-F","|","-c",sql],
                       capture_output=True, text=True, timeout=30)
    if echo and r.returncode != 0:
        print("SQLERR:", r.stderr.strip())
    return r.stdout

# Clear dispatch log and regenerate
psql("DELETE FROM gis.dispatch_log;")

# Get all incidents with id, type, reported_time (full timestamp) and coords
inc = [r.split("|") for r in psql("""
    SELECT i.incident_id, i.incident_type, 
           to_char(i.reported_time,'YYYY-MM-DD'),
           to_char(i.reported_time,'HH24:MI') AS rt,
           round(ST_Y(i.geom)::numeric,4), round(ST_X(i.geom)::numeric,4)
    FROM gis.incidents i ORDER BY i.incident_id;
""").splitlines() if r.strip()]

# FRV unit pools: (call_sign, type, station_name, role)
def units_for(itype):
    t = itype.lower()
    pulls = []
    if any(x in t for x in ("structure","building","warehouse","explosion","kitchen","zoo","restaurant","gallery","museum","substation","high-rise","highrise","car park")):
        pulls += [("P1","Heavy Pumper (P)","Eastern Hill (HQ) Station 1","First Due - Attack")]
        pulls += [("L1","Aerial Ladder (L)","Eastern Hill (HQ) Station 1","Ventilation/Rescue")]
        pulls += [("R1","Heavy Rescue (R)","Eastern Hill (HQ) Station 1","RIT / Extrication")]
        if "explosion" in t:
            pulls += [("H1","Hazmat Unit (H)","Richmond Station 10","Hazmat Monitoring")]
            pulls += [("P4","Heavy Pumper (P)","Richmond Station 10","Backup Attack")]
        if "kitchen" in t or "restaurant" in t or "grease" in t:
            pulls = [("P1","Heavy Pumper (P)","Eastern Hill (HQ) Station 1","First Due - Attack"),
                     ("LP1","Light Pumper (LP)","Carlton Station 3","Kitchen Line")]
    if "grass" in t or "bush" in t or "vegetation" in t or "bushfire" in t:
        pulls = [("P5","Heavy Pumper (P)","Carlton Station 3","First Due - Attack"),
                 ("T2","Tanker (T)","Carlton Station 3","Water Supply"),
                 ("T1","Tanker (T)","Port Melbourne Station 39","Water Supply"),
                 ("LP1","Light Pumper (LP)","Carlton Station 3","Grass Attack")]
    if "vehicle" in t or "car" in t:
        pulls = [("MP1","Medium Pumper (MP)","Richmond Station 10","First Due - Attack"),
                 ("R2","Rescue (R)","South Melbourne Station 38","Extrication")]
    if "hazmat" in t or "chemical" in t or "fuel" in t or "spill" in t or "airport" in t:
        pulls = [("H1","Hazmat Unit (H)","Richmond Station 10","Hazmat"),
                 ("P6","Heavy Pumper (P)","South Melbourne Station 38","Foam / Decon"),
                 ("T1","Tanker (T)","Port Melbourne Station 39","Water Supply"),
                 ("MP1","Medium Pumper (MP)","Richmond Station 10","BA Decontamination")]
    if "electrical" in t:
        pulls = [("P2","Heavy Pumper (P)","Eastern Hill (HQ) Station 1","First Due - Attack"),
                 ("MP1","Medium Pumper (MP)","Richmond Station 10","Electrical Fire")]
    if "mar" in t or "water" in t or "ship" in t or "boat" in t or "rescue" in t:
        pulls = [("FB1","Fire Boat (FB)","Port Melbourne Station 39","Water Attack / Rescue"),
                 ("R1","Heavy Rescue (R)","Eastern Hill (HQ) Station 1","Water Rescue"),
                 ("P6","Heavy Pumper (P)","South Melbourne Station 38","Shore Support")]
    return pulls

rows = []
from datetime import datetime, timedelta
for iid, itype, rdate, rt, lat, lon in inc:
    units = units_for(itype) or [("P1","Heavy Pumper (P)","Eastern Hill (HQ) Station 1","First Due - Attack")]
    units = units[:4]
    base = datetime.strptime(f"{rdate} {rt}", "%Y-%m-%d %H:%M")
    for idx,(cs,typ,st,role) in enumerate(units):
        disp = base + timedelta(minutes=idx*2)
        arr = disp + timedelta(minutes=3+idx)
        clr = arr + timedelta(minutes=30+idx*20)
        rows.append((iid, cs, typ, st,
                     disp.strftime("%Y-%m-%d %H:%M:%S"),
                     arr.strftime("%Y-%m-%d %H:%M:%S"),
                     clr.strftime("%Y-%m-%d %H:%M:%S"),
                     role))

# Insert
vals = []
for (iid, cs, typ, st, ds, ar, cl, role) in rows:
    vals.append(f"({iid}, '{cs}', '{typ}', '{st}', '{ds}', '{ar}', '{cl}', '{role}')")
sql = "INSERT INTO gis.dispatch_log (incident_id, apparatus_call_sign, apparatus_type, station_name, dispatched_at, arrived_at, cleared_at, role) VALUES " + ",\n".join(vals) + ";"
psql(sql)
print(f"Inserted {len(rows)} dispatch rows across incidents")