-- =============================================================
-- public-transport-analytics
-- 04_migrate_elron_linetype.sql
-- One-time migration: fix Elron vehicle_models line_type_code 2 → 4
--
-- Problem: Elron models were stored with line_type_code = 2 (bus)
--          because reference.line_types had no code for 'train'.
--          This caused fleet_summary and fuel_cost_daily to show
--          Elron trains as transport_type = 'bus'.
--
-- Fix: add line_type code 4 = train, update Elron vehicle_models.
--
-- Run ONCE in DBeaver before reloading reference data:
--   docker cp 04_migrate_elron_linetype.sql transport-db:/tmp/
--   docker exec transport-db psql -U transport_user -d transport \
--       -f /tmp/04_migrate_elron_linetype.sql
--
-- Then reload reference data:
--   docker exec transport-pipeline python scripts/load_reference.py
--
-- Then run dbt:
--   docker exec transport-dbt dbt run --project-dir /app/dbt --profiles-dir /app/dbt
-- =============================================================

BEGIN;

-- Step 1: Add train to line_types
INSERT INTO reference.line_types (code, name, name_et, fuel_category)
VALUES (4, 'train', 'rong', 'mixed')
ON CONFLICT (code) DO NOTHING;

-- Step 2: Move Elron vehicle_models from line_type_code 2 → 4
-- The UNIQUE constraint is (operator_code, line_type_code, model)
-- so we must delete old rows and re-insert, not just UPDATE,
-- to avoid a constraint violation during the transition.
DELETE FROM reference.vehicle_models
WHERE operator_code = 'Elron'
  AND line_type_code = 2;

INSERT INTO reference.vehicle_models
    (operator_code, line_type_code, model, fuel_type_code,
     consumption, consumption_unit, vehicle_amount, active)
VALUES
    ('Elron', 4, 'Stadler FLIRT DMU',         'diesel',   3.5, 'l/100km',    20, TRUE),
    ('Elron', 4, 'Stadler FLIRT EMU',         'electric', 8.0, 'kWh/100km',  18, TRUE),
    ('Elron', 4, 'Škoda 21Ev (pikamaa)',      'electric', 8.0, 'kWh/100km',  11, TRUE),
    ('Elron', 4, 'Škoda 21Ev (linnalähirong)','electric', 6.0, 'kWh/100km',   5, TRUE)
ON CONFLICT (operator_code, line_type_code, model) DO UPDATE SET
    fuel_type_code   = EXCLUDED.fuel_type_code,
    consumption      = EXCLUDED.consumption,
    consumption_unit = EXCLUDED.consumption_unit,
    vehicle_amount   = EXCLUDED.vehicle_amount,
    active           = EXCLUDED.active,
    updated_at       = NOW();

COMMIT;

-- Verify: should show train for all Elron models
SELECT m.model, lt.name AS line_type_name, m.operator_code, m.fuel_type_code
FROM reference.vehicle_models m
JOIN reference.line_types lt ON lt.code = m.line_type_code
WHERE m.operator_code = 'Elron'
ORDER BY m.model;
-- Expected:
-- Stadler FLIRT DMU          | train | Elron | diesel
-- Stadler FLIRT EMU          | train | Elron | electric
-- Škoda 21Ev (linnalähirong) | train | Elron | electric
-- Škoda 21Ev (pikamaa)       | train | Elron | electric