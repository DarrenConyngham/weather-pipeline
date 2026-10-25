-- One row per location, hour and raw file. Duplicates across runs are expected
-- here; they are resolved in int_weather_hourly_latest.

with source as (
    select * from {{ source('open_meteo', 'weather') }}
),

unnested as (
    -- Unnesting several lists in one select zips them together in lockstep,
    -- which is exactly what Open-Meteo's parallel `hourly` arrays need.
    select
        location_id,
        ingested_at_utc,
        ingest_date,
        filename as source_file,
        unnest(response.hourly.time) as observed_at,
        unnest(response.hourly.temperature_2m) as temperature_2m,
        unnest(response.hourly.relative_humidity_2m) as relative_humidity_2m,
        unnest(response.hourly.precipitation) as precipitation,
        unnest(response.hourly.wind_speed_10m) as wind_speed_10m,
        unnest(response.hourly.wind_direction_10m) as wind_direction_10m,
        unnest(response.hourly.wind_gusts_10m) as wind_gusts_10m,
        unnest(response.hourly.cloud_cover) as cloud_cover,
        unnest(response.hourly.pressure_msl) as pressure_msl
    from source
)

select
    cast(location_id as varchar) as location_id,
    -- Requested with timezone=UTC, so this naive timestamp is UTC.
    strptime(observed_at, '%Y-%m-%dT%H:%M') as observed_at_utc,
    cast(temperature_2m as double) as temperature_c,
    cast(relative_humidity_2m as double) as relative_humidity_pct,
    cast(precipitation as double) as precipitation_mm,
    cast(wind_speed_10m as double) as wind_speed_kmh,
    cast(wind_direction_10m as double) as wind_direction_deg,
    cast(wind_gusts_10m as double) as wind_gusts_kmh,
    cast(cloud_cover as double) as cloud_cover_pct,
    cast(pressure_msl as double) as pressure_msl_hpa,
    cast(ingested_at_utc as timestamptz) as ingested_at_utc,
    cast(ingest_date as date) as ingest_date,
    source_file
from unnested
