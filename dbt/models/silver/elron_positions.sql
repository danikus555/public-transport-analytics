-- =============================================================
-- silver.elron_positions
-- Enriches Elron bronze data with fuel type, consumption, route km
--
-- Fixes vs original:
--   1. liin normalised before join: "Tartu-Tallinn" → "Tartu - Tallinn"
--      handles API inconsistency (spaces around dash)
--   2. Reverse route fallback: "Keila - Tallinn" tries route_distances
--      for "Tallinn - Keila" when direct match is NULL
--   3. consumption and vehicle_model joined from vehicle_models
--   4. avg_round_trip_km from gold.route_distances for GTFS km
-- =============================================================

SELECT
    e.reis,
    e.liin                                              AS liin_raw,
    {{ normalise_liin('e.liin') }}                      AS liin,
    'train'                                             AS transport_type,
    COALESCE(elt.fuel_type, 'diesel')                   AS fuel_type,
    elt.model                                           AS vehicle_model,

    -- Consumption from vehicle_models (L/100km diesel, kWh/100km electric)
    vm.consumption,
    vm.consumption_unit,

    e.kiirus,
    e.lat,
    e.lon,
    e.suund,
    e.erinevus                                          AS delay_min,
    e.reisi_staatus,
    e.viimane_peatus,
    e.asukoha_uuendus,
    e.ingested_at,

    -- Route distance from GTFS shapes
    -- Primary: match normalised liin directly (e.g. "Tallinn - Keila")
    -- Fallback: try reversed liin (e.g. "Keila - Tallinn" → "Tallinn - Keila")
    COALESCE(
        rd.avg_round_trip_km,
        rd_rev.avg_round_trip_km
    )                                                   AS avg_round_trip_km,

    COALESCE(
        rd.avg_one_way_km,
        rd_rev.avg_one_way_km
    )                                                   AS avg_one_way_km

FROM {{ source('bronze', 'elron_positions') }} e

-- Join on normalised liin: fixes "Tartu-Tallinn" → "Tartu - Tallinn"
LEFT JOIN {{ source('reference', 'elron_line_types') }} elt
    ON elt.liin = {{ normalise_liin('e.liin') }}

-- Consumption: match operator + model from elron_line_types
LEFT JOIN {{ source('reference', 'vehicle_models') }} vm
    ON  vm.operator_code = 'Elron'
    AND vm.line_type_code = 4
    AND vm.model         = elt.model
    AND vm.active        = TRUE

-- Primary route distance: direct liin match
LEFT JOIN {{ ref('route_distances') }} rd
    ON  rd.route_long_name = {{ normalise_liin('e.liin') }}
    AND rd.operator        = 'Elron'

-- Reverse route fallback:
-- "Keila - Tallinn" has no GTFS shape — try "Tallinn - Keila"
-- Splits on " - ", reverses parts: "A - B" → "B - A"
LEFT JOIN {{ ref('route_distances') }} rd_rev
    ON  rd.avg_round_trip_km IS NULL
    AND rd_rev.route_long_name = CONCAT(
            TRIM(SPLIT_PART({{ normalise_liin('e.liin') }}, ' - ', 2)),
            ' - ',
            TRIM(SPLIT_PART({{ normalise_liin('e.liin') }}, ' - ', 1))
        )
    AND rd_rev.operator        = 'Elron'