-- =============================================================
-- gold.fleet_summary
-- Vehicle fleet overview from reference data
-- Shows all models with consumption and vehicle count
-- =============================================================

SELECT
    o.name                          AS operator,
    CASE o.code
        WHEN 'Elron' THEN 'train'
        ELSE lt.name
    END                             AS transport_type,
    CASE o.code
        WHEN 'Elron' THEN 'rong'
        ELSE lt.name_et
    END                             AS transport_type_et,
    m.model,
    m.fuel_type_code                AS fuel_type,
    ft.name                         AS fuel_name,
    m.consumption,
    m.consumption_unit,
    m.vehicle_amount,
    m.active,
    m.valid_from
FROM {{ source('reference', 'vehicle_models') }} m
JOIN {{ source('reference', 'operators') }} o
    ON o.code = m.operator_code
JOIN {{ source('reference', 'line_types') }} lt
    ON lt.code = m.line_type_code
JOIN {{ source('reference', 'fuel_types') }} ft
    ON ft.code = m.fuel_type_code
WHERE m.active = TRUE
ORDER BY o.name, lt.code, m.model