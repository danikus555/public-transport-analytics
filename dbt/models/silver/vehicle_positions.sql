-- =============================================================
-- silver.vehicle_positions
-- Enriches bronze GPS data with GTFS transport type and fuel type
--
-- Materialization: INCREMENTAL (unique_key = id)
--   First run: full build from all bronze rows
--   Subsequent runs: only new rows since last ingested_at
--   Result: drops from ~245s to <1s per dbt run
--
-- NOTE: v.line_type is TLT GPS feed internal code:
--   2 = bus, 3 = tram
--   NOT GTFS route_type (0=tram, 2=train, 3=bus, 11=trolleybus)
-- =============================================================

WITH dominant_fuel AS (
    -- For each line_type, find the fuel_type with the most vehicles.
    -- Buses: dominant = gas (CNG fleet is majority)
    -- This gives one fuel_type per line_type, avoiding fan-out.
    SELECT DISTINCT ON (line_type_code)
        line_type_code,
        fuel_type_code              AS dominant_fuel_type
    FROM {{ source('reference', 'vehicle_models') }}
    WHERE operator_code = 'TLT'
      AND active        = TRUE
    ORDER BY line_type_code, vehicle_amount DESC NULLS LAST
)

SELECT
    v.id,
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

    -- bus fuel_type = 'mixed': GPS has no per-vehicle fuel info
    -- tram/trolleybus = electric (always)
    CASE r.route_type
        WHEN 0  THEN 'electric'
        WHEN 11 THEN 'electric'
        WHEN 3  THEN 'mixed'
        ELSE
            CASE v.line_type
                WHEN 3 THEN 'electric'
                WHEN 2 THEN 'mixed'
                ELSE 'mixed'
            END
    END                             AS fuel_type,

    -- Fix UTF-8 encoding issues from TLT GPS feed
    -- GPS feed serves latin-1 (ISO-8859-1) but stored as UTF-8
    -- Full Estonian character set replacement
    REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(
    REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(
        v.destination,
        'Ã¤', 'ä'),  -- a umlaut
        'Ã¶', 'ö'),  -- o umlaut
        'Ã¼', 'ü'),  -- u umlaut
        'Ãµ', 'õ'),  -- o tilde (Estonian)
        'Ã„', 'Ä'),  -- A umlaut
        'Ã–', 'Ö'),  -- O umlaut
        'Ãœ', 'Ü'),  -- U umlaut
        'Ã•', 'Õ'),  -- O tilde capital
        'Ã©', 'é'),  -- e acute
        'Ã ', 'à '), -- a grave (catches Ã followed by space/control)
        chr(194)||chr(181), 'µ'),  -- strip orphaned continuation bytes
        chr(194)||chr(160), ' ')   -- non-breaking space → regular space
                                AS destination,
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
        (v.line_type = 3 AND r.route_type = 0)
        OR
        (v.line_type = 2 AND r.route_type = 3)
    )

LEFT JOIN dominant_fuel df
    ON df.line_type_code = v.line_type

{% if is_incremental() %}
-- Incremental: only process rows newer than the last silver row
WHERE v.ingested_at > (SELECT MAX(ingested_at) FROM {{ this }})
{% endif %}