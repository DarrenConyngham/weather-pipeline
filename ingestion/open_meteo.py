"""Open-Meteo API client: building requests and wrapping responses.

Request-building and record-wrapping are pure functions so they can be unit
tested without the network. The only function that does I/O is `fetch`.
"""

from datetime import datetime
from typing import Any

import httpx


def build_params(location: dict, hourly_vars: list[str], past_days: int) -> dict[str, Any]:
    """Query parameters for a 'recent data' request for one location."""
    return {
        "latitude": location["latitude"],
        "longitude": location["longitude"],
        "hourly": ",".join(hourly_vars),
        "timezone": "UTC",
        "past_days": past_days,
        "forecast_days": 0,
    }


def fetch(client: httpx.Client, url: str, params: dict[str, Any]) -> tuple[str, dict]:
    """GET the endpoint and return (requested_url, parsed JSON).

    Raises on any non-2xx status so the run fails loudly. Retries with
    backoff and response-shape validation arrive in phase 2.
    """
    response = client.get(url, params=params)
    response.raise_for_status()
    return str(response.request.url), response.json()


def build_raw_record(
    location_id: str, requested_url: str, ingested_at: datetime, response: dict
) -> dict:
    """Wrap the untouched API response with the metadata the raw zone requires."""
    return {
        "location_id": location_id,
        "requested_url": requested_url,
        "ingested_at_utc": ingested_at.isoformat(),
        "response": response,
    }
