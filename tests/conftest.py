"""Shared fixtures. Tests never hit the real API: HTTP goes through httpx.MockTransport."""

import httpx
import pytest


@pytest.fixture
def hourly_vars() -> list[str]:
    """The variables `good_response` contains."""
    return ["temperature_2m", "precipitation"]


@pytest.fixture
def good_response() -> dict:
    """A minimal valid Open-Meteo response for `hourly_vars`. A fresh copy per test."""
    return {
        "utc_offset_seconds": 0,
        "timezone": "GMT",  # what Open-Meteo actually returns for timezone=UTC
        "hourly": {
            "time": ["2026-10-24T00:00", "2026-10-24T01:00"],
            "temperature_2m": [15.1, None],  # nulls are real gaps and allowed
            "precipitation": [0.0, 0.2],
        },
    }


@pytest.fixture
def scripted_client():
    """Build a client whose fake server replies with each item in turn.

    Items are (status, json_body), (status, json_body, headers), or an exception
    to raise as if the network failed. Returns (client, list_of_requests_seen).
    """
    clients = []

    def make(*replies):
        queue = list(replies)
        seen = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            reply = queue.pop(0)
            if isinstance(reply, Exception):
                raise reply
            status, body, *rest = reply
            return httpx.Response(status, json=body, headers=rest[0] if rest else None)

        client = httpx.Client(transport=httpx.MockTransport(handler))
        clients.append(client)
        return client, seen

    yield make
    for client in clients:
        client.close()
