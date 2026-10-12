"""Household income by census tract from the ACS 5-year table B19001.

Uses the Census's own 16 income ranges and also rolls them up into six groups
that sit on Census boundaries (no estimation):

  under_20k  20_30k  30_50k  50_75k  75_125k  125k_plus

Both the 16 raw ranges and the six groups are written for each tract.
"""
import json
import math
import os
import urllib.parse
import urllib.request
from pathlib import Path

from .log import get_logger

log = get_logger()
API = "https://api.census.gov/data/{year}/acs/acs5"
STATE_NE = "31"
COUNTIES = {"055": "Douglas", "153": "Sarpy"}
BINS = [f"B19001_{i:03d}" for i in range(2, 18)]  # 16 brackets, <10k ... 200k+

# bracket index (0-15) -> list of (group, weight)
_EXACT = {**{i: [("under_20k", 1)] for i in (0, 1, 2)},
          **{i: [("20_30k", 1)] for i in (3, 4)},
          **{i: [("30_50k", 1)] for i in (5, 6, 7, 8)},
          **{i: [("50_75k", 1)] for i in (9, 10)},
          11: [("75_125k", 1)], 12: [("75_125k", 1)],
          **{i: [("125k_plus", 1)] for i in (13, 14, 15)}}
GROUPS = ["under_20k", "20_30k", "30_50k", "50_75k", "75_125k", "125k_plus"]
# Census labels for the 16 raw ranges, in table order
RANGES = ["<10k", "10-15k", "15-20k", "20-25k", "25-30k", "30-35k", "35-40k", "40-45k",
          "45-50k", "50-60k", "60-75k", "75-100k", "100-125k", "125-150k", "150-200k", "200k+"]


def fetch(year: int, api_key: str, counties=COUNTIES) -> list[dict]:
    """Call the Census API once per county; returns raw rows as dicts."""
    fields = ["NAME", "B19001_001E", "B19001_001M"] + [b + s for b in BINS for s in ("E", "M")]
    rows = []
    for fips in counties:
        q = urllib.parse.urlencode({"get": ",".join(fields), "for": "tract:*",
                                    "in": f"state:{STATE_NE} county:{fips}", "key": api_key})
        with urllib.request.urlopen(f"{API.format(year=year)}?{q}", timeout=60) as r:
            table = json.load(r)
        header, *data = table
        rows += [dict(zip(header, rec, strict=True)) for rec in data]
        log.info("census_fetch", extra={"ctx": {"year": year, "county": fips, "tracts": len(data)}})
    return rows


def regroup(row: dict) -> dict:
    """Keep the 16 Census ranges and roll them up into six groups.

    Group margins of error use root-sum-of-squares (Census's standard approximation).
    """
    est = {g: 0.0 for g in GROUPS}
    moe_sq = {g: 0.0 for g in GROUPS}
    raw = {}
    for i, var in enumerate(BINS):
        e = max(float(row[var + "E"]), 0)
        m = max(float(row.get(var + "M", 0) or 0), 0)  # negative MOE codes = not applicable
        raw[RANGES[i]] = int(e)
        for group, w in _EXACT[i]:
            est[group] += e * w
            moe_sq[group] += (m * w) ** 2
    total = float(row["B19001_001E"])
    geoid = STATE_NE + row["county"] + row["tract"]
    out = {"geoid": geoid, "name": row["NAME"], "county": COUNTIES.get(row["county"], row["county"]),
           "households": int(total), "ranges": raw}
    for g in GROUPS:
        out[f"hh_{g}"] = round(est[g], 1)
        out[f"moe_{g}"] = round(math.sqrt(moe_sq[g]), 1)
        out[f"share_{g}"] = round(est[g] / total, 4) if total else None
    return out


def build(rows: list[dict]) -> list[dict]:
    # Skip tracts with no households (parks, airport, water)
    return [regroup(r) for r in rows if float(r["B19001_001E"]) > 0]


def run(year: int, out_path: Path, api_key: str | None = None,
        raw_path: Path | None = None) -> list[dict]:
    """Fetch (or load a saved raw response), regroup and write JSON."""
    if raw_path:
        rows = json.loads(Path(raw_path).read_text())
    else:
        key = api_key or os.environ.get("CENSUS_API_KEY")
        if not key:
            raise SystemExit("Set CENSUS_API_KEY or pass --key (free: api.census.gov/data/key_signup.html)")
        rows = fetch(year, key)
        raw = out_path.with_name(f"census_b19001_raw_{year}.json")
        raw.write_text(json.dumps(rows))  # keep the untouched source for audit
    tracts = build(rows)
    out_path.write_text(json.dumps({"source": f"ACS {year} 5-year, table B19001", "groups": GROUPS,
                                    "ranges": RANGES, "tracts": tracts}, indent=1))
    log.info("census_income_written", extra={"ctx": {"tracts": len(tracts), "path": str(out_path)}})
    return tracts
