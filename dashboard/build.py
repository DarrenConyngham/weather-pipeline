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
        -- The mart is a full outer join, so an hour can have air quality but no weather.
        where temperature_c is not null
        order by location_id, observed_at_local
    """
    cursor = duckdb.execute(query, [parquet_path])
    columns = [col[0] for col in cursor.description]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def summarise(rows: list[dict], names: list[str]) -> list[dict]:
    """Headline numbers for the stat tiles: one per location, in config order."""
    summaries = []
    for slot, name in enumerate(names, start=1):
        loc_rows = [r for r in rows if r["location_name"] == name]
        if not loc_rows:
            continue
        temps = [r["temperature_c"] for r in loc_rows if r["temperature_c"] is not None]
        latest = max(loc_rows, key=lambda r: r["observed_at_local"])
        summaries.append(
            {
                "name": name,
                "colour_slot": slot,  # matches the chart's colour, even if a location is missing
                "latest_temp": latest["temperature_c"],
                "latest_at": latest["observed_at_local"],
                "min_temp": min(temps),
                "max_temp": max(temps),
            }
        )
    return summaries


def end_labels(rows: list[dict], chart_height: int, label_px: int = 16) -> list[dict]:
    """One label per location at its last point, nudged apart so none overlap.

    Lines that finish at similar values would print their names on top of each
    other, so labels are sorted by value and pushed up until each sits at least
    `label_px` above the one below. The gap is converted from pixels to °C
    using the data range, which is close enough to the chart's y scale.
    """
    last: dict[str, dict] = {}
    for r in rows:
        if r["temperature_c"] is None:
            continue
        current = last.get(r["location_name"])
        if current is None or r["observed_at_local"] > current["observed_at_local"]:
            last[r["location_name"]] = r

    temps = [r["temperature_c"] for r in rows if r["temperature_c"] is not None]
    gap = (max(temps) - min(temps)) * label_px / chart_height

    labels = []
    for r in sorted(last.values(), key=lambda r: r["temperature_c"]):
        label_y = r["temperature_c"]
        if labels:
            label_y = max(label_y, labels[-1]["label_y"] + gap)
        labels.append(
            {
                "location_name": r["location_name"],
                "observed_at_local": r["observed_at_local"],
                "label_y": label_y,
            }
        )
    return labels


def build_chart_spec(rows: list[dict], names: list[str]) -> dict:
    """Vega-Lite spec: one temperature line per location, with a hover crosshair.

    `names` fixes the colour order to config order, so each location keeps its
    colour even when another location is missing from the data. Colours
    themselves are left out on purpose; the page injects them from its CSS so
    the chart follows light/dark mode.
    """
    hovered = {"condition": {"param": "hover", "empty": False, "value": 1}, "value": 0}
    y = {
        "field": "temperature_c",
        "type": "quantitative",
        "title": None,  # the card heading already says "Temperature (°C)"
        "scale": {"zero": False, "nice": True},
    }
    color = {
        "field": "location_name",
        "type": "nominal",
        "title": None,
        "scale": {"domain": names},
        "legend": {"orient": "top", "direction": "horizontal"},
    }
    height = 280
    return {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "width": "container",
        "height": height,
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
            {
                "mark": {"type": "line", "strokeWidth": 2},
                "encoding": {"y": y, "color": color},
            },
            {
                # Name each line at its end, so identity isn't colour alone.
                "data": {"values": end_labels(rows, height)},
                "mark": {"type": "text", "align": "left", "dx": 6},
                "encoding": {
                    "y": {"field": "label_y", "type": "quantitative"},
                    "text": {"field": "location_name"},
                },
            },
            {
                # Reshape to one row per hour so the tooltip lists every location.
                "transform": [
                    {
                        "pivot": "location_name",
                        "value": "temperature_c",
                        "groupby": ["observed_at_local"],
                    }
                ],
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
                        *(
                            {
                                "field": name,
                                "type": "quantitative",
                                "title": f"{name} (°C)",
                                "format": ".1f",
                            }
                            for name in names
                        ),
                    ],
                },
            },
            {
                "mark": {"type": "point", "filled": True, "size": 80},
                "encoding": {"y": y, "color": color, "opacity": hovered},
            },
        ],
    }


def tiles_html(summaries: list[dict]) -> str:
    """One stat tile per location. The swatch ties the tile to its chart line."""
    return "\n".join(
        f'<div class="card tile"><dt><span class="swatch" '
        f'style="background: var(--series-{s["colour_slot"]})"></span>{html.escape(s["name"])}</dt>'
        f"<dd>{s['latest_temp']:.1f} °C"
        f'<span class="note">at {s["latest_at"].replace("T", " ")} · '
        f"range {s['min_temp']:.1f} to {s['max_temp']:.1f} °C</span></dd></div>"
        for s in summaries
    )


def table_html(rows: list[dict], names: list[str]) -> tuple[str, str]:
    """(header cells, body rows) for the table view: one row per hour, one column per location."""
    by_hour: dict[str, dict[str, float]] = {}
    for r in rows:
        by_hour.setdefault(r["observed_at_local"], {})[r["location_name"]] = r["temperature_c"]

    def cell(value: float | None) -> str:
        return "" if value is None else f"{value:.1f}"

    header = "".join(f"<th>{html.escape(name)} (°C)</th>" for name in names)
    body = "\n".join(
        f"<tr><td>{html.escape(hour.replace('T', ' '))}</td>"
        + "".join(f"<td>{cell(temps.get(name))}</td>" for name in names)
        + "</tr>"
        for hour, temps in sorted(by_hour.items())
    )
    return header, body


def render_page(
    template: str,
    spec: dict,
    tiles: str,
    table: tuple[str, str],
    first_at: str,
    generated_at: datetime,
) -> str:
    # "</" inside an inline <script> would end it early, so escape it.
    spec_json = json.dumps(spec).replace("</", "<\\/")
    table_header, table_rows = table
    return Template(template).substitute(
        tiles=tiles,
        first_at=first_at.replace("T", " "),
        table_header=table_header,
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

    # Config order sets the colour and column order; names come from config too.
    with LOCATIONS_PATH.open() as f:
        locations = yaml.safe_load(f)
    names = [loc["name"] for loc in locations]
    name_by_id = {loc["location_id"]: loc["name"] for loc in locations}
    for r in rows:
        r["location_name"] = name_by_id[r["location_id"]]

    page = render_page(
        TEMPLATE_PATH.read_text(encoding="utf-8"),
        build_chart_spec(rows, names),
        tiles_html(summarise(rows, names)),
        table_html(rows, names),
        min(r["observed_at_local"] for r in rows),
        datetime.now(UTC),
    )
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(page, encoding="utf-8")
    print(f"wrote {OUTPUT_PATH.relative_to(Path.cwd())} ({len(rows)} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
