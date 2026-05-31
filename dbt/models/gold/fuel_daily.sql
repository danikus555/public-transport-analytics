-- =============================================================
-- gold.fuel_daily
-- Daily fuel prices with change from previous day
-- Shows: current price, yesterday price, change in € and %
-- =============================================================

WITH today AS (
    SELECT DISTINCT ON (LOWER(fuel_type))
        LOWER(fuel_type)            AS fuel_type,
        price_eur                   AS price_today,
        source_date                 AS date_today,
        source
    FROM {{ source('bronze', 'fuel_prices') }}
    ORDER BY LOWER(fuel_type), source_date DESC
),

yesterday AS (
    SELECT DISTINCT ON (LOWER(fuel_type))
        LOWER(fuel_type)            AS fuel_type,
        price_eur                   AS price_yesterday
    FROM {{ source('bronze', 'fuel_prices') }}
    WHERE source_date < CURRENT_DATE
    ORDER BY LOWER(fuel_type), source_date DESC
)

SELECT
    t.fuel_type,
    t.price_today,
    y.price_yesterday,
    ROUND(t.price_today - COALESCE(y.price_yesterday, t.price_today), 4)
                                    AS change_eur,
    ROUND(
        (t.price_today - COALESCE(y.price_yesterday, t.price_today))
        / NULLIF(y.price_yesterday, 0) * 100,
        2
    )                               AS change_pct,
    t.date_today,
    t.source
FROM today t
LEFT JOIN yesterday y ON y.fuel_type = t.fuel_type
ORDER BY t.fuel_type