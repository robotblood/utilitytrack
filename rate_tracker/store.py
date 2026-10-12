"""Load, validate and query the JSON data store."""
import json
from dataclasses import dataclass, field
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

SERVICES = {"electric", "water", "gas"}
STATUSES = {"proposed", "approved", "rejected", "withdrawn"}
VERIFICATION = {"verified", "needs_verification"}
DIRECTIONS = {"up", "down"}
DRIVER_CATEGORIES = {
    "fuel_purchased_power", "gas_commodity", "capital_investment", "infrastructure_replacement",
    "load_growth", "weather", "regulatory", "inflation_supply_chain", "reliability_om",
    "cost_savings_offset", "debt_service", "other",
}


@dataclass
class Store:
    utilities: list = field(default_factory=list)
    rate_actions: list = field(default_factory=list)
    cost_drivers: list = field(default_factory=list)

    @classmethod
    def load(cls, data_dir: Path = DATA_DIR) -> "Store":
        read = lambda name: json.loads((data_dir / name).read_text(encoding="utf-8"))
        return cls(read("utilities.json"), read("rate_actions.json"), read("cost_drivers.json"))

    def save(self, data_dir: Path = DATA_DIR) -> None:
        for name, rows in (("utilities.json", self.utilities),
                           ("rate_actions.json", self.rate_actions),
                           ("cost_drivers.json", self.cost_drivers)):
            (data_dir / name).write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")

    # ---- lookups -------------------------------------------------------
    def driver(self, driver_id: str) -> dict | None:
        return next((d for d in self.cost_drivers if d["id"] == driver_id), None)

    def actions_for(self, utility: str | None = None, service: str | None = None) -> list:
        rows = [a for a in self.rate_actions
                if (utility is None or a["utility"] == utility)
                and (service is None or a["service"] == service)]
        return sorted(rows, key=lambda a: a["effective_date"])

    # ---- validation ----------------------------------------------------
    def validate(self) -> list[str]:
        """Return a list of problems; empty list means the store is consistent."""
        errors = []
        util_codes = {u["code"] for u in self.utilities}
        driver_ids = [d["id"] for d in self.cost_drivers]
        action_ids = [a["id"] for a in self.rate_actions]

        for ids, label in ((driver_ids, "driver"), (action_ids, "rate action")):
            dupes = {i for i in ids if ids.count(i) > 1}
            errors += [f"duplicate {label} id: {i}" for i in dupes]

        for d in self.cost_drivers:
            if d["utility"] not in util_codes:
                errors.append(f"driver {d['id']}: unknown utility {d['utility']}")
            if d["category"] not in DRIVER_CATEGORIES:
                errors.append(f"driver {d['id']}: unknown category {d['category']}")
            if d["direction"] not in DIRECTIONS:
                errors.append(f"driver {d['id']}: bad direction {d['direction']}")
            if not d.get("sources"):
                errors.append(f"driver {d['id']}: no sources")

        for a in self.rate_actions:
            aid = a["id"]
            if a["utility"] not in util_codes:
                errors.append(f"{aid}: unknown utility {a['utility']}")
            if a["service"] not in SERVICES:
                errors.append(f"{aid}: unknown service {a['service']}")
            if a["status"] not in STATUSES:
                errors.append(f"{aid}: bad status {a['status']}")
            if a.get("verification") not in VERIFICATION:
                errors.append(f"{aid}: bad verification flag")
            if not a.get("sources"):
                errors.append(f"{aid}: no sources")
            if not a.get("changes"):
                errors.append(f"{aid}: no changes")
            for did in a.get("driver_ids", []):
                drv = self.driver(did)
                if drv is None:
                    errors.append(f"{aid}: missing driver {did}")
                elif drv["utility"] != a["utility"]:
                    errors.append(f"{aid}: driver {did} belongs to {drv['utility']}")
        return errors
