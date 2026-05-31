-- =============================================================
-- public-transport-analytics
-- 01_schemas.sql
-- Database initialization — runs automatically on first startup
-- =============================================================

-- Schemas
CREATE SCHEMA IF NOT EXISTS reference;
CREATE SCHEMA IF NOT EXISTS bronze;
CREATE SCHEMA IF NOT EXISTS silver;
CREATE SCHEMA IF NOT EXISTS gold;

-- =============================================================
-- REFERENCE — static lookup tables
-- Loaded by scripts/load_reference.py (weekly)
-- =============================================================

CREATE TABLE IF NOT EXISTS reference.operators (
    id          SERIAL PRIMARY KEY,
    code        TEXT UNIQUE NOT NULL,
    name        TEXT NOT NULL,
    city        TEXT,
    website     TEXT,
    active      BOOLEAN DEFAULT TRUE,
    created_at  TIMESTAMP DEFAULT NOW(),
    updated_at  TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS reference.line_types (
    id            SERIAL PRIMARY KEY,
    code          INT UNIQUE NOT NULL,
    name          TEXT NOT NULL,
    name_et       TEXT,
    fuel_category TEXT
);

CREATE TABLE IF NOT EXISTS reference.fuel_types (
    id     SERIAL PRIMARY KEY,
    code   TEXT UNIQUE NOT NULL,
    name   TEXT NOT NULL,
    unit   TEXT NOT NULL,
    active BOOLEAN DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS reference.cities (
    id      SERIAL PRIMARY KEY,
    code    TEXT UNIQUE NOT NULL,
    name    TEXT NOT NULL,
    lat_min NUMERIC,
    lat_max NUMERIC,
    lon_min NUMERIC,
    lon_max NUMERIC
);

CREATE TABLE IF NOT EXISTS reference.vehicle_models (
    id               SERIAL PRIMARY KEY,
    operator_code    TEXT REFERENCES reference.operators(code),
    line_type_code   INT  REFERENCES reference.line_types(code),
    model            TEXT NOT NULL,
    fuel_type_code   TEXT REFERENCES reference.fuel_types(code),
    consumption      NUMERIC,
    consumption_unit TEXT DEFAULT 'l/100km',
    vehicle_amount   INT,
    active           BOOLEAN DEFAULT TRUE,
    valid_from       DATE DEFAULT CURRENT_DATE,
    updated_at       TIMESTAMP DEFAULT NOW(),
    CONSTRAINT uq_vehicle_model UNIQUE (operator_code, line_type_code, model)
);

-- =============================================================
-- BRONZE — raw data exactly as received
-- =============================================================

CREATE TABLE IF NOT EXISTS bronze.vehicle_positions (
    id          SERIAL PRIMARY KEY,
    vehicle_id  INT,
    line_type   INT,
    line_number TEXT,
    destination TEXT,
    lat         NUMERIC,
    lon         NUMERIC,
    bearing     INT,
    low_floor   BOOLEAN,
    operator    TEXT DEFAULT 'TLT',
    ingested_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS bronze.fuel_prices (
    id          SERIAL PRIMARY KEY,
    fuel_type   TEXT,
    price_eur   NUMERIC,
    source_date DATE,
    source      TEXT,
    scraped_at  TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS bronze.client_discounts (
    id         SERIAL PRIMARY KEY,
    company    TEXT,
    fuel_type  TEXT,
    discount   NUMERIC,
    updated_by TEXT,
    updated_at TIMESTAMP DEFAULT NOW()
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
    fuel_type   TEXT,
    price_eur   NUMERIC,
    source_date DATE
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
    change_pct      NUMERIC,
    source_date     DATE
);

CREATE TABLE IF NOT EXISTS gold.fuel_with_discount (
    company          TEXT,
    fuel_type        TEXT,
    price_eur        NUMERIC,
    discount         NUMERIC,
    discounted_price NUMERIC,
    source_date      DATE
);

-- =============================================================
-- INDEXES
-- =============================================================

CREATE INDEX IF NOT EXISTS idx_vp_ingested_at ON bronze.vehicle_positions(ingested_at);
CREATE INDEX IF NOT EXISTS idx_vp_line_number  ON bronze.vehicle_positions(line_number);
CREATE INDEX IF NOT EXISTS idx_vp_vehicle_id   ON bronze.vehicle_positions(vehicle_id);
CREATE INDEX IF NOT EXISTS idx_fp_source_date  ON bronze.fuel_prices(source_date);
CREATE INDEX IF NOT EXISTS idx_svp_snapshot    ON silver.vehicle_positions(snapshot_date);
CREATE INDEX IF NOT EXISTS idx_svp_operator    ON silver.vehicle_positions(operator);

-- =============================================================
-- REFERENCE SEED DATA
-- =============================================================

INSERT INTO reference.operators (code, name, city, website) VALUES
('TLT',   'Tallinna Linnatransport', 'Tallinn',  'https://tlt.ee'),
('Elron', 'Elron',                   'Regional', 'https://elron.ee'),
('SEBE',  'SEBE',                    'Regional', 'https://sebe.ee')
ON CONFLICT (code) DO NOTHING;

INSERT INTO reference.line_types (code, name, name_et, fuel_category) VALUES
(1, 'tram',       'tramm', 'electric'),
(2, 'bus',        'buss',  'mixed'),
(3, 'trolleybus', 'troll', 'electric')
ON CONFLICT (code) DO NOTHING;

-- fuel_types: 95/98/diesel for price tracking, electric/gas/hybrid_diesel for vehicles
INSERT INTO reference.fuel_types (code, name, unit) VALUES
('diesel',        'Diislikütus',    'litre'),
('95',            'Bensiin 95',     'litre'),
('98',            'Bensiin 98',     'litre'),
('electric',      'Elekter',        'kwh'),
('gas',           'CNG gaas',       'kg'),
('hybrid_diesel', 'Hübriid-diisel', 'litre')
ON CONFLICT (code) DO NOTHING;

INSERT INTO reference.cities (code, name, lat_min, lat_max, lon_min, lon_max) VALUES
('tallinn',  'Tallinn',     59.35, 59.55, 24.55, 24.95),
('tartu',    'Tartu',       58.30, 58.45, 26.60, 26.85),
('regional', 'Regionaalne', 57.50, 59.70, 21.50, 28.20)
ON CONFLICT (code) DO NOTHING;

-- Vehicle models loaded by scripts/load_reference.py on startup