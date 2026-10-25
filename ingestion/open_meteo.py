"""Open-Meteo API client: building requests, retries and response validation.

Request-building, validation and record-wrapping are pure functions so they can
be unit tested without the network. The only function that does I/O is `fetch`,
and it takes `sleep` as a parameter so tests can skip the real waits.
"""

import logging
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

import httpx

log = logging.getLogger(__name__)

# Open-Meteo hourly timestamps when requested with timezone=UTC; staging parses this format.
TIME_FORMAT = "%Y-%m-%dT%H:%M"
MAX_RETRY_AFTER_S = 60


class FetchError(RuntimeError):
    """The request failed for good: a non-retryable status, or retries ran out."""


class InvalidResponseError(ValueError):
    """The API answered, but not in the shape the raw zone and staging rely on."""


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


def fetch(
    client: httpx.Client,
    url: str,
    params: dict[str, Any],
    *,
    retries: int = 3,
    backoff_s: float = 1.0,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[str, dict]:
    """GET the endpoint and return (requested_url, parsed JSON).

    Network errors, 429 and 5xx are temporary, so they are retried up to
    `retries` times with exponential backoff (1 s, 2 s, 4 s by default), or
    the server's Retry-After on a 429. Any other 4xx means our request is wrong,
    so retrying can't help: it raises FetchError at once, with Open-Meteo's reason.
    """
    for attempt in range(retries + 1):
        wait = backoff_s * 2**attempt
        try:
            response = client.get(url, params=params)
        except httpx.TransportError as exc:
            problem = f"{type(exc).__name__}: {exc}"
        else:
            if response.is_success:
                try:
                    return str(response.request.url), response.json()
                except ValueError as exc:
                    raise InvalidResponseError(f"response is not JSON: {exc}") from exc
            if not is_retryable(response.status_code):
                raise FetchError(f"HTTP {response.status_code}: {error_reason(response)}")
            problem = f"HTTP {response.status_code}"
            wait = retry_after_s(response) or wait

        if attempt < retries:
            log.warning("  attempt %d failed (%s); retrying in %gs", attempt + 1, problem, wait)
            sleep(wait)

    raise FetchError(f"gave up after {retries} retries ({problem})")


def is_retryable(status_code: int) -> bool:
    """Too Many Requests and server errors are worth another try; other 4xx aren't."""
    return status_code == 429 or status_code >= 500


def retry_after_s(response: httpx.Response) -> float | None:
    """The server's requested wait in seconds, if it sent one we can use (capped)."""
    value = response.headers.get("Retry-After", "")
    return min(float(value), MAX_RETRY_AFTER_S) if value.isdigit() else None


def error_reason(response: httpx.Response) -> str:
    """Open-Meteo explains bad requests as {"error": true, "reason": "..."}."""
    try:
        return response.json()["reason"]
    except (ValueError, KeyError, TypeError):
        return response.text[:200] or response.reason_phrase


def validate_response(response: Any, hourly_vars: list[str]) -> None:
    """Raise InvalidResponseError unless the response has the shape staging relies on.

    Null values are allowed (they are real gaps in the data); missing keys,
    ragged arrays and non-UTC timestamps are not.
    """
    if not isinstance(response, dict):
        raise InvalidResponseError(f"expected a JSON object, got {type(response).__name__}")
    # Asking for timezone=UTC comes back named "GMT", so check the offset, not the name.
    if response.get("utc_offset_seconds") != 0:
        raise InvalidResponseError(
            f"timestamps are not UTC (utc_offset_seconds={response.get('utc_offset_seconds')})"
        )

    hourly = response.get("hourly")
    if not isinstance(hourly, dict):
        raise InvalidResponseError("missing 'hourly'")
    times = hourly.get("time")
    if not isinstance(times, list) or not times:
        raise InvalidResponseError("'hourly.time' is missing or empty")

    missing = [var for var in hourly_vars if var not in hourly]
    if missing:
        raise InvalidResponseError(f"missing hourly variables: {missing}")

    # Staging unnests these arrays in lockstep, so they must all be the same length.
    ragged = {
        var: len(hourly[var]) if isinstance(hourly[var], list) else type(hourly[var]).__name__
        for var in hourly_vars
        if not isinstance(hourly[var], list) or len(hourly[var]) != len(times)
    }
    if ragged:
        raise InvalidResponseError(f"arrays don't match {len(times)} timestamps: {ragged}")

    bad_times = [t for t in times if not _is_hour_timestamp(t)]
    if bad_times:
        raise InvalidResponseError(f"unexpected time format, e.g. {bad_times[:3]}")


def _is_hour_timestamp(value: Any) -> bool:
    try:
        datetime.strptime(value, TIME_FORMAT)
    except (TypeError, ValueError):
        return False
    return True


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
