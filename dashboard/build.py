"""Build the static dashboard page from the curated marts.

uv run --env-file .env python dashboard/build.py

Reads fct_hourly_conditions with DuckDB, fills dashboard/template.html, and
writes dashboard/build/index.html. The chart is a Vega-Lite spec built here in
Python and drawn in the browser.
"""

import html
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from string import Template

import duckdb
import yaml

DASHBOARD_DIR = Path(__file__).resolve().parent
TEMPLATE_PATH = DASHBOARD_DIR / "template.html"
OUTPUT_PATH = DASHBOARD_DIR / "build" / "index.html"
LOCATIONS_PATH = DASHBOARD_DIR.parent / "config" / "locations.yml"


def load_hourly(parquet_path: str) -> list[dict]:
    """Rows for the chart, with local time as an ISO string the browser can parse."""
    query = """
        select
            location_id,
            strftime(observed_at_local, '%Y-%m-%dT%H:%M') as observed_at_local,
            temperature_c
        from read_parquet(?)
        order by location_id, observed_at_local
    """
    cursor = duckdb.execute(query, [parquet_path])
    columns = [col[0] for col in cursor.description]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def summarise(rows: list[dict]) -> dict:
    """Headline numbers for the stat tiles."""
    temps = [r["temperature_c"] for r in rows if r["temperature_c"] is not None]
    latest = max(rows, key=lambda r: r["observed_at_local"])
    return {
        "latest_temp": latest["temperature_c"],
        "latest_at": latest["observed_at_local"],
        "min_temp": min(temps),
        "max_temp": max(temps),
        "first_at": min(r["observed_at_local"] for r in rows),
    }


def build_chart_spec(rows: list[dict]) -> dict:
    """Vega-Lite spec: temperature line with a hover crosshair and tooltip.

    Colours are left out on purpose; the page injects them from its CSS so the
    chart follows light/dark mode.
    """
    hovered = {"condition": {"param": "hover", "empty": False, "value": 1}, "value": 0}
    y = {
        "field": "temperature_c",
        "type": "quantitative",
        "title": None,  # the card heading already says "Temperature (°C)"
        "scale": {"zero": False, "nice": True},
    }
    return {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "width": "container",
        "height": 280,
        "data": {"values": rows},
        "encoding": {
            "x": {
                "field": "observed_at_local",
                "type": "temporal",
                "title": None,
                "axis": {"format": "%a %H:%M", "tickCount": 8, "grid": False},
            }
        },
        "layer": [
            {"mark": {"type": "line", "strokeWidth": 2}, "encoding": {"y": y}},
            {
                # Invisible until hovered; `nearest` snaps to the closest hour.
                "params": [
                    {
                        "name": "hover",
                        "select": {
                            "type": "point",
                            "encodings": ["x"],
                            "nearest": True,
                            "on": "pointermove",
                            "clear": "pointerout",
                        },
                    }
                ],
                "mark": {"type": "rule", "strokeWidth": 1},
                "encoding": {
                    "opacity": hovered,
                    "tooltip": [
                        {
                            "field": "observed_at_local",
                            "type": "temporal",
                            "title": "Local time",
                            "format": "%a %d %b, %H:%M",
                        },
                        {
                            "field": "temperature_c",
                            "type": "quantitative",
                            "title": "Temperature (°C)",
                            "format": ".1f",
                        },
                    ],
                },
            },
            {
                "mark": {"type": "point", "filled": True, "size": 80},
                "encoding": {"y": y, "opacity": hovered},
            },
        ],
    }


def table_rows_html(rows: list[dict]) -> str:
    """<tr> rows for the accessible table view."""
    return "\n".join(
        f"<tr><td>{html.escape(r['observed_at_local'].replace('T', ' '))}</td>"
        f"<td>{r['temperature_c']:.1f}</td></tr>"
        for r in rows
    )


def render_page(
    template: str,
    spec: dict,
    summary: dict,
    location_name: str,
    table_rows: str,
    generated_at: datetime,
) -> str:
    # "</" inside an inline <script> would end it early, so escape it.
    spec_json = json.dumps(spec).replace("</", "<\\/")
    return Template(template).substitute(
        location_name=html.escape(location_name),
        latest_temp=f"{summary['latest_temp']:.1f}",
        latest_at=summary["latest_at"].replace("T", " "),
        min_temp=f"{summary['min_temp']:.1f}",
        max_temp=f"{summary['max_temp']:.1f}",
        first_at=summary["first_at"].replace("T", " "),
        table_rows=table_rows,
        chart_spec=spec_json,
        generated_at=f"{generated_at:%Y-%m-%d %H:%M} UTC",
    )


def main() -> int:
    data_root = os.environ.get("DATA_ROOT")
    if not data_root:
        sys.exit("DATA_ROOT is not set (copy .env.example to .env; run with --env-file .env)")

    rows = load_hourly(f"{data_root}/curated/fct_hourly_conditions.parquet")
    if not rows:
        sys.exit("fct_hourly_conditions is empty; run ingestion and dbt build first")

    # Phase 1 has a single location; the multi-location view comes in phase 2.
    with LOCATIONS_PATH.open() as f:
        names = {loc["location_id"]: loc["name"] for loc in yaml.safe_load(f)}
    location_name = ", ".join(sorted({names[r["location_id"]] for r in rows}))

    page = render_page(
        TEMPLATE_PATH.read_text(encoding="utf-8"),
        build_chart_spec(rows),
        summarise(rows),
        location_name,
        table_rows_html(rows),
        datetime.now(UTC),
    )
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(page, encoding="utf-8")
    print(f"wrote {OUTPUT_PATH.relative_to(Path.cwd())} ({len(rows)} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
