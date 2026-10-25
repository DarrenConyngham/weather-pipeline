import gzip
import json
from datetime import UTC, datetime

import pytest

from ingestion import storage

INGESTED_AT = datetime(2026, 10, 25, 4, 5, 6, tzinfo=UTC)


def test_raw_key_is_hive_partitioned_by_ingest_date():
    key = storage.raw_key("weather", "cpt_cbd", INGESTED_AT)

    assert key == "raw/open_meteo/weather/ingest_date=2026-10-25/cpt_cbd_20261025T040506Z.json.gz"


def test_write_raw_writes_gzipped_json(tmp_path):
    record = {"location_id": "cpt_cbd", "response": {"hourly": {}}}

    path = storage.write_raw(str(tmp_path), "raw/a/b.json.gz", record)

    assert path == tmp_path / "raw/a/b.json.gz"
    with gzip.open(path, "rt", encoding="utf-8") as f:
        assert json.load(f) == record


def test_write_raw_never_overwrites(tmp_path):
    """The raw zone is immutable: a second write to the same key must fail."""
    storage.write_raw(str(tmp_path), "raw/a/b.json.gz", {"v": 1})

    with pytest.raises(FileExistsError):
        storage.write_raw(str(tmp_path), "raw/a/b.json.gz", {"v": 2})

    with gzip.open(tmp_path / "raw/a/b.json.gz", "rt", encoding="utf-8") as f:
        assert json.load(f) == {"v": 1}


def test_write_raw_rejects_s3_until_phase_3():
    with pytest.raises(NotImplementedError):
        storage.write_raw("s3://bucket/prefix", "raw/a/b.json.gz", {})
