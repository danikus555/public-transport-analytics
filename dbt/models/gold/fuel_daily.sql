-- =============================================================
-- gold.fuel_daily
-- Daily fuel prices with change from previous day
--
-- Electric price note:
--   price_today = latest Nord Pool spot (changes hourly, informational)
--   price_today_avg = daily average (used in fuel_cost_daily calculations)
--   Both shown so dashboard can display spot context + stable daily avg
-- =============================================================

WITH today AS (
    SELECT DISTINCT ON (LOWER(fuel_type))
        LOWER(fuel_type)                AS fuel_type,
        price_eur                       AS price_today,
        source_date                     AS date_today,
        source
    FROM {{ source('bronze', 'fuel_prices') }}
    ORDER BY LOWER(fuel_type), source_date DESC
),

today_avg AS (
    -- Daily average per fuel type — meaningful for electric (hourly volatility)
    SELECT
        LOWER(fuel_type)                AS fuel_type,
        ROUND(AVG(price_eur)::NUMERIC, 6) AS price_today_avg,
        COUNT(*)                        AS readings_today
    FROM {{ source('bronze', 'fuel_prices') }}
    WHERE source_date = CURRENT_DATE
    GROUP BY LOWER(fuel_type)
),

yesterday AS (
    SELECT DISTINCT ON (LOWER(fuel_type))
        LOWER(fuel_type)                AS fuel_type,
        price_eur                       AS price_yesterday
    FROM {{ source('bronze', 'fuel_prices') }}
    WHERE source_date < CURRENT_DATE
    ORDER BY LOWER(fuel_type), source_date DESC
)

SELECT
    t.fuel_type,

    -- Latest spot price (diesel/gas: same as avg; electric: current hour)
    t.price_today,

    -- Daily average (electric: smoothed over all hourly readings today)
    ta.price_today_avg,

    -- How many readings today (electric has many; diesel has 1)
    ta.readings_today,

    -- Day-over-day change uses average vs average for fair comparison
    ROUND(
        COALESCE(ta.price_today_avg, t.price_today)
        - COALESCE(y.price_yesterday, t.price_today),
        4
    )                                   AS change_eur,

    ROUND(
        (COALESCE(ta.price_today_avg, t.price_today)
        - COALESCE(y.price_yesterday, t.price_today))
        / NULLIF(y.price_yesterday, 0) * 100,
        2
    )                                   AS change_pct,

    y.price_yesterday,
    t.date_today,
    t.source

FROM today t
LEFT JOIN today_avg ta ON ta.fuel_type = t.fuel_type
LEFT JOIN yesterday y  ON y.fuel_type  = t.fuel_type
ORDER BY t.fuel_type