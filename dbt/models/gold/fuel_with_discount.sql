-- =============================================================
-- gold.fuel_with_discount
-- Current fuel prices with per-company contract discounts applied
--
-- Business questions answered:
--   - What does each operator actually pay per litre/kWh?
--   - How much cheaper is TLT/Elron vs private person?
--   - What is the real electricity cost vs Nord Pool spot price?
--
-- Price logic:
--   override_price_eur IS NOT NULL → use override directly
--     Used for electricity: Nord Pool spot is not a real consumer price.
--     Override = realistic all-in price (energy + grid + taxes + VAT)
--   override_price_eur IS NULL     → pump_price - discount
--     Used for diesel/95/98/gas: pump price is real, discount is applied
--
-- saving_vs_pump_pct:
--   diesel/gas/95/98 → % saved vs pump price (positive = cheaper)
--   electric         → NULL (Nord Pool spot is not a real baseline)
--
-- saving_vs_private_pct:
--   For all fuel types: how much cheaper vs Eraisik (private person).
--   This is the meaningful comparison for electric:
--   Elron 0.10 vs Eraisik 0.17 = 41% cheaper.
--
-- Sources:
--   bronze.fuel_prices      — live scraped market prices (daily)
--   bronze.client_discounts — contract tiers + electricity overrides (manual)
-- =============================================================

WITH latest_prices AS (
    SELECT DISTINCT ON (LOWER(fuel_type))
        LOWER(fuel_type)                    AS fuel_type,
        price_eur                           AS pump_price_eur,
        source_date,
        source
    FROM {{ source('bronze', 'fuel_prices') }}
    ORDER BY LOWER(fuel_type), source_date DESC
),

discounts_normalised AS (
    SELECT
        company,
        LOWER(fuel_type)                    AS fuel_type,
        discount,
        override_price_eur,
        price_basis
    FROM {{ source('bronze', 'client_discounts') }}
),

effective_prices AS (
    -- Calculate effective price per company × fuel_type
    SELECT
        d.company,
        p.fuel_type,
        p.pump_price_eur,
        d.discount                          AS discount_eur,
        d.override_price_eur,
        d.price_basis,
        p.source_date,
        p.source,
        ROUND(
            COALESCE(
                d.override_price_eur,
                p.pump_price_eur - d.discount
            )::NUMERIC, 4
        )                                   AS effective_price_eur
    FROM discounts_normalised d
    JOIN latest_prices p ON p.fuel_type = d.fuel_type
),

-- Private person baseline per fuel_type for operator comparison
private_baseline AS (
    SELECT fuel_type, effective_price_eur   AS private_price_eur
    FROM effective_prices
    WHERE company = 'Eraisik'
)

SELECT
    e.company,
    e.fuel_type,

    -- Market reference (Nord Pool spot for electric — informational only)
    e.pump_price_eur,

    e.discount_eur,
    e.effective_price_eur,

    -- Savings vs pump price:
    --   meaningful for diesel/gas/95/98 (pump price is real)
    --   NULL for electric (Nord Pool spot is not a real baseline)
    CASE
        WHEN e.override_price_eur IS NOT NULL THEN NULL
        ELSE ROUND(e.discount_eur::NUMERIC, 4)
    END                                     AS saving_vs_pump_eur,

    CASE
        WHEN e.override_price_eur IS NOT NULL THEN NULL
        ELSE ROUND(
            e.discount_eur / NULLIF(e.pump_price_eur, 0) * 100, 1
        )
    END                                     AS saving_vs_pump_pct,

    -- Savings vs private person (Eraisik) — meaningful for ALL fuel types
    -- Positive = cheaper than private person
    -- Key insight: Elron electric 0.10 vs Eraisik 0.17 = 41% cheaper
    ROUND(
        (pb.private_price_eur - e.effective_price_eur)::NUMERIC, 4
    )                                       AS saving_vs_private_eur,

    ROUND(
        (pb.private_price_eur - e.effective_price_eur)
        / NULLIF(pb.private_price_eur, 0) * 100, 1
    )                                       AS saving_vs_private_pct,

    -- Price method label for dashboard tooltip
    CASE
        WHEN e.override_price_eur IS NOT NULL
        THEN 'tegelik hind (ei ole Nord Pool)'
        ELSE 'pump - ' || e.discount_eur::TEXT || ' €'
    END                                     AS price_method,

    e.price_basis,
    e.source_date,
    e.source                                AS market_price_source,

    CASE e.company
        WHEN 'Eraisik' THEN 'Eraisik'
        WHEN 'TLT'     THEN 'TLT (leping)'
        WHEN 'Elron'   THEN 'Elron (leping)'
        ELSE e.company
    END                                     AS company_label

FROM effective_prices e
LEFT JOIN private_baseline pb ON pb.fuel_type = e.fuel_type
ORDER BY e.fuel_type, e.company