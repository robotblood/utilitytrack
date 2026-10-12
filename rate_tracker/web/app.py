"""FastAPI app over the JSON store. Read-only for now; JSON stays the source of truth."""
import json
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from ..log import get_logger
from ..store import DATA_DIR, Store

log = get_logger()
TEMPLATES = Jinja2Templates(directory=Path(__file__).resolve().parent / "templates")
INCOME_FILE = "geo_income_tracts.json"


def load_income(data_dir: Path) -> dict | None:
    """Household income by tract, written by `rate_tracker census-income`; None until generated."""
    path = data_dir / INCOME_FILE
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def create_app(data_dir: Path = DATA_DIR) -> FastAPI:
    store = Store.load(data_dir)
    income = load_income(data_dir)
    app = FastAPI(title="UtilityTrack")

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

    @app.get("/healthz")
    def healthz():
        return {"ok": True, "rate_actions": len(store.rate_actions),
                "drivers": len(store.cost_drivers), "income_loaded": income is not None}

    log.info("web_app_created",
             extra={"ctx": {"data_dir": str(data_dir), "income_loaded": income is not None}})
    return app
