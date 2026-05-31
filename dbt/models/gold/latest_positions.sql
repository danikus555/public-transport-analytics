-- =============================================================
-- gold.latest_positions
-- Latest GPS position for each active vehicle
-- Updated every dbt run (~5 min)
-- =============================================================

SELECT DISTINCT ON (vehicle_id)
    vehicle_id,
    line_number,
    transport_type,
    fuel_type,
    destination,
    operator,
    lat,
    lon,
    bearing,
    low_floor,
    ingested_at
FROM {{ ref('vehicle_positions') }}
ORDER BY vehicle_id, ingested_at DESC