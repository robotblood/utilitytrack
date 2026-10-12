"""Tariffs -> monthly bills, and energy burden (utility cost as a share of household income).

Two kinds of burden:
  observed  ACS-reported monthly electricity/gas/water costs vs. median income (per tract/area)
  modeled   a tariff bill for a given usage vs. a given income
"""
import json
from pathlib import Path

from .store import DATA_DIR, VERIFICATION

# Common thresholds in energy-burden research (e.g. ACEEE): >6% high, >10% severe
HIGH_BURDEN = 0.06
SEVERE_BURDEN = 0.10
UNITS = {"electric": "kWh", "gas": "Ccf", "water": "Ccf"}


def load_tariffs(data_dir: Path = DATA_DIR) -> list[dict]:
    path = data_dir / "tariffs.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def validate_tariffs(tariffs: list[dict]) -> list[str]:
    errors = []
    ids = [t.get("id") for t in tariffs]
    errors += [f"duplicate tariff id: {i}" for i in {i for i in ids if ids.count(i) > 1}]
    for t in tariffs:
        tid = t.get("id", "?")
        if t.get("service") not in UNITS:
            errors.append(f"tariff {tid}: unknown service {t.get('service')}")
        if not t.get("sources"):
            errors.append(f"tariff {tid}: no sources")
        if t.get("verification") not in VERIFICATION:
            errors.append(f"tariff {tid}: bad verification flag")
        months = sorted(m for s in t.get("seasons", {}).values() for m in s.get("months", []))
        if months != list(range(1, 13)):
            errors.append(f"tariff {tid}: seasons must cover months 1-12 exactly once")
        for name, s in t.get("seasons", {}).items():
            blocks = s.get("blocks", [])
            limits = [b.get("up_to") for b in blocks]
            if not blocks or limits[-1] is not None or limits[:-1] != sorted(x for x in limits[:-1] if x):
                errors.append(f"tariff {tid}: season {name} blocks must ascend and end with up_to null")
    return errors


def season_for(tariff: dict, month: int) -> dict:
    return next(s for s in tariff["seasons"].values() if month in s["months"])


def monthly_bill(tariff: dict, usage: float, month: int) -> dict:
    """Itemized bill for one month's usage (in the tariff's unit)."""
    lines, used = [], 0.0
    for f in tariff.get("fixed_monthly", []):
        lines.append({"item": f["name"], "amount": f["amount"]})
    for b in season_for(tariff, month)["blocks"]:
        cap = b["up_to"]
        qty = max(0.0, min(usage, cap if cap is not None else usage) - used)
        if qty:
            lines.append({"item": f"energy {used:g}-{used + qty:g} {tariff['unit']} @ {b['rate']}",
                          "amount": qty * b["rate"]})
        used += qty
    for r in tariff.get("riders", []):
        lines.append({"item": r["name"], "amount": usage * r["rate"]})
    total = sum(x["amount"] for x in lines)
    minimum = tariff.get("minimum_bill")
    if minimum is not None and total < minimum:
        lines.append({"item": "minimum bill adjustment", "amount": minimum - total})
        total = minimum
    return {"tariff": tariff["id"], "month": month, "usage": usage, "unit": tariff["unit"],
            "lines": [{**x, "amount": round(x["amount"], 2)} for x in lines], "total": round(total, 2)}


def annual_bill(tariff: dict, monthly_usage: list[float]) -> float:
    if len(monthly_usage) != 12:
        raise ValueError("monthly_usage needs 12 values (Jan..Dec)")
    return round(sum(monthly_bill(tariff, u, m)["total"] for m, u in enumerate(monthly_usage, 1)), 2)


def burden(annual_cost: float | None, income: float | None) -> float | None:
    if annual_cost is None or not income:
        return None
    return round(annual_cost / income, 4)


def level(b: float | None) -> str | None:
    if b is None:
        return None
    return "severe" if b > SEVERE_BURDEN else "high" if b > HIGH_BURDEN else "ok"


def observed_burden(profile: dict) -> dict:
    """Burden from ACS-reported costs for a tract or area profile.

    ACS does not split utility costs by tenure, so owner/renter burdens use the same
    cost against tenure-specific income: they show the income side of the gap, not usage.
    """
    costs = profile.get("costs") or {}
    med = {k: (costs.get(k) or {}).get("median_est") for k in ("electricity", "gas", "water_sewer")}
    energy = (med["electricity"] or 0) + (med["gas"] or 0) if med["electricity"] is not None else None
    utility = energy + (med["water_sewer"] or 0) if energy is not None else None
    annual_energy = energy * 12 if energy is not None else None
    annual_utility = utility * 12 if utility is not None else None
    incomes = {
        "all": profile.get("median_income", profile.get("median_income_hhwavg")),
        "owner": profile.get("median_income_owner", profile.get("median_income_owner_est")),
        "renter": profile.get("median_income_renter", profile.get("median_income_renter_est")),
    }
    elec = costs.get("electricity") or {}
    paying = (elec.get("charged_hh") or 0) + (elec.get("not_charged_hh") or 0)
    out = {"monthly_energy_cost": energy, "monthly_utility_cost": utility,
           # households whose electricity is included in rent/fees: hidden cost, mostly renters
           "share_electric_not_billed": round(elec["not_charged_hh"] / paying, 4) if paying else None}
    for who, inc in incomes.items():
        out[f"energy_burden_{who}"] = burden(annual_energy, inc)
        out[f"utility_burden_{who}"] = burden(annual_utility, inc)
        out[f"energy_burden_{who}_level"] = level(out[f"energy_burden_{who}"])
    return out
