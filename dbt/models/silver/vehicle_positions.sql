-- =============================================================
-- silver.vehicle_positions
-- Enriches bronze GPS data with GTFS transport type
-- Joins bronze.vehicle_positions with reference.gtfs_routes
-- =============================================================

SELECT
    v.vehicle_id,
    v.line_type,
    v.line_number,
    r.route_id,
    CASE r.route_type
        WHEN 0  THEN 'tram'
        WHEN 3  THEN 'bus'
        WHEN 11 THEN 'trolleybus'
        ELSE
            CASE v.line_type
                WHEN 3 THEN 'tram'
                WHEN 2 THEN 'bus'
                ELSE 'unknown'
            END
    END                             AS transport_type,
    CASE r.route_type
        WHEN 0  THEN 'electric'
        WHEN 11 THEN 'electric'
        WHEN 3  THEN
            COALESCE(m.fuel_type_code, 'diesel')
        ELSE 'diesel'
    END                             AS fuel_type,
    v.destination,
    v.operator,
    v.lat,
    v.lon,
    v.bearing,
    v.low_floor,
    v.ingested_at::date             AS snapshot_date,
    v.ingested_at
FROM {{ source('bronze', 'vehicle_positions') }} v
LEFT JOIN {{ source('reference', 'gtfs_routes') }} r
    ON  r.route_short_name = v.line_number
    AND r.operator         = 'TLT'
    AND (
        (v.line_type = 3 AND r.route_type = 0)   -- tram
        OR
        (v.line_type = 2 AND r.route_type = 3)   -- bus
    )
LEFT JOIN {{ source('reference', 'vehicle_models') }} m
    ON  m.operator_code  = 'TLT'
    AND m.line_type_code = v.line_type
    AND m.active         = TRUE