-- One row per location, from the seed (a copy of config/locations.yml).

select
    location_id,
    name as location_name,
    latitude,
    longitude
from {{ ref('locations') }}
