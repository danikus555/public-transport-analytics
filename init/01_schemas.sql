-- =============================================================
-- public-transport-analytics
-- Database initialization — runs automatically on first startup
-- =============================================================

-- Schemas
CREATE SCHEMA IF NOT EXISTS reference;
CREATE SCHEMA IF NOT EXISTS bronze;
CREATE SCHEMA IF NOT EXISTS silver;
CREATE SCHEMA IF NOT EXISTS gold;

-- =============================================================
-- REFERENCE — static lookup tables
-- Loaded by scripts/load_reference.py
-- Editable via Streamlit admin UI
-- =============================================================

CREATE TABLE IF NOT EXISTS reference.operators (
    id              SERIAL PRIMARY KEY,
    code            TEXT UNIQUE NOT NULL,   -- 'TLT', 'Elron', 'SEBE'
    name            TEXT NOT NULL,
    city            TEXT,                   -- 'Tallinn', 'Tartu', 'Regional'
    website         TEXT,
    active          BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS reference.line_types (
    id              SERIAL PRIMARY KEY,
    code            INT UNIQUE NOT NULL,    -- 1, 2, 3
    name            TEXT NOT NULL,          -- 'tram', 'bus', 'trolleybus'
    name_et         TEXT,                   -- 'tramm', 'buss', 'troll'
    fuel_category   TEXT                    -- 'electric', 'diesel', 'gas', 'mixed'
);

CREATE TABLE IF NOT EXISTS reference.fuel_types (
    id              SERIAL PRIMARY KEY,
    code            TEXT UNIQUE NOT NULL,   -- 'diesel', '95', '98', 'electric', 'gas'
    name            TEXT NOT NULL,
    unit            TEXT NOT NULL,          -- 'litre', 'kwh', 'kg'
    active          BOOLEAN DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS reference.cities (
    id              SERIAL PRIMARY KEY,
    code            TEXT UNIQUE NOT NULL,   -- 'tallinn', 'tartu', 'regional'
    name            TEXT NOT NULL,
    lat_min         NUMERIC,
    lat_max         NUMERIC,
    lon_min         NUMERIC,
    lon_max         NUMERIC
);

CREATE TABLE IF NOT EXISTS reference.vehicle_models (
    id              SERIAL PRIMARY KEY,
    operator_code   TEXT REFERENCES reference.operators(code),
    line_type_code  INT REFERENCES reference.line_types(code),
    model           TEXT NOT NULL,
    fuel_type_code  TEXT REFERENCES reference.fuel_types(code),
    consumption     NUMERIC,                -- litres or kWh per 100km
    notes           TEXT,
    active          BOOLEAN DEFAULT TRUE,
    valid_from      DATE DEFAULT CURRENT_DATE,
    updated_at      TIMESTAMP DEFAULT NOW()
);

-- =============================================================
-- BRONZE — raw data exactly as received
-- =============================================================

CREATE TABLE IF NOT EXISTS bronze.vehicle_positions (
    id              SERIAL PRIMARY KEY,
    vehicle_id      INT,
    line_type       INT,
    line_number     TEXT,
    destination     TEXT,
    lat             NUMERIC,
    lon             NUMERIC,
    bearing         INT,
    low_floor       BOOLEAN,
    operator        TEXT DEFAULT 'TLT',
    ingested_at     TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS bronze.fuel_prices (
    id              SERIAL PRIMARY KEY,
    fuel_type       TEXT,
    price_eur       NUMERIC,
    source_date     DATE,
    scraped_at      TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS bronze.client_discounts (
    id              SERIAL PRIMARY KEY,
    company         TEXT,
    fuel_type       TEXT,
    discount        NUMERIC,
    updated_by      TEXT,
    updated_at      TIMESTAMP DEFAULT NOW()
);

-- =============================================================
-- SILVER — cleaned and typed (dbt)
-- =============================================================

CREATE TABLE IF NOT EXISTS silver.vehicle_positions (
    vehicle_id      INT,
    line_type       INT,
    line_type_label TEXT,
    line_number     TEXT,
    destination     TEXT,
    operator        TEXT,
    lat             NUMERIC,
    lon             NUMERIC,
    bearing         INT,
    low_floor       BOOLEAN,
    snapshot_date   DATE,
    ingested_at     TIMESTAMP
);

CREATE TABLE IF NOT EXISTS silver.fuel_prices (
    fuel_type       TEXT,
    price_eur       NUMERIC,
    source_date     DATE
);

-- =============================================================
-- GOLD — analytics ready (dbt)
-- =============================================================

CREATE TABLE IF NOT EXISTS gold.latest_positions (
    vehicle_id      INT,
    line_type_label TEXT,
    line_number     TEXT,
    destination     TEXT,
    operator        TEXT,
    lat             NUMERIC,
    lon             NUMERIC,
    bearing         INT,
    ingested_at     TIMESTAMP
);

CREATE TABLE IF NOT EXISTS gold.route_activity (
    line_number     TEXT,
    line_type_label TEXT,
    operator        TEXT,
    snapshot_date   DATE,
    hour            INT,
    vehicle_count   INT
);

CREATE TABLE IF NOT EXISTS gold.fuel_daily (
    fuel_type       TEXT,
    price_eur       NUMERIC,
    price_yesterday NUMERIC,
    source_date     DATE
);

CREATE TABLE IF NOT EXISTS gold.fuel_with_discount (
    company         TEXT,
    fuel_type       TEXT,
    price_eur       NUMERIC,
    discount        NUMERIC,
    discounted_price NUMERIC,
    source_date     DATE
);

-- =============================================================
-- INDEXES
-- =============================================================

CREATE INDEX IF NOT EXISTS idx_vp_ingested_at
    ON bronze.vehicle_positions(ingested_at);
CREATE INDEX IF NOT EXISTS idx_vp_line_number
    ON bronze.vehicle_positions(line_number);
CREATE INDEX IF NOT EXISTS idx_vp_vehicle_id
    ON bronze.vehicle_positions(vehicle_id);
CREATE INDEX IF NOT EXISTS idx_fp_source_date
    ON bronze.fuel_prices(source_date);
CREATE INDEX IF NOT EXISTS idx_svp_snapshot_date
    ON silver.vehicle_positions(snapshot_date);
CREATE INDEX IF NOT EXISTS idx_svp_operator
    ON silver.vehicle_positions(operator);

-- =============================================================
-- REFERENCE SEED DATA
-- =============================================================

-- Operators
INSERT INTO reference.operators (code, name, city, website) VALUES
('TLT',   'Tallinna Linnatransport', 'Tallinn',  'https://tlt.ee'),
('Elron', 'Elron',                   'Regional', 'https://elron.ee'),
('SEBE',  'SEBE',                    'Regional', 'https://sebe.ee')
ON CONFLICT (code) DO NOTHING;

-- Line types
INSERT INTO reference.line_types (code, name, name_et, fuel_category) VALUES
(1, 'tram',       'tramm', 'electric'),
(2, 'bus',        'buss',  'mixed'),
(3, 'trolleybus', 'troll', 'electric')
ON CONFLICT (code) DO NOTHING;

-- Fuel types
INSERT INTO reference.fuel_types (code, name, unit) VALUES
('diesel',   'Diislikütus', 'litre'),
('95',       'Bensiin 95',  'litre'),
('98',       'Bensiin 98',  'litre'),
('electric', 'Elekter',     'kwh'),
('gas',      'CNG gaas',    'kg')
ON CONFLICT (code) DO NOTHING;

-- Cities with bounding boxes
INSERT INTO reference.cities (code, name, lat_min, lat_max, lon_min, lon_max) VALUES
('tallinn',  'Tallinn',    59.35, 59.55, 24.55, 24.95),
('tartu',    'Tartu',      58.30, 58.45, 26.60, 26.85),
('regional', 'Regionaalne', 57.50, 59.70, 21.50, 28.20)
ON CONFLICT (code) DO NOTHING;

-- Vehicle models — real TLT fleet from tlt.ee

-- TLT trams (electric)
INSERT INTO reference.vehicle_models
    (operator_code, line_type_code, model, fuel_type_code, consumption, notes) VALUES
('TLT', 1, 'PESA Twist 147N',     'electric',  8.5, '23 tükki, alates 2024'),
('TLT', 1, 'CAF Urbos AXL',       'electric',  8.0, 'alates 2015'),
('TLT', 1, 'Tatra KT4',           'electric',  9.0, 'alles 5 tükki'),
('TLT', 1, 'Tatra KT6TM',         'electric',  8.8, 'moderniseeritud KT4'),

-- TLT trolleybuses (electric, almost replaced)
('TLT', 3, 'Solaris Trollino III 18 AC', 'electric', 3.0, 'alles 1 tükk'),
('TLT', 3, 'Solaris Trollino III 12 AC', 'electric', 2.5, 'alles 1 tükk'),
('TLT', 3, 'Škoda 14Tr',                'electric', 2.8, 'alles 1 tükk'),

-- TLT buses — electric
('TLT', 2, 'Solaris Urbino IV 12 Electric', 'electric', 120.0, '15 tükki, alates 2024'),

-- TLT buses — CNG gas
('TLT', 2, 'Solaris Urbino IV 12 CNG', 'gas', 32.0, 'alates 2020'),
('TLT', 2, 'Solaris Urbino IV 18 CNG', 'gas', 42.0, 'liigendbuss, alates 2020'),

-- TLT buses — diesel
('TLT', 2, 'MAN A78 Lion City LE EL293',  'diesel', 32.0, 'alates 2013'),
('TLT', 2, 'MAN A40 Lion City GL NG323',  'diesel', 42.0, 'liigendbuss, alates 2013'),
('TLT', 2, 'MAN A21 Lion City NL283',     'diesel', 30.0, '5 tükki'),

-- TLT buses — hybrid
('TLT', 2, 'Volvo 7900 Hybrid', 'diesel', 24.0, 'hübriid -30% kütust, alates 2015'),

-- TLT minibuses
('TLT', 2, 'Mercedes-Benz Sprinter', 'diesel', 15.0, 'väikebussid, sotsiaaltransport'),

-- Elron trains
('Elron', 2, 'Stadler FLIRT',     'diesel',   3.5, 'diiselrong'),
('Elron', 2, 'Stadler FLIRT EMU', 'electric', 8.0, 'elektrirongid')

ON CONFLICT DO NOTHING;