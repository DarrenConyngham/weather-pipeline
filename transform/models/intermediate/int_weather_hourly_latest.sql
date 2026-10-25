-- Grain: one row per (location_id, observed_at_utc).
-- Each daily run overlaps the previous one, and Open-Meteo can revise recent
-- hours, so the most recently ingested value wins.

select *
from {{ ref('stg_open_meteo__weather_hourly') }}
qualify row_number() over (
    partition by location_id, observed_at_utc
    order by ingested_at_utc desc
) = 1
