"""Writing raw files under DATA_ROOT.

Phase 1 supports a local DATA_ROOT only; S3 support arrives in phase 3.
"""

import gzip
import json
from datetime import datetime
from pathlib import Path


def raw_key(dataset: str, location_id: str, ingested_at: datetime) -> str:
    """Relative path of a raw file, partitioned by ingest date (Hive-style)."""
    run_ts = ingested_at.strftime("%Y%m%dT%H%M%SZ")
    partition = f"ingest_date={ingested_at:%Y-%m-%d}"
    return f"raw/open_meteo/{dataset}/{partition}/{location_id}_{run_ts}.json.gz"


def write_raw(data_root: str, key: str, record: dict) -> Path:
    """Write a record as gzipped JSON. Refuses to overwrite: the raw zone is immutable."""
    if data_root.startswith("s3://"):
        raise NotImplementedError("S3 storage arrives in phase 3; use a local DATA_ROOT for now")

    path = Path(data_root) / key
    path.parent.mkdir(parents=True, exist_ok=True)
    # Mode "x" fails if the file already exists, enforcing append-only at the filesystem level.
    with gzip.open(path, "xt", encoding="utf-8") as f:
        json.dump(record, f)
    return path
