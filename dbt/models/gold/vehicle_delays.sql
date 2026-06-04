-- =============================================================
-- gold.vehicle_delays
-- TLT vehicle proximity to nearest stop + estimated schedule status
--
-- Limitation: TLT GPS feed has no delay field (unlike Elron API).
-- True schedule delay requires GTFS-RT realtime feed (not available).
-- This model provides: nearest stop, distance to stop, line info.
-- delay_min is NULL for TLT — use gold.elron_delays for delay data.
--
-- What this answers:
--   - Which stop is each TLT vehicle closest to right now?
--   - How far is each vehicle from its nearest stop?
--   - Which lines have the most active vehicles?
-- =============================================================

WITH current_vehicles AS (
    -- Latest position per vehicle today
    SELECT DISTINCT ON (vehicle_id)
        vehicle_id,
        line_number,
        transport_type,
        lat,
        lon,
        ingested_at,
        ingested_at::date               AS snapshot_date
    FROM {{ ref('vehicle_positions') }}
    WHERE snapshot_date = CURRENT_DATE
    ORDER BY vehicle_id, ingested_at DESC
),

-- TLT stops with coordinates only — no time window needed
tlt_stops AS (
    SELECT DISTINCT
        s.stop_id,
        s.stop_name,
        s.stop_lat,
        s.stop_lon
    FROM {{ source('reference', 'gtfs_stops') }} s
    WHERE s.operator  = 'TLT'
      AND s.stop_lat  IS NOT NULL
      AND s.stop_lon  IS NOT NULL
      AND s.location_type = 0           -- platform stops only, not stations
),

-- For each vehicle find nearest stop
-- Uses indexed lat/lon bounding box first to reduce cross join size
nearest_stop AS (
    SELECT DISTINCT ON (v.vehicle_id)
        v.vehicle_id,
        v.line_number,
        v.transport_type,
        v.lat,
        v.lon,
        v.ingested_at,
        v.snapshot_date,
        s.stop_name,
        ROUND((
            6371000 * 2 * ASIN(SQRT(
                POWER(SIN(RADIANS(v.lat - s.stop_lat) / 2), 2)
                + COS(RADIANS(s.stop_lat)) * COS(RADIANS(v.lat))
                * POWER(SIN(RADIANS(v.lon - s.stop_lon) / 2), 2)
            ))
        )::NUMERIC, 0)                  AS dist_to_stop_m
    FROM current_vehicles v
    JOIN tlt_stops s
        -- Bounding box pre-filter: ~1km radius (0.009 degrees ≈ 1km)
        ON  s.stop_lat BETWEEN v.lat - 0.009 AND v.lat + 0.009
        AND s.stop_lon BETWEEN v.lon - 0.013 AND v.lon + 0.013
    ORDER BY v.vehicle_id, dist_to_stop_m ASC
)

SELECT
    vehicle_id,
    line_number,
    transport_type,
    stop_name,
    NULL::TEXT                          AS scheduled_time,
    ingested_at                         AS actual_time,
    NULL::INT                           AS delay_min,
    -- At stop = within 50m, approaching = 50-200m, in transit = >200m
    CASE
        WHEN dist_to_stop_m <= 50   THEN 'at_stop'
        WHEN dist_to_stop_m <= 200  THEN 'approaching'
        ELSE                             'in_transit'
    END                                 AS delay_category,
    snapshot_date,
    EXTRACT(HOUR FROM ingested_at)::INT AS hour
FROM nearest_stop
ORDER BY line_number, vehicle_id