# CLAUDE.md

## Project overview

**Cape Town Weather & Air Quality Pipeline**: a small end-to-end batch data pipeline built as a data engineering learning project.

It pulls hourly weather and air quality data for a handful of Cape Town locations from the free Open-Meteo APIs. It lands the raw responses in S3, models them with dbt and DuckDB, and publishes a static dashboard. Everything runs on a schedule in GitHub Actions. There are no servers, and the running cost should be close to zero.

**Goals, in priority order:**
1. Learn core data engineering patterns properly: idempotent loads, raw/staged/curated layers, incremental processing, data testing, orchestration, CI, and infrastructure hygiene. Focus on teaching me the skills along the way.
2. Keep it cheap and low-maintenance. It should run unattended for months.
3. Produce a dashboard worth looking at.

## How to work with me on this repo

- This is a learning project. When you make a design choice, explain why, and mention the main alternative.
- Prefer the simplest thing that works. Don't add new services, frameworks or paid tools without asking first.
- Ask before adding a dependency.
- Keep changes small and reviewable. Do one concern per change.
- Never commit secrets, credentials or `.env` files.
- When something is a judgment call, ask me rather than guessing.

## Architecture

```
Open-Meteo APIs ──▶ Python ingestion ──▶ S3 raw zone (gzipped JSON, immutable)
                                              │
                                              ▼
                                dbt + DuckDB (staging → intermediate → marts)
                                              │
                                              ▼
                                 S3 curated zone (Parquet) ──▶ Evidence dashboard
                                                                (static site, GitHub Pages)

Orchestration: GitHub Actions (daily cron + manual trigger)
```

### Stack
- **Language:** Python 3.12, managed with `uv`.
- **Ingestion:** plain Python using `httpx` and `boto3`. No ingestion framework.
- **Storage:** an S3 bucket with `raw/` and `curated/` prefixes. Local development uses a local folder instead (see `DATA_ROOT`).
- **Transformation:** dbt Core with the `dbt-duckdb` adapter. DuckDB reads from S3 through its `httpfs` extension.
- **Data quality:** dbt tests and source freshness checks.
- **Dashboard:** Evidence, built as a static site and deployed to GitHub Pages.
- **Orchestration and CI:** GitHub Actions.
- **Linting:** `ruff` for Python and `sqlfluff` (DuckDB dialect) for SQL.

## Data sources

All sources are free Open-Meteo APIs, so no API key is needed. Be polite: fetch all locations in one daily run and don't hammer the APIs.

| Dataset | Endpoint | Hourly variables |
|---|---|---|
| Weather | `https://api.open-meteo.com/v1/forecast` | `temperature_2m`, `relative_humidity_2m`, `precipitation`, `wind_speed_10m`, `wind_direction_10m`, `wind_gusts_10m`, `cloud_cover`, `pressure_msl` |
| Air quality | `https://air-quality-api.open-meteo.com/v1/air-quality` | `pm10`, `pm2_5`, `nitrogen_dioxide`, `ozone`, `sulphur_dioxide`, `carbon_monoxide`, `european_aqi`, `us_aqi` |
| Weather history (backfills only) | `https://archive-api.open-meteo.com/v1/archive` | same as Weather, where available |

- Always request `timezone=UTC`. All timestamps are stored in UTC and converted to `Africa/Johannesburg` only in marts and the dashboard.
- The daily run uses `past_days=2` (with `forecast_days=0` where supported). Each run therefore overlaps the previous one. Recent values can be revised, and the staging layer resolves this (see "Key design rules").
- Check the Open-Meteo docs before changing variables. Names differ slightly between endpoints, and history depth varies by dataset.

### Locations

Locations live in `config/locations.yml` and are also loaded as a dbt seed. They are the single source of truth: ingestion and dbt both read from them.

```yaml
- location_id: cpt_cbd
  name: Cape Town CBD
  latitude: -33.9249
  longitude: 18.4241
- location_id: newlands
  name: Newlands
  latitude: -33.9760
  longitude: 18.4620
- location_id: muizenberg
  name: Muizenberg
  latitude: -34.1083
  longitude: 18.4695
```

## Repository layout

```
.
├── CLAUDE.md
├── README.md                  # architecture diagram, setup, how to run
├── pyproject.toml
├── .env.example               # documents env vars; the real .env is gitignored
├── config/
│   └── locations.yml
├── ingestion/
│   ├── __init__.py
│   ├── open_meteo.py          # API client: building requests, retries, response validation
│   ├── storage.py             # write/read to local folder or S3, chosen by DATA_ROOT
│   └── run.py                 # CLI entrypoint
├── tests/                     # pytest; mock HTTP calls, never hit the real API in tests
├── transform/                 # dbt project
│   ├── dbt_project.yml
│   ├── profiles.yml           # uses env vars only, no secrets
│   ├── seeds/locations.csv
│   └── models/
│       ├── staging/           # stg_open_meteo__weather_hourly, stg_open_meteo__air_quality_hourly
│       ├── intermediate/      # int_weather_hourly_latest, int_air_quality_hourly_latest
│       └── marts/             # dim_locations, fct_hourly_conditions, fct_daily_conditions
├── dashboard/                 # Evidence project
└── .github/workflows/
    ├── pipeline.yml           # scheduled: ingest → dbt build → publish dashboard
    ├── backfill.yml           # manual: ingest a date range
    └── ci.yml                 # on pull request: lint, pytest, dbt build against fixture data
```

## Storage layout

`DATA_ROOT` is either a local path (for example `./data`) or `s3://<bucket>/weather-pipeline`.

```
{DATA_ROOT}/raw/open_meteo/{dataset}/ingest_date=YYYY-MM-DD/{location_id}_{run_ts}.json.gz
{DATA_ROOT}/curated/{model_name}.parquet
```

- **The raw zone is append-only and immutable.** Never overwrite or delete raw files. Each file holds the full API response plus metadata: `location_id`, `requested_url`, `ingested_at_utc`.
- **The curated zone is fully rebuilt by dbt.** Use dbt-duckdb `external` materialization for marts. The data volume is tiny (5 locations × 24 hours × 365 days is roughly 44k rows per dataset per year), so full rebuilds are fine. Don't introduce incremental models until full rebuilds become a real problem. If we add them later, it should be as an explicit learning exercise.

## Key design rules

1. **Idempotency.** Re-running the pipeline for the same day must not create duplicate rows in marts. Raw data may hold duplicates; dedupe happens in the intermediate layer.
2. **Latest value wins.** The grain is `(location_id, observed_at_utc)` per dataset. When several raw records exist for the same key, keep the row with the latest `ingested_at_utc`.
3. **UTC everywhere** until the marts. Marts carry both `observed_at_utc` and `observed_at_local`.
4. **Fail loudly.** Ingestion should exit non-zero on HTTP errors, retrying 3 times with backoff before giving up. It should also fail if a response doesn't match the expected shape (missing `hourly`, arrays of different lengths). A failed run should turn the GitHub Actions run red.
5. **Config over code.** Locations and variable lists come from config, not from hard-coded values.
6. **Small, pure functions** in ingestion, so they're easy to unit test. Keep I/O at the edges.

## Data modelling

- **Staging:** one model per source dataset. It reads raw JSON with DuckDB `read_json`, unnests the parallel `hourly` arrays into one row per hour, renames columns to snake_case with units in the name (for example `temperature_c`, `wind_speed_kmh`, `pm2_5_ugm3`), and casts types. No business logic here.
- **Intermediate:** dedupe to the latest record per key.
- **Marts:**
  - `dim_locations` comes from the seed.
  - `fct_hourly_conditions` joins weather and air quality on `(location_id, observed_at_utc)`.
  - `fct_daily_conditions` holds daily min/max/avg temperature, total rain, max gust, average and max PM2.5, worst AQI, and the count of hours with an AQI above threshold. It's aggregated on the local (SAST) date.

### Tests (the minimum for every model)
- `unique` and `not_null` on the grain columns. Use `dbt_utils.unique_combination_of_columns` for composite keys.
- `relationships` from fact tables to `dim_locations`.
- Plausible value ranges using `dbt_utils.accepted_range`:
  - temperature between -10 and 50 °C
  - humidity between 0 and 100
  - precipitation of 0 or more
  - AQI and pollutant values of 0 or more
- Source freshness: warn after 36 hours without new raw data, error after 72 hours.

## Commands

```bash
uv sync                                                    # install dependencies
cp .env.example .env                                       # then set DATA_ROOT=./data for local work

uv run python -m ingestion.run --dataset all --past-days 2            # daily-style run
uv run python -m ingestion.run --dataset weather --start 2026-01-01 --end 2026-01-31   # backfill

uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run sqlfluff lint transform/models

uv run dbt deps  --project-dir transform --profiles-dir transform
uv run dbt build --project-dir transform --profiles-dir transform    # runs models + tests
uv run dbt source freshness --project-dir transform --profiles-dir transform
```

## Environment variables

| Variable | Purpose |
|---|---|
| `DATA_ROOT` | Local path or `s3://bucket/prefix` |
| `AWS_REGION` | Use `af-south-1` (Cape Town) or another region, but be consistent |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | Local development only. In GitHub Actions, prefer OIDC (see phase 4) |

In GitHub Actions, credentials come from repository secrets or an assumed IAM role. They never come from files.

## AWS and cost guardrails

- Use one S3 bucket with public access blocked, versioning on, and a lifecycle rule moving `raw/` to cheaper storage after 90 days.
- Use a dedicated IAM principal for the pipeline, scoped to this bucket only (`s3:GetObject`, `s3:PutObject`, `s3:ListBucket`). Never use root or admin credentials.
- Set an AWS Budget alert at a small monthly amount.
- Don't add other AWS services without asking.

## Build phases

Work through these phases in order, and don't skip ahead.

- [ ] **Phase 1: walking skeleton.** Ingest one dataset for one location to a local `DATA_ROOT`, then build one staging model, one mart and one chart.
- [ ] **Phase 2: complete and robust.** Add all locations and both datasets, retries, response validation, the dedupe layer, unit tests and dbt tests.
- [ ] **Phase 3: run in the cloud.** Switch `DATA_ROOT` to S3. Set up `pipeline.yml` on a daily cron (around 04:00 UTC) plus `workflow_dispatch`, set up `ci.yml`, and deploy the dashboard to GitHub Pages.
- [ ] **Phase 4: production habits.** Replace access keys with GitHub OIDC and an IAM role, add failure notifications and freshness alerts, add a backfill workflow, define the AWS resources in Terraform, and polish the README with an architecture diagram.
- [ ] **Stretch goals:** add incremental dbt models, compare the forecast API with the archive API (ERA5) for the same hours, add another source (for example a South African weather or air quality feed), or port the pipeline to Option B (Lambda, EventBridge and Athena).