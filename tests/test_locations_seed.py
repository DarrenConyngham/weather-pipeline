"""config/locations.yml is the source of truth; the dbt seed is a copy that must not drift."""

import csv
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def test_dbt_seed_matches_config_locations():
    with (ROOT / "config" / "locations.yml").open() as f:
        config = yaml.safe_load(f)
    with (ROOT / "transform" / "seeds" / "locations.csv").open(newline="") as f:
        seed = list(csv.DictReader(f))

    def normalise(rows):
        return [
            (r["location_id"], r["name"], float(r["latitude"]), float(r["longitude"])) for r in rows
        ]

    assert normalise(seed) == normalise(config), (
        "transform/seeds/locations.csv differs from config/locations.yml; update the seed to match"
    )
