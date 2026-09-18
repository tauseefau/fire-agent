--
-- PostgreSQL database dump
--

\restrict 4U6c7xiM2dTu0DftdKtCfTFXAEMUddRVHhhbAKFurqeSFViWoklA3rfe4SpoLaw

-- Dumped from database version 15.19 (Debian 15.19-1.pgdg13+2)
-- Dumped by pg_dump version 15.19 (Debian 15.19-1.pgdg13+2)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: ai; Type: SCHEMA; Schema: -; Owner: tauseef
--

CREATE SCHEMA ai;


ALTER SCHEMA ai OWNER TO tauseef;

--
-- Name: analytics; Type: SCHEMA; Schema: -; Owner: tauseef
--

CREATE SCHEMA analytics;


ALTER SCHEMA analytics OWNER TO tauseef;

--
-- Name: gis; Type: SCHEMA; Schema: -; Owner: tauseef
--

CREATE SCHEMA gis;


ALTER SCHEMA gis OWNER TO tauseef;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: incident_assessment; Type: TABLE; Schema: ai; Owner: tauseef
--

CREATE TABLE ai.incident_assessment (
    assessment_id integer NOT NULL,
    incident_id integer,
    risk_level text,
    exposed_assets integer,
    recommendation text,
    assessment_time timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE ai.incident_assessment OWNER TO tauseef;

--
-- Name: incident_assessment_assessment_id_seq; Type: SEQUENCE; Schema: ai; Owner: tauseef
--

CREATE SEQUENCE ai.incident_assessment_assessment_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE ai.incident_assessment_assessment_id_seq OWNER TO tauseef;

--
-- Name: incident_assessment_assessment_id_seq; Type: SEQUENCE OWNED BY; Schema: ai; Owner: tauseef
--

ALTER SEQUENCE ai.incident_assessment_assessment_id_seq OWNED BY ai.incident_assessment.assessment_id;


--
-- Name: dispatch; Type: TABLE; Schema: analytics; Owner: tauseef
--

CREATE TABLE analytics.dispatch (
    dispatch_internal_id bigint NOT NULL,
    incident_id integer,
    station_name text,
    apparatus_call_sign text,
    time_call_arrival timestamp without time zone,
    time_dispatched timestamp without time zone,
    time_on_scene timestamp without time zone,
    time_incident_clear timestamp without time zone,
    response_sec integer
);


ALTER TABLE analytics.dispatch OWNER TO tauseef;

--
-- Name: fire_departments; Type: TABLE; Schema: analytics; Owner: tauseef
--

CREATE TABLE analytics.fire_departments (
    fd_neris_id text NOT NULL,
    fd_name text,
    fd_type text,
    fd_organization text,
    fd_population_protected bigint,
    fd_station_count integer,
    fd_state text,
    fd_point public.geometry(Point,4326),
    fd_jurisdiction_set public.geometry(Geometry,4326)
);


ALTER TABLE analytics.fire_departments OWNER TO tauseef;

--
-- Name: incidents; Type: TABLE; Schema: analytics; Owner: tauseef
--

CREATE TABLE analytics.incidents (
    incident_neris_id text NOT NULL,
    incident_id integer,
    fd_neris_id text,
    incident_final_type text,
    incident_state_province text,
    incident_county text,
    incident_point public.geometry(Point,4326),
    nearest_station_id integer,
    distance_km numeric,
    reported_time timestamp without time zone
);


ALTER TABLE analytics.incidents OWNER TO tauseef;

--
-- Name: stations; Type: TABLE; Schema: analytics; Owner: tauseef
--

CREATE TABLE analytics.stations (
    station_id integer NOT NULL,
    fd_neris_id text,
    station_name text,
    station_staffing integer,
    station_unit_capability text,
    station_point public.geometry(Point,4326)
);


ALTER TABLE analytics.stations OWNER TO tauseef;

--
-- Name: agency_notifications; Type: TABLE; Schema: gis; Owner: tauseef
--

CREATE TABLE gis.agency_notifications (
    notification_id integer NOT NULL,
    incident_id integer,
    agency text,
    contact_method text,
    reference_number text,
    requested_at timestamp without time zone DEFAULT now(),
    acknowledged_at timestamp without time zone,
    status text DEFAULT 'Sent'::text,
    notes text
);


ALTER TABLE gis.agency_notifications OWNER TO tauseef;

--
-- Name: agency_notifications_notification_id_seq; Type: SEQUENCE; Schema: gis; Owner: tauseef
--

CREATE SEQUENCE gis.agency_notifications_notification_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE gis.agency_notifications_notification_id_seq OWNER TO tauseef;

--
-- Name: agency_notifications_notification_id_seq; Type: SEQUENCE OWNED BY; Schema: gis; Owner: tauseef
--

ALTER SEQUENCE gis.agency_notifications_notification_id_seq OWNED BY gis.agency_notifications.notification_id;


--
-- Name: agent_state; Type: TABLE; Schema: gis; Owner: tauseef
--

CREATE TABLE gis.agent_state (
    firefighter_id integer NOT NULL,
    step text DEFAULT 'idle'::text NOT NULL,
    context jsonb DEFAULT '{}'::jsonb NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


ALTER TABLE gis.agent_state OWNER TO tauseef;

--
-- Name: airs_codes; Type: TABLE; Schema: gis; Owner: tauseef
--

CREATE TABLE gis.airs_codes (
    airs_code text NOT NULL,
    airs_category text NOT NULL,
    airs_subcategory text,
    description text NOT NULL,
    keywords text[],
    nfirs_equivalent text,
    priority integer DEFAULT 1
);


ALTER TABLE gis.airs_codes OWNER TO tauseef;

--
-- Name: alarm_codes; Type: TABLE; Schema: gis; Owner: tauseef
--

CREATE TABLE gis.alarm_codes (
    alarm_code text NOT NULL,
    detection_method text NOT NULL,
    description text NOT NULL,
    priority text NOT NULL,
    as1670_category text,
    zone_type text
);


ALTER TABLE gis.alarm_codes OWNER TO tauseef;

--
-- Name: alarms; Type: TABLE; Schema: gis; Owner: tauseef
--

CREATE TABLE gis.alarms (
    alarm_id integer NOT NULL,
    property_id integer,
    alarm_date timestamp without time zone,
    alarm_type text,
    outcome text,
    geom public.geometry(Point,4326),
    alarm_code text
);


ALTER TABLE gis.alarms OWNER TO tauseef;

--
-- Name: alarms_alarm_id_seq; Type: SEQUENCE; Schema: gis; Owner: tauseef
--

CREATE SEQUENCE gis.alarms_alarm_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE gis.alarms_alarm_id_seq OWNER TO tauseef;

--
-- Name: alarms_alarm_id_seq; Type: SEQUENCE OWNED BY; Schema: gis; Owner: tauseef
--

ALTER SEQUENCE gis.alarms_alarm_id_seq OWNED BY gis.alarms.alarm_id;


--
-- Name: apparatus; Type: TABLE; Schema: gis; Owner: tauseef
--

CREATE TABLE gis.apparatus (
    apparatus_id integer NOT NULL,
    call_sign text,
    apparatus_type text,
    station_id integer,
    status text DEFAULT 'Available'::text,
    water_capacity_l integer,
    pump_capacity_lpm integer,
    crew_min integer,
    crew_max integer,
    equipment text[]
);


ALTER TABLE gis.apparatus OWNER TO tauseef;

--
-- Name: apparatus_apparatus_id_seq; Type: SEQUENCE; Schema: gis; Owner: tauseef
--

CREATE SEQUENCE gis.apparatus_apparatus_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE gis.apparatus_apparatus_id_seq OWNER TO tauseef;

--
-- Name: apparatus_apparatus_id_seq; Type: SEQUENCE OWNED BY; Schema: gis; Owner: tauseef
--

ALTER SEQUENCE gis.apparatus_apparatus_id_seq OWNED BY gis.apparatus.apparatus_id;


--
-- Name: assets; Type: TABLE; Schema: gis; Owner: tauseef
--

CREATE TABLE gis.assets (
    asset_id integer NOT NULL,
    asset_name text,
    asset_type text,
    risk_category text,
    geom public.geometry(Point,4326),
    capacity_litres numeric,
    description text
);


ALTER TABLE gis.assets OWNER TO tauseef;

--
-- Name: assets_asset_id_seq; Type: SEQUENCE; Schema: gis; Owner: tauseef
--

CREATE SEQUENCE gis.assets_asset_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE gis.assets_asset_id_seq OWNER TO tauseef;

--
-- Name: assets_asset_id_seq; Type: SEQUENCE OWNED BY; Schema: gis; Owner: tauseef
--

ALTER SEQUENCE gis.assets_asset_id_seq OWNED BY gis.assets.asset_id;


--
-- Name: call_notes; Type: TABLE; Schema: gis; Owner: tauseef
--

CREATE TABLE gis.call_notes (
    note_id integer NOT NULL,
    property_id integer,
    firefighter_id integer,
    note_text text NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE gis.call_notes OWNER TO tauseef;

--
-- Name: call_notes_note_id_seq; Type: SEQUENCE; Schema: gis; Owner: tauseef
--

CREATE SEQUENCE gis.call_notes_note_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE gis.call_notes_note_id_seq OWNER TO tauseef;

--
-- Name: call_notes_note_id_seq; Type: SEQUENCE OWNED BY; Schema: gis; Owner: tauseef
--

ALTER SEQUENCE gis.call_notes_note_id_seq OWNED BY gis.call_notes.note_id;


--
-- Name: conversation_log; Type: TABLE; Schema: gis; Owner: tauseef
--

CREATE TABLE gis.conversation_log (
    log_id integer NOT NULL,
    firefighter_id integer,
    property_id integer,
    question text,
    answer text,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE gis.conversation_log OWNER TO tauseef;

--
-- Name: conversation_log_log_id_seq; Type: SEQUENCE; Schema: gis; Owner: tauseef
--

CREATE SEQUENCE gis.conversation_log_log_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE gis.conversation_log_log_id_seq OWNER TO tauseef;

--
-- Name: conversation_log_log_id_seq; Type: SEQUENCE OWNED BY; Schema: gis; Owner: tauseef
--

ALTER SEQUENCE gis.conversation_log_log_id_seq OWNED BY gis.conversation_log.log_id;


--
-- Name: dispatch_log; Type: TABLE; Schema: gis; Owner: tauseef
--

CREATE TABLE gis.dispatch_log (
    dispatch_id integer NOT NULL,
    incident_id integer,
    apparatus_id integer,
    apparatus_call_sign text,
    apparatus_type text,
    station_name text,
    dispatched_at timestamp without time zone,
    arrived_at timestamp without time zone,
    cleared_at timestamp without time zone,
    role text,
    firefighter_ids integer[],
    notes text,
    turned_out_at timestamp without time zone,
    enroute_at timestamp without time zone,
    on_scene_at timestamp without time zone,
    return_station_at timestamp without time zone,
    in_station_at timestamp without time zone
);


ALTER TABLE gis.dispatch_log OWNER TO tauseef;

--
-- Name: dispatch_log_dispatch_id_seq; Type: SEQUENCE; Schema: gis; Owner: tauseef
--

CREATE SEQUENCE gis.dispatch_log_dispatch_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE gis.dispatch_log_dispatch_id_seq OWNER TO tauseef;

--
-- Name: dispatch_log_dispatch_id_seq; Type: SEQUENCE OWNED BY; Schema: gis; Owner: tauseef
--

ALTER SEQUENCE gis.dispatch_log_dispatch_id_seq OWNED BY gis.dispatch_log.dispatch_id;


--
-- Name: fire_stations; Type: TABLE; Schema: gis; Owner: tauseef
--

CREATE TABLE gis.fire_stations (
    station_id integer NOT NULL,
    station_name text,
    tankers integer,
    personnel integer,
    geom public.geometry(Point,4326)
);


ALTER TABLE gis.fire_stations OWNER TO tauseef;

--
-- Name: fire_stations_station_id_seq; Type: SEQUENCE; Schema: gis; Owner: tauseef
--

CREATE SEQUENCE gis.fire_stations_station_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE gis.fire_stations_station_id_seq OWNER TO tauseef;

--
-- Name: fire_stations_station_id_seq; Type: SEQUENCE OWNED BY; Schema: gis; Owner: tauseef
--

ALTER SEQUENCE gis.fire_stations_station_id_seq OWNED BY gis.fire_stations.station_id;


--
-- Name: firefighters; Type: TABLE; Schema: gis; Owner: tauseef
--

CREATE TABLE gis.firefighters (
    firefighter_id integer NOT NULL,
    call_sign text NOT NULL,
    full_name text,
    station_id integer,
    role text,
    auth_id text NOT NULL,
    voice_credential text,
    phone text,
    active boolean DEFAULT true,
    email text,
    qualifications text[],
    current_shift text
);


ALTER TABLE gis.firefighters OWNER TO tauseef;

--
-- Name: firefighters_firefighter_id_seq; Type: SEQUENCE; Schema: gis; Owner: tauseef
--

CREATE SEQUENCE gis.firefighters_firefighter_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE gis.firefighters_firefighter_id_seq OWNER TO tauseef;

--
-- Name: firefighters_firefighter_id_seq; Type: SEQUENCE OWNED BY; Schema: gis; Owner: tauseef
--

ALTER SEQUENCE gis.firefighters_firefighter_id_seq OWNED BY gis.firefighters.firefighter_id;


--
-- Name: hydrants; Type: TABLE; Schema: gis; Owner: tauseef
--

CREATE TABLE gis.hydrants (
    hydrant_id integer NOT NULL,
    hydrant_number text,
    flow_rate integer,
    status text,
    geom public.geometry(Point,4326)
);


ALTER TABLE gis.hydrants OWNER TO tauseef;

--
-- Name: hydrants_hydrant_id_seq; Type: SEQUENCE; Schema: gis; Owner: tauseef
--

CREATE SEQUENCE gis.hydrants_hydrant_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE gis.hydrants_hydrant_id_seq OWNER TO tauseef;

--
-- Name: hydrants_hydrant_id_seq; Type: SEQUENCE OWNED BY; Schema: gis; Owner: tauseef
--

ALTER SEQUENCE gis.hydrants_hydrant_id_seq OWNED BY gis.hydrants.hydrant_id;


--
-- Name: incident_reports; Type: TABLE; Schema: gis; Owner: tauseef
--

CREATE TABLE gis.incident_reports (
    report_id integer NOT NULL,
    incident_id integer,
    report_type text,
    content_json jsonb,
    content_text text,
    generated_by integer,
    generated_at timestamp without time zone DEFAULT now(),
    status text DEFAULT 'Draft'::text
);


ALTER TABLE gis.incident_reports OWNER TO tauseef;

--
-- Name: incident_reports_report_id_seq; Type: SEQUENCE; Schema: gis; Owner: tauseef
--

CREATE SEQUENCE gis.incident_reports_report_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE gis.incident_reports_report_id_seq OWNER TO tauseef;

--
-- Name: incident_reports_report_id_seq; Type: SEQUENCE OWNED BY; Schema: gis; Owner: tauseef
--

ALTER SEQUENCE gis.incident_reports_report_id_seq OWNED BY gis.incident_reports.report_id;


--
-- Name: incidents; Type: TABLE; Schema: gis; Owner: tauseef
--

CREATE TABLE gis.incidents (
    incident_id integer NOT NULL,
    incident_name text,
    incident_type text,
    status text,
    reported_time timestamp without time zone DEFAULT now(),
    geom public.geometry(Point,4326),
    comment text,
    firefighter_id integer,
    airs_code text,
    airs_suggested_code text,
    airs_suggestion_reason text,
    airs_confirmed_by integer,
    airs_confirmed_at timestamp without time zone
);


ALTER TABLE gis.incidents OWNER TO tauseef;

--
-- Name: incidents_incident_id_seq; Type: SEQUENCE; Schema: gis; Owner: tauseef
--

CREATE SEQUENCE gis.incidents_incident_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE gis.incidents_incident_id_seq OWNER TO tauseef;

--
-- Name: incidents_incident_id_seq; Type: SEQUENCE OWNED BY; Schema: gis; Owner: tauseef
--

ALTER SEQUENCE gis.incidents_incident_id_seq OWNED BY gis.incidents.incident_id;


--
-- Name: post_incident_surveys; Type: TABLE; Schema: gis; Owner: tauseef
--

CREATE TABLE gis.post_incident_surveys (
    survey_id integer NOT NULL,
    firefighter_id integer,
    firefighter_name text,
    incident_id integer,
    incident_name text,
    property_id integer,
    property_name text,
    role text,
    response_time_rating integer,
    comms_rating integer,
    equipment_rating integer,
    coordination_rating integer,
    hydrant_access boolean,
    access_difficulty text,
    hazards text,
    what_went_well text,
    improvements text,
    overall_satisfaction integer,
    created_at timestamp without time zone DEFAULT now(),
    CONSTRAINT post_incident_surveys_comms_rating_check CHECK (((comms_rating >= 1) AND (comms_rating <= 5))),
    CONSTRAINT post_incident_surveys_coordination_rating_check CHECK (((coordination_rating >= 1) AND (coordination_rating <= 5))),
    CONSTRAINT post_incident_surveys_equipment_rating_check CHECK (((equipment_rating >= 1) AND (equipment_rating <= 5))),
    CONSTRAINT post_incident_surveys_overall_satisfaction_check CHECK (((overall_satisfaction >= 1) AND (overall_satisfaction <= 5))),
    CONSTRAINT post_incident_surveys_response_time_rating_check CHECK (((response_time_rating >= 1) AND (response_time_rating <= 5)))
);


ALTER TABLE gis.post_incident_surveys OWNER TO tauseef;

--
-- Name: post_incident_surveys_survey_id_seq; Type: SEQUENCE; Schema: gis; Owner: tauseef
--

CREATE SEQUENCE gis.post_incident_surveys_survey_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE gis.post_incident_surveys_survey_id_seq OWNER TO tauseef;

--
-- Name: post_incident_surveys_survey_id_seq; Type: SEQUENCE OWNED BY; Schema: gis; Owner: tauseef
--

ALTER SEQUENCE gis.post_incident_surveys_survey_id_seq OWNED BY gis.post_incident_surveys.survey_id;


--
-- Name: properties; Type: TABLE; Schema: gis; Owner: tauseef
--

CREATE TABLE gis.properties (
    property_id integer NOT NULL,
    property_name text,
    property_type text,
    geom public.geometry(Point,4326),
    construction_type text,
    occupancy_type text,
    floors integer,
    floor_area_sqm numeric,
    sprinkler_coverage text,
    alarm_system text,
    access_notes text,
    hazards text,
    aliases text
);


ALTER TABLE gis.properties OWNER TO tauseef;

--
-- Name: properties_property_id_seq; Type: SEQUENCE; Schema: gis; Owner: tauseef
--

CREATE SEQUENCE gis.properties_property_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE gis.properties_property_id_seq OWNER TO tauseef;

--
-- Name: properties_property_id_seq; Type: SEQUENCE OWNED BY; Schema: gis; Owner: tauseef
--

ALTER SEQUENCE gis.properties_property_id_seq OWNED BY gis.properties.property_id;


--
-- Name: property_risks; Type: TABLE; Schema: gis; Owner: tauseef
--

CREATE TABLE gis.property_risks (
    risk_id integer NOT NULL,
    property_id integer,
    risk_type text,
    risk_level text
);


ALTER TABLE gis.property_risks OWNER TO tauseef;

--
-- Name: property_risks_risk_id_seq; Type: SEQUENCE; Schema: gis; Owner: tauseef
--

CREATE SEQUENCE gis.property_risks_risk_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE gis.property_risks_risk_id_seq OWNER TO tauseef;

--
-- Name: property_risks_risk_id_seq; Type: SEQUENCE OWNED BY; Schema: gis; Owner: tauseef
--

ALTER SEQUENCE gis.property_risks_risk_id_seq OWNED BY gis.property_risks.risk_id;


--
-- Name: standard_operating_procedures; Type: TABLE; Schema: gis; Owner: tauseef
--

CREATE TABLE gis.standard_operating_procedures (
    sop_id integer NOT NULL,
    sop_number text,
    title text,
    incident_types text[],
    keywords text[],
    content text,
    version text DEFAULT '1.0'::text,
    effective_date date DEFAULT CURRENT_DATE
);


ALTER TABLE gis.standard_operating_procedures OWNER TO tauseef;

--
-- Name: standard_operating_procedures_sop_id_seq; Type: SEQUENCE; Schema: gis; Owner: tauseef
--

CREATE SEQUENCE gis.standard_operating_procedures_sop_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE gis.standard_operating_procedures_sop_id_seq OWNER TO tauseef;

--
-- Name: standard_operating_procedures_sop_id_seq; Type: SEQUENCE OWNED BY; Schema: gis; Owner: tauseef
--

ALTER SEQUENCE gis.standard_operating_procedures_sop_id_seq OWNED BY gis.standard_operating_procedures.sop_id;


--
-- Name: v_alarm_analysis; Type: VIEW; Schema: gis; Owner: tauseef
--

CREATE VIEW gis.v_alarm_analysis AS
 SELECT a.alarm_id,
    a.property_id,
    p.property_name,
    p.property_type,
    a.alarm_date,
    a.alarm_type,
    a.alarm_code,
    ac.detection_method,
    ac.description AS alarm_description,
    ac.priority AS alarm_priority,
    ac.as1670_category,
    ac.zone_type,
    a.outcome,
        CASE
            WHEN (a.outcome ~~* 'REAL FIRE%'::text) THEN 'Real Fire'::text
            WHEN (a.outcome ~~* 'MALICIOUS%'::text) THEN 'Malicious False'::text
            ELSE 'False Alarm'::text
        END AS result_classification,
    (public.st_y(a.geom))::numeric(9,6) AS lat,
    (public.st_x(a.geom))::numeric(9,6) AS lon
   FROM ((gis.alarms a
     JOIN gis.properties p ON ((p.property_id = a.property_id)))
     LEFT JOIN gis.alarm_codes ac ON ((ac.alarm_code = a.alarm_code)));


ALTER TABLE gis.v_alarm_analysis OWNER TO tauseef;

--
-- Name: v_assets; Type: VIEW; Schema: gis; Owner: tauseef
--

CREATE VIEW gis.v_assets AS
 SELECT assets.asset_id,
    assets.asset_name,
    assets.asset_type,
    assets.risk_category,
    round((public.st_y(assets.geom))::numeric, 6) AS lat,
    round((public.st_x(assets.geom))::numeric, 6) AS lon
   FROM gis.assets;


ALTER TABLE gis.v_assets OWNER TO tauseef;

--
-- Name: v_call_notes; Type: VIEW; Schema: gis; Owner: tauseef
--

CREATE VIEW gis.v_call_notes AS
 SELECT cn.note_id,
    cn.property_id,
    p.property_name,
    ff.call_sign,
    ff.full_name AS firefighter,
    cn.note_text,
    cn.created_at
   FROM ((gis.call_notes cn
     LEFT JOIN gis.properties p ON ((p.property_id = cn.property_id)))
     LEFT JOIN gis.firefighters ff ON ((ff.firefighter_id = cn.firefighter_id)));


ALTER TABLE gis.v_call_notes OWNER TO tauseef;

--
-- Name: v_conversation_log; Type: VIEW; Schema: gis; Owner: tauseef
--

CREATE VIEW gis.v_conversation_log AS
 SELECT cl.log_id,
    ff.call_sign,
    ff.full_name AS firefighter,
    cl.property_id,
    p.property_name,
    cl.question,
    cl.answer,
    cl.created_at
   FROM ((gis.conversation_log cl
     LEFT JOIN gis.firefighters ff ON ((ff.firefighter_id = cl.firefighter_id)))
     LEFT JOIN gis.properties p ON ((p.property_id = cl.property_id)));


ALTER TABLE gis.v_conversation_log OWNER TO tauseef;

--
-- Name: v_fire_stations; Type: VIEW; Schema: gis; Owner: tauseef
--

CREATE VIEW gis.v_fire_stations AS
 SELECT fire_stations.station_id,
    fire_stations.station_name,
    fire_stations.tankers,
    fire_stations.personnel,
    round((public.st_y(fire_stations.geom))::numeric, 6) AS lat,
    round((public.st_x(fire_stations.geom))::numeric, 6) AS lon
   FROM gis.fire_stations;


ALTER TABLE gis.v_fire_stations OWNER TO tauseef;

--
-- Name: v_hydrants; Type: VIEW; Schema: gis; Owner: tauseef
--

CREATE VIEW gis.v_hydrants AS
 SELECT hydrants.hydrant_id,
    hydrants.hydrant_number,
    hydrants.flow_rate,
    hydrants.status,
    round((public.st_y(hydrants.geom))::numeric, 6) AS lat,
    round((public.st_x(hydrants.geom))::numeric, 6) AS lon
   FROM gis.hydrants;


ALTER TABLE gis.v_hydrants OWNER TO tauseef;

--
-- Name: v_incidents; Type: VIEW; Schema: gis; Owner: tauseef
--

CREATE VIEW gis.v_incidents AS
 SELECT i.incident_id,
    i.incident_name,
    i.incident_type,
    i.status,
    i.reported_time,
    round((public.st_y(i.geom))::numeric, 6) AS lat,
    round((public.st_x(i.geom))::numeric, 6) AS lon,
    i.geom,
    i.comment,
    i.firefighter_id,
    ff.call_sign AS firefighter_call_sign,
    ff.full_name AS firefighter_name,
    i.airs_code,
    i.airs_suggested_code,
    i.airs_suggestion_reason,
    i.airs_confirmed_by,
    i.airs_confirmed_at,
    ffc.full_name AS airs_confirmed_by_name,
    ac.airs_category,
    ac.airs_subcategory,
    ac.description AS airs_description,
    ac.nfirs_equivalent
   FROM (((gis.incidents i
     LEFT JOIN gis.firefighters ff ON ((ff.firefighter_id = i.firefighter_id)))
     LEFT JOIN gis.firefighters ffc ON ((ffc.firefighter_id = i.airs_confirmed_by)))
     LEFT JOIN gis.airs_codes ac ON ((ac.airs_code = COALESCE(i.airs_code, i.airs_suggested_code))));


ALTER TABLE gis.v_incidents OWNER TO tauseef;

--
-- Name: v_property_risks; Type: VIEW; Schema: gis; Owner: tauseef
--

CREATE VIEW gis.v_property_risks AS
 SELECT r.risk_id,
    r.property_id,
    p.property_name,
    p.property_type,
    r.risk_type,
    r.risk_level,
    round((public.st_y(p.geom))::numeric, 6) AS lat,
    round((public.st_x(p.geom))::numeric, 6) AS lon
   FROM (gis.property_risks r
     LEFT JOIN gis.properties p ON ((p.property_id = r.property_id)));


ALTER TABLE gis.v_property_risks OWNER TO tauseef;

--
-- Name: water_sources; Type: TABLE; Schema: gis; Owner: tauseef
--

CREATE TABLE gis.water_sources (
    water_source_id integer NOT NULL,
    source_name text,
    source_type text,
    capacity_litres numeric,
    geom public.geometry(Point,4326)
);


ALTER TABLE gis.water_sources OWNER TO tauseef;

--
-- Name: v_water_sources; Type: VIEW; Schema: gis; Owner: tauseef
--

CREATE VIEW gis.v_water_sources AS
 SELECT water_sources.water_source_id,
    water_sources.source_name,
    water_sources.source_type,
    water_sources.capacity_litres,
    round((public.st_y(water_sources.geom))::numeric, 6) AS lat,
    round((public.st_x(water_sources.geom))::numeric, 6) AS lon
   FROM gis.water_sources;


ALTER TABLE gis.v_water_sources OWNER TO tauseef;

--
-- Name: water_sources_water_source_id_seq; Type: SEQUENCE; Schema: gis; Owner: tauseef
--

CREATE SEQUENCE gis.water_sources_water_source_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE gis.water_sources_water_source_id_seq OWNER TO tauseef;

--
-- Name: water_sources_water_source_id_seq; Type: SEQUENCE OWNED BY; Schema: gis; Owner: tauseef
--

ALTER SEQUENCE gis.water_sources_water_source_id_seq OWNED BY gis.water_sources.water_source_id;


--
-- Name: weather_observations; Type: TABLE; Schema: gis; Owner: tauseef
--

CREATE TABLE gis.weather_observations (
    obs_id integer NOT NULL,
    district text,
    observed_at timestamp without time zone,
    temp_c numeric,
    humidity_pct integer,
    wind_kmh integer,
    wind_dir text,
    fdr_rating text,
    fdr_index numeric,
    source text DEFAULT 'BOM'::text
);


ALTER TABLE gis.weather_observations OWNER TO tauseef;

--
-- Name: weather_observations_obs_id_seq; Type: SEQUENCE; Schema: gis; Owner: tauseef
--

CREATE SEQUENCE gis.weather_observations_obs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE gis.weather_observations_obs_id_seq OWNER TO tauseef;

--
-- Name: weather_observations_obs_id_seq; Type: SEQUENCE OWNED BY; Schema: gis; Owner: tauseef
--

ALTER SEQUENCE gis.weather_observations_obs_id_seq OWNED BY gis.weather_observations.obs_id;


--
-- Name: incident_assessment assessment_id; Type: DEFAULT; Schema: ai; Owner: tauseef
--

ALTER TABLE ONLY ai.incident_assessment ALTER COLUMN assessment_id SET DEFAULT nextval('ai.incident_assessment_assessment_id_seq'::regclass);


--
-- Name: agency_notifications notification_id; Type: DEFAULT; Schema: gis; Owner: tauseef
--

ALTER TABLE ONLY gis.agency_notifications ALTER COLUMN notification_id SET DEFAULT nextval('gis.agency_notifications_notification_id_seq'::regclass);


--
-- Name: alarms alarm_id; Type: DEFAULT; Schema: gis; Owner: tauseef
--

ALTER TABLE ONLY gis.alarms ALTER COLUMN alarm_id SET DEFAULT nextval('gis.alarms_alarm_id_seq'::regclass);


--
-- Name: apparatus apparatus_id; Type: DEFAULT; Schema: gis; Owner: tauseef
--

ALTER TABLE ONLY gis.apparatus ALTER COLUMN apparatus_id SET DEFAULT nextval('gis.apparatus_apparatus_id_seq'::regclass);


--
-- Name: assets asset_id; Type: DEFAULT; Schema: gis; Owner: tauseef
--

ALTER TABLE ONLY gis.assets ALTER COLUMN asset_id SET DEFAULT nextval('gis.assets_asset_id_seq'::regclass);


--
-- Name: call_notes note_id; Type: DEFAULT; Schema: gis; Owner: tauseef
--

ALTER TABLE ONLY gis.call_notes ALTER COLUMN note_id SET DEFAULT nextval('gis.call_notes_note_id_seq'::regclass);


--
-- Name: conversation_log log_id; Type: DEFAULT; Schema: gis; Owner: tauseef
--

ALTER TABLE ONLY gis.conversation_log ALTER COLUMN log_id SET DEFAULT nextval('gis.conversation_log_log_id_seq'::regclass);


--
-- Name: dispatch_log dispatch_id; Type: DEFAULT; Schema: gis; Owner: tauseef
--

ALTER TABLE ONLY gis.dispatch_log ALTER COLUMN dispatch_id SET DEFAULT nextval('gis.dispatch_log_dispatch_id_seq'::regclass);


--
-- Name: fire_stations station_id; Type: DEFAULT; Schema: gis; Owner: tauseef
--

ALTER TABLE ONLY gis.fire_stations ALTER COLUMN station_id SET DEFAULT nextval('gis.fire_stations_station_id_seq'::regclass);


--
-- Name: firefighters firefighter_id; Type: DEFAULT; Schema: gis; Owner: tauseef
--

ALTER TABLE ONLY gis.firefighters ALTER COLUMN firefighter_id SET DEFAULT nextval('gis.firefighters_firefighter_id_seq'::regclass);


--
-- Name: hydrants hydrant_id; Type: DEFAULT; Schema: gis; Owner: tauseef
--

ALTER TABLE ONLY gis.hydrants ALTER COLUMN hydrant_id SET DEFAULT nextval('gis.hydrants_hydrant_id_seq'::regclass);


--
-- Name: incident_reports report_id; Type: DEFAULT; Schema: gis; Owner: tauseef
--

ALTER TABLE ONLY gis.incident_reports ALTER COLUMN report_id SET DEFAULT nextval('gis.incident_reports_report_id_seq'::regclass);


--
-- Name: incidents incident_id; Type: DEFAULT; Schema: gis; Owner: tauseef
--

ALTER TABLE ONLY gis.incidents ALTER COLUMN incident_id SET DEFAULT nextval('gis.incidents_incident_id_seq'::regclass);


--
-- Name: post_incident_surveys survey_id; Type: DEFAULT; Schema: gis; Owner: tauseef
--

ALTER TABLE ONLY gis.post_incident_surveys ALTER COLUMN survey_id SET DEFAULT nextval('gis.post_incident_surveys_survey_id_seq'::regclass);


--
-- Name: properties property_id; Type: DEFAULT; Schema: gis; Owner: tauseef
--

ALTER TABLE ONLY gis.properties ALTER COLUMN property_id SET DEFAULT nextval('gis.properties_property_id_seq'::regclass);


--
-- Name: property_risks risk_id; Type: DEFAULT; Schema: gis; Owner: tauseef
--

ALTER TABLE ONLY gis.property_risks ALTER COLUMN risk_id SET DEFAULT nextval('gis.property_risks_risk_id_seq'::regclass);


--
-- Name: standard_operating_procedures sop_id; Type: DEFAULT; Schema: gis; Owner: tauseef
--

ALTER TABLE ONLY gis.standard_operating_procedures ALTER COLUMN sop_id SET DEFAULT nextval('gis.standard_operating_procedures_sop_id_seq'::regclass);


--
-- Name: water_sources water_source_id; Type: DEFAULT; Schema: gis; Owner: tauseef
--

ALTER TABLE ONLY gis.water_sources ALTER COLUMN water_source_id SET DEFAULT nextval('gis.water_sources_water_source_id_seq'::regclass);


--
-- Name: weather_observations obs_id; Type: DEFAULT; Schema: gis; Owner: tauseef
--

ALTER TABLE ONLY gis.weather_observations ALTER COLUMN obs_id SET DEFAULT nextval('gis.weather_observations_obs_id_seq'::regclass);


--
-- Name: incident_assessment incident_assessment_pkey; Type: CONSTRAINT; Schema: ai; Owner: tauseef
--

ALTER TABLE ONLY ai.incident_assessment
    ADD CONSTRAINT incident_assessment_pkey PRIMARY KEY (assessment_id);


--
-- Name: dispatch dispatch_pkey; Type: CONSTRAINT; Schema: analytics; Owner: tauseef
--

ALTER TABLE ONLY analytics.dispatch
    ADD CONSTRAINT dispatch_pkey PRIMARY KEY (dispatch_internal_id);


--
-- Name: fire_departments fire_departments_pkey; Type: CONSTRAINT; Schema: analytics; Owner: tauseef
--

ALTER TABLE ONLY analytics.fire_departments
    ADD CONSTRAINT fire_departments_pkey PRIMARY KEY (fd_neris_id);


--
-- Name: incidents incidents_pkey; Type: CONSTRAINT; Schema: analytics; Owner: tauseef
--

ALTER TABLE ONLY analytics.incidents
    ADD CONSTRAINT incidents_pkey PRIMARY KEY (incident_neris_id);


--
-- Name: stations stations_pkey; Type: CONSTRAINT; Schema: analytics; Owner: tauseef
--

ALTER TABLE ONLY analytics.stations
    ADD CONSTRAINT stations_pkey PRIMARY KEY (station_id);


--
-- Name: agency_notifications agency_notifications_pkey; Type: CONSTRAINT; Schema: gis; Owner: tauseef
--

ALTER TABLE ONLY gis.agency_notifications
    ADD CONSTRAINT agency_notifications_pkey PRIMARY KEY (notification_id);


--
-- Name: agent_state agent_state_pkey; Type: CONSTRAINT; Schema: gis; Owner: tauseef
--

ALTER TABLE ONLY gis.agent_state
    ADD CONSTRAINT agent_state_pkey PRIMARY KEY (firefighter_id);


--
-- Name: airs_codes airs_codes_pkey; Type: CONSTRAINT; Schema: gis; Owner: tauseef
--

ALTER TABLE ONLY gis.airs_codes
    ADD CONSTRAINT airs_codes_pkey PRIMARY KEY (airs_code);


--
-- Name: alarm_codes alarm_codes_pkey; Type: CONSTRAINT; Schema: gis; Owner: tauseef
--

ALTER TABLE ONLY gis.alarm_codes
    ADD CONSTRAINT alarm_codes_pkey PRIMARY KEY (alarm_code);


--
-- Name: alarms alarms_pkey; Type: CONSTRAINT; Schema: gis; Owner: tauseef
--

ALTER TABLE ONLY gis.alarms
    ADD CONSTRAINT alarms_pkey PRIMARY KEY (alarm_id);


--
-- Name: apparatus apparatus_call_sign_key; Type: CONSTRAINT; Schema: gis; Owner: tauseef
--

ALTER TABLE ONLY gis.apparatus
    ADD CONSTRAINT apparatus_call_sign_key UNIQUE (call_sign);


--
-- Name: apparatus apparatus_pkey; Type: CONSTRAINT; Schema: gis; Owner: tauseef
--

ALTER TABLE ONLY gis.apparatus
    ADD CONSTRAINT apparatus_pkey PRIMARY KEY (apparatus_id);


--
-- Name: assets assets_pkey; Type: CONSTRAINT; Schema: gis; Owner: tauseef
--

ALTER TABLE ONLY gis.assets
    ADD CONSTRAINT assets_pkey PRIMARY KEY (asset_id);


--
-- Name: call_notes call_notes_pkey; Type: CONSTRAINT; Schema: gis; Owner: tauseef
--

ALTER TABLE ONLY gis.call_notes
    ADD CONSTRAINT call_notes_pkey PRIMARY KEY (note_id);


--
-- Name: conversation_log conversation_log_pkey; Type: CONSTRAINT; Schema: gis; Owner: tauseef
--

ALTER TABLE ONLY gis.conversation_log
    ADD CONSTRAINT conversation_log_pkey PRIMARY KEY (log_id);


--
-- Name: dispatch_log dispatch_log_pkey; Type: CONSTRAINT; Schema: gis; Owner: tauseef
--

ALTER TABLE ONLY gis.dispatch_log
    ADD CONSTRAINT dispatch_log_pkey PRIMARY KEY (dispatch_id);


--
-- Name: fire_stations fire_stations_pkey; Type: CONSTRAINT; Schema: gis; Owner: tauseef
--

ALTER TABLE ONLY gis.fire_stations
    ADD CONSTRAINT fire_stations_pkey PRIMARY KEY (station_id);


--
-- Name: firefighters firefighters_auth_id_key; Type: CONSTRAINT; Schema: gis; Owner: tauseef
--

ALTER TABLE ONLY gis.firefighters
    ADD CONSTRAINT firefighters_auth_id_key UNIQUE (auth_id);


--
-- Name: firefighters firefighters_call_sign_key; Type: CONSTRAINT; Schema: gis; Owner: tauseef
--

ALTER TABLE ONLY gis.firefighters
    ADD CONSTRAINT firefighters_call_sign_key UNIQUE (call_sign);


--
-- Name: firefighters firefighters_pkey; Type: CONSTRAINT; Schema: gis; Owner: tauseef
--

ALTER TABLE ONLY gis.firefighters
    ADD CONSTRAINT firefighters_pkey PRIMARY KEY (firefighter_id);


--
-- Name: hydrants hydrants_pkey; Type: CONSTRAINT; Schema: gis; Owner: tauseef
--

ALTER TABLE ONLY gis.hydrants
    ADD CONSTRAINT hydrants_pkey PRIMARY KEY (hydrant_id);


--
-- Name: incident_reports incident_reports_pkey; Type: CONSTRAINT; Schema: gis; Owner: tauseef
--

ALTER TABLE ONLY gis.incident_reports
    ADD CONSTRAINT incident_reports_pkey PRIMARY KEY (report_id);


--
-- Name: incidents incidents_pkey; Type: CONSTRAINT; Schema: gis; Owner: tauseef
--

ALTER TABLE ONLY gis.incidents
    ADD CONSTRAINT incidents_pkey PRIMARY KEY (incident_id);


--
-- Name: post_incident_surveys post_incident_surveys_pkey; Type: CONSTRAINT; Schema: gis; Owner: tauseef
--

ALTER TABLE ONLY gis.post_incident_surveys
    ADD CONSTRAINT post_incident_surveys_pkey PRIMARY KEY (survey_id);


--
-- Name: properties properties_pkey; Type: CONSTRAINT; Schema: gis; Owner: tauseef
--

ALTER TABLE ONLY gis.properties
    ADD CONSTRAINT properties_pkey PRIMARY KEY (property_id);


--
-- Name: property_risks property_risks_pkey; Type: CONSTRAINT; Schema: gis; Owner: tauseef
--

ALTER TABLE ONLY gis.property_risks
    ADD CONSTRAINT property_risks_pkey PRIMARY KEY (risk_id);


--
-- Name: standard_operating_procedures standard_operating_procedures_pkey; Type: CONSTRAINT; Schema: gis; Owner: tauseef
--

ALTER TABLE ONLY gis.standard_operating_procedures
    ADD CONSTRAINT standard_operating_procedures_pkey PRIMARY KEY (sop_id);


--
-- Name: standard_operating_procedures standard_operating_procedures_sop_number_key; Type: CONSTRAINT; Schema: gis; Owner: tauseef
--

ALTER TABLE ONLY gis.standard_operating_procedures
    ADD CONSTRAINT standard_operating_procedures_sop_number_key UNIQUE (sop_number);


--
-- Name: water_sources water_sources_pkey; Type: CONSTRAINT; Schema: gis; Owner: tauseef
--

ALTER TABLE ONLY gis.water_sources
    ADD CONSTRAINT water_sources_pkey PRIMARY KEY (water_source_id);


--
-- Name: weather_observations weather_observations_pkey; Type: CONSTRAINT; Schema: gis; Owner: tauseef
--

ALTER TABLE ONLY gis.weather_observations
    ADD CONSTRAINT weather_observations_pkey PRIMARY KEY (obs_id);


--
-- Name: idx_alarms_geom; Type: INDEX; Schema: gis; Owner: tauseef
--

CREATE INDEX idx_alarms_geom ON gis.alarms USING gist (geom);


--
-- Name: idx_assets_geom; Type: INDEX; Schema: gis; Owner: tauseef
--

CREATE INDEX idx_assets_geom ON gis.assets USING gist (geom);


--
-- Name: idx_call_notes_property; Type: INDEX; Schema: gis; Owner: tauseef
--

CREATE INDEX idx_call_notes_property ON gis.call_notes USING btree (property_id);


--
-- Name: idx_conversation_firefighter; Type: INDEX; Schema: gis; Owner: tauseef
--

CREATE INDEX idx_conversation_firefighter ON gis.conversation_log USING btree (firefighter_id);


--
-- Name: idx_conversation_property; Type: INDEX; Schema: gis; Owner: tauseef
--

CREATE INDEX idx_conversation_property ON gis.conversation_log USING btree (property_id);


--
-- Name: idx_fire_stations_geom; Type: INDEX; Schema: gis; Owner: tauseef
--

CREATE INDEX idx_fire_stations_geom ON gis.fire_stations USING gist (geom);


--
-- Name: idx_hydrants_geom; Type: INDEX; Schema: gis; Owner: tauseef
--

CREATE INDEX idx_hydrants_geom ON gis.hydrants USING gist (geom);


--
-- Name: idx_incidents_geom; Type: INDEX; Schema: gis; Owner: tauseef
--

CREATE INDEX idx_incidents_geom ON gis.incidents USING gist (geom);


--
-- Name: idx_properties_geom; Type: INDEX; Schema: gis; Owner: tauseef
--

CREATE INDEX idx_properties_geom ON gis.properties USING gist (geom);


--
-- Name: idx_water_sources_geom; Type: INDEX; Schema: gis; Owner: tauseef
--

CREATE INDEX idx_water_sources_geom ON gis.water_sources USING gist (geom);


--
-- Name: incident_assessment fk_assessment_incident; Type: FK CONSTRAINT; Schema: ai; Owner: tauseef
--

ALTER TABLE ONLY ai.incident_assessment
    ADD CONSTRAINT fk_assessment_incident FOREIGN KEY (incident_id) REFERENCES gis.incidents(incident_id);


--
-- Name: stations stations_fd_neris_id_fkey; Type: FK CONSTRAINT; Schema: analytics; Owner: tauseef
--

ALTER TABLE ONLY analytics.stations
    ADD CONSTRAINT stations_fd_neris_id_fkey FOREIGN KEY (fd_neris_id) REFERENCES analytics.fire_departments(fd_neris_id);


--
-- Name: agency_notifications agency_notifications_incident_id_fkey; Type: FK CONSTRAINT; Schema: gis; Owner: tauseef
--

ALTER TABLE ONLY gis.agency_notifications
    ADD CONSTRAINT agency_notifications_incident_id_fkey FOREIGN KEY (incident_id) REFERENCES gis.incidents(incident_id);


--
-- Name: apparatus apparatus_station_id_fkey; Type: FK CONSTRAINT; Schema: gis; Owner: tauseef
--

ALTER TABLE ONLY gis.apparatus
    ADD CONSTRAINT apparatus_station_id_fkey FOREIGN KEY (station_id) REFERENCES gis.fire_stations(station_id);


--
-- Name: call_notes call_notes_firefighter_id_fkey; Type: FK CONSTRAINT; Schema: gis; Owner: tauseef
--

ALTER TABLE ONLY gis.call_notes
    ADD CONSTRAINT call_notes_firefighter_id_fkey FOREIGN KEY (firefighter_id) REFERENCES gis.firefighters(firefighter_id);


--
-- Name: call_notes call_notes_property_id_fkey; Type: FK CONSTRAINT; Schema: gis; Owner: tauseef
--

ALTER TABLE ONLY gis.call_notes
    ADD CONSTRAINT call_notes_property_id_fkey FOREIGN KEY (property_id) REFERENCES gis.properties(property_id) ON DELETE CASCADE;


--
-- Name: conversation_log conversation_log_firefighter_id_fkey; Type: FK CONSTRAINT; Schema: gis; Owner: tauseef
--

ALTER TABLE ONLY gis.conversation_log
    ADD CONSTRAINT conversation_log_firefighter_id_fkey FOREIGN KEY (firefighter_id) REFERENCES gis.firefighters(firefighter_id);


--
-- Name: conversation_log conversation_log_property_id_fkey; Type: FK CONSTRAINT; Schema: gis; Owner: tauseef
--

ALTER TABLE ONLY gis.conversation_log
    ADD CONSTRAINT conversation_log_property_id_fkey FOREIGN KEY (property_id) REFERENCES gis.properties(property_id);


--
-- Name: dispatch_log dispatch_log_incident_id_fkey; Type: FK CONSTRAINT; Schema: gis; Owner: tauseef
--

ALTER TABLE ONLY gis.dispatch_log
    ADD CONSTRAINT dispatch_log_incident_id_fkey FOREIGN KEY (incident_id) REFERENCES gis.incidents(incident_id);


--
-- Name: firefighters firefighters_station_id_fkey; Type: FK CONSTRAINT; Schema: gis; Owner: tauseef
--

ALTER TABLE ONLY gis.firefighters
    ADD CONSTRAINT firefighters_station_id_fkey FOREIGN KEY (station_id) REFERENCES gis.fire_stations(station_id);


--
-- Name: alarms fk_alarms_property; Type: FK CONSTRAINT; Schema: gis; Owner: tauseef
--

ALTER TABLE ONLY gis.alarms
    ADD CONSTRAINT fk_alarms_property FOREIGN KEY (property_id) REFERENCES gis.properties(property_id);


--
-- Name: property_risks fk_risks_property; Type: FK CONSTRAINT; Schema: gis; Owner: tauseef
--

ALTER TABLE ONLY gis.property_risks
    ADD CONSTRAINT fk_risks_property FOREIGN KEY (property_id) REFERENCES gis.properties(property_id);


--
-- Name: incident_reports incident_reports_generated_by_fkey; Type: FK CONSTRAINT; Schema: gis; Owner: tauseef
--

ALTER TABLE ONLY gis.incident_reports
    ADD CONSTRAINT incident_reports_generated_by_fkey FOREIGN KEY (generated_by) REFERENCES gis.firefighters(firefighter_id);


--
-- Name: incident_reports incident_reports_incident_id_fkey; Type: FK CONSTRAINT; Schema: gis; Owner: tauseef
--

ALTER TABLE ONLY gis.incident_reports
    ADD CONSTRAINT incident_reports_incident_id_fkey FOREIGN KEY (incident_id) REFERENCES gis.incidents(incident_id);


--
-- Name: incidents incidents_airs_code_fkey; Type: FK CONSTRAINT; Schema: gis; Owner: tauseef
--

ALTER TABLE ONLY gis.incidents
    ADD CONSTRAINT incidents_airs_code_fkey FOREIGN KEY (airs_code) REFERENCES gis.airs_codes(airs_code);


--
-- Name: incidents incidents_airs_confirmed_by_fkey; Type: FK CONSTRAINT; Schema: gis; Owner: tauseef
--

ALTER TABLE ONLY gis.incidents
    ADD CONSTRAINT incidents_airs_confirmed_by_fkey FOREIGN KEY (airs_confirmed_by) REFERENCES gis.firefighters(firefighter_id);


--
-- Name: incidents incidents_firefighter_id_fkey; Type: FK CONSTRAINT; Schema: gis; Owner: tauseef
--

ALTER TABLE ONLY gis.incidents
    ADD CONSTRAINT incidents_firefighter_id_fkey FOREIGN KEY (firefighter_id) REFERENCES gis.firefighters(firefighter_id);


--
-- Name: post_incident_surveys post_incident_surveys_firefighter_id_fkey; Type: FK CONSTRAINT; Schema: gis; Owner: tauseef
--

ALTER TABLE ONLY gis.post_incident_surveys
    ADD CONSTRAINT post_incident_surveys_firefighter_id_fkey FOREIGN KEY (firefighter_id) REFERENCES gis.firefighters(firefighter_id);


--
-- Name: SCHEMA ai; Type: ACL; Schema: -; Owner: tauseef
--

GRANT USAGE ON SCHEMA ai TO powerbi_ro;


--
-- Name: SCHEMA gis; Type: ACL; Schema: -; Owner: tauseef
--

GRANT USAGE ON SCHEMA gis TO powerbi_ro;


--
-- Name: TABLE incident_assessment; Type: ACL; Schema: ai; Owner: tauseef
--

GRANT SELECT ON TABLE ai.incident_assessment TO powerbi_ro;


--
-- Name: SEQUENCE incident_assessment_assessment_id_seq; Type: ACL; Schema: ai; Owner: tauseef
--

GRANT SELECT ON SEQUENCE ai.incident_assessment_assessment_id_seq TO powerbi_ro;


--
-- Name: TABLE alarms; Type: ACL; Schema: gis; Owner: tauseef
--

GRANT SELECT ON TABLE gis.alarms TO powerbi_ro;


--
-- Name: SEQUENCE alarms_alarm_id_seq; Type: ACL; Schema: gis; Owner: tauseef
--

GRANT SELECT ON SEQUENCE gis.alarms_alarm_id_seq TO powerbi_ro;


--
-- Name: TABLE assets; Type: ACL; Schema: gis; Owner: tauseef
--

GRANT SELECT ON TABLE gis.assets TO powerbi_ro;


--
-- Name: SEQUENCE assets_asset_id_seq; Type: ACL; Schema: gis; Owner: tauseef
--

GRANT SELECT ON SEQUENCE gis.assets_asset_id_seq TO powerbi_ro;


--
-- Name: TABLE call_notes; Type: ACL; Schema: gis; Owner: tauseef
--

GRANT SELECT ON TABLE gis.call_notes TO powerbi_ro;


--
-- Name: SEQUENCE call_notes_note_id_seq; Type: ACL; Schema: gis; Owner: tauseef
--

GRANT SELECT ON SEQUENCE gis.call_notes_note_id_seq TO powerbi_ro;


--
-- Name: TABLE conversation_log; Type: ACL; Schema: gis; Owner: tauseef
--

GRANT SELECT ON TABLE gis.conversation_log TO powerbi_ro;


--
-- Name: SEQUENCE conversation_log_log_id_seq; Type: ACL; Schema: gis; Owner: tauseef
--

GRANT SELECT ON SEQUENCE gis.conversation_log_log_id_seq TO powerbi_ro;


--
-- Name: TABLE fire_stations; Type: ACL; Schema: gis; Owner: tauseef
--

GRANT SELECT ON TABLE gis.fire_stations TO powerbi_ro;


--
-- Name: SEQUENCE fire_stations_station_id_seq; Type: ACL; Schema: gis; Owner: tauseef
--

GRANT SELECT ON SEQUENCE gis.fire_stations_station_id_seq TO powerbi_ro;


--
-- Name: TABLE firefighters; Type: ACL; Schema: gis; Owner: tauseef
--

GRANT SELECT ON TABLE gis.firefighters TO powerbi_ro;


--
-- Name: SEQUENCE firefighters_firefighter_id_seq; Type: ACL; Schema: gis; Owner: tauseef
--

GRANT SELECT ON SEQUENCE gis.firefighters_firefighter_id_seq TO powerbi_ro;


--
-- Name: TABLE hydrants; Type: ACL; Schema: gis; Owner: tauseef
--

GRANT SELECT ON TABLE gis.hydrants TO powerbi_ro;


--
-- Name: SEQUENCE hydrants_hydrant_id_seq; Type: ACL; Schema: gis; Owner: tauseef
--

GRANT SELECT ON SEQUENCE gis.hydrants_hydrant_id_seq TO powerbi_ro;


--
-- Name: TABLE incidents; Type: ACL; Schema: gis; Owner: tauseef
--

GRANT SELECT ON TABLE gis.incidents TO powerbi_ro;


--
-- Name: SEQUENCE incidents_incident_id_seq; Type: ACL; Schema: gis; Owner: tauseef
--

GRANT SELECT ON SEQUENCE gis.incidents_incident_id_seq TO powerbi_ro;


--
-- Name: TABLE properties; Type: ACL; Schema: gis; Owner: tauseef
--

GRANT SELECT ON TABLE gis.properties TO powerbi_ro;


--
-- Name: SEQUENCE properties_property_id_seq; Type: ACL; Schema: gis; Owner: tauseef
--

GRANT SELECT ON SEQUENCE gis.properties_property_id_seq TO powerbi_ro;


--
-- Name: TABLE property_risks; Type: ACL; Schema: gis; Owner: tauseef
--

GRANT SELECT ON TABLE gis.property_risks TO powerbi_ro;


--
-- Name: SEQUENCE property_risks_risk_id_seq; Type: ACL; Schema: gis; Owner: tauseef
--

GRANT SELECT ON SEQUENCE gis.property_risks_risk_id_seq TO powerbi_ro;


--
-- Name: TABLE v_assets; Type: ACL; Schema: gis; Owner: tauseef
--

GRANT SELECT ON TABLE gis.v_assets TO powerbi_ro;


--
-- Name: TABLE v_call_notes; Type: ACL; Schema: gis; Owner: tauseef
--

GRANT SELECT ON TABLE gis.v_call_notes TO powerbi_ro;


--
-- Name: TABLE v_conversation_log; Type: ACL; Schema: gis; Owner: tauseef
--

GRANT SELECT ON TABLE gis.v_conversation_log TO powerbi_ro;


--
-- Name: TABLE v_fire_stations; Type: ACL; Schema: gis; Owner: tauseef
--

GRANT SELECT ON TABLE gis.v_fire_stations TO powerbi_ro;


--
-- Name: TABLE v_hydrants; Type: ACL; Schema: gis; Owner: tauseef
--

GRANT SELECT ON TABLE gis.v_hydrants TO powerbi_ro;


--
-- Name: TABLE v_property_risks; Type: ACL; Schema: gis; Owner: tauseef
--

GRANT SELECT ON TABLE gis.v_property_risks TO powerbi_ro;


--
-- Name: TABLE water_sources; Type: ACL; Schema: gis; Owner: tauseef
--

GRANT SELECT ON TABLE gis.water_sources TO powerbi_ro;


--
-- Name: TABLE v_water_sources; Type: ACL; Schema: gis; Owner: tauseef
--

GRANT SELECT ON TABLE gis.v_water_sources TO powerbi_ro;


--
-- Name: SEQUENCE water_sources_water_source_id_seq; Type: ACL; Schema: gis; Owner: tauseef
--

GRANT SELECT ON SEQUENCE gis.water_sources_water_source_id_seq TO powerbi_ro;


--
-- PostgreSQL database dump complete
--

\unrestrict 4U6c7xiM2dTu0DftdKtCfTFXAEMUddRVHhhbAKFurqeSFViWoklA3rfe4SpoLaw

