# Cape Town Weather & Air Quality Pipeline

A small batch data pipeline: Open-Meteo APIs → raw zone (gzipped JSON) → dbt + DuckDB → static Evidence dashboard, orchestrated with GitHub Actions. See `CLAUDE.md` for the full design.

**Status:** Phase 1 (walking skeleton). Weather ingestion and the dbt models work against a local folder.

## Setup

```bash
uv sync
cp .env.example .env        # DATA_ROOT=./data for local work
mkdir -p data/curated       # DuckDB won't create the output folder for local Parquet files
```

## Run ingestion

```bash
uv run --env-file .env python -m ingestion.run --dataset weather --location cpt_cbd
```

Files land at `data/raw/open_meteo/weather/ingest_date=YYYY-MM-DD/{location_id}_{run_ts}.json.gz`.

## Run the dbt models

Run from the repo root (paths in `transform/profiles.yml` are relative to it):

```bash
uv run --env-file .env dbt build --project-dir transform --profiles-dir transform
```

Models: `stg_open_meteo__weather_hourly` (view) → `int_weather_hourly_latest` (view, latest ingest wins)
→ `fct_hourly_conditions` (written to `data/curated/fct_hourly_conditions.parquet`).
