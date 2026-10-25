-- One row per location, hour and raw file. Duplicates across runs are expected
-- here; they are resolved in int_air_quality_hourly_latest.

with source as (
    select * from {{ source('open_meteo', 'air_quality') }}
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
        unnest(response.hourly.pm10) as pm10,
        unnest(response.hourly.pm2_5) as pm2_5,
        unnest(response.hourly.nitrogen_dioxide) as nitrogen_dioxide,
        unnest(response.hourly.ozone) as ozone,
        unnest(response.hourly.sulphur_dioxide) as sulphur_dioxide,
        unnest(response.hourly.carbon_monoxide) as carbon_monoxide,
        unnest(response.hourly.european_aqi) as european_aqi,
        unnest(response.hourly.us_aqi) as us_aqi
    from source
)

select
    cast(location_id as varchar) as location_id,
    -- Requested with timezone=UTC, so this naive timestamp is UTC.
    strptime(observed_at, '%Y-%m-%dT%H:%M') as observed_at_utc,
    -- All pollutants, carbon monoxide included, are reported in µg/m³.
    cast(pm10 as double) as pm10_ugm3,
    cast(pm2_5 as double) as pm2_5_ugm3,
    cast(nitrogen_dioxide as double) as nitrogen_dioxide_ugm3,
    cast(ozone as double) as ozone_ugm3,
    cast(sulphur_dioxide as double) as sulphur_dioxide_ugm3,
    cast(carbon_monoxide as double) as carbon_monoxide_ugm3,
    -- AQIs are unitless index values.
    cast(european_aqi as integer) as european_aqi,
    cast(us_aqi as integer) as us_aqi,
    cast(ingested_at_utc as timestamptz) as ingested_at_utc,
    cast(ingest_date as date) as ingest_date,
    source_file
from unnested
