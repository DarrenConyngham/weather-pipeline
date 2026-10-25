"""Tests for the dashboard's pure helpers (no DuckDB, no browser)."""

import pytest

from dashboard import build

NAMES = ["Cape Town CBD", "Newlands", "Muizenberg"]


def row(name, hour, temp):
    return {
        "location_name": name,
        "observed_at_local": f"2026-10-24T{hour:02d}:00",
        "temperature_c": temp,
    }


# --- European AQI bands -------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "band"),
    [
        (0, "Good"),
        (19, "Good"),
        (20, "Fair"),
        (59, "Moderate"),
        (100, "Extremely poor"),
        (250, "Extremely poor"),
    ],
)
def test_aqi_band_boundaries_belong_to_the_band_above(value, band):
    assert build.aqi_band(value) == band


def test_band_lines_show_reached_bands_plus_the_next_one_up():
    lines = build.band_lines(28)

    assert [line["band"] for line in lines] == ["Good", "Fair", "Moderate"]


def test_band_labels_sit_mid_band_and_the_top_band_gets_a_nominal_height():
    lines = {line["band"]: line["label_y"] for line in build.band_lines(150)}

    assert lines["Fair"] == 30
    assert lines["Extremely poor"] == 110


# --- temperature chart helpers -------------------------------------------------


def test_end_labels_that_would_collide_are_pushed_apart():
    rows = [row("A", 0, 10.0), row("A", 1, 16.0), row("B", 0, 20.0), row("B", 1, 16.0)]

    labels = build.end_labels(rows, chart_height=100, label_px=10)

    # Data range 10 °C over 100 px, so a 10 px gap is 1 °C.
    assert [lbl["label_y"] for lbl in labels] == [16.0, 17.0]
    assert all(lbl["observed_at_local"] == "2026-10-24T01:00" for lbl in labels)


def test_end_labels_far_apart_are_left_alone():
    rows = [row("A", 0, 10.0), row("B", 0, 20.0)]

    labels = build.end_labels(rows, chart_height=100, label_px=10)

    assert [lbl["label_y"] for lbl in labels] == [10.0, 20.0]


def test_end_labels_ignore_a_trailing_null():
    rows = [row("A", 0, 12.0), row("A", 1, None), row("B", 0, 20.0)]

    labels = {lbl["location_name"]: lbl for lbl in build.end_labels(rows, 100)}

    assert labels["A"]["observed_at_local"] == "2026-10-24T00:00"


def test_tile_colours_follow_config_order_when_a_location_is_missing():
    """Muizenberg must keep colour 3 even if Newlands has no data."""
    rows = [row("Cape Town CBD", 0, 15.0), row("Muizenberg", 0, 16.0)]

    summaries = build.summarise(rows, NAMES)

    assert [(s["name"], s["colour_slot"]) for s in summaries] == [
        ("Cape Town CBD", 1),
        ("Muizenberg", 3),
    ]


def test_table_keeps_hours_missing_from_either_dataset():
    rows = [row("Cape Town CBD", 0, 15.0)]
    aq_rows = [{"observed_at_local": "2026-10-24T01:00", "european_aqi": 28}]

    header, body = build.table_html(rows, ["Cape Town CBD"], aq_rows)

    assert header == "<th>Cape Town CBD (°C)</th><th>European AQI</th>"
    assert body.splitlines() == [
        "<tr><td>2026-10-24 00:00</td><td>15.0</td><td></td></tr>",
        "<tr><td>2026-10-24 01:00</td><td></td><td>28</td></tr>",
    ]
