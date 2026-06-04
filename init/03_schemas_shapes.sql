-- =============================================================
-- public-transport-analytics
-- 03_schemas_shapes.sql — GTFS shapes table
-- Sprint 3: replaces hardcoded km estimates with real route distances
--
-- Run once manually in DBeaver or add to init/ folder:
--   docker exec transport-db psql -U transport_user -d transport -f /docker-entrypoint-initdb.d/03_schemas_shapes.sql
--
-- After running: docker exec transport-pipeline python scripts/load_gtfs.py --force
-- =============================================================

-- =============================================================
-- REFERENCE — GTFS shapes
-- Loaded by scripts/load_gtfs.py (updated in Sprint 3)
-- shape_dist_traveled unit: METERS (cumulative)
-- Last point per shape_id = total route length in meters
-- =============================================================

CREATE TABLE IF NOT EXISTS reference.gtfs_shapes (
    id                   SERIAL PRIMARY KEY,
    shape_id             TEXT NOT NULL,
    shape_pt_lat         NUMERIC(10,7) NOT NULL,
    shape_pt_lon         NUMERIC(10,7) NOT NULL,
    shape_pt_sequence    INT NOT NULL,
    shape_dist_traveled  NUMERIC(12,2),          -- meters, cumulative
    operator             TEXT,                   -- 'TLT', 'Elron'
    updated_at           TIMESTAMP DEFAULT NOW()
);

-- Index for fast MAX(shape_dist_traveled) GROUP BY shape_id queries
CREATE INDEX IF NOT EXISTS idx_gtfs_shapes_shape_id
    ON reference.gtfs_shapes (shape_id);

CREATE INDEX IF NOT EXISTS idx_gtfs_shapes_operator
    ON reference.gtfs_shapes (operator);

-- Also add shape_id to gtfs_trips if not present
-- (needed for the route_distances join)
ALTER TABLE reference.gtfs_trips
    ADD COLUMN IF NOT EXISTS shape_id TEXT;