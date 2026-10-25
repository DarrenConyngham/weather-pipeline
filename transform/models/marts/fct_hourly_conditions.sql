-- Hourly conditions per location. Weather only for now; air quality is joined
-- on (location_id, observed_at_utc) in phase 2.

select
    location_id,
    observed_at_utc,
    -- Treat the naive value as UTC, then express it as Cape Town wall-clock time.
    timezone('Africa/Johannesburg', timezone('UTC', observed_at_utc)) as observed_at_local,
    temperature_c,
    relative_humidity_pct,
    precipitation_mm,
    wind_speed_kmh,
    wind_direction_deg,
    wind_gusts_kmh,
    cloud_cover_pct,
    pressure_msl_hpa,
    ingested_at_utc
from {{ ref('int_weather_hourly_latest') }}
