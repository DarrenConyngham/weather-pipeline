-- Hourly conditions per location: weather and air quality on one row.
-- Grain: one row per (location_id, observed_at_utc).
--
-- A full outer join keeps every hour that either dataset has. If one dataset's
-- fetch fails or lags, its columns are NULL for those hours instead of the
-- other dataset's rows silently disappearing, so gaps stay visible.

with weather as (
    select * from {{ ref('int_weather_hourly_latest') }}
),

air_quality as (
    select * from {{ ref('int_air_quality_hourly_latest') }}
),

joined as (
    select
        -- On a full outer join either side's key can be NULL, so take whichever exists.
        coalesce(weather.location_id, air_quality.location_id) as location_id,
        coalesce(weather.observed_at_utc, air_quality.observed_at_utc) as observed_at_utc,
        weather.temperature_c,
        weather.relative_humidity_pct,
        weather.precipitation_mm,
        weather.wind_speed_kmh,
        weather.wind_direction_deg,
        weather.wind_gusts_kmh,
        weather.cloud_cover_pct,
        weather.pressure_msl_hpa,
        air_quality.pm10_ugm3,
        air_quality.pm2_5_ugm3,
        air_quality.nitrogen_dioxide_ugm3,
        air_quality.ozone_ugm3,
        air_quality.sulphur_dioxide_ugm3,
        air_quality.carbon_monoxide_ugm3,
        air_quality.european_aqi,
        air_quality.us_aqi,
        weather.ingested_at_utc as weather_ingested_at_utc,
        air_quality.ingested_at_utc as air_quality_ingested_at_utc
    from weather
    full outer join air_quality
        on
            weather.location_id = air_quality.location_id
            and weather.observed_at_utc = air_quality.observed_at_utc
)

select
    location_id,
    observed_at_utc,
    -- Treat the naive value as UTC, then express it as Cape Town wall-clock time.
    timezone('Africa/Johannesburg', timezone('UTC', observed_at_utc)) as observed_at_local,
    * exclude (location_id, observed_at_utc)
from joined
