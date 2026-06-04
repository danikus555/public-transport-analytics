-- =============================================================
-- 09_fix_elron_fleet.sql
-- Fix Elron vehicle_models:
--   1. Remove duplicate Škoda 21Ev EMU (generic) — already covered
--      by specific variants Škoda 21Ev (pikamaa) and (linnalähirong)
-- =============================================================

-- Remove generic duplicate
DELETE FROM reference.vehicle_models
WHERE operator_code = 'Elron'
  AND model = 'Škoda 21Ev EMU';

-- Verify — should show 4 Elron models totalling 54 vehicles
SELECT model, fuel_type_code, vehicle_amount
FROM reference.vehicle_models
WHERE operator_code = 'Elron'
ORDER BY model;
-- Expected:
-- Stadler FLIRT DMU          diesel   20
-- Stadler FLIRT EMU          electric 18
-- Škoda 21Ev (linnalähirong) electric  5
-- Škoda 21Ev (pikamaa)       electric 11
-- Total: 54 vehicles