-- =============================================================
-- gold.fleet_summary
-- Vehicle fleet overview from reference data
-- Shows all models with consumption and vehicle count
--
-- Sprint 3 fix: removed CASE o.code WHEN 'Elron' THEN 'train' workaround.
-- Elron now uses line_type_code = 4 (train) in reference.vehicle_models,
-- so lt.name correctly returns 'train' for all Elron models.
-- =============================================================

SELECT
    o.name                          AS operator,
    lt.name                         AS transport_type,
    lt.name_et                      AS transport_type_et,
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