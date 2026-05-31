-- =============================================================
-- public-transport-analytics
-- 02_schemas.sql — GTFS + Elron tables
-- Runs automatically after 01_schemas.sql on first startup
-- =============================================================

-- =============================================================
-- REFERENCE — GTFS tables
-- Loaded by scripts/load_gtfs.py
-- TLT:   weekly    (GTFS_TLT_CRON_DAY)
-- Elron: monthly   (GTFS_ELRON_CRON_DAY)
-- Sources:
--   TLT:   https://eu-gtfs.remix.com/tallinn.zip
--          https://mobilitydatabase.org/feeds/gtfs/mdb-3047
--   Elron: https://eu-gtfs.remix.com/elron.zip
--          https://mobilitydatabase.org/feeds/gtfs/mdb-3153
-- =============================================================

CREATE TABLE IF NOT EXISTS reference.gtfs_feed_info (
    id              SERIAL PRIMARY KEY,
    operator        TEXT NOT NULL,          -- 'TLT', 'Elron'
    feed_version    TEXT,                   -- from feed_info.txt
    feed_start_date DATE,
    feed_end_date   DATE,
    loaded_at       TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS reference.gtfs_agency (
    agency_id       TEXT PRIMARY KEY,
    agency_name     TEXT NOT NULL,
    agency_url      TEXT,
    agency_timezone TEXT,
    agency_phone    TEXT,
    agency_email    TEXT,
    operator        TEXT                    -- 'TLT', 'Elron'
);

-- Key table — identifies transport type per route
-- route_type: 0=tram, 2=train, 3=bus, 11=trolleybus
CREATE TABLE IF NOT EXISTS reference.gtfs_routes (
    route_id         TEXT PRIMARY KEY,
    agency_id        TEXT,
    route_short_name TEXT,                  -- '1', '5', '36', 'R14'
    route_long_name  TEXT,                  -- 'Kopli - Kadriorg'
    route_type       INT,
    route_color      TEXT,
    route_text_color TEXT,
    operator         TEXT,
    updated_at       TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS reference.gtfs_stops (
    stop_id        TEXT PRIMARY KEY,
    stop_name      TEXT NOT NULL,
    stop_lat       NUMERIC(10,7),
    stop_lon       NUMERIC(10,7),
    location_type  INT DEFAULT 0,           -- 0=stop, 1=station
    parent_station TEXT,
    operator       TEXT,
    updated_at     TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS reference.gtfs_trips (
    trip_id       TEXT PRIMARY KEY,
    route_id      TEXT REFERENCES reference.gtfs_routes(route_id),
    service_id    TEXT,
    trip_headsign TEXT,                     -- destination name
    direction_id  INT,                      -- 0=outbound, 1=inbound
    operator      TEXT,
    updated_at    TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS reference.gtfs_stop_times (
    id             SERIAL PRIMARY KEY,
    trip_id        TEXT REFERENCES reference.gtfs_trips(trip_id),
    arrival_time   TEXT,                    -- HH:MM:SS (can exceed 24:00)
    departure_time TEXT,
    stop_id        TEXT REFERENCES reference.gtfs_stops(stop_id),
    stop_sequence  INT,
    updated_at     TIMESTAMP DEFAULT NOW()
);

-- =============================================================
-- REFERENCE — Elron line fuel mapping
-- Maps Elron route names to fuel type
-- Sources:
--   https://elron.ee/elronist/elroni-rongid
--   https://et.wikipedia.org/wiki/Škoda_21Ev
-- =============================================================

CREATE TABLE IF NOT EXISTS reference.elron_line_types (
    liin      TEXT PRIMARY KEY,             -- matches map_data.json "liin" field
    fuel_type TEXT NOT NULL,               -- 'diesel', 'electric'
    model     TEXT,
    notes     TEXT
);

INSERT INTO reference.elron_line_types (liin, fuel_type, model, notes) VALUES
-- Electric — Elektriraudtee 3kV (Stadler FLIRT EMU, alates 2013)
('Tallinn - Keila',       'electric', 'Stadler FLIRT EMU', 'Elektriraudtee 3kV võrk'),
('Keila - Tallinn',       'electric', 'Stadler FLIRT EMU', 'Elektriraudtee 3kV võrk'),
('Tallinn - Pääsküla',    'electric', 'Stadler FLIRT EMU', 'Elektriraudtee 3kV võrk'),
('Pääsküla - Tallinn',    'electric', 'Stadler FLIRT EMU', 'Elektriraudtee 3kV võrk'),
-- Electric — Škoda 21Ev (alates 2025, 3kV + 25kV kahesüsteemne)
('Tallinn - Kloogaranna', 'electric', 'Škoda 21Ev EMU', 'Škoda 21Ev, alates 2025'),
('Kloogaranna - Tallinn', 'electric', 'Škoda 21Ev EMU', 'Škoda 21Ev, alates 2025'),
('Tallinn - Tapa',        'electric', 'Škoda 21Ev EMU', 'Škoda 21Ev, alates jan 2026'),
('Tapa - Tallinn',        'electric', 'Škoda 21Ev EMU', 'Škoda 21Ev, alates jan 2026'),
-- Diesel — Stadler FLIRT DMU (alates 2013)
('Tallinn - Tartu',       'diesel', 'Stadler FLIRT DMU', 'Elektrifitseerimine käimas'),
('Tartu - Tallinn',       'diesel', 'Stadler FLIRT DMU', 'Elektrifitseerimine käimas'),
('Tallinn - Narva',       'diesel', 'Stadler FLIRT DMU', 'Elektrifitseerimine käimas'),
('Narva - Tallinn',       'diesel', 'Stadler FLIRT DMU', 'Elektrifitseerimine käimas'),
('Tallinn - Viljandi',    'diesel', 'Stadler FLIRT DMU', NULL),
('Viljandi - Tallinn',    'diesel', 'Stadler FLIRT DMU', NULL),
('Tallinn - Rapla',       'diesel', 'Stadler FLIRT DMU', NULL),
('Rapla - Tallinn',       'diesel', 'Stadler FLIRT DMU', NULL),
('Tallinn - Paldiski',    'diesel', 'Stadler FLIRT DMU', NULL),
('Paldiski - Tallinn',    'diesel', 'Stadler FLIRT DMU', NULL),
('Tallinn - Turba',       'diesel', 'Stadler FLIRT DMU', NULL),
('Turba - Tallinn',       'diesel', 'Stadler FLIRT DMU', NULL),
('Tallinn - Aegviidu',    'diesel', 'Stadler FLIRT DMU', NULL),
('Aegviidu - Tallinn',    'diesel', 'Stadler FLIRT DMU', NULL),
('Tallinn - Rakvere',     'diesel', 'Stadler FLIRT DMU', NULL),
('Rakvere - Tallinn',     'diesel', 'Stadler FLIRT DMU', NULL),
('Tallinn - Riia',        'diesel', 'Stadler FLIRT DMU', 'Rahvusvaheline liin'),
('Riia - Tallinn',        'diesel', 'Stadler FLIRT DMU', 'Rahvusvaheline liin'),
('Tartu - Valga',         'diesel', 'Stadler FLIRT DMU', NULL),
('Valga - Tartu',         'diesel', 'Stadler FLIRT DMU', NULL),
('Tartu - Koidula',       'diesel', 'Stadler FLIRT DMU', NULL),
('Tartu - Piusa',         'diesel', 'Stadler FLIRT DMU', NULL),
('Jõgeva - Tartu',        'diesel', 'Stadler FLIRT DMU', NULL)
ON CONFLICT (liin) DO NOTHING;

-- =============================================================
-- BRONZE — Elron realtime positions
-- Loaded by scripts/ingest_elron.py (every 30s)
-- Source: https://elron.ee/map_data.json
-- =============================================================

CREATE TABLE IF NOT EXISTS bronze.elron_positions (
    id              SERIAL PRIMARY KEY,
    reis            TEXT,                   -- trip number
    liin            TEXT,                   -- route e.g. "Tallinn - Tartu"
    reisi_algus     TEXT,                   -- departure time HH:MM
    reisi_lopp      TEXT,                   -- arrival time HH:MM
    kiirus          INT,                    -- speed km/h
    lat             NUMERIC(10,7),
    lon             NUMERIC(10,7),
    suund           INT,                    -- bearing degrees
    erinevus        INT,                    -- delay minutes (negative=early)
    reisi_staatus   TEXT,                   -- 'plaaniline', 'hilineb peatuses'
    viimane_peatus  TEXT,                   -- last known stop
    asukoha_uuendus TIMESTAMP,
    ingested_at     TIMESTAMP DEFAULT NOW()
);

-- =============================================================
-- SILVER — enriched with GTFS transport type (dbt)
-- =============================================================

DROP TABLE IF EXISTS silver.vehicle_positions;
CREATE TABLE IF NOT EXISTS silver.vehicle_positions (
    vehicle_id     INT,
    line_type      INT,
    line_number    TEXT,
    route_id       TEXT,                    -- from GTFS
    transport_type TEXT,                    -- 'tram', 'bus', 'trolleybus'
    fuel_type      TEXT,                    -- 'electric', 'diesel', 'gas'
    destination    TEXT,
    operator       TEXT,
    lat            NUMERIC,
    lon            NUMERIC,
    bearing        INT,
    low_floor      BOOLEAN,
    snapshot_date  DATE,
    ingested_at    TIMESTAMP
);

CREATE TABLE IF NOT EXISTS silver.elron_positions (
    reis           TEXT,
    liin           TEXT,
    transport_type TEXT DEFAULT 'train',
    fuel_type      TEXT,
    model          TEXT,
    kiirus         INT,
    lat            NUMERIC(10,7),
    lon            NUMERIC(10,7),
    suund          INT,
    delay_min      INT,
    reisi_staatus  TEXT,
    viimane_peatus TEXT,
    ingested_at    TIMESTAMP
);

-- =============================================================
-- GOLD — analytics (dbt)
-- =============================================================

CREATE TABLE IF NOT EXISTS gold.vehicle_delays (
    vehicle_id     INT,
    line_number    TEXT,
    transport_type TEXT,
    stop_name      TEXT,
    scheduled_time TEXT,
    actual_time    TIMESTAMP,
    delay_min      INT,
    snapshot_date  DATE
);

CREATE TABLE IF NOT EXISTS gold.elron_delays (
    reis          TEXT,
    liin          TEXT,
    fuel_type     TEXT,
    delay_min     INT,
    reisi_staatus TEXT,
    snapshot_date DATE,
    hour          INT
);

CREATE TABLE IF NOT EXISTS gold.transport_summary (
    transport_type  TEXT,
    fuel_type       TEXT,
    operator        TEXT,
    active_vehicles INT,
    avg_speed       NUMERIC,
    snapshot_hour   TIMESTAMP
);

-- Fleet summary — number of vehicles per model
CREATE TABLE IF NOT EXISTS gold.fleet_summary (
    operator       TEXT,
    transport_type TEXT,
    fuel_type      TEXT,
    model          TEXT,
    vehicle_count  INT,
    consumption    NUMERIC,
    consumption_unit TEXT,
    notes          TEXT
);

-- =============================================================
-- INDEXES
-- =============================================================

CREATE INDEX IF NOT EXISTS idx_gtfs_routes_short_name
    ON reference.gtfs_routes(route_short_name);
CREATE INDEX IF NOT EXISTS idx_gtfs_routes_type
    ON reference.gtfs_routes(route_type);
CREATE INDEX IF NOT EXISTS idx_gtfs_routes_operator
    ON reference.gtfs_routes(operator);
CREATE INDEX IF NOT EXISTS idx_gtfs_stops_name
    ON reference.gtfs_stops(stop_name);
CREATE INDEX IF NOT EXISTS idx_gtfs_trips_route
    ON reference.gtfs_trips(route_id);
CREATE INDEX IF NOT EXISTS idx_gtfs_st_trip
    ON reference.gtfs_stop_times(trip_id);
CREATE INDEX IF NOT EXISTS idx_gtfs_st_stop
    ON reference.gtfs_stop_times(stop_id);
CREATE INDEX IF NOT EXISTS idx_elron_ingested
    ON bronze.elron_positions(ingested_at);
CREATE INDEX IF NOT EXISTS idx_elron_liin
    ON bronze.elron_positions(liin);