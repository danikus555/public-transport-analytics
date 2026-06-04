-- =============================================================
-- 05_migrate_missing_elron_routes.sql
-- Add missing Elron routes to reference tables
--
-- Problem: several routes appear in bronze.elron_positions but
-- are missing from reference.elron_line_types, causing NULL
-- fuel_type and NULL vehicle_model in silver.elron_positions.
--
-- Run in DBeaver once, then: dbt run
-- =============================================================

BEGIN;

-- Step 1: Add missing routes to elron_line_types
INSERT INTO reference.elron_line_types (liin, fuel_type, model, notes) VALUES
-- Electric routes missing from original seed
('Tallinn - Tapa',        'electric', 'Škoda 21Ev EMU', 'Elektrifitseeritud alates jan 2026'),
('Tapa - Tallinn',        'electric', 'Škoda 21Ev EMU', 'Elektrifitseeritud alates jan 2026'),
('Tallinn - Kloogaranna', 'electric', 'Škoda 21Ev EMU', 'Škoda 21Ev, alates 2025'),
('Kloogaranna - Tallinn', 'electric', 'Škoda 21Ev EMU', 'Škoda 21Ev, alates 2025'),
-- Diesel routes missing from original seed
('Koidula - Tartu',       'diesel',   'Stadler FLIRT DMU', NULL),
('Tallinn - Türi',        'diesel',   'Stadler FLIRT DMU', 'Türi liin'),
('Türi - Tallinn',        'diesel',   'Stadler FLIRT DMU', 'Türi liin')
ON CONFLICT (liin) DO NOTHING;

-- Step 2: Add Škoda 21Ev EMU to vehicle_models with consumption
-- (was missing — caused NULL consumption for Kloogaranna/Tapa lines)
INSERT INTO reference.vehicle_models
    (operator_code, line_type_code, model, fuel_type_code,
     consumption, consumption_unit, vehicle_amount, active)
VALUES
    ('Elron', 4, 'Škoda 21Ev EMU', 'electric', 7.5, 'kWh/100km', 16, TRUE)
ON CONFLICT (operator_code, line_type_code, model) DO UPDATE SET
    consumption      = EXCLUDED.consumption,
    consumption_unit = EXCLUDED.consumption_unit,
    vehicle_amount   = EXCLUDED.vehicle_amount,
    updated_at       = NOW();

COMMIT;

-- Verify: all elron_line_types should now have a matching vehicle_model
SELECT
    elt.liin,
    elt.fuel_type,
    elt.model,
    vm.consumption,
    vm.consumption_unit
FROM reference.elron_line_types elt
LEFT JOIN reference.vehicle_models vm
    ON  vm.operator_code  = 'Elron'
    AND vm.line_type_code = 4
    AND vm.model          = elt.model
    AND vm.active         = TRUE
ORDER BY elt.fuel_type, elt.liin;
-- Expected: zero NULL consumption rows for routes with known model