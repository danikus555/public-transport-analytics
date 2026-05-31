-- =============================================================
-- silver.elron_positions
-- Enriches Elron bronze data with fuel type from reference
-- =============================================================

SELECT
    e.reis,
    e.liin,
    'train'                         AS transport_type,
    COALESCE(lt.fuel_type, 'diesel') AS fuel_type,
    lt.model,
    e.kiirus,
    e.lat,
    e.lon,
    e.suund,
    e.erinevus                      AS delay_min,
    e.reisi_staatus,
    e.viimane_peatus,
    e.ingested_at
FROM {{ source('bronze', 'elron_positions') }} e
LEFT JOIN {{ source('reference', 'elron_line_types') }} lt
    ON lt.liin = e.liin