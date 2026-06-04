-- =============================================================
-- 07_seed_client_discounts.sql
-- Seed reference discount tiers for fuel_with_discount model
--
-- Discount tiers (illustrative, from head):
--   Private person  — retail pump price minus small loyalty discount
--   TLT             — municipal operator, volume contract
--   Elron           — national rail operator, volume contract
--
-- Discounts in €/litre (or €/kWh for electric):
--   Private / 95        -0.05 €/l
--   Private / Diesel    -0.05 €/l
--   Private / Electric  -0.03 €/kWh
--   TLT     / Diesel    -0.10 €/l    (fleet contract)
--   TLT     / Gas       -0.08 €/kg   (CNG volume contract)
--   TLT     / Electric  -0.03 €/kWh  (municipal rate)
--   Elron   / Diesel    -0.13 €/l    (national operator contract)
--   Elron   / Electric  -0.04 €/kWh  (infrastructure rate)
--
-- Run once in DBeaver, then: dbt run
-- =============================================================

-- Clear existing discounts to avoid duplicates on re-run
TRUNCATE bronze.client_discounts;

INSERT INTO bronze.client_discounts (company, fuel_type, discount, updated_by) VALUES

-- Private person — standard retail, small loyalty/app discount
('Eraisik',  'diesel',   0.05, 'seed'),
('Eraisik',  '95',       0.05, 'seed'),
('Eraisik',  '98',       0.03, 'seed'),
('Eraisik',  'electric', 0.03, 'seed'),
('Eraisik',  'gas',      0.04, 'seed'),

-- TLT — Tallinna Linnatransport, municipal fleet contract
-- Diesel: trolleybus depot + small diesel fleet
-- Gas: main bus fleet (CNG)
-- Electric: charging infrastructure
('TLT',      'diesel',   0.10, 'seed'),
('TLT',      'gas',      0.08, 'seed'),
('TLT',      'electric', 0.03, 'seed'),

-- Elron — national rail operator, long-term infrastructure contracts
-- Diesel: DMU fuel (Stadler FLIRT DMU fleet)
-- Electric: EMU traction power (Škoda 21Ev + Stadler FLIRT EMU)
('Elron',    'diesel',   0.13, 'seed'),
('Elron',    'electric', 0.04, 'seed');

-- Verify
SELECT company, fuel_type, discount,
       concat('-', discount::TEXT, ' €/unit') AS discount_display
FROM bronze.client_discounts
ORDER BY company, fuel_type;