from datetime import UTC, datetime

import httpx
import pytest

from ingestion import open_meteo

URL = "https://example.test/v1/forecast"


def fetch(client, sleeps: list[float]):
    """Call fetch with a fake sleep that records waits instead of waiting."""
    return open_meteo.fetch(client, URL, {}, sleep=sleeps.append)


# --- building requests and records ----------------------------------------


def test_build_params_requests_utc_recent_hours_only():
    location = {"location_id": "cpt_cbd", "latitude": -33.9, "longitude": 18.4}

    params = open_meteo.build_params(location, ["a", "b"], past_days=2)

    assert params == {
        "latitude": -33.9,
        "longitude": 18.4,
        "hourly": "a,b",
        "timezone": "UTC",
        "past_days": 2,
        "forecast_days": 0,
    }


def test_build_raw_record_wraps_response_untouched_with_metadata(good_response):
    ingested_at = datetime(2026, 10, 25, 4, 0, tzinfo=UTC)

    record = open_meteo.build_raw_record("cpt_cbd", URL, ingested_at, good_response)

    assert record == {
        "location_id": "cpt_cbd",
        "requested_url": URL,
        "ingested_at_utc": "2026-10-25T04:00:00+00:00",
        "response": good_response,
    }


# --- retries ----------------------------------------------------------------


def test_fetch_returns_url_and_json_on_success(scripted_client, good_response):
    client, seen = scripted_client((200, good_response))
    sleeps = []

    requested_url, body = fetch(client, sleeps)

    assert body == good_response
    assert requested_url == URL
    assert len(seen) == 1 and sleeps == []


def test_fetch_retries_server_errors_with_exponential_backoff(scripted_client, good_response):
    client, seen = scripted_client((503, {}), (500, {}), (200, good_response))
    sleeps = []

    _, body = fetch(client, sleeps)

    assert body == good_response
    assert len(seen) == 3
    assert sleeps == [1, 2]


def test_fetch_gives_up_after_three_retries(scripted_client):
    client, seen = scripted_client(*[(503, {})] * 4)
    sleeps = []

    with pytest.raises(open_meteo.FetchError, match=r"gave up after 3 retries \(HTTP 503\)"):
        fetch(client, sleeps)

    assert len(seen) == 4  # the first try plus 3 retries
    assert sleeps == [1, 2, 4]  # no pointless wait after the last attempt


def test_fetch_retries_network_errors(scripted_client, good_response):
    client, seen = scripted_client(httpx.ConnectTimeout("timed out"), (200, good_response))
    sleeps = []

    fetch(client, sleeps)

    assert len(seen) == 2 and sleeps == [1]


def test_fetch_honours_retry_after_on_429(scripted_client, good_response):
    client, _ = scripted_client((429, {}, {"Retry-After": "7"}), (200, good_response))
    sleeps = []

    fetch(client, sleeps)

    assert sleeps == [7]


def test_fetch_caps_a_huge_retry_after(scripted_client, good_response):
    client, _ = scripted_client((429, {}, {"Retry-After": "3600"}), (200, good_response))
    sleeps = []

    fetch(client, sleeps)

    assert sleeps == [open_meteo.MAX_RETRY_AFTER_S]


def test_fetch_fails_fast_on_client_error_with_open_meteos_reason(scripted_client):
    client, seen = scripted_client((400, {"error": True, "reason": "Invalid value: not_a_var"}))
    sleeps = []

    with pytest.raises(open_meteo.FetchError, match="HTTP 400: Invalid value: not_a_var"):
        fetch(client, sleeps)

    assert len(seen) == 1 and sleeps == []  # our request is wrong; retrying can't help


def test_fetch_logs_each_retry(scripted_client, good_response, caplog):
    client, _ = scripted_client((503, {}), (200, good_response))

    fetch(client, [])

    assert "attempt 1 failed (HTTP 503); retrying in 1s" in caplog.text


def test_fetch_rejects_a_success_that_is_not_json():
    client = httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, text="<html>"))
    )

    with pytest.raises(open_meteo.InvalidResponseError, match="not JSON"):
        fetch(client, [])


@pytest.mark.parametrize(
    ("status", "retryable"),
    [(400, False), (404, False), (429, True), (500, True), (503, True)],
)
def test_is_retryable(status, retryable):
    assert open_meteo.is_retryable(status) is retryable


# --- response validation ------------------------------------------------------


def test_validate_accepts_a_good_response_including_nulls(good_response, hourly_vars):
    open_meteo.validate_response(good_response, hourly_vars)  # does not raise


@pytest.mark.parametrize(
    ("break_it", "message"),
    [
        (lambda r: r.pop("hourly"), "missing 'hourly'"),
        (lambda r: r["hourly"].update(time=[]), "'hourly.time' is missing or empty"),
        (lambda r: r["hourly"].pop("time"), "'hourly.time' is missing or empty"),
        (
            lambda r: r["hourly"].pop("precipitation"),
            r"missing hourly variables: \['precipitation'\]",
        ),
        (lambda r: r["hourly"]["precipitation"].pop(), "arrays don't match 2 timestamps"),
        (lambda r: r["hourly"].update(precipitation=None), "arrays don't match 2 timestamps"),
        (lambda r: r.update(utc_offset_seconds=7200), "not UTC"),
        (lambda r: r.pop("utc_offset_seconds"), "not UTC"),
        (lambda r: r["hourly"].update(time=["2026-10-24 00:00", "x"]), "unexpected time format"),
    ],
    ids=[
        "no hourly",
        "empty time",
        "no time",
        "missing variable",
        "ragged arrays",
        "variable not a list",
        "non-UTC offset",
        "no offset",
        "bad time format",
    ],
)
def test_validate_rejects_bad_shapes(good_response, hourly_vars, break_it, message):
    break_it(good_response)

    with pytest.raises(open_meteo.InvalidResponseError, match=message):
        open_meteo.validate_response(good_response, hourly_vars)


def test_validate_rejects_a_non_object(hourly_vars):
    with pytest.raises(open_meteo.InvalidResponseError, match="expected a JSON object"):
        open_meteo.validate_response([], hourly_vars)
