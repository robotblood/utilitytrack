# UtilityTrack — Nebraska Utility Rate Tracker

Tracks how utility costs affect different groups: which decisions, events and conditions
raise or lower the cost of living, and who carries it, broken down by neighborhood,
demographics and household income.

## Setup
    python3 -m venv .venv && source .venv/bin/activate
    pip install -e ".[dev]"        # core CLI is stdlib-only; [web] FastAPI, [geo] shapely/pyshp, [dev] all + tests/lint
    cp .env.example .env           # add CENSUS_API_KEY

## Web app
    python -m rate_tracker serve --reload     # http://127.0.0.1:8000

- `/` rate timeline (filter by utility, service, customer class)
- `/actions/<id>` one rate action with its cost drivers and sources
- `/income` household income share by census tract (after running `census-income`)
- `/neighborhoods` renter share, income, energy burden (owner vs renter), 65+ households, by neighborhood / ZIP / tract
- `/bill` itemized monthly bill from a tariff, and its share of a household income
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
Get a free key at https://api.census.gov/data/key_signup.html and put it in `.env` as
`CENSUS_API_KEY` (the CLI reads `.env` itself; a shell export wins), then:

    python3 -m rate_tracker census-income --year 2024

Writes `data/geo_income_tracts.json` (all 16 Census ranges, plus six groups: <$20k, $20–30k, $30–50k, $50–75k, $75–125k, $125k+, each with count, margin of error and share)
and keeps the untouched API response beside it.

Logs go to `logs/tracker.jsonl` (one JSON object per line).

## Neighborhood pipeline: who carries utility costs
Census tracts are the smallest areas with reliable tenure, income and utility-cost data, so
everything starts there and is rolled up to named neighborhoods (and ZIP codes) by area overlay.

1. **Tract profiles** (ACS 5-year, Douglas + Sarpy) → `data/acs_tracts.json`

       python -m rate_tracker acs-profiles --year 2024

   Owner/renter households, median income overall and by tenure, household size, householders 65+,
   race and Hispanic origin, income bins by tenure, and monthly electricity / gas / water-sewer
   cost bins. Variables are matched by their Census labels, so a layout change fails loudly.
   The untouched pull is kept as `data/acs_raw_<year>.json`.

2. **Boundaries** go in `data/geo/`:
   - tracts: `cb_2024_31_tract_500k.zip` from https://www2.census.gov/geo/tiger/GENZ2024/shp/
   - neighborhoods / neighborhood associations: GeoJSON or zipped shapefile (source still to pick)
   - ZIP codes: Census ZCTA file, e.g. `cb_2020_us_zcta520_500k.zip` from https://www2.census.gov/geo/tiger/GENZ2020/shp/

3. **Crosswalk + rollup** (one per boundary layer)

       python -m rate_tracker crosswalk neighborhoods --areas data/geo/neighborhoods.geojson --id-field NAME
       python -m rate_tracker rollup neighborhoods
       python -m rate_tracker crosswalk zcta --areas data/geo/cb_2020_us_zcta520_500k.zip --id-field ZCTA5CE20
       python -m rate_tracker rollup zcta

   Writes `data/areas_<layer>.json`. Counts are split by the share of each tract's area in each
   neighborhood; medians are re-estimated from the combined bins.

**Energy burden** = median monthly electricity + gas cost × 12 ÷ median household income
(>6% high, >10% severe). "Elec. in rent" is the share of households whose electricity is
included in rent or fees, a cost that is hidden but still paid, mostly by renters.

**Bills:** `data/tariffs.json` holds rate schedules (service charge, seasonal per-unit blocks,
riders such as FPPA, sources, verification flag).

    python -m rate_tracker bill oppd-rate-110-2026 1000 --month 7

## Path to deployment
JSON → Notion (import `exports/*.csv`) → PostgreSQL (`sql/schema.sql`) or FileMaker.

## Known gaps
- Tariffs: only OPPD Rate 110 is loaded, from a third-party snapshot and flagged `needs_verification`
  (service charge vs minimum bill, summer months, block tiers, FPPA). MUD gas and water schedules are not loaded yet.
- Neighborhood boundaries: no official free Omaha neighborhood-association layer found yet.
- ACS does not split utility costs by tenure; owner/renter burdens differ only on the income side.
  DOE's LEAD tool (tract-level burden by income and tenure) would fill this.
- Area rollups assume households are spread evenly across each tract (block-level population weighting would be better)
  and do not carry margins of error.
- OPPD 2024 class splits beyond residential, and 2022 approval status, need confirmation.
- 2027 proposals (OPPD and MUD typically present in November) are not out yet.
- 2017–2021 history not yet loaded.
