-- =============================================================
-- gold.fuel_cost_daily
-- Estimated daily fuel cost by transport type and operator
-- Business question: how much does daily operation cost?
--
-- Formula:
--   active_vehicles × km_per_vehicle × consumption / 100 × price_eur
--
-- TLT bus fuel_type = 'mixed':
--   The GPS feed does not identify vehicle type per line.
--   Per-vehicle fuel type cannot be assigned from public data.
--   Cost calculated per fuel type separately using fleet proportions,
--   then summed. Units stay native (l, kg, kWh) — no invalid blending.
--
-- Elron: split by fuel_type (electric EMU/Škoda vs diesel DMU).
--   km from GTFS shapes via silver.elron_positions.
--
-- TLT km: GTFS scheduled km for today's service_ids ÷ active vehicles.
--   Day-of-week filtered in route_daily_km.sql.
--
-- CTE order (PostgreSQL requires definition before reference):
--   1. latest_prices
--   2. tlt_network_km
--   3. tlt_bus_cost        (references latest_prices + tlt_network_km)
--   4. active_vehicles
--   5. elron_active
--   6. all_active
--   7. fleet_total
--   8. tlt_fixed_consumption
-- =============================================================

WITH latest_prices AS (
    SELECT DISTINCT ON (normalized_type)
        normalized_type                     AS fuel_type,
        price_eur,
        source_date
    FROM (
        SELECT
            CASE LOWER(fuel_type)
                WHEN 'cng'      THEN 'gas'
                WHEN 'diesel'   THEN 'diesel'
                WHEN 'electric' THEN 'electric'
                ELSE LOWER(fuel_type)
            END                             AS normalized_type,
            price_eur,
            source_date
        FROM {{ source('bronze', 'fuel_prices') }}
    ) sub
    ORDER BY normalized_type, source_date DESC
),

-- TLT scheduled km for today — defined early so tlt_bus_cost can use it
tlt_network_km AS (
    SELECT
        transport_type,
        SUM(scheduled_km_per_day)           AS total_network_km
    FROM {{ ref('route_daily_km') }}
    WHERE operator = 'TLT'
    GROUP BY transport_type
),

-- TLT bus fleet total — pre-calculated to avoid window-in-aggregate error
tlt_bus_fleet_total AS (
    SELECT SUM(COALESCE(m.vehicle_amount, 1)) AS total_vehicles
    FROM {{ source('reference', 'vehicle_models') }} m
    JOIN {{ source('reference', 'line_types') }} lt ON lt.code = m.line_type_code
    JOIN {{ source('reference', 'operators') }} o   ON o.code  = m.operator_code
    WHERE o.code = 'TLT' AND lt.name = 'bus' AND m.active = TRUE
),

-- TLT bus: calculate total cost per fuel type separately then sum.
-- Cannot blend l/kg/kWh — units are incompatible.
-- For each model: fleet_proportion × network_km × consumption × price.
-- Fleet proportion = vehicles of that fuel type / total bus fleet.
tlt_bus_cost AS (
    SELECT
        SUM(
            (COALESCE(m.vehicle_amount, 1)::NUMERIC
                / NULLIF(bft.total_vehicles, 0))
            * COALESCE(tk.total_network_km, 0)
            * m.consumption / 100.0
            * COALESCE(p.price_eur, 0)
        )                                   AS total_cost_eur,
        bft.total_vehicles                  AS total_bus_vehicles
    FROM {{ source('reference', 'vehicle_models') }} m
    JOIN {{ source('reference', 'line_types') }} lt
        ON lt.code = m.line_type_code
    JOIN {{ source('reference', 'operators') }} o
        ON o.code = m.operator_code
    CROSS JOIN tlt_bus_fleet_total bft
    LEFT JOIN latest_prices p
        ON p.fuel_type = CASE m.fuel_type_code
            WHEN 'hybrid_diesel' THEN 'diesel'
            ELSE m.fuel_type_code
        END
    LEFT JOIN tlt_network_km tk
        ON tk.transport_type = 'bus'
    WHERE o.code           = 'TLT'
      AND lt.name          = 'bus'
      AND m.active         = TRUE
      AND m.consumption    IS NOT NULL
    GROUP BY bft.total_vehicles
),

active_vehicles AS (
    -- TLT: count DISTINCT vehicles at the latest GPS snapshot only
    -- Using latest snapshot avoids counting same vehicle multiple times
    -- as it moves through different lines during the day
    SELECT
        transport_type,
        fuel_type,
        operator,
        COUNT(DISTINCT vehicle_id)          AS vehicle_count,
        snapshot_date
    FROM {{ ref('vehicle_positions') }}
    WHERE ingested_at = (
        SELECT MAX(ingested_at)
        FROM {{ ref('vehicle_positions') }}
        WHERE snapshot_date = CURRENT_DATE
    )
    GROUP BY transport_type, fuel_type, operator, snapshot_date
),

elron_active AS (
    -- Elron: count DISTINCT trains at the latest API snapshot only
    -- Using latest snapshot gives physically running trains right now
    -- NOT all-day trip count (which inflates: 13 trains → 59 trip IDs)
    SELECT
        'train'                             AS transport_type,
        fuel_type,
        vehicle_model,
        'Elron'                             AS operator,
        COUNT(DISTINCT reis)                AS vehicle_count,
        ingested_at::date                   AS snapshot_date,
        AVG(consumption)                    AS avg_consumption,
        MAX(consumption_unit)               AS consumption_unit,
        AVG(avg_round_trip_km)              AS gtfs_km_per_vehicle
    FROM {{ ref('elron_positions') }}
    WHERE ingested_at = (
        SELECT MAX(ingested_at)
        FROM {{ ref('elron_positions') }}
        WHERE ingested_at::date = CURRENT_DATE
    )
      AND fuel_type          IS NOT NULL
      AND avg_round_trip_km  IS NOT NULL
    GROUP BY fuel_type, vehicle_model, ingested_at::date
),

all_active AS (
    SELECT
        transport_type,
        fuel_type,
        NULL::TEXT                          AS vehicle_model,
        operator,
        vehicle_count,
        snapshot_date,
        NULL::NUMERIC                       AS elron_avg_consumption,
        NULL::TEXT                          AS elron_consumption_unit,
        NULL::NUMERIC                       AS gtfs_km_per_vehicle
    FROM active_vehicles
    UNION ALL
    SELECT
        transport_type,
        fuel_type,
        vehicle_model,
        operator,
        vehicle_count,
        snapshot_date,
        avg_consumption,
        consumption_unit,
        gtfs_km_per_vehicle
    FROM elron_active
),

-- Fleet total for utilization %
-- TLT bus: all models collapsed to 'mixed' (one fleet total)
fleet_total AS (
    SELECT
        lt.name                             AS transport_type,
        CASE
            WHEN o.code = 'TLT' AND lt.name = 'bus' THEN 'mixed'
            ELSE m.fuel_type_code
        END                                 AS fuel_type,
        o.code                              AS operator,
        SUM(m.vehicle_amount)               AS total_vehicles
    FROM {{ source('reference', 'vehicle_models') }} m
    JOIN {{ source('reference', 'line_types') }} lt
        ON lt.code = m.line_type_code
    JOIN {{ source('reference', 'operators') }} o
        ON o.code = m.operator_code
    WHERE m.active = TRUE
    GROUP BY lt.name,
        CASE WHEN o.code = 'TLT' AND lt.name = 'bus' THEN 'mixed'
             ELSE m.fuel_type_code END,
        o.code
),

-- TLT tram/trolleybus consumption (not bus — bus handled in tlt_bus_cost)
tlt_fixed_consumption AS (
    SELECT
        m.fuel_type_code                    AS fuel_type,
        lt.name                             AS transport_type,
        AVG(m.consumption)                  AS avg_consumption,
        MAX(m.consumption_unit)             AS consumption_unit
    FROM {{ source('reference', 'vehicle_models') }} m
    JOIN {{ source('reference', 'line_types') }} lt
        ON lt.code = m.line_type_code
    WHERE m.operator_code  = 'TLT'
      AND lt.name         != 'bus'
      AND m.active         = TRUE
    GROUP BY m.fuel_type_code, lt.name
)

SELECT
    av.transport_type,
    av.fuel_type,
    av.vehicle_model,
    av.operator,
    av.snapshot_date,

    -- Fleet utilization
    ft.total_vehicles                       AS fleet_total,
    av.vehicle_count                        AS active_today,
    ROUND(
        av.vehicle_count * 100.0 / NULLIF(ft.total_vehicles, 0), 1
    )                                       AS utilization_pct,

    -- Consumption
    -- TLT bus: NULL — cost pre-calculated per fuel type in tlt_bus_cost
    -- TLT tram + Elron: real consumption from vehicle_models / silver
    COALESCE(
        av.elron_avg_consumption,
        fc.avg_consumption
    )                                       AS avg_consumption,
    COALESCE(
        av.elron_consumption_unit,
        fc.consumption_unit,
        CASE WHEN av.operator = 'TLT' AND av.transport_type = 'bus'
             THEN 'mixed_units' END
    )                                       AS consumption_unit,

    -- Price
    -- TLT bus: NULL — already inside tlt_bus_cost calculation
    CASE WHEN av.operator = 'TLT' AND av.transport_type = 'bus'
         THEN NULL
         ELSE p.price_eur
    END                                     AS fuel_price_eur,

    -- km per vehicle per day
    ROUND(
        COALESCE(
            av.gtfs_km_per_vehicle,
            tk.total_network_km / NULLIF(av.vehicle_count, 0),
            CASE av.transport_type
                WHEN 'tram'       THEN 180
                WHEN 'trolleybus' THEN 160
                WHEN 'bus'        THEN 225
                WHEN 'train'      THEN 800
                ELSE 200
            END
        )::NUMERIC, 1
    )                                       AS estimated_km_per_vehicle,

    CASE
        WHEN av.gtfs_km_per_vehicle IS NOT NULL THEN 'gtfs_shapes_elron'
        WHEN tk.total_network_km    IS NOT NULL THEN 'gtfs_shapes_tlt'
        ELSE                                         'hardcoded_fallback'
    END                                     AS km_source,

    CASE
        WHEN av.operator = 'TLT' AND av.transport_type = 'bus'
            THEN 'Per-fuel-type cost summed across fleet proportions. Per-vehicle fuel type unknown from GPS data.'
        WHEN av.operator = 'Elron'
            THEN 'Per-route GTFS distance. Electric/diesel split by elron_line_types.'
        ELSE NULL
    END                                     AS methodology_note,

    -- Estimated daily cost
    -- TLT bus: from tlt_bus_cost (per-fuel-type, correct units)
    -- All others: active_vehicles × km × consumption / 100 × price
    ROUND(
        CASE
            WHEN av.operator = 'TLT' AND av.transport_type = 'bus'
            THEN bc.total_cost_eur
            ELSE (
                av.vehicle_count
                * COALESCE(
                    av.gtfs_km_per_vehicle,
                    tk.total_network_km / NULLIF(av.vehicle_count, 0),
                    CASE av.transport_type
                        WHEN 'tram'       THEN 180
                        WHEN 'trolleybus' THEN 160
                        WHEN 'train'      THEN 800
                        ELSE 200
                    END
                  )
                * COALESCE(av.elron_avg_consumption, fc.avg_consumption, 0) / 100
                * COALESCE(p.price_eur, 0)
            )
        END::NUMERIC, 2
    )                                       AS estimated_daily_cost_eur

FROM all_active av

LEFT JOIN fleet_total ft
    ON  ft.transport_type = av.transport_type
    AND ft.fuel_type      = av.fuel_type
    AND ft.operator       = av.operator

LEFT JOIN tlt_bus_cost bc
    ON  av.operator       = 'TLT'
    AND av.transport_type = 'bus'

LEFT JOIN tlt_fixed_consumption fc
    ON  fc.fuel_type      = av.fuel_type
    AND fc.transport_type = av.transport_type

LEFT JOIN latest_prices p
    ON  p.fuel_type = CASE av.fuel_type
            WHEN 'hybrid_diesel' THEN 'diesel'
            WHEN 'mixed'         THEN NULL
            ELSE av.fuel_type
        END
    AND NOT (av.operator = 'TLT' AND av.transport_type = 'bus')

LEFT JOIN tlt_network_km tk
    ON  tk.transport_type = av.transport_type
    AND av.operator       = 'TLT'