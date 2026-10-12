"""Tract profiles from the ACS 5-year: tenure, race/ethnicity, age, income by tenure, utility costs.

Variables are found by their Census *labels* (fetched from the API with each pull), not by
hard-coded codes, so a table that shifts between vintages fails loudly instead of silently
reading the wrong column.

Tables
  B19013  median household income
  B25119  median household income by tenure (owner / renter)
  B25003  tenure: owner vs renter households
  B25010  average household size by tenure
  B25007  tenure by age of householder (65+)
  B03002  race and Hispanic origin (population)
  B25118  tenure by household income (bins)
  B25132  monthly electricity costs (bins)
  B25133  monthly gas costs (bins)
  B25134  monthly water and sewer costs (bins)
"""
import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path

from .log import get_logger

log = get_logger()
API = "https://api.census.gov/data/{year}/acs/acs5"
STATE_NE = "31"
COUNTIES = {"055": "Douglas", "153": "Sarpy"}
MAX_VARS = 48  # API allows 50 per call; leave room for NAME

# metric -> (table, regex on the normalized label path). One label must match each.
SIMPLE = {
    "median_income":        ("B19013", r"^Median household income[^/]*$"),
    "median_income_owner":  ("B25119", r"^Median household income[^/]*(/Total)?/Owner occupied"),
    "median_income_renter": ("B25119", r"^Median household income[^/]*(/Total)?/Renter occupied"),
    "households":           ("B25003", r"^Total$"),
    "owner_hh":             ("B25003", r"^Total/Owner occupied$"),
    "renter_hh":            ("B25003", r"^Total/Renter occupied$"),
    "avg_hh_size_owner":    ("B25010", r"^Average household size[^/]*(/Total)?/Owner occupied$"),
    "avg_hh_size_renter":   ("B25010", r"^Average household size[^/]*(/Total)?/Renter occupied$"),
    "population":           ("B03002", r"^Total$"),
    "white_nh":             ("B03002", r"^Total/Not Hispanic or Latino/White alone$"),
    "black_nh":             ("B03002", r"^Total/Not Hispanic or Latino/Black or African American alone$"),
    "aian_nh":              ("B03002", r"^Total/Not Hispanic or Latino/American Indian and Alaska Native alone$"),
    "asian_nh":             ("B03002", r"^Total/Not Hispanic or Latino/Asian alone$"),
    "nhpi_nh":              ("B03002", r"^Total/Not Hispanic or Latino/Native Hawaiian and Other Pacific Islander alone$"),
    "other_nh":             ("B03002", r"^Total/Not Hispanic or Latino/Some other race alone$"),
    "multi_nh":             ("B03002", r"^Total/Not Hispanic or Latino/Two or more races$"),
    "hispanic":             ("B03002", r"^Total/Hispanic or Latino$"),
}
# metric -> (table, regex); every matching label is summed (at least one must match)
SUMMED = {
    "owner_hh_65plus":  ("B25007", r"^Total/Owner occupied/Householder (65|75|85)"),
    "renter_hh_65plus": ("B25007", r"^Total/Renter occupied/Householder (65|75|85)"),
}
# name -> (table, regex for the parent path whose children are $ bins)
BINNED = {
    "income_owner":  ("B25118", r"^Total/Owner occupied$"),
    "income_renter": ("B25118", r"^Total/Renter occupied$"),
    "electricity":   ("B25132", r"^Total/Charged for[^/]*$"),
    "gas":           ("B25133", r"^Total/Charged for[^/]*$"),
    "water_sewer":   ("B25134", r"^Total/Charged for[^/]*$"),
}
RACE = ["white_nh", "black_nh", "aian_nh", "asian_nh", "nhpi_nh", "other_nh", "multi_nh", "hispanic"]
TABLES = sorted({t for t, _ in [*SIMPLE.values(), *SUMMED.values(), *BINNED.values()]})


def normalize(label: str) -> str:
    """'Estimate!!Total:!!Owner occupied:' -> 'Total/Owner occupied'."""
    parts = [p.strip().rstrip(":").strip() for p in label.split("!!")]
    if parts and parts[0].lower().startswith("estimate"):
        parts = parts[1:]
    return "/".join(p for p in parts if p)


def parse_bin(text: str) -> tuple[float, float | None] | None:
    """'$50 to $99' -> (50, 100); 'Less than $5,000' -> (0, 5000); '$250 or more' -> (250, None)."""
    nums = [float(n.replace(",", "")) for n in re.findall(r"\$([\d,]+)", text)]
    if text.startswith("Less than") and len(nums) == 1:
        return 0.0, nums[0]
    if text.endswith("or more") and len(nums) == 1:
        return nums[0], None
    if " to " in text and len(nums) == 2:
        return nums[0], nums[1] + 1
    return None


def median_from_bins(bins: dict[str, float]) -> float | None:
    """Linear interpolation inside the bin holding the middle household (Census's own method)."""
    parsed = sorted(((parse_bin(k), v) for k, v in bins.items()), key=lambda x: x[0][0])
    total = sum(v for _, v in parsed)
    if total <= 0:
        return None
    half, run = total / 2, 0.0
    for (lo, hi), n in parsed:
        if n and run + n >= half:
            if hi is None:  # open-ended top bin: the most we can say is "at least lo"
                return lo
            return round(lo + (half - run) / n * (hi - lo), 2)
        run += n
    return None


def resolve(labels: dict[str, dict[str, str]]) -> dict:
    """Map metrics to variable codes using labels. Raises if a table's layout is not as expected."""
    paths = {t: {normalize(lab): var for var, lab in tab.items() if var.endswith("E")}
             for t, tab in labels.items()}
    plan = {"simple": {}, "summed": {}, "binned": {}}
    problems = []
    for metric, (table, pat) in SIMPLE.items():
        hits = [v for p, v in paths.get(table, {}).items() if re.search(pat, p)]
        if len(hits) != 1:
            problems.append(f"{metric}: {len(hits)} labels in {table} match /{pat}/")
        else:
            plan["simple"][metric] = hits[0]
    for metric, (table, pat) in SUMMED.items():
        hits = sorted(v for p, v in paths.get(table, {}).items() if re.search(pat, p))
        if not hits:
            problems.append(f"{metric}: no labels in {table} match /{pat}/")
        plan["summed"][metric] = hits
    for name, (table, pat) in BINNED.items():
        parents = [p for p in paths.get(table, {}) if re.search(pat, p)]
        if len(parents) != 1:
            problems.append(f"{name}: {len(parents)} parent labels in {table} match /{pat}/")
            continue
        parent = parents[0]
        bins = {p.split("/")[-1]: v for p, v in paths[table].items()
                if p.startswith(parent + "/") and p.count("/") == parent.count("/") + 1
                and parse_bin(p.split("/")[-1])}
        if not bins:
            problems.append(f"{name}: no $ bins under '{parent}' in {table}")
        # households in the table but not charged (cost included in rent, not used, ...)
        not_charged = [v for p, v in paths[table].items()
                       if p.count("/") == 1 and p.startswith("Total/") and p != parent]
        plan["binned"][name] = {"charged": paths[table][parent], "bins": bins, "other": not_charged}
    if problems:
        raise ValueError("ACS label layout changed:\n  " + "\n  ".join(problems))
    return plan


def _num(row: dict, var: str) -> float | None:
    v = row.get(var)
    if v in (None, ""):
        return None
    v = float(v)
    return None if v < 0 else v  # negative values are Census annotation codes (n/a, suppressed)


def profile(row: dict, plan: dict) -> dict:
    """One tract's profile from a merged API row."""
    out = {"geoid": STATE_NE + row["county"] + row["tract"], "name": row["NAME"],
           "county": COUNTIES.get(row["county"], row["county"])}
    for metric, var in plan["simple"].items():
        out[metric] = _num(row, var)
        moe = _num(row, var[:-1] + "M")
        if moe is not None:
            out.setdefault("moe", {})[metric] = moe
    for metric, vars_ in plan["summed"].items():
        out[metric] = sum(_num(row, v) or 0 for v in vars_)
    hh = out.get("households") or 0
    out["renter_share"] = round(out["renter_hh"] / hh, 4) if hh and out["renter_hh"] is not None else None
    pop = out.get("population") or 0
    out["race_share"] = {r: (round(out[r] / pop, 4) if pop and out[r] is not None else None) for r in RACE}
    for name, spec in plan["binned"].items():
        bins = {label: _num(row, v) or 0 for label, v in spec["bins"].items()}
        entry = {"bins": bins, "median_est": median_from_bins(bins)}
        if name in ("electricity", "gas", "water_sewer"):
            entry["charged_hh"] = _num(row, spec["charged"])
            entry["not_charged_hh"] = sum(_num(row, v) or 0 for v in spec["other"])
            out.setdefault("costs", {})[name] = entry
        else:
            out[name] = entry
    return out


def build(labels: dict, rows: list[dict]) -> list[dict]:
    plan = resolve(labels)
    return [profile(r, plan) for r in rows if (_num(r, plan["simple"]["households"]) or 0) > 0]


# ---- fetching ----------------------------------------------------------
def _get_json(url: str):
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.load(r)


def fetch_labels(year: int) -> dict[str, dict[str, str]]:
    labels = {}
    for t in TABLES:
        group = _get_json(f"{API.format(year=year)}/groups/{t}.json")
        labels[t] = {v: meta["label"] for v, meta in group["variables"].items()
                     if v.endswith(("E", "M")) and v.startswith(t)}
    return labels


def fetch_rows(year: int, api_key: str, labels: dict, counties=COUNTIES) -> list[dict]:
    """All E and M variables for every tract, merged into one dict per tract."""
    variables = sorted(v for tab in labels.values() for v in tab)
    merged: dict[tuple, dict] = {}
    for fips in counties:
        for i in range(0, len(variables), MAX_VARS):
            chunk = variables[i:i + MAX_VARS]
            q = urllib.parse.urlencode({"get": ",".join(["NAME", *chunk]), "for": "tract:*",
                                        "in": f"state:{STATE_NE} county:{fips}", "key": api_key})
            header, *data = _get_json(f"{API.format(year=year)}?{q}")
            for rec in data:
                row = dict(zip(header, rec, strict=True))
                merged.setdefault((row["county"], row["tract"]), {}).update(row)
        log.info("acs_fetch", extra={"ctx": {"year": year, "county": fips, "vars": len(variables)}})
    return list(merged.values())


def run(year: int, out_path: Path, api_key: str | None = None, raw_path: Path | None = None) -> list[dict]:
    """Fetch (or reuse a saved raw pull), build tract profiles and write JSON."""
    if raw_path:
        raw = json.loads(Path(raw_path).read_text())
    else:
        key = api_key or os.environ.get("CENSUS_API_KEY")
        if not key:
            raise SystemExit("Set CENSUS_API_KEY or pass --key (free: api.census.gov/data/key_signup.html)")
        labels = fetch_labels(year)
        raw = {"year": year, "labels": labels, "rows": fetch_rows(year, key, labels)}
        out_path.with_name(f"acs_raw_{year}.json").write_text(json.dumps(raw))  # untouched source
    tracts = build(raw["labels"], raw["rows"])
    out_path.write_text(json.dumps({"source": f"ACS {raw['year']} 5-year", "tables": TABLES,
                                    "tracts": tracts}, indent=1))
    log.info("acs_profiles_written", extra={"ctx": {"tracts": len(tracts), "path": str(out_path)}})
    return tracts
