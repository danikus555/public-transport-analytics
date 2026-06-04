-- =============================================================
-- gold.elron_delays
-- Elron train delay analysis from realtime API
-- One row per train per snapshot (deduplicated)
--
-- Source: silver.elron_positions
--   delay_min: positive = late, negative = early, 0/NULL = on time
--   reisi_staatus: 'plaaniline' | 'hilineb peatuses' | 'varajane'
--
-- Business questions:
--   - Which routes are most frequently delayed?
--   - Average delay by route and hour?
--   - How many trains late vs on time right now?
-- =============================================================

WITH deduplicated AS (
    -- One row per reis per 30s snapshot window
    -- Elron API returns same train multiple times if scraped during same interval
    SELECT DISTINCT ON (reis, ingested_at)
        reis,
        liin,
        fuel_type,
        vehicle_model,
        delay_min,
        reisi_staatus,
        viimane_peatus          AS last_stop,
        kiirus                  AS speed_kmh,
        ingested_at
    FROM {{ ref('elron_positions') }}
    WHERE ingested_at::date = CURRENT_DATE
      AND liin IS NOT NULL
    ORDER BY reis, ingested_at
)

SELECT
    reis,
    liin,
    fuel_type,
    vehicle_model,
    delay_min,
    reisi_staatus,

    CASE
        WHEN delay_min IS NULL          THEN 'unknown'
        WHEN delay_min <= 0             THEN 'on_time'
        WHEN delay_min BETWEEN 1 AND 5  THEN 'slight_delay'
        WHEN delay_min BETWEEN 6 AND 15 THEN 'delayed'
        ELSE                                 'severely_delayed'
    END                             AS delay_category,

    last_stop,
    speed_kmh,
    ingested_at::date               AS snapshot_date,
    EXTRACT(HOUR FROM ingested_at)::INT AS hour,
    ingested_at

FROM deduplicated