-- Daily conditions per location, on the Cape Town local (SAST) date.
-- Grain: one row per (location_id, local_date).
--
-- Days at the edges of the data are partial (e.g. only 2 hours of today), so
-- every day carries its hour counts and is_complete_day; aggregates for a
-- partial day describe only the hours we have.

with hourly as (
    select * from {{ ref('fct_hourly_conditions') }}
),

daily as (
    select
        location_id,
        cast(observed_at_local as date) as local_date,
        count(*) as hours_observed,
        count(temperature_c) as weather_hours,
        count(european_aqi) as air_quality_hours,
        min(temperature_c) as min_temperature_c,
        max(temperature_c) as max_temperature_c,
        avg(temperature_c) as avg_temperature_c,
        sum(precipitation_mm) as total_precipitation_mm,
        max(wind_gusts_kmh) as max_wind_gusts_kmh,
        avg(pm2_5_ugm3) as avg_pm2_5_ugm3,
        max(pm2_5_ugm3) as max_pm2_5_ugm3,
        max(european_aqi) as worst_european_aqi,
        count(*) filter (
            where european_aqi >= {{ var('eaqi_poor_threshold') }}
        ) as hours_eaqi_poor_or_worse
    from hourly
    group by location_id, cast(observed_at_local as date)
)

select
    *,
    -- Africa/Johannesburg has no daylight saving, so a local day is always 24 hours.
    -- Complete means both datasets cover every hour.
    coalesce(weather_hours = 24 and air_quality_hours = 24, false) as is_complete_day
from daily
