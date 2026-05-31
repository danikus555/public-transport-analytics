-- =============================================================
-- gold.route_activity
-- Active vehicles per line per hour
-- =============================================================

SELECT
    line_number,
    transport_type,
    fuel_type,
    operator,
    snapshot_date,
    DATE_PART('hour', ingested_at)  AS hour,
    COUNT(DISTINCT vehicle_id)      AS vehicle_count
FROM {{ ref('vehicle_positions') }}
GROUP BY 1, 2, 3, 4, 5, 6