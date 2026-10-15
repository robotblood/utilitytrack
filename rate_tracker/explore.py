"""Derived views behind the /explore pages: fixed-charge math and the decision calendar.
Read-only over the Store and tariffs; nothing here is written back."""
from datetime import date, timedelta
from urllib.parse import urlparse

from .bills import monthly_bill
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
