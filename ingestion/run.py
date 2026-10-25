"""CLI entrypoint: fetch Open-Meteo data and land it in the raw zone.

uv run --env-file .env python -m ingestion.run --dataset all
uv run --env-file .env python -m ingestion.run --dataset weather --location cpt_cbd
"""

import argparse
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx
import yaml

from ingestion import open_meteo, storage

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


def load_yaml(path: Path):
    with path.open() as f:
        return yaml.safe_load(f)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset", required=True, help="dataset name from config/datasets.yml, or 'all'"
    )
    parser.add_argument(
        "--location", action="append", help="location_id to fetch (repeatable; default: all)"
    )
    parser.add_argument("--past-days", type=int, default=2)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)

    data_root = os.environ.get("DATA_ROOT")
    if not data_root:
        sys.exit("DATA_ROOT is not set (copy .env.example to .env; run with --env-file .env)")

    datasets = load_yaml(CONFIG_DIR / "datasets.yml")
    if args.dataset != "all":
        if args.dataset not in datasets:
            sys.exit(f"Unknown dataset {args.dataset!r}; expected 'all' or {sorted(datasets)}")
        datasets = {args.dataset: datasets[args.dataset]}

    locations = load_yaml(CONFIG_DIR / "locations.yml")
    if args.location:
        unknown = set(args.location) - {loc["location_id"] for loc in locations}
        if unknown:
            sys.exit(f"Unknown location(s): {sorted(unknown)}")
        locations = [loc for loc in locations if loc["location_id"] in args.location]

    # One timestamp per run, so every file from the same run shares it.
    ingested_at = datetime.now(UTC).replace(microsecond=0)

    with httpx.Client(timeout=30) as client:
        for dataset_name, dataset in datasets.items():
            for location in locations:
                params = open_meteo.build_params(location, dataset["hourly"], args.past_days)
                requested_url, response = open_meteo.fetch(client, dataset["url"], params)
                record = open_meteo.build_raw_record(
                    location["location_id"], requested_url, ingested_at, response
                )
                key = storage.raw_key(dataset_name, location["location_id"], ingested_at)
                path = storage.write_raw(data_root, key, record)
                hours = len(response.get("hourly", {}).get("time", []))
                print(f"wrote {path} ({hours} hours)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
