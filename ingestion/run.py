"""CLI entrypoint: fetch Open-Meteo data and land it in the raw zone.

uv run --env-file .env python -m ingestion.run --dataset all
uv run --env-file .env python -m ingestion.run --dataset weather --location cpt_cbd
"""

import argparse
import logging
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

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    # httpx logs every request at INFO; our "wrote ..." lines already cover that.
    logging.getLogger("httpx").setLevel(logging.WARNING)

    # One timestamp per run, so every file from the same run shares it.
    ingested_at = datetime.now(UTC).replace(microsecond=0)

    # A failure in one dataset/location doesn't stop the others: we keep as much
    # good data as possible, then exit non-zero so the scheduled run still goes red.
    failures = []
    with httpx.Client(timeout=30) as client:
        for dataset_name, dataset in datasets.items():
            for location in locations:
                label = f"{dataset_name}/{location['location_id']}"
                params = open_meteo.build_params(location, dataset["hourly"], args.past_days)
                try:
                    requested_url, response = open_meteo.fetch(client, dataset["url"], params)
                    # Validate before writing: the raw zone is immutable, so bad data would stay.
                    open_meteo.validate_response(response, dataset["hourly"])
                except (open_meteo.FetchError, open_meteo.InvalidResponseError) as exc:
                    print(f"FAILED {label}: {exc}", file=sys.stderr)
                    failures.append(label)
                    continue
                record = open_meteo.build_raw_record(
                    location["location_id"], requested_url, ingested_at, response
                )
                key = storage.raw_key(dataset_name, location["location_id"], ingested_at)
                path = storage.write_raw(data_root, key, record)
                print(f"wrote {path} ({len(response['hourly']['time'])} hours)")

    if failures:
        print(
            f"{len(failures)} of {len(datasets) * len(locations)} fetches failed: "
            f"{', '.join(failures)}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
