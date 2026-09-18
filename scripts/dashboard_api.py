#!/usr/bin/env python3
"""Fire Services Dashboard JSON API - serves structured incident data for the web timeline page."""
import json
import os
import re
import subprocess
import urllib.parse
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer

PGPASSWORD = os.environ.get("PGPASSWORD") or os.environ.get("PGPASS", "")
DB = "postgres-db-1"

def psql(sql):
    cmd = ["docker", "exec", "-e", f"PGPASSWORD={PGPASSWORD}", DB,
           "psql", "-U", "tauseef", "-d", "fire_services",
           "-At", "-F", "|", "-c", sql]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError(r.stderr)
    return [ln for ln in r.stdout.splitlines() if ln.strip()]


def incidents_json():
    rows = psql("""SELECT
        i.incident_id, i.incident_name, COALESCE(i.incident_type,''), COALESCE(i.status,''),
        to_char(i.reported_time,'YYYY-MM-DD HH24:MI') AS reported,
        COALESCE(i.airs_code,'') AS airs_code,
        COALESCE(i.comment,'') AS comment,
        COALESCE(round(ST_Y(i.geom)::numeric,6)::text,'') AS lat,
        COALESCE(round(ST_X(i.geom)::numeric,6)::text,'') AS lon,
        (SELECT count(*) FROM gis.dispatch_log d WHERE d.incident_id=i.incident_id) AS dc
        FROM gis.incidents i ORDER BY i.reported_time DESC""")
    items = []
    for r in rows:
        p = r.split('|')
        if len(p) < 10:
            continue
        items.append({
            "id": int(p[0]), "name": p[1], "type": p[2], "status": p[3],
            "reported": p[4], "airs_code": p[5], "comment": p[6],
            "lat": p[7] or None, "lon": p[8] or None, "dispatch_count": int(p[9] or 0)
        })
    return {"incidents": items}


def incident_timeline_json(iid):
    incs = psql(f"""SELECT
        i.incident_id, i.incident_name, COALESCE(i.incident_type,''), COALESCE(i.status,''),
        to_char(i.reported_time,'YYYY-MM-DD HH24:MI') AS reported,
        COALESCE(i.airs_code,'') AS airs_code, COALESCE(i.comment,'') AS comment,
        COALESCE(round(ST_Y(i.geom)::numeric,6)::text,'') AS lat,
        COALESCE(round(ST_X(i.geom)::numeric,6)::text,'') AS lon
        FROM gis.incidents i WHERE i.incident_id={int(iid)}""")
    if not incs:
        return {"error": "not found"}, 404
    p = incs[0].split('|')
    info = {"id": int(p[0]), "name": p[1], "type": p[2], "status": p[3], "reported": p[4],
            "airs_code": p[5], "comment": p[6], "lat": p[7] or None, "lon": p[8] or None}
    disp = psql(f"""SELECT
        d.apparatus_call_sign, COALESCE(d.apparatus_type,''), COALESCE(d.role,''),
        to_char(d.dispatched_at,'HH24:MI') AS dispatched,
        COALESCE(to_char(d.turned_out_at,'HH24:MI'),'') AS turned_out,
        COALESCE(to_char(d.enroute_at,'HH24:MI'),'') AS enroute,
        COALESCE(to_char(d.on_scene_at,'HH24:MI'),'') AS on_scene,
        COALESCE(to_char(d.return_station_at,'HH24:MI'),'') AS returned_station,
        COALESCE(to_char(d.in_station_at,'HH24:MI'),'') AS in_station,
        COALESCE(d.notes,'') AS notes,
        COALESCE(round(ST_Y(fs.geom)::numeric,6)::text,'') AS st_lat,
        COALESCE(round(ST_X(fs.geom)::numeric,6)::text,'') AS st_lon,
        COALESCE(fs.station_name,'') AS station_name,
        -- Calculated durations (minutes:seconds "MM:SS")
        CASE WHEN d.on_scene_at IS NOT NULL AND d.enroute_at IS NOT NULL
             THEN to_char((d.on_scene_at - d.enroute_at),'MI:SS') ELSE NULL END AS out_time,
        CASE WHEN d.return_station_at IS NOT NULL AND d.on_scene_at IS NOT NULL
             THEN to_char((d.return_station_at - d.on_scene_at),'MI:SS') ELSE NULL END AS time_on_scene,
        CASE WHEN d.in_station_at IS NOT NULL AND d.return_station_at IS NOT NULL
             THEN to_char((d.in_station_at - d.return_station_at),'MI:SS') ELSE NULL END AS in_return_time,
        CASE WHEN d.in_station_at IS NOT NULL AND d.dispatched_at IS NOT NULL
             THEN to_char((d.in_station_at - d.dispatched_at),'MI:SS') ELSE NULL END AS total_out_min,
        CASE WHEN d.on_scene_at IS NOT NULL AND d.enroute_at IS NOT NULL
             THEN to_char((d.on_scene_at - d.enroute_at),'MI:SS') ELSE NULL END AS response_time
        FROM gis.dispatch_log d
        LEFT JOIN gis.fire_stations fs ON fs.station_name = d.station_name OR fs.station_id = d.apparatus_id
        WHERE d.incident_id={int(iid)} ORDER BY d.dispatched_at""")
    events = []
    for r in disp:
        q = r.split('|')
        if len(q) >= 15:
            events.append({"call_sign": q[0], "type": q[1], "role": q[2],
                           "dispatched": q[3], "turned_out": q[4], "enroute": q[5],
                           "on_scene": q[6], "returned_station": q[7], "in_station": q[8],
                           "notes": q[9],
                           "station_lat": q[10] or None, "station_lon": q[11] or None,
                           "station_name": q[12],
                           "out_time": q[13], "time_on_scene": q[14],
                           "in_return_time": q[15], "total_out_min": q[16], "response_time": q[17]})
    stations = psql("""SELECT station_name, COALESCE(round(ST_Y(geom)::numeric,6)::text,''),
        COALESCE(round(ST_X(geom)::numeric,6)::text,''), tankers, personnel
        FROM gis.fire_stations ORDER BY station_id""")
    stl = []
    for r in stations:
        q = r.split('|')
        if len(q) >= 5:
            stl.append({"name": q[0], "lat": q[1] or None, "lon": q[2] or None,
                        "tankers": q[3], "personnel": q[4]})
    return {"incident": info, "events": events, "stations": stl}


def map_json():
    """All geo layers for the live Leaflet map: incidents, hydrants, water_sources, stations."""
    incs = psql("""SELECT i.incident_id, COALESCE(i.incident_name,'Incident #'||i.incident_id),
        COALESCE(i.incident_type,''), COALESCE(i.status,''), COALESCE(i.airs_code,''),
        COALESCE(to_char(i.reported_time,'YYYY-MM-DD HH24:MI'),''),
        COALESCE(round(ST_Y(i.geom)::numeric,6)::text,''), COALESCE(round(ST_X(i.geom)::numeric,6)::text,'')
        FROM gis.incidents i WHERE i.geom IS NOT NULL""")
    incident_list = []
    for r in incs:
        p = r.split('|')
        if len(p) >= 8 and p[6] and p[7]:
            incident_list.append({"id": int(p[0]), "name": p[1], "type": p[2], "status": p[3],
                                  "airs_code": p[4], "reported": p[5], "lat": float(p[6]), "lon": float(p[7])})

    hyd = psql("""SELECT hydrant_number, status, COALESCE(flow_rate::text,''),
        COALESCE(round(ST_Y(geom)::numeric,6)::text,''), COALESCE(round(ST_X(geom)::numeric,6)::text,'')
        FROM gis.hydrants WHERE geom IS NOT NULL""")
    hydrant_list = []
    for r in hyd:
        p = r.split('|')
        if len(p) >= 5 and p[3] and p[4]:
            hydrant_list.append({"number": p[0], "status": p[1], "flow": p[2],
                                 "lat": float(p[3]), "lon": float(p[4])})

    wat = psql("""SELECT COALESCE(source_name,''), COALESCE(source_type,''), COALESCE(capacity_litres::text,''),
        COALESCE(round(ST_Y(geom)::numeric,6)::text,''), COALESCE(round(ST_X(geom)::numeric,6)::text,'')
        FROM gis.water_sources WHERE geom IS NOT NULL""")
    water_list = []
    for r in wat:
        p = r.split('|')
        if len(p) >= 5 and p[3] and p[4]:
            water_list.append({"name": p[0], "type": p[1], "capacity": p[2],
                               "lat": float(p[3]), "lon": float(p[4])})

    stn = psql("""SELECT station_name, tankers, personnel,
        COALESCE(round(ST_Y(geom)::numeric,6)::text,''), COALESCE(round(ST_X(geom)::numeric,6)::text,'')
        FROM gis.fire_stations WHERE geom IS NOT NULL""")
    station_list = []
    for r in stn:
        p = r.split('|')
        if len(p) >= 5 and p[3] and p[4]:
            station_list.append({"name": p[0], "tankers": p[1], "personnel": p[2],
                                 "lat": float(p[3]), "lon": float(p[4])})

    return {"incidents": incident_list, "hydrants": hydrant_list,
            "water_sources": water_list, "stations": station_list}


def nearby_json(lat, lon, radius_m=1500):
    """Nearest hydrants + water sources to a point (PostGIS ST_DWithin), sorted by distance."""
    try:
        lat_f = float(lat); lon_f = float(lon); rad = int(radius_m or 1500)
    except (TypeError, ValueError):
        return {"error": "lat & lon required"}, 400
    pt = f"ST_SetSRID(ST_Point({lon_f},{lat_f}),4326)"
    hq = psql(f"""SELECT h.hydrant_number, COALESCE(h.status,''), COALESCE(h.flow_rate::text,''),
        round(ST_Y(h.geom)::numeric,3)::text, round(ST_X(h.geom)::numeric,3)::text,
        round((ST_Distance(h.geom::geography, ({pt})::geography))::numeric,0)::text
        FROM gis.hydrants h
        WHERE ST_DWithin(h.geom::geography, ({pt})::geography, {rad})
        ORDER BY ST_Distance(h.geom::geography, ({pt})::geography)
        LIMIT 12""")
    hydrants = []
    for r in hq:
        p = r.split('|')
        if len(p) >= 6:
            hydrants.append({"number": p[0], "status": p[1], "flow": p[2],
                             "lat": float(p[3]), "lon": float(p[4]), "dist_m": int(p[5] or -1)})
    wq = psql(f"""SELECT COALESCE(w.source_name,''), COALESCE(w.source_type,''), COALESCE(w.capacity_litres::text,''),
        round(ST_Y(w.geom)::numeric,3)::text, round(ST_X(w.geom)::numeric,3)::text,
        round((ST_Distance(w.geom::geography, ({pt})::geography))::numeric,0)::text
        FROM gis.water_sources w
        WHERE ST_DWithin(w.geom::geography, ({pt})::geography, {rad})
        ORDER BY ST_Distance(w.geom::geography, ({pt})::geography)
        LIMIT 12""")
    water = []
    for r in wq:
        p = r.split('|')
        if len(p) >= 6:
            water.append({"name": p[0], "type": p[1], "capacity": p[2],
                          "lat": float(p[3]), "lon": float(p[4]), "dist_m": int(p[5] or -1)})
    return {"lat": lat_f, "lon": lon_f, "radius_m": rad, "hydrants": hydrants, "water_sources": water}


def surveys_json():
    """Return post-incident survey records + summary stats for the analytics page."""
    rows = psql("""SELECT s.survey_id, s.firefighter_id, s.firefighter_name, s.incident_id, s.incident_name,
        s.property_id, s.property_name, s.role,
        s.response_time_rating, s.comms_rating, s.equipment_rating, s.coordination_rating,
        s.hydrant_access, COALESCE(s.access_difficulty,''), COALESCE(s.hazards,''),
        COALESCE(s.what_went_well,''), COALESCE(s.improvements,''),
        s.overall_satisfaction, to_char(s.created_at,'YYYY-MM-DD HH24:MI')
        FROM gis.post_incident_surveys s ORDER BY s.created_at DESC""")
    surveys = []
    for r in rows:
        q = r.split('|')
        while len(q) < 19:
            q.append('')
        surveys.append({
            "id": q[0], "firefighter_id": q[1] or None, "firefighter_name": q[2] or None,
            "incident_id": q[3] or None, "incident_name": q[4] or None,
            "property_id": q[5] or None, "property_name": q[6] or None, "role": q[7] or None,
            "response_time_rating": q[8] or None, "comms_rating": q[9] or None,
            "equipment_rating": q[10] or None, "coordination_rating": q[11] or None,
            "hydrant_access": q[12] or None, "access_difficulty": q[13],
            "hazards": q[14], "what_went_well": q[15], "improvements": q[16],
            "overall_satisfaction": q[17] or None, "created_at": q[18]
        })
    # Summary aggregates
    agg = psql("""SELECT
        count(*)::text,
        COALESCE(round(avg(response_time_rating)::numeric,2)::text,'0'),
        COALESCE(round(avg(comms_rating)::numeric,2)::text,'0'),
        COALESCE(round(avg(equipment_rating)::numeric,2)::text,'0'),
        COALESCE(round(avg(coordination_rating)::numeric,2)::text,'0'),
        COALESCE(round(avg(overall_satisfaction)::numeric,2)::text,'0'),
        count(*) FILTER (WHERE hydrant_access)::text,
        count(*) FILTER (WHERE NOT hydrant_access AND hydrant_access IS NOT NULL)::text
        FROM gis.post_incident_surveys""")
    a = agg[0].split('|') if agg else ['0']*8
    summary = {"total": int(a[0] or 0),
               "avg_response_time": a[1], "avg_comms": a[2], "avg_equipment": a[3],
               "avg_coordination": a[4], "avg_satisfaction": a[5],
               "hydrant_ok": int(a[6] or 0), "hydrant_not_ok": int(a[7] or 0)}
    return {"surveys": surveys, "summary": summary}


def stats_json(filters=None):
    """Comprehensive analytics — supports cross-filter via filters={status,type,station}."""
    filters = filters or {}
    status_f = (filters.get('status') or '').strip()
    type_f = (filters.get('type') or '').strip()
    station_f = (filters.get('station') or '').strip()

    # build WHERE fragments safely (escape single quotes)
    def esc(s): return s.replace("'", "''")

    inc_where = []
    if status_f and status_f.lower() != 'all':
        inc_where.append(f"i.status ILIKE '{esc(status_f)}'")
    if type_f and type_f.lower() != 'all':
        inc_where.append(f"i.incident_type ILIKE '{esc(type_f)}'")

    # station filter requires existence of a dispatch from that station
    station_clause = ""
    if station_f and station_f.lower() != 'all':
        # match station_name contains the filter (handles "Eastern Hill (HQ) Station 1" vs "Eastern Hill")
        station_clause = f"EXISTS (SELECT 1 FROM gis.dispatch_log d2 WHERE d2.incident_id=i.incident_id AND d2.station_name ILIKE '%{esc(station_f)}%')"

    where_parts = inc_where[:]
    if station_clause:
        where_parts.append(station_clause)
    where_sql = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""

    # For station/apparatus panels when filtering by station, we still want to show breakdown;
    # but incident counts should reflect the filtered incident set.
    # Use CTE filtered_ids for consistent filtering
    cte = f"WITH filtered AS (SELECT i.incident_id FROM gis.incidents i {where_sql})"

    # Total counts — filtered context
    totals = psql(f"""{cte}
        SELECT
        (SELECT count(*) FROM filtered) AS total_incidents,
        (SELECT count(*) FROM gis.incidents i WHERE i.incident_id IN (SELECT incident_id FROM filtered) AND i.status ILIKE 'active') AS active_incidents,
        (SELECT count(*) FROM gis.alarms) AS total_alarms,
        (SELECT count(*) FROM gis.alarms WHERE alarm_type ILIKE 'false%' OR alarm_type ILIKE 'malicious%') AS false_malicious_alarms,
        (SELECT count(*) FROM gis.properties) AS total_properties,
        (SELECT count(*) FROM gis.call_notes) AS total_call_notes,
        (SELECT count(*) FROM gis.conversation_log) AS total_conversations,
        (SELECT count(*) FROM gis.apparatus) AS total_apparatus,
        (SELECT count(*) FROM gis.fire_stations) AS total_stations,
        (SELECT count(*) FROM gis.hydrants) AS total_hydrants""")
    if not totals:
        return {"error": "no data", "total_incidents": 0}
    t = totals[0].split('|')

    # Incidents by status — filtered
    by_st = psql(f"SELECT i.status, count(*) FROM gis.incidents i {where_sql} GROUP BY i.status ORDER BY i.status")
    by_status = {r.split('|')[0]: int(r.split('|')[1]) for r in by_st if '|' in r and len(r.split('|')) >= 2}
    # Incidents by type — filtered
    if where_sql:
        by_ty = psql(f"SELECT i.incident_type, count(*) FROM gis.incidents i {where_sql} AND i.incident_type IS NOT NULL GROUP BY i.incident_type ORDER BY count DESC")
    else:
        by_ty = psql("SELECT incident_type, count(*) FROM gis.incidents WHERE incident_type IS NOT NULL GROUP BY incident_type ORDER BY count DESC")
    by_type = {r.split('|')[0]: int(r.split('|')[1]) for r in by_ty if '|' in r and len(r.split('|')) >= 2}

    # Station incident counts — filtered by incident subset
    if where_parts:
        st_q = psql(f"""{cte}
            SELECT fs.station_name, count(d.incident_id) AS cnt
            FROM gis.fire_stations fs
            LEFT JOIN gis.dispatch_log d ON d.station_name = fs.station_name AND d.incident_id IN (SELECT incident_id FROM filtered)
            GROUP BY fs.station_name""")
    else:
        st_q = psql("SELECT fs.station_name, count(d.incident_id) AS cnt FROM gis.fire_stations fs LEFT JOIN gis.dispatch_log d ON d.station_name = fs.station_name GROUP BY fs.station_name")
    st_inc = {r.split('|')[0]: int(r.split('|')[1]) for r in st_q if '|' in r and len(r.split('|')) >= 2}

    # Apparatus by station — not incident-filtered (fleet is static), but keep as is
    app_q = psql("""
        SELECT fs.station_name, count(a.apparatus_id) AS units
        FROM gis.fire_stations fs
        LEFT JOIN gis.apparatus a ON a.station_id = fs.station_id
        GROUP BY fs.station_name""")
    app_by_st = {r.split('|')[0]: int(r.split('|')[1]) for r in app_q if '|' in r and len(r.split('|')) >= 2}

    # Top properties by alarm count — global (not incident-filtered)
    tp_q = psql("SELECT p.property_name, count(a.alarm_id) AS alarm_count FROM gis.properties p LEFT JOIN gis.alarms a ON a.property_id = p.property_id GROUP BY p.property_id ORDER BY alarm_count DESC LIMIT 5")
    top_props = [{"name": r.split('|')[0], "alarm_count": int(r.split('|')[1])} for r in tp_q if '|' in r and len(r.split('|')) >= 2]

    # Unconfirmed AIRS — filtered by incident subset
    un_where = "WHERE (i.airs_code IS NULL OR i.airs_code = '')"
    if where_parts:
        # combine with filtered CTE: only show unconfirmed within filtered set
        un_raw = psql(f"""{cte}
            SELECT i.incident_id, i.incident_name, to_char(i.reported_time,'YYYY-MM-DD') AS reported, COALESCE(i.airs_code,'') AS airs_code, COALESCE(i.status,''), COALESCE(i.incident_type,'')
            FROM gis.incidents i
            WHERE i.incident_id IN (SELECT incident_id FROM filtered) AND (i.airs_code IS NULL OR i.airs_code = '')
            ORDER BY i.reported_time DESC LIMIT 10""")
    else:
        un_raw = psql("SELECT i.incident_id, i.incident_name, to_char(i.reported_time,'YYYY-MM-DD') AS reported, COALESCE(i.airs_code,'') AS airs_code, COALESCE(i.status,''), COALESCE(i.incident_type,'') FROM gis.incidents i WHERE i.airs_code IS NULL OR i.airs_code = '' ORDER BY i.reported_time DESC LIMIT 10")
    un_details = []
    for r in un_raw:
        p = r.split('|')
        if len(p) >= 4:
            un_details.append({"id": int(p[0]), "name": p[1] or "Incident #%s" % p[0], "address": "", "reported": p[2], "airs_code": p[3] or "not confirmed", "status": p[4] if len(p)>4 else "", "type": p[5] if len(p)>5 else ""})

    # Also return active filters and true totals for UI
    true_total = psql("SELECT count(*) FROM gis.incidents")[0] if psql("SELECT count(*) FROM gis.incidents") else "0"

    return {
        "total_incidents": int(t[0] or 0),
        "active_incidents": int(t[1] or 0),
        "total_alarms": int(t[2] or 0),
        "false_malicious_alarms": int(t[3] or 0),
        "total_properties": int(t[4] or 0),
        "total_call_notes": int(t[5] or 0),
        "total_conversations": int(t[6] or 0),
        "apparatus_summary": "(%s units across %s stations)" % (t[7] or 0, t[8] or 0),
        "total_hydrants": int(t[9] or 0),
        "incidents_by_status": by_status,
        "incidents_by_type": by_type,
        "station_incidents": st_inc,
        "apparatus_by_station": app_by_st,
        "top_properties_by_alarms": top_props,
        "unconfirmed_airs": len(un_details) if where_parts else int(true_total) - int(psql("SELECT count(*) FROM gis.incidents WHERE airs_code IS NOT NULL AND airs_code <> ''")[0] or 0),
        "unconfirmed_airs_details": un_details,
        "filters": {"status": status_f, "type": type_f, "station": station_f},
        "is_filtered": bool(where_parts),
        "true_total_incidents": int(true_total or 0)
    }


# ----------------------------------------------------------------------------
# Live external ArcGIS / NERIS query proxy
# ----------------------------------------------------------------------------
# Reachable live ArcGIS feature services (public, no auth). Used to demonstrate
# connecting the analytics/agent to live external spatial data.
ARCGIS_LAYERS = {
    "neris_fd": {
        "label": "NERIS Public Fire Departments (jurisdictions)",
        "url": "https://services5.arcgis.com/lPbcyJOcoLyZmvo6/ArcGIS/rest/services/NERIS%20Public%20Fire%20Departments/FeatureServer/2/query",
        "geom": "polygon",
        "fields": "OBJECTID,neris_id,name,department_type,region_type",
    },
    "utah_fire_response": {
        "label": "Utah Fire Response Areas (NG911)",
        "url": "https://services1.arcgis.com/99lidPhWCzftIe9K/ArcGIS/rest/services/FireResponseAreas/FeatureServer/0/query",
        "geom": "polygon",
        "fields": "OBJECTID,DsplayName,FOUR_AGENCY,AGENCY",
    },
    "wfigs_wildfire": {
        "label": "WFIGS Wildfire Perimeters (live)",
        "url": "https://services3.arcgis.com/T4QMspbfLg3qTGWY/ArcGIS/rest/services/WFIGS_Interagency_Perimeters_Current/FeatureServer/0/query",
        "geom": "polygon",
        "fields": "*",
    },
}


def arcgis_proxy(layer_key, params):
    """Forward a query to a live ArcGIS feature-service and return parsed GeoJSON.
    params: dict of ArcGIS query params (where, outFields, resultRecordCount, ...)."""
    layer = ARCGIS_LAYERS.get(layer_key)
    if not layer:
        return {"error": f"unknown layer '{layer_key}'", "layers": list(ARCGIS_LAYERS.keys())}, 404
    q = {
        "where": params.get("where", "1=1"),
        "outFields": params.get("outFields", layer["fields"]),
        "f": "geojson",
        "outSR": "4326",
    }
    if params.get("returnGeometry") in ("false", "False"):
        q["returnGeometry"] = "false"
    if params.get("resultRecordCount"):
        q["resultRecordCount"] = params["resultRecordCount"]
    # minimal URL-safe where
    where = q["where"]
    if "," in where or ";" in where:
        # keep as-is; caller responsible for safety
        pass
    url = layer["url"] + "?" + urllib.parse.urlencode(q)
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (FireServices-Showcase) Hermes/1.0"
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read().decode("utf-8"))
        if isinstance(data, dict) and data.get("error"):
            return {"error": data["error"].get("message", "ArcGIS error"),
                    "details": data["error"].get("details", [])}, 502
        return {"ok": True, "layer": layer["label"], "geom": layer["geom"],
                "source": layer["url"], "data": data}
    except urllib.error.HTTPError as e:
        return {"error": f"ArcGIS HTTP {e.code}", "source": url}, 502
    except Exception as e:
        return {"error": str(e), "source": url}, 502


def arcgis_layers():
    return {"layers": [{"key": k, "label": v["label"], "geom": v["geom"]}
                       for k, v in ARCGIS_LAYERS.items()]}


class Handler(BaseHTTPRequestHandler):
    def _send(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)
        # flatten qs (take first value)
        filters = {k: v[0] for k,v in qs.items() if v}
        try:
            if path in ("/incidents", "/incidents/", "/api/incidents"):
                return self._send(incidents_json())
            m = re.match(r"/api/incident/(\d+)/timeline", path)
            if m:
                res = incident_timeline_json(m.group(1))
                if isinstance(res, tuple):
                    obj, code = res
                else:
                    obj, code = res, 200
                return self._send(obj, code)
            m = re.match(r"/incident/(\d+)", path)
            if m:
                res = incident_timeline_json(m.group(1))
                if isinstance(res, tuple):
                    obj, code = res
                else:
                    obj, code = res, 200
                return self._send(obj, code)
            if path in ("/api/stats", "/stats", "/api/stats/", "/timeline/api/stats", "/timeline/api/stats/"):
                return self._send(stats_json(filters))
            if path in ("/api/map", "/map", "/api/map/", "/timeline/api/map", "/timeline/api/map/"):
                return self._send(map_json())
            if path in ("/api/surveys", "/surveys", "/timeline/api/surveys", "/api/surveys/", "/timeline/surveys"):
                return self._send(surveys_json())
            if path in ("/api/arcgis/layers", "/timeline/api/arcgis/layers", "/arcgis/layers",
                        "/api/arcgis/", "/arcgis/"):
                return self._send(arcgis_layers())
            m = re.match(r"/api/arcgis/([a-z_]+)/query", path)
            _layer = m.group(1) if m else None
            if not m:
                m = re.match(r"/arcgis/([a-z_]+)/query", path)
                _layer = m.group(1) if m else None
            if not m:
                m = re.match(r"/timeline/arcgis/([a-z_]+)/query", path)
                _layer = m.group(1) if m else None
            if _layer:
                pq = {k: v[0] for k, v in qs.items() if v}
                res = arcgis_proxy(_layer, pq)
                if isinstance(res, tuple):
                    obj, code = res
                else:
                    obj, code = res, 200
                return self._send(obj, code)
            m = re.match(r"/api/nearby", path)
            if m:
                return self._send(nearby_json(qs.get('lat',[None])[0], qs.get('lon',[None])[0], qs.get('radius',[None])[0]))
            if path in ("/nearby", "/api/nearby/", "/timeline/api/nearby/"):
                return self._send(nearby_json(qs.get('lat',[None])[0], qs.get('lon',[None])[0], qs.get('radius',[None])[0]))
            self._send({"error": "not found", "path": path}, 404)
        except Exception as e:
            self._send({"error": str(e)}, 500)

    def log_message(self, *a):
        pass

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        try:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b"{}"
            body = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            body = {}

        def s(v):  # sanitise a single value or None
            return None if v is None else str(v).strip()

        def num(v):
            try:
                return int(v)
            except (TypeError, ValueError):
                return None

        def boolv(v):
            if v is None:
                return None
            if isinstance(v, bool):
                return v
            return str(v).lower() in ("1", "true", "yes", "on")

        if path in ("/api/surveys/submit", "/surveys/submit", "/timeline/api/surveys/submit", "/survey/submit"):
            try:
                def N(v):  # -> SQL NULL literal or int
                    if v is None or v == "":
                        return "NULL"
                    try:
                        return str(int(v))
                    except (TypeError, ValueError):
                        return "NULL"
                def B(v):  # -> SQL NULL or boolean
                    if v is None or v == "":
                        return "NULL"
                    if isinstance(v, bool):
                        return str(v).upper()
                    return str(v).lower() in ("1","true","yes","on") and "TRUE" or "FALSE"
                def S(v):  # -> SQL NULL or quoted string
                    if v is None:
                        return "NULL"
                    return "'" + str(v).replace("'", "''") + "'"
                sql = ("INSERT INTO gis.post_incident_surveys "
                       "(firefighter_id, firefighter_name, incident_id, incident_name, property_id, property_name, role, "
                       "response_time_rating, comms_rating, equipment_rating, coordination_rating, "
                       "hydrant_access, access_difficulty, hazards, what_went_well, improvements, overall_satisfaction) VALUES ("
                       + N(body.get("firefighter_id")) + ", " + S(body.get("firefighter_name"))
                       + ", " + N(body.get("incident_id")) + ", " + S(body.get("incident_name"))
                       + ", " + N(body.get("property_id")) + ", " + S(body.get("property_name")) + ", " + S(body.get("role"))
                       + ", " + N(body.get("response_time_rating")) + ", " + N(body.get("comms_rating"))
                       + ", " + N(body.get("equipment_rating")) + ", " + N(body.get("coordination_rating"))
                       + ", " + B(body.get("hydrant_access")) + ", " + S(body.get("access_difficulty"))
                       + ", " + S(body.get("hazards")) + ", " + S(body.get("what_went_well"))
                       + ", " + S(body.get("improvements")) + ", " + N(body.get("overall_satisfaction")) + ")")
                psql(sql)
                return self._send({"ok": True, "message": "Survey submitted"})
            except Exception as e:
                return self._send({"ok": False, "error": str(e)}, 500)
        return self._send({"error": "not found", "path": path}, 404)


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", 8001), Handler).serve_forever()
