-- =============================================================
-- 08_electricity_real_price.sql
-- Add override_price_eur to client_discounts
-- Reseed with realistic all-in electricity prices
--
-- Problem: bronze.fuel_prices.electric = Nord Pool spot price
-- (~0.003-0.01 €/kWh). This is the wholesale exchange price.
-- Real all-in Estonian electricity price includes:
--   - Energy component (Nord Pool spot)
--   - Distribution fee (võrguteenus): ~0.04-0.06 €/kWh
--   - Renewable energy levy (taastuvenergia tasu): ~0.01 €/kWh
--   - Electricity excise tax (aktsiis): ~0.005 €/kWh
--   - VAT 22%
-- Result: real consumer price = 0.12-0.20 €/kWh depending on tariff
--
-- Solution: override_price_eur column — when set, fuel_with_discount
-- uses this directly instead of pump_price - discount.
-- The Nord Pool price is kept in bronze.fuel_prices as market reference.
--
-- Realistic 2026 Estonian electricity prices:
--   Private (variable tariff, all-in): ~0.17 €/kWh
--   TLT (municipal charging, volume):  ~0.12 €/kWh
--   Elron (traction power, 3kV DC):    ~0.10 €/kWh
--
-- Sources:
--   Elering: https://dashboard.elering.ee
--   Elektrilevi tariffs: https://elektrilevi.ee/hinnakiri
--   Elron traction: estimated from Elron annual reports
-- =============================================================

BEGIN;

-- Step 1: Add override_price_eur column
ALTER TABLE bronze.client_discounts
    ADD COLUMN IF NOT EXISTS override_price_eur NUMERIC,
    ADD COLUMN IF NOT EXISTS price_basis        TEXT;   -- explains what the price represents

-- Step 2: Reseed all discounts
TRUNCATE bronze.client_discounts;

INSERT INTO bronze.client_discounts
    (company, fuel_type, discount, override_price_eur, price_basis, updated_by)
VALUES

-- ── Private person ─────────────────────────────────────────
-- Diesel/95/98: pump price minus small loyalty/app discount
('Eraisik', 'diesel',   0.05, NULL,  'pump - 0.05€ sooduskaart',    'seed'),
('Eraisik', '95',       0.05, NULL,  'pump - 0.05€ sooduskaart',    'seed'),
('Eraisik', '98',       0.03, NULL,  'pump - 0.03€ sooduskaart',    'seed'),
('Eraisik', 'gas',      0.04, NULL,  'pump - 0.04€ sooduskaart',    'seed'),

-- Electric: override with realistic all-in retail price
-- Variable tariff + Elektrilevi distribution + taxes + VAT
('Eraisik', 'electric', NULL, 0.17,  'Nord Pool + võrk + aktsiis + km 22% ≈ 0.17€/kWh', 'seed'),

-- ── TLT — Tallinna Linnatransport ──────────────────────────
-- Municipal fleet, volume contracts, direct billing
('TLT',     'diesel',   0.10, NULL,  'mahulepinguline hind -0.10€', 'seed'),
('TLT',     'gas',      0.08, NULL,  'CNG mahulepinguline -0.08€',  'seed'),

-- Electric: municipal charging infrastructure rate
-- TLT owns charging depots, pays distribution + energy, no retail margin
('TLT',     'electric', NULL, 0.12,  'omavalitsuse tariif, laadimisinfrast. ≈ 0.12€/kWh', 'seed'),

-- ── Elron — national rail operator ─────────────────────────
-- Diesel: long-term fuel supply contract
('Elron',   'diesel',   0.13, NULL,  'riikliku operaatori leping -0.13€', 'seed'),

-- Electric: traction power via Elering 3kV DC infrastructure
-- Separate from retail grid — wholesale traction tariff
-- Elron annual report 2023: electricity cost ~0.10€/kWh effective
('Elron',   'electric', NULL, 0.10,  'Elering traktsioonitoide 3kV DC ≈ 0.10€/kWh', 'seed');

COMMIT;

-- Verify: show all discount tiers with effective prices
-- Note: effective_price for electric uses override, others use pump - discount
-- Pump prices from bronze.fuel_prices shown for context
SELECT
    d.company,
    d.fuel_type,
    d.discount,
    d.override_price_eur,
    d.price_basis
FROM bronze.client_discounts d
ORDER BY d.fuel_type, d.company;