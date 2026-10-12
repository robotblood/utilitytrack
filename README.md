# UtilityTrack — Nebraska Utility Rate Tracker

Tracks how utility costs affect different groups: which decisions, events and conditions
raise or lower the cost of living, and who carries it, broken down by neighborhood,
demographics and household income.

## Setup
    python3 -m venv .venv && source .venv/bin/activate
    pip install -e ".[dev]"        # core CLI is stdlib-only; [web] adds FastAPI, [dev] adds tests/lint
    cp .env.example .env           # add CENSUS_API_KEY

## Web app
    python -m rate_tracker serve --reload     # http://127.0.0.1:8000

- `/` rate timeline (filter by utility, service, customer class)
- `/actions/<id>` one rate action with its cost drivers and sources
- `/income` household income share by census tract (after running `census-income`)
- `/api/...` JSON endpoints; interactive docs at `/docs`

## Coverage
Tracks OPPD (electric) and MUD (water, gas) rate actions in Omaha, each linked to the
cost drivers that explain why rates moved. Built to expand to LES, NPPD, Lincoln Water
and Black Hills Energy (listed as `planned` in `data/utilities.json`).

## Data (JSON is the source of truth for now)
- `data/rate_actions.json` — one record per utility/service/year; `changes` holds each class/metric.
- `data/cost_drivers.json` — causes (fuel, weather, load growth, regulation, infrastructure…), `up` or `down`.
- Every record carries `sources` and a `verification` flag.

## Commands
    python3 -m rate_tracker validate
    python3 -m rate_tracker timeline -u MUD -s gas
    python3 -m rate_tracker why oppd-2025
    python3 -m rate_tracker todo            # records still needing verification
    python3 -m rate_tracker export-csv exports
    pytest                  # or: python3 -m unittest discover -s tests -t .
    ruff check .

### Household income by census tract (Douglas + Sarpy)
Get a free key at https://api.census.gov/data/key_signup.html, then:

    export CENSUS_API_KEY=your_key
    python3 -m rate_tracker census-income --year 2024

Writes `data/geo_income_tracts.json` (all 16 Census ranges, plus six groups: <$20k, $20–30k, $30–50k, $50–75k, $75–125k, $125k+, each with count, margin of error and share)
and keeps the untouched API response beside it.

Logs go to `logs/tracker.jsonl` (one JSON object per line).

## Path to deployment
JSON → Notion (import `exports/*.csv`) → PostgreSQL (`sql/schema.sql`) or FileMaker.

## Known gaps
- Per-kWh / per-therm / per-CCF tariff values by rate code are not loaded yet; only average % changes.
- OPPD 2024 class splits beyond residential, and 2022 approval status, need confirmation.
- 2027 proposals (OPPD and MUD typically present in November) are not out yet.
- 2017–2021 history not yet loaded.
