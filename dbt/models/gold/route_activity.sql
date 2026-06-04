-- =============================================================
-- gold.route_activity
-- Active vehicles per line per hour
--
-- Covers last 7 days — enough for dashboard trend charts.
-- Rebuilt fully each run but only scans recent rows via index.
-- =============================================================

SELECT
    line_number,
    transport_type,
    fuel_type,
    operator,
    snapshot_date,
    DATE_PART('hour', ingested_at)::INT     AS hour,
    COUNT(DISTINCT vehicle_id)              AS vehicle_count
FROM {{ ref('vehicle_positions') }}
WHERE snapshot_date >= CURRENT_DATE - INTERVAL '7 days'
GROUP BY 1, 2, 3, 4, 5, 6