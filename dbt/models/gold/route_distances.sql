-- =============================================================
-- gold.route_distances
-- Real one-way and round-trip route lengths from GTFS shapes.txt
-- Covers TLT (tram, bus, trolleybus) and Elron (train)
--
-- shape_dist_traveled in reference.gtfs_shapes is METERS (cumulative).
-- MAX per shape_id = total length of that shape in meters.
-- One route has multiple shapes (IB, OB, variants) — we avg them.
--
-- Elron shapes filtered to known routes via elron_line_types:
-- excludes phantom GTFS entries like "(Tartu) Tapa - Tallinn"
-- =============================================================

WITH known_elron_routes AS (
    -- Whitelist: only real Elron routes from our reference table
    SELECT DISTINCT liin AS route_long_name
    FROM {{ source('reference', 'elron_line_types') }}
),

shape_lengths AS (
    -- Total length per shape in meters → convert to km
    SELECT
        shape_id,
        operator,
        MAX(shape_dist_traveled) / 1000.0   AS shape_length_km
    FROM {{ source('reference', 'gtfs_shapes') }}
    WHERE shape_dist_traveled IS NOT NULL
    GROUP BY shape_id, operator
),

trips_with_shapes AS (
    -- One row per distinct (route, shape) combination
    SELECT DISTINCT
        t.route_id,
        t.shape_id,
        r.route_short_name,
        r.route_long_name,
        r.route_type,
        r.operator
    FROM {{ source('reference', 'gtfs_trips') }} t
    JOIN {{ source('reference', 'gtfs_routes') }} r
        ON r.route_id = t.route_id
    -- Elron: only known routes; TLT: all routes
    LEFT JOIN known_elron_routes ker
        ON  ker.route_long_name = r.route_long_name
        AND r.route_type        = 2
    WHERE r.route_type IN (0, 2, 3, 11)
      AND t.shape_id IS NOT NULL
      AND (
          r.route_type != 2                      -- TLT: pass all
          OR ker.route_long_name IS NOT NULL      -- Elron: whitelist only
      )
),

route_shape_km AS (
    SELECT
        tw.route_short_name,
        tw.route_long_name,
        tw.route_type,
        tw.operator,
        tw.shape_id,
        sl.shape_length_km
    FROM trips_with_shapes tw
    JOIN shape_lengths sl
        ON  sl.shape_id  = tw.shape_id
        AND sl.operator  = tw.operator
    WHERE sl.shape_length_km > 0            -- exclude zero-length shapes
)

SELECT
    -- For Elron: route_long_name is the join key — must be unique per route
    -- Multiple route_ids can share the same route_long_name (schedule variants)
    -- We aggregate all of them into one row per route_long_name
    MAX(route_short_name)                   AS route_short_name,
    route_long_name,
    CASE MAX(route_type)
        WHEN 0  THEN 'tram'
        WHEN 2  THEN 'train'
        WHEN 3  THEN 'bus'
        WHEN 11 THEN 'trolleybus'
    END                                     AS transport_type,
    operator,
    COUNT(DISTINCT shape_id)                AS shape_count,
    ROUND(MIN(shape_length_km)::NUMERIC, 2) AS min_one_way_km,
    ROUND(AVG(shape_length_km)::NUMERIC, 2) AS avg_one_way_km,
    ROUND(MAX(shape_length_km)::NUMERIC, 2) AS max_one_way_km,
    ROUND((AVG(shape_length_km) * 2)::NUMERIC, 2) AS avg_round_trip_km
FROM route_shape_km
GROUP BY route_long_name, operator
ORDER BY operator, transport_type, route_long_name