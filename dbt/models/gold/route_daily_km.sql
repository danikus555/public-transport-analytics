-- =============================================================
-- gold.route_daily_km
-- Scheduled daily km per route from GTFS trips × shape distances
--
-- Sprint 3 fix: filter trips to today's active service_ids only.
-- Without this filter, ALL service_ids are counted (Mon+Tue+...+Sun),
-- inflating daily km by ~3-7×.
--
-- service_id patterns:
--   TLT:   "juuni_-_august_2026-Weekday"  → Mon-Fri
--          "juuni_-_august_2026-Sa"        → Saturday
--          "juuni_-_august_2026-Su"        → Sunday
--   Elron: "Laane_26.01-31.12.026.02.2026-Mo"  → Monday only
--          "Laane_26.01-31.12.026.02.2026-Fr"  → Friday only
--          etc.
--
-- Elron filtered to known routes via elron_line_types whitelist.
-- Phantom GTFS entries excluded.
-- =============================================================

WITH today_dow AS (
    -- Day of week: 0=Sunday, 1=Monday, ..., 6=Saturday (PostgreSQL EXTRACT)
    SELECT EXTRACT(DOW FROM CURRENT_DATE)::INT AS dow
),

active_services AS (
    -- TLT: service_id ends with -Weekday, -Sa, or -Su
    SELECT DISTINCT t.service_id
    FROM reference.gtfs_trips t
    JOIN reference.gtfs_routes r ON r.route_id = t.route_id
    CROSS JOIN today_dow td
    WHERE r.operator    = 'TLT'
      AND r.route_type IN (0, 3, 11)
      AND (
          (td.dow BETWEEN 1 AND 5 AND t.service_id ILIKE '%Weekday%')
          OR (td.dow = 6             AND t.service_id ILIKE '%-Sa%')
          OR (td.dow = 0             AND t.service_id ILIKE '%-Su%')
      )

    UNION

    -- Elron: service_id ends with -Mo, -Tu, -We, -Th, -Fr, -Sa, -Su
    SELECT DISTINCT t.service_id
    FROM reference.gtfs_trips t
    JOIN reference.gtfs_routes r ON r.route_id = t.route_id
    CROSS JOIN today_dow td
    WHERE r.operator   = 'Elron'
      AND r.route_type = 2
      AND (
          (td.dow = 1 AND t.service_id LIKE '%-Mo')
          OR (td.dow = 2 AND t.service_id LIKE '%-Tu')
          OR (td.dow = 3 AND t.service_id LIKE '%-We')
          OR (td.dow = 4 AND t.service_id LIKE '%-Th')
          OR (td.dow = 5 AND t.service_id LIKE '%-Fr')
          OR (td.dow = 6 AND t.service_id LIKE '%-Sa')
          OR (td.dow = 0 AND t.service_id LIKE '%-Su')
      )
),

known_elron_routes AS (
    SELECT DISTINCT liin AS route_long_name
    FROM {{ source('reference', 'elron_line_types') }}
),

trips_scheduled AS (
    SELECT
        t.route_id,
        t.shape_id,
        r.operator,
        r.route_short_name,
        r.route_long_name,
        r.route_type,
        COUNT(DISTINCT t.trip_id)           AS trips_count
    FROM {{ source('reference', 'gtfs_trips') }} t
    JOIN {{ source('reference', 'gtfs_routes') }} r
        ON r.route_id = t.route_id
    -- Only today's active service_ids
    JOIN active_services svc
        ON svc.service_id = t.service_id
    -- Elron: only known routes (excludes phantom GTFS variants)
    LEFT JOIN known_elron_routes ker
        ON  ker.route_long_name = r.route_long_name
        AND r.route_type        = 2
    WHERE r.route_type IN (0, 2, 3, 11)
      AND t.shape_id IS NOT NULL
      AND (
          r.route_type != 2
          OR ker.route_long_name IS NOT NULL
      )
    GROUP BY t.route_id, t.shape_id, r.operator,
             r.route_short_name, r.route_long_name, r.route_type
),

shape_lengths AS (
    SELECT
        shape_id,
        operator,
        MAX(shape_dist_traveled) / 1000.0   AS shape_length_km
    FROM {{ source('reference', 'gtfs_shapes') }}
    WHERE shape_dist_traveled IS NOT NULL
    GROUP BY shape_id, operator
)

SELECT
    ts.operator,
    ts.route_short_name,
    ts.route_long_name,
    CASE ts.route_type
        WHEN 0  THEN 'tram'
        WHEN 2  THEN 'train'
        WHEN 3  THEN 'bus'
        WHEN 11 THEN 'trolleybus'
    END                                             AS transport_type,
    SUM(ts.trips_count)                             AS total_trips_scheduled,
    ROUND(
        SUM(ts.trips_count * sl.shape_length_km)::NUMERIC,
        1
    )                                               AS scheduled_km_per_day
FROM trips_scheduled ts
JOIN shape_lengths sl
    ON  sl.shape_id = ts.shape_id
    AND sl.operator = ts.operator
GROUP BY ts.operator, ts.route_short_name, ts.route_long_name, ts.route_type
ORDER BY ts.operator, transport_type, ts.route_short_name