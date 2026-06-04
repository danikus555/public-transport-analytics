-- =============================================================
-- 06_cleanup_elron_phantom_routes.sql
-- Remove phantom GTFS routes from reference.elron_line_types
--
-- These routes appear in GTFS data but are not real distinct Elron
-- routes — they are combined schedule variants, bracket suffixes,
-- or historical entries. They cause NULL avg_round_trip_km in
-- silver.elron_positions and inflate route_daily_km counts.
--
-- After running: dbt run (no GTFS reload needed)
-- =============================================================

BEGIN;

-- Remove combined/slash routes — these are not separate physical routes,
-- just schedule variants combining two lines
DELETE FROM reference.elron_line_types
WHERE liin IN (
    'Riia / Valga - Tallinn',
    'Tallinn - Valga / Riia',
    'Tallinn - Tartu / Valga',
    'Tartu / Valga - Tallinn'
);

-- Remove bracket variants — GTFS scheduling artifact, not real route names
-- The real routes (Tallinn - Tapa, Tallinn - Tartu) already exist
DELETE FROM reference.elron_line_types
WHERE liin IN (
    'Tallinn - Tapa (Tartu)',
    'Tartu - Tapa (Tallinn)',
    'Tapa - Tartu (Tallinn)',
    'Tallinn - Tartu RV',
    'Tallinn - Tapa (Tartu) RV'
);

-- Remove Türi line if not actually running currently
-- (check against bronze.elron_positions first — if Türi appears, do NOT delete)
-- DELETE FROM reference.elron_line_types WHERE liin IN ('Tallinn - Türi', 'Türi - Tallinn');

COMMIT;

-- Verify remaining routes — should be clean real Elron routes only
SELECT liin, fuel_type, model
FROM reference.elron_line_types
ORDER BY fuel_type, liin;

-- Cross-check: any bronze liin values not in reference? (should be 0 or only phantoms)
SELECT DISTINCT e.liin, elt.liin AS matched
FROM bronze.elron_positions e
LEFT JOIN reference.elron_line_types elt ON elt.liin = e.liin
WHERE elt.liin IS NULL
ORDER BY e.liin;