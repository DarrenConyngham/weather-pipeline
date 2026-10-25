"""End-to-end tests of the CLI with a fake API, a temporary config and a temporary DATA_ROOT."""

import gzip
import json

import httpx
import pytest
import yaml

from ingestion import run

LOCATIONS = [
    {"location_id": "good_place", "name": "Good", "latitude": -33.0, "longitude": 18.0},
    {"location_id": "bad_place", "name": "Bad", "latitude": -34.0, "longitude": 18.5},
]
DATASETS = {"weather": {"url": "https://example.test/v1/forecast", "hourly": ["a", "b"]}}


def fake_api(request: httpx.Request) -> httpx.Response:
    """Valid responses, except bad_place gets ragged arrays."""
    variables = request.url.params["hourly"].split(",")
    hourly = {"time": ["2026-10-24T00:00", "2026-10-24T01:00"]}
    hourly |= {var: [1.0, 2.0] for var in variables}
    if request.url.params["latitude"] == "-34.0":
        hourly["b"] = [1.0]
    return httpx.Response(200, json={"utc_offset_seconds": 0, "hourly": hourly})


@pytest.fixture
def project(tmp_path, monkeypatch):
    """Point the CLI at a temporary config, data root and fake API. Returns DATA_ROOT."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "locations.yml").write_text(yaml.safe_dump(LOCATIONS))
    (config_dir / "datasets.yml").write_text(yaml.safe_dump(DATASETS))
    monkeypatch.setattr(run, "CONFIG_DIR", config_dir)

    data_root = tmp_path / "data"
    monkeypatch.setenv("DATA_ROOT", str(data_root))

    real_client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(fake_api), **kw)
    )
    return data_root


def written_locations(data_root) -> list[str]:
    return sorted(p.name.split("_2026")[0] for p in data_root.rglob("*.json.gz"))


def test_a_failed_location_does_not_stop_the_others_but_the_run_fails(project, capsys):
    exit_code = run.main(["--dataset", "all"])

    assert exit_code == 1
    assert written_locations(project) == ["good_place"]
    err = capsys.readouterr().err
    assert "FAILED weather/bad_place: arrays don't match 2 timestamps" in err
    assert "1 of 2 fetches failed: weather/bad_place" in err


def test_a_clean_run_exits_zero_and_writes_raw_records(project):
    exit_code = run.main(["--dataset", "weather", "--location", "good_place"])

    assert exit_code == 0
    [path] = project.rglob("*.json.gz")
    with gzip.open(path, "rt", encoding="utf-8") as f:
        record = json.load(f)
    assert record["location_id"] == "good_place"
    assert set(record) == {"location_id", "requested_url", "ingested_at_utc", "response"}
    assert "timezone=UTC" in record["requested_url"]


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["--dataset", "nope"], "Unknown dataset 'nope'"),
        (["--dataset", "all", "--location", "nowhere"], "Unknown location"),
    ],
)
def test_bad_arguments_exit_with_a_message(project, argv, message):
    with pytest.raises(SystemExit, match=message):
        run.main(argv)


def test_missing_data_root_exits(project, monkeypatch):
    monkeypatch.delenv("DATA_ROOT")

    with pytest.raises(SystemExit, match="DATA_ROOT is not set"):
        run.main(["--dataset", "all"])
