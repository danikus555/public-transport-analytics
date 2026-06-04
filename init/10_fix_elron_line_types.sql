-- =============================================================
-- 10_fix_elron_line_types.sql
-- Fix elron_line_types model names to match vehicle_models
--
-- Problem: elron_line_types has model = 'Škoda 21Ev EMU'
-- but vehicle_models has 'Škoda 21Ev (pikamaa)' and
-- 'Škoda 21Ev (linnalähirong)' — the generic entry was deleted.
-- The JOIN silver.elron_positions → vehicle_models fails → cost = 0.
--
-- Fix: map routes to correct specific model names.
-- Kloogaranna route uses shorter trainsets → linnalähirong
-- Tapa route uses longer trainsets → pikamaa
-- =============================================================

BEGIN;

-- Kloogaranna line: short commuter route → linnalähirong (shorter train)
UPDATE reference.elron_line_types
SET model = 'Škoda 21Ev (linnalähirong)'
WHERE model = 'Škoda 21Ev EMU'
  AND liin IN (
      'Tallinn - Kloogaranna',
      'Kloogaranna - Tallinn'
  );

-- Tapa line: longer route → pikamaa (longer train)
UPDATE reference.elron_line_types
SET model = 'Škoda 21Ev (pikamaa)'
WHERE model = 'Škoda 21Ev EMU'
  AND liin IN (
      'Tallinn - Tapa',
      'Tapa - Tallinn'
  );

-- Any remaining Škoda 21Ev EMU entries → pikamaa as default
UPDATE reference.elron_line_types
SET model = 'Škoda 21Ev (pikamaa)'
WHERE model = 'Škoda 21Ev EMU';

COMMIT;

-- Verify — no Škoda 21Ev EMU should remain
SELECT liin, fuel_type, model
FROM reference.elron_line_types
WHERE model LIKE '%Škoda%'
ORDER BY liin;