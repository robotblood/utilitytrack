"""Derived views behind the /explore pages: fixed-charge math, the decision calendar, and who
carries the cost by tract. Read-only over the Store, tariffs and tract profiles; nothing is written back."""
from datetime import date, timedelta
from urllib.parse import urlparse

from .acs import parse_bin
from .bills import HIGH_BURDEN, SEVERE_BURDEN, monthly_bill
from .store import Store

# What a household feels: residential before all classes, a bill change before a rate change
HEADLINE_CLASSES = ("residential", "all")
HEADLINE_METRICS = ("avg_bill_change_pct", "avg_rate_change_pct")
METRIC_LABELS = {"avg_bill_change_pct": "bill", "avg_rate_change_pct": "rate"}
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
ORDINALS = ("first", "second", "third", "fourth", "fifth")


def year_of(action: dict) -> int:
    return int(action["effective_date"][:4])


def domain(url: str) -> str:
    return urlparse(url).netloc.removeprefix("www.")


def headline_change(action: dict) -> dict | None:
    """The one change that best answers 'what happened to a household bill', or None."""
    for cls in HEADLINE_CLASSES:
        for metric in HEADLINE_METRICS:
            for c in action["changes"]:
                if c["customer_class"] == cls and c["metric"] == metric:
                    return {**c, "label": f"{cls} {METRIC_LABELS[metric]}"}
    return None


# ---- fixed charge --------------------------------------------------------
def as_minimum_bill(tariff: dict) -> dict:
    """The same tariff read the other way: its fixed charges become a minimum monthly bill."""
    return {**tariff, "fixed_monthly": [],
            "minimum_bill": sum(f["amount"] for f in tariff.get("fixed_monthly", []))}


def bill_parts(tariff: dict, usage: float, month: int) -> dict:
    """A monthly bill split into what you pay regardless of use, energy, and riders."""
    bill = monthly_bill(tariff, usage, month)
    fixed_names = {f["name"] for f in tariff.get("fixed_monthly", [])} | {"minimum bill adjustment"}
    rider_names = {r["name"] for r in tariff.get("riders", [])}
    parts = {"fixed": 0.0, "energy": 0.0, "riders": 0.0}
    for line in bill["lines"]:
        item = line["item"]
        key = "fixed" if item in fixed_names else "riders" if item in rider_names else "energy"
        parts[key] += line["amount"]
    return {"usage": usage, "total": bill["total"], **{k: round(v, 2) for k, v in parts.items()},
            "cents": round(bill["total"] / usage * 100, 2) if usage else None}


def usage_curves(tariff: dict, usages: list[float]) -> dict:
    """Bills across a usage range for each season, read both ways (fixed charge / minimum bill)."""
    readings = {"fixed_charge": tariff, "minimum_bill": as_minimum_bill(tariff)}
    return {season: {"month": s["months"][0],
                     **{name: [bill_parts(t, u, s["months"][0]) for u in usages]
                        for name, t in readings.items()}}
            for season, s in tariff["seasons"].items()}


# ---- decision calendar ---------------------------------------------------
def nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    first = date(year, month, 1)
    return first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))


def vote_pattern(store: Store, utility: str) -> dict | None:
    """When a utility's board has voted on rates. A pattern needs at least two votes that all fell
    on the same nth weekday of the same month; it is a guess from history, not an announced date."""
    votes: dict[date, list] = {}
    for a in store.actions_for(utility):
        if a.get("approved_date"):
            votes.setdefault(date.fromisoformat(a["approved_date"]), []).append(a)
    days = sorted(votes)
    keys = {(d.month, d.weekday(), (d.day - 1) // 7 + 1) for d in days}
    out = {"votes": [{"date": d, "actions": votes[d]} for d in days], "rule": None}
    if len(days) >= 2 and len(keys) == 1:
        month, weekday, n = keys.pop()
        out["rule"] = {"month": month, "weekday": weekday, "n": n,
                       "text": f"{ORDINALS[n - 1]} {WEEKDAYS[weekday]} of "
                               f"{date(2000, month, 1):%B}"}
    return out


def next_decisions(store: Store, today: date) -> list[dict]:
    """For each active utility: past votes, the next vote date if a pattern holds, the latest action."""
    out = []
    for u in store.utilities:
        if u["status"] != "active":
            continue
        pattern = vote_pattern(store, u["code"])
        projected = None
        if pattern["rule"]:
            r = pattern["rule"]
            projected = nth_weekday(today.year, r["month"], r["weekday"], r["n"])
            if projected < today:
                projected = nth_weekday(today.year + 1, r["month"], r["weekday"], r["n"])
        actions = store.actions_for(u["code"])
        latest_year = max(year_of(a) for a in actions)
        out.append({"utility": u, "pattern": pattern, "projected": projected,
                    "days": (projected - today).days if projected else None,
                    "latest": [{**a, "headline": headline_change(a)} for a in actions
                               if year_of(a) == latest_year]})
    return out


# ---- who carries it: tract views -------------------------------------------
# Tract dicts here are web-layer tract profiles: ACS profile + "burden" from bills.observed_burden.
SERVICE_COST = {"electric": "electricity", "gas": "gas", "water": "water_sewer"}
ANNUAL_COSTS = {"water_sewer"}  # ACS B25134 is annual; electricity (B25132) and gas (B25133) are monthly
TENURES = ("owner", "renter")


def short_name(t: dict) -> str:
    """'Census Tract 2; Douglas County; Nebraska' -> 'Tract 2, Douglas'."""
    return f"Tract {t['name'].split(';')[0].removeprefix('Census Tract ').strip()}, {t['county']}"


def monthly_cost(t: dict, key: str) -> float | None:
    med = ((t.get("costs") or {}).get(key) or {}).get("median_est")
    if med is None:
        return None
    return med / 12 if key in ANNUAL_COSTS else med


def cost_is_floor(t: dict, key: str) -> bool:
    """True when the median fell in ACS's open-ended top bin ('$150 or more'), so it is a lower bound."""
    c = (t.get("costs") or {}).get(key) or {}
    tops = [parse_bin(b)[0] for b in c.get("bins", {}) if parse_bin(b) and parse_bin(b)[1] is None]
    return c.get("median_est") is not None and c["median_est"] in tops


# Map classes: the burden breaks share one scale so the all-household and renter maps compare directly
MAP_METRICS = {
    "burden": {"label": "Energy burden", "who": "all households", "breaks": [0.03, 0.045, 0.06, 0.10]},
    "renter": {"label": "Energy burden", "who": "renters", "breaks": [0.03, 0.045, 0.06, 0.10]},
    "in_rent": {"label": "Electricity paid through rent", "who": "share of households",
                "breaks": [0.05, 0.15, 0.30, 0.50]},
}
# Approximate centers, only to orient readers on a map with no basemap
LANDMARKS = [("Downtown", -95.937, 41.259), ("North Omaha", -95.960, 41.300),
             ("South Omaha", -95.950, 41.207), ("Elkhorn", -96.236, 41.286),
             ("Papillion", -96.042, 41.155), ("Bellevue", -95.915, 41.145)]


def map_class(v: float | None, breaks: list[float]) -> int | None:
    """0..len(breaks): how many breaks the value is above. None stays None (no data)."""
    return None if v is None else sum(v > b for b in breaks)


def map_rows(tracts: list[dict]) -> list[dict]:
    """One row per tract with every map metric, its class, and what the tooltip needs."""
    rows = []
    for t in tracts:
        b = t["burden"]
        vals = {"burden": b["energy_burden_all"], "renter": b["energy_burden_renter"],
                  "in_rent": b["share_electric_not_billed"]}
        rows.append({"geoid": t["geoid"], "name": short_name(t), "households": t.get("households"),
                     "income": t.get("median_income"), "renter_share": t.get("renter_share"),
                     "cost": b["monthly_energy_cost"], "floor": cost_is_floor(t, "gas"), "vals": vals,
                     "classes": {k: map_class(v, MAP_METRICS[k]["breaks"]) for k, v in vals.items()}})
    return rows


def cost_income_points(tracts: list[dict]) -> list[dict]:
    """Monthly electricity + gas against median income (all, owner, renter) for each tract."""
    return [{"geoid": t["geoid"], "name": short_name(t), "cost": t["burden"]["monthly_energy_cost"],
             "floor": cost_is_floor(t, "gas"), "households": t.get("households"),
             "income": {"all": t.get("median_income"), "owner": t.get("median_income_owner"),
                        "renter": t.get("median_income_renter")}}
            for t in tracts if t["burden"]["monthly_energy_cost"] is not None]


def spread(values: list[float], lo: float = 0.1, hi: float = 0.9) -> tuple[float, float]:
    """The 10th and 90th percentile (nearest rank): the range most tracts sit in."""
    v = sorted(values)
    return v[round(lo * (len(v) - 1))], v[round(hi * (len(v) - 1))]


def increase_actions(store: Store) -> list[dict]:
    """Rate actions that can be applied to a tract bill: a residential/all % headline on a service ACS prices
    (electricity, gas, water)."""
    out = []
    for a in store.rate_actions:
        h = headline_change(a)
        if h and a["service"] in SERVICE_COST:
            out.append({**a, "headline": h})
    return sorted(out, key=lambda a: (a["utility"], a["service"], a["effective_date"]))


def increase_by_group(tracts: list[dict], action: dict, groups: int = 5) -> list[dict]:
    """Apply one action's headline % to every tract's median bill for that service, then group tracts
    into income fifths (each about a fifth of households, ordered by tract median income).

    Per group: household-weighted mean added dollars a year, and the same as a share of median income.
    """
    h = headline_change(action)
    key = SERVICE_COST[action["service"]]
    usable = [t for t in tracts if monthly_cost(t, key) and t.get("median_income") and t.get("households")]
    rows = sorted(((monthly_cost(t, key), t["median_income"], t["households"], cost_is_floor(t, key))
                   for t in usable), key=lambda r: r[1])
    total, run = sum(r[2] for r in rows), 0.0
    acc = [{"households": 0.0, "added": 0.0, "share": 0.0, "lo": None, "hi": None, "tracts": 0, "floors": 0}
           for _ in range(groups)]
    for cost, income, hh, floor in rows:
        g = acc[min(groups - 1, int((run + hh / 2) / total * groups))]
        run += hh
        added = cost * 12 * h["value"] / 100
        g["households"] += hh
        g["added"] += added * hh
        g["share"] += added / income * hh
        g["lo"] = income if g["lo"] is None else g["lo"]
        g["hi"] = income
        g["tracts"] += 1
        g["floors"] += floor
    return [{**g, "group": i + 1, "added": round(g["added"] / g["households"], 2),
             "share": round(g["share"] / g["households"], 5)} for i, g in enumerate(acc) if g["households"]]


def _share_below(lo: float, hi: float | None, x: float) -> float:
    """Share of an income bin [lo, hi) under x, households spread evenly through the bin."""
    if hi is None:  # open top bin: no upper edge to spread across
        return 0.0 if x <= lo else 1.0
    return min(1.0, max(0.0, (x - lo) / (hi - lo)))


def under_the_line(tracts: list[dict]) -> dict:
    """Households earning less than it takes to keep their tract's typical energy bill under 6% (and 10%).

    The line for a tract is median monthly electricity + gas x 12 / 6%. Households are counted from
    income-by-tenure bins (B25118), spread evenly inside each bin. This is not a count of burdened
    households: ACS has no cost by income, and lower-income homes often use less energy.
    """
    tenure = {k: {"households": 0.0, "under_6": 0.0, "under_10": 0.0} for k in TENURES}
    in_flagged = {"under_6": 0.0, "households": 0.0}
    lines = []
    for t in tracts:
        cost = t["burden"]["monthly_energy_cost"]
        if cost is None:
            continue
        line6, line10 = cost * 12 / HIGH_BURDEN, cost * 12 / SEVERE_BURDEN
        flagged = t["burden"]["energy_burden_all_level"] in ("high", "severe")
        under = 0.0
        for k in TENURES:
            for label, n in (t.get(f"income_{k}") or {}).get("bins", {}).items():
                lo, hi = parse_bin(label)
                u6, u10 = n * _share_below(lo, hi, line6), n * _share_below(lo, hi, line10)
                tenure[k]["households"] += n
                tenure[k]["under_6"] += u6
                tenure[k]["under_10"] += u10
                under += u6
        if flagged:
            in_flagged["under_6"] += under
            in_flagged["households"] += t.get("households") or 0
        lines.append({"geoid": t["geoid"], "name": short_name(t), "line": round(line6), "under": round(under),
                      "households": t.get("households"), "floor": cost_is_floor(t, "gas"),
                      "flagged": flagged})
    all_ = {f: sum(v[f] for v in tenure.values()) for f in ("households", "under_6", "under_10")}
    rnd = lambda d: {k: round(v) for k, v in d.items()}
    return {"tenure": {k: rnd(v) for k, v in tenure.items()}, "all": rnd(all_), "in_flagged": rnd(in_flagged),
            "flagged_tracts": sum(r["flagged"] for r in lines), "tracts": len(lines),
            "lines": sorted(lines, key=lambda r: r["line"]),
            "line_spread": spread([r["line"] for r in lines]) if lines else None}
