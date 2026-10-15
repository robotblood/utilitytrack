"""FastAPI app over the JSON store. Read-only for now; JSON stays the source of truth."""
import json
import time
from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .. import explore
from ..bills import load_tariffs, monthly_bill, observed_burden
from ..log import get_logger
from ..store import DATA_DIR, Store
from .charts import usage_chart

log = get_logger()
WEB_DIR = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=WEB_DIR / "templates")
TEMPLATES.env.globals.update(headline=explore.headline_change, domain=explore.domain)
USAGES = list(range(100, 2501, 50))
INCOME_FILE = "geo_income_tracts.json"


def load_income(data_dir: Path) -> dict | None:
    """Household income by tract, written by `rate_tracker census-income`; None until generated."""
    path = data_dir / INCOME_FILE
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def load_layers(data_dir: Path) -> dict[str, list[dict]]:
    """Area profiles by layer: 'tracts' from acs_tracts.json plus every areas_<layer>.json rollup."""
    layers = {}
    acs = data_dir / "acs_tracts.json"
    if acs.exists():
        tracts = json.loads(acs.read_text(encoding="utf-8"))["tracts"]
        layers["tracts"] = [{**t, "area": t["geoid"], "burden": observed_burden(t)} for t in tracts]
    for f in sorted(data_dir.glob("areas_*.json")):
        layers[f.stem.removeprefix("areas_")] = json.loads(f.read_text(encoding="utf-8"))["areas"]
    return layers


SORTS = {"area": lambda a: a["area"], "renter_share": lambda a: a.get("renter_share") or 0,
         "burden": lambda a: a["burden"].get("energy_burden_all") or 0,
         "renter_burden": lambda a: a["burden"].get("energy_burden_renter") or 0}


def create_app(data_dir: Path = DATA_DIR) -> FastAPI:
    store = Store.load(data_dir)
    income = load_income(data_dir)
    layers = load_layers(data_dir)
    tariffs = {t["id"]: t for t in load_tariffs(data_dir)}
    app = FastAPI(title="UtilityTrack")
    app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")

    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        log.info("http_request", extra={"ctx": {
            "method": request.method, "path": request.url.path, "status": response.status_code,
            "ms": round((time.perf_counter() - start) * 1000, 1)}})
        return response

    def get_action(action_id: str) -> dict:
        action = next((a for a in store.rate_actions if a["id"] == action_id), None)
        if action is None:
            raise HTTPException(404, f"No rate action '{action_id}'")
        return action

    # ---- pages ---------------------------------------------------------
    @app.get("/", response_class=HTMLResponse)
    def timeline(request: Request, utility: str | None = None, service: str | None = None,
                 customer_class: str | None = None):
        actions = [{**a, "changes": [c for c in a["changes"]
                                     if customer_class in (None, "", c["customer_class"])]}
                   for a in store.actions_for(utility or None, service or None)]
        return TEMPLATES.TemplateResponse(request, "timeline.html", {
            "actions": [a for a in actions if a["changes"]], "store": store,
            "filters": {"utility": utility, "service": service, "customer_class": customer_class},
            "utilities": sorted({a["utility"] for a in store.rate_actions}),
            "services": sorted({a["service"] for a in store.rate_actions}),
            "classes": sorted({c["customer_class"] for a in store.rate_actions for c in a["changes"]}),
        })

    @app.get("/actions/{action_id}", response_class=HTMLResponse)
    def action_page(request: Request, action_id: str):
        action = get_action(action_id)
        drivers = [store.driver(d) for d in action.get("driver_ids", [])]
        return TEMPLATES.TemplateResponse(request, "action.html", {"a": action, "drivers": drivers})

    @app.get("/income", response_class=HTMLResponse)
    def income_page(request: Request, county: str | None = None):
        tracts = [t for t in (income or {}).get("tracts", []) if county in (None, "", t["county"])]
        return TEMPLATES.TemplateResponse(request, "income.html", {
            "income": income, "tracts": sorted(tracts, key=lambda t: t["geoid"]), "county": county})

    @app.get("/neighborhoods", response_class=HTMLResponse)
    def neighborhoods_page(request: Request, layer: str | None = None, sort: str = "burden"):
        layer = layer if layer in layers else next(iter(layers), None)
        rows = sorted(layers.get(layer, []), key=SORTS.get(sort, SORTS["burden"]), reverse=sort != "area")
        return TEMPLATES.TemplateResponse(request, "neighborhoods.html", {
            "layers": list(layers), "layer": layer, "rows": rows, "sort": sort})

    @app.get("/bill", response_class=HTMLResponse)
    def bill_page(request: Request, tariff: str | None = None, usage: float = 1000, month: int = 7,
                  income: float | None = None):
        t = tariffs.get(tariff) or next(iter(tariffs.values()), None)
        bill = monthly_bill(t, usage, month) if t and 1 <= month <= 12 else None
        share = round(bill["total"] * 12 / income, 4) if bill and income else None
        return TEMPLATES.TemplateResponse(request, "bill.html", {
            "tariffs": list(tariffs.values()), "t": t, "bill": bill, "usage": usage, "month": month,
            "income": income, "share": share})

    # ---- explore: the same data shown another way ----------------------
    @app.get("/explore", response_class=HTMLResponse)
    def explore_index(request: Request):
        t = next(iter(tariffs.values()), None)
        upcoming = [u for u in explore.next_decisions(store, date.today()) if u["projected"]]
        return TEMPLATES.TemplateResponse(request, "explore/index.html", {
            "t": t, "small_big": [explore.bill_parts(t, u, 1) for u in (300, 1500)] if t else None,
            "upcoming": min(upcoming, key=lambda u: u["projected"], default=None)})

    @app.get("/explore/fixed-charge", response_class=HTMLResponse)
    def explore_fixed_charge(request: Request, tariff: str | None = None):
        t = tariffs.get(tariff) or next(iter(tariffs.values()), None)
        curves = explore.usage_curves(t, USAGES) if t else None
        return TEMPLATES.TemplateResponse(request, "explore/fixed_charge.html", {
            "t": t, "tariffs": list(tariffs.values()), "curves": curves,
            "chart": usage_chart(curves, USAGES) if curves else None})

    @app.get("/explore/next", response_class=HTMLResponse)
    def explore_next(request: Request):
        today = date.today()
        return TEMPLATES.TemplateResponse(request, "explore/next.html", {
            "today": today, "utilities": explore.next_decisions(store, today), "store": store})

    # ---- JSON API ------------------------------------------------------
    @app.get("/api/utilities")
    def api_utilities():
        return store.utilities

    @app.get("/api/actions")
    def api_actions(utility: str | None = None, service: str | None = None):
        return store.actions_for(utility, service)

    @app.get("/api/actions/{action_id}")
    def api_action(action_id: str):
        action = get_action(action_id)
        return {**action, "drivers": [store.driver(d) for d in action.get("driver_ids", [])]}

    @app.get("/api/drivers")
    def api_drivers():
        return store.cost_drivers

    @app.get("/api/income/tracts")
    def api_income():
        if income is None:
            raise HTTPException(404, "No income data yet; run: python -m rate_tracker census-income")
        return income

    @app.get("/api/areas/{layer}")
    def api_areas(layer: str):
        if layer not in layers:
            raise HTTPException(404, f"No layer '{layer}'; have: {sorted(layers)}")
        return layers[layer]

    @app.get("/api/tariffs")
    def api_tariffs():
        return list(tariffs.values())

    @app.get("/api/bill/{tariff_id}")
    def api_bill(tariff_id: str, usage: float, month: int = 7):
        if tariff_id not in tariffs:
            raise HTTPException(404, f"No tariff '{tariff_id}'")
        if not 1 <= month <= 12:
            raise HTTPException(422, "month must be 1-12")
        return monthly_bill(tariffs[tariff_id], usage, month)

    @app.get("/healthz")
    def healthz():
        return {"ok": True, "rate_actions": len(store.rate_actions),
                "drivers": len(store.cost_drivers), "income_loaded": income is not None,
                "layers": sorted(layers), "tariffs": len(tariffs)}

    log.info("web_app_created",
             extra={"ctx": {"data_dir": str(data_dir), "income_loaded": income is not None}})
    return app
