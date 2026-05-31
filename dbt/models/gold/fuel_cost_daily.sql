-- =============================================================
-- gold.fuel_cost_daily
-- Estimated daily fuel cost by transport type and operator
-- Business question: how much does daily operation cost?
--
-- Formula:
--   active_vehicles × estimated_daily_km × consumption / 100 × price_eur
--
-- Estimated daily km per vehicle:
--   TLT tram:       ~180km  (avg 9km route × 20 trips)
--   TLT bus:        ~225km  (avg 15km route × 15 trips)
--   TLT trolleybus: ~160km  (avg 8km route × 20 trips)
--   Elron train:    ~800km  (avg 160km route × 5 trips)
--   Note: Sprint 3 will replace estimates with GTFS shapes km
-- =============================================================

WITH active_vehicles AS (
    SELECT
        transport_type,
        fuel_type,
        operator,
        COUNT(DISTINCT vehicle_id)  AS vehicle_count,
        snapshot_date
    FROM {{ ref('vehicle_positions') }}
    WHERE snapshot_date = CURRENT_DATE
    GROUP BY transport_type, fuel_type, operator, snapshot_date
),

elron_active AS (
    SELECT
        'train'                     AS transport_type,
        fuel_type,
        'Elron'                     AS operator,
        COUNT(DISTINCT reis)        AS vehicle_count,
        ingested_at::date           AS snapshot_date
    FROM {{ ref('elron_positions') }}
    WHERE ingested_at::date = CURRENT_DATE
    GROUP BY fuel_type, ingested_at::date
),

all_active AS (
    SELECT * FROM active_vehicles
    UNION ALL
    SELECT * FROM elron_active
),

-- fleet total from reference — for utilization calculation
fleet_total AS (
    SELECT
        CASE o.code
            WHEN 'Elron' THEN 'train'
            ELSE lt.name
        END                         AS transport_type,
        m.fuel_type_code            AS fuel_type,
        o.code                      AS operator,
        SUM(m.vehicle_amount)       AS total_vehicles
    FROM {{ source('reference', 'vehicle_models') }} m
    JOIN {{ source('reference', 'line_types') }} lt
        ON lt.code = m.line_type_code
    JOIN {{ source('reference', 'operators') }} o
        ON o.code = m.operator_code
    WHERE m.active = TRUE
    GROUP BY
        CASE o.code WHEN 'Elron' THEN 'train' ELSE lt.name END,
        m.fuel_type_code, o.code
),

-- normalize fuel_type for consistent joining
-- CNG → gas (vehicle_models uses 'gas', fuel_prices uses 'CNG')
latest_prices AS (
    SELECT DISTINCT ON (normalized_type)
        normalized_type             AS fuel_type,
        price_eur,
        source_date
    FROM (
        SELECT
            CASE LOWER(fuel_type)
                WHEN 'cng'      THEN 'gas'
                WHEN 'diesel'   THEN 'diesel'
                WHEN 'electric' THEN 'electric'
                ELSE LOWER(fuel_type)
            END                     AS normalized_type,
            price_eur,
            source_date
        FROM {{ source('bronze', 'fuel_prices') }}
    ) sub
    ORDER BY normalized_type, source_date DESC
),

fleet AS (
    SELECT
        m.fuel_type_code            AS fuel_type,
        CASE o.code
            WHEN 'Elron' THEN 'train'
            ELSE lt.name
        END                         AS transport_type,
        o.code                      AS operator,
        AVG(m.consumption)          AS avg_consumption,
        MAX(m.consumption_unit)     AS consumption_unit
    FROM {{ source('reference', 'vehicle_models') }} m
    JOIN {{ source('reference', 'fuel_types') }} ft
        ON ft.code = m.fuel_type_code
    JOIN {{ source('reference', 'line_types') }} lt
        ON lt.code = m.line_type_code
    JOIN {{ source('reference', 'operators') }} o
        ON o.code = m.operator_code
    WHERE m.active = TRUE
    GROUP BY
        m.fuel_type_code,
        CASE o.code WHEN 'Elron' THEN 'train' ELSE lt.name END,
        o.code
)

SELECT
    av.transport_type,
    av.fuel_type,
    av.operator,
    av.snapshot_date,

    -- fleet utilization
    ft.total_vehicles               AS fleet_total,
    av.vehicle_count                AS active_today,
    ROUND(
        av.vehicle_count * 100.0 / NULLIF(ft.total_vehicles, 0), 1
    )                               AS utilization_pct,

    -- consumption
    f.avg_consumption,
    f.consumption_unit,
    p.price_eur                     AS fuel_price_eur,

    -- estimated daily km per vehicle by transport type
    CASE av.transport_type
        WHEN 'tram'        THEN 180
        WHEN 'trolleybus'  THEN 160
        WHEN 'bus'         THEN 225
        WHEN 'train'       THEN 800
        ELSE 200
    END                             AS estimated_km_per_vehicle,

    -- estimated daily cost
    ROUND(
        av.vehicle_count
        * CASE av.transport_type
            WHEN 'tram'        THEN 180
            WHEN 'trolleybus'  THEN 160
            WHEN 'bus'         THEN 225
            WHEN 'train'       THEN 800
            ELSE 200
          END
        * COALESCE(f.avg_consumption, 0) / 100
        * COALESCE(p.price_eur, 0),
        2
    )                               AS estimated_daily_cost_eur

FROM all_active av
LEFT JOIN fleet_total ft
    ON  ft.transport_type = av.transport_type
    AND ft.fuel_type      = av.fuel_type
    AND ft.operator       = av.operator
LEFT JOIN fleet f
    ON  f.fuel_type      = av.fuel_type
    AND f.transport_type = av.transport_type
    AND f.operator       = av.operator
LEFT JOIN latest_prices p
    ON p.fuel_type = CASE av.fuel_type
        WHEN 'hybrid_diesel' THEN 'diesel'
        ELSE av.fuel_type
    END