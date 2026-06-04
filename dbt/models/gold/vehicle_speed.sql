-- =============================================================
-- gold.vehicle_speed
-- Estimated vehicle speed and jam detection from GPS snapshots
--
-- Performance optimisations vs original:
--   1. Pre-filter to 2 hours BEFORE window functions (534k → ~60k rows)
--   2. Flat-earth distance formula replaces Haversine ASIN/SQRT
--      (accurate to 0.1% for <50km — city scale is fine)
--   3. slow_count window merged into with_speed — eliminates self-JOIN
--   4. Single pass over data: 3 CTEs instead of 5
--
-- Method: distance between consecutive positions ÷ time gap = speed
-- GPS interval: ~60s → speed accurate to ±5 km/h
--
-- Jam detection: speed < 5 km/h for 3+ consecutive snapshots
-- =============================================================

WITH recent_positions AS (
    -- Pre-filter to last 2 hours BEFORE window functions
    -- Reduces 534k rows to ~60k — critical for window function performance
    SELECT
        vehicle_id,
        line_number,
        transport_type,
        operator,
        lat,
        lon,
        ingested_at,
        snapshot_date,
        destination
    FROM {{ ref('vehicle_positions') }}
    WHERE ingested_at > NOW() - INTERVAL '2 hours'
),

with_prev AS (
    -- Add previous position in single pass using window functions
    SELECT
        vehicle_id,
        line_number,
        transport_type,
        operator,
        lat,
        lon,
        ingested_at,
        snapshot_date,
        destination,
        LAG(lat)         OVER w  AS prev_lat,
        LAG(lon)         OVER w  AS prev_lon,
        LAG(ingested_at) OVER w  AS prev_time
    FROM recent_positions
    WINDOW w AS (PARTITION BY vehicle_id ORDER BY ingested_at)
),

with_speed AS (
    SELECT
        vehicle_id,
        line_number,
        transport_type,
        operator,
        lat,
        lon,
        ingested_at,
        snapshot_date,
        destination,

        ROUND(
            EXTRACT(EPOCH FROM (ingested_at - prev_time))::NUMERIC, 0
        )                                               AS gap_sec,

        -- Flat-earth distance in metres (accurate <0.1% for city scale)
        -- ~10x faster than Haversine ASIN/SQRT for same accuracy at <50km
        ROUND((
            111320.0 * SQRT(
                POWER((lat - prev_lat), 2)
                + POWER((lon - prev_lon) * COS(RADIANS((lat + prev_lat) / 2)), 2)
            )
        )::NUMERIC, 1)                                  AS dist_m,

        -- Speed in km/h — calculated inline, reused below
        ROUND((
            111320.0 * SQRT(
                POWER((lat - prev_lat), 2)
                + POWER((lon - prev_lon) * COS(RADIANS((lat + prev_lat) / 2)), 2)
            )
            / NULLIF(EXTRACT(EPOCH FROM (ingested_at - prev_time)), 0)
            * 3.6
        )::NUMERIC, 1)                                  AS speed_kmh,

        -- Jam detection window merged here — no separate CTE or JOIN needed
        SUM(CASE WHEN (
            111320.0 * SQRT(
                POWER((lat - prev_lat), 2)
                + POWER((lon - prev_lon) * COS(RADIANS((lat + prev_lat) / 2)), 2)
            )
            / NULLIF(EXTRACT(EPOCH FROM (ingested_at - prev_time)), 0)
            * 3.6
        ) < 5 THEN 1 ELSE 0 END)
            OVER (
                PARTITION BY vehicle_id
                ORDER BY ingested_at
                ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
            )                                           AS slow_snapshots_last3

    FROM with_prev
    WHERE prev_lat IS NOT NULL
      AND EXTRACT(EPOCH FROM (ingested_at - prev_time)) BETWEEN 30 AND 180
)

SELECT
    vehicle_id,
    line_number,
    transport_type,
    operator,
    lat,
    lon,
    ingested_at,
    snapshot_date,
    destination,
    dist_m,
    gap_sec,
    speed_kmh,

    CASE
        WHEN speed_kmh = 0      THEN 'stopped'
        WHEN speed_kmh < 5      THEN 'very_slow'
        WHEN speed_kmh < 15     THEN 'slow'
        WHEN speed_kmh < 35     THEN 'normal'
        ELSE                         'fast'
    END                             AS speed_category,

    CASE
        WHEN slow_snapshots_last3 >= 3
         AND speed_kmh < 5      THEN TRUE
        ELSE                         FALSE
    END                             AS in_jam,

    EXTRACT(HOUR FROM ingested_at)::INT AS hour

FROM with_speed
-- Filter GPS glitches — >120 km/h impossible for bus/tram
WHERE speed_kmh < 120
  AND speed_kmh IS NOT NULL
ORDER BY ingested_at DESC, line_number