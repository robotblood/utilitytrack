"""Command line: python -m rate_tracker <command>

  validate                  check ids, links and sources
  timeline [-u OPPD] [-s gas] [-c residential]
                            rate changes over time with their drivers
  why <action_id>           explain one rate action and its linked causes
  todo                      list records flagged needs_verification
  export-csv <out_dir>      flat CSVs for Notion / PostgreSQL import
  serve [--port 8000]       run the web app (needs: pip install -e ".[web]")

  Neighborhood pipeline (see README):
  acs-profiles [--year 2024]                 tract demographics + utility costs from the ACS
  crosswalk <layer> --areas F --id-field N   tract -> area weights (needs ".[geo]")
  rollup <layer>                             area profiles with energy burden
  bill <tariff_id> <usage> [--month 7]       itemized monthly bill
"""
import argparse
import csv
import sys
from pathlib import Path

from .bills import load_tariffs, monthly_bill, validate_tariffs
from .log import get_logger
from .store import DATA_DIR, Store

log = get_logger()
ARROW = {"up": "▲", "down": "▼"}


def cmd_validate(store: Store, _args) -> int:
    errors = store.validate() + validate_tariffs(load_tariffs())
    log.info("validate", extra={"ctx": {"errors": len(errors)}})
    for e in errors:
        print("ERROR", e)
    print(f"{len(store.rate_actions)} rate actions, {len(store.cost_drivers)} drivers, "
          f"{len(errors)} problems")
    return 1 if errors else 0


def cmd_timeline(store: Store, args) -> int:
    for a in store.actions_for(args.utility, args.service):
        rows = [c for c in a["changes"]
                if args.customer_class in (None, c["customer_class"])]
        if not rows:
            continue
        flag = "" if a["verification"] == "verified" else "  [needs verification]"
        print(f"\n{a['effective_date']}  {a['utility']} {a['service']}  ({a['status']}){flag}")
        for c in rows:
            print(f"    {c['customer_class']:<12} {c['metric']:<36} {c['value']:+.2f}")
        for did in a.get("driver_ids", []):
            d = store.driver(did)
            print(f"    {ARROW[d['direction']]} {d['category']}: {d['title']}")
    return 0


def cmd_why(store: Store, args) -> int:
    a = next((x for x in store.rate_actions if x["id"] == args.action_id), None)
    if a is None:
        print(f"No rate action '{args.action_id}'")
        return 1
    print(f"{a['utility']} {a['service']} effective {a['effective_date']} ({a['status']})")
    if a.get("notes"):
        print(f"  note: {a['notes']}")
    for did in a.get("driver_ids", []):
        d = store.driver(did)
        print(f"  {ARROW[d['direction']]} {d['title']}")
        for s in d["sources"]:
            print(f"      {s}")
    print("  rate sources:")
    for s in a["sources"]:
        print(f"      {s}")
    return 0


def cmd_todo(store: Store, _args) -> int:
    flagged = [r for r in store.rate_actions + store.cost_drivers + load_tariffs()
               if r.get("verification") == "needs_verification"]
    for r in flagged:
        print(f"{r['id']:<34} {r['sources'][0]}")
    print(f"{len(flagged)} records need verification")
    return 0


def cmd_export(store: Store, args) -> int:
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    # One row per individual change: easiest shape for Notion or a SQL table
    with open(out / "rate_changes.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["action_id", "utility", "service", "effective_date", "status",
                    "customer_class", "metric", "value", "verification", "driver_ids", "sources"])
        for a in store.rate_actions:
            for c in a["changes"]:
                w.writerow([a["id"], a["utility"], a["service"], a["effective_date"], a["status"],
                            c["customer_class"], c["metric"], c["value"], a["verification"],
                            ";".join(a.get("driver_ids", [])), " ".join(a["sources"])])
    with open(out / "cost_drivers.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["driver_id", "utility", "category", "direction", "title", "verification", "sources"])
        for d in store.cost_drivers:
            w.writerow([d["id"], d["utility"], d["category"], d["direction"], d["title"],
                        d["verification"], " ".join(d["sources"])])
    log.info("export_csv", extra={"ctx": {"out_dir": str(out)}})
    print(f"Wrote {out/'rate_changes.csv'} and {out/'cost_drivers.csv'}")
    return 0


GEO_DIR = DATA_DIR / "geo"
ACS_FILE = DATA_DIR / "acs_tracts.json"


def cmd_crosswalk(args) -> int:
    import json

    from .geo import crosswalk, load_features
    keep = {"COUNTYFP": {"055", "153"}} if not args.all_counties else None
    tracts = load_features(Path(args.tracts), args.tract_id_field, keep=keep)
    areas = load_features(Path(args.areas), args.id_field)
    rows = crosswalk(tracts, areas)
    GEO_DIR.mkdir(parents=True, exist_ok=True)
    out = GEO_DIR / f"crosswalk_{args.layer}.json"
    out.write_text(json.dumps({"layer": args.layer, "tracts_file": Path(args.tracts).name,
                               "areas_file": Path(args.areas).name, "rows": rows}, indent=1))
    print(f"{len(rows)} tract/area pairs for {len({r['area'] for r in rows})} areas -> {out}")
    return 0


def cmd_rollup(args) -> int:
    import json

    from .bills import observed_burden
    from .geo import rollup
    if not ACS_FILE.exists():
        print("No tract profiles yet; run: python -m rate_tracker acs-profiles")
        return 1
    acs = json.loads(ACS_FILE.read_text())
    xw = json.loads((GEO_DIR / f"crosswalk_{args.layer}.json").read_text())
    areas = [{**a, "burden": observed_burden(a)} for a in rollup(acs["tracts"], xw["rows"])]
    out = DATA_DIR / f"areas_{args.layer}.json"
    out.write_text(json.dumps({"layer": args.layer, "source": acs["source"],
                               "method": "area-weighted tract overlay", "areas": areas}, indent=1))
    log.info("rollup_written", extra={"ctx": {"layer": args.layer, "areas": len(areas)}})
    print(f"Wrote {len(areas)} {args.layer} profiles to {out}")
    return 0


def cmd_bill(args) -> int:
    tariff = next((t for t in load_tariffs() if t["id"] == args.tariff_id), None)
    if tariff is None:
        print(f"No tariff '{args.tariff_id}'; have: {', '.join(t['id'] for t in load_tariffs())}")
        return 1
    b = monthly_bill(tariff, args.usage, args.month)
    if tariff["verification"] != "verified":
        print("[tariff needs verification]")
    for line in b["lines"]:
        print(f"  {line['item']:<50} ${line['amount']:>8.2f}")
    print(f"  {'total':<50} ${b['total']:>8.2f}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="rate_tracker", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("validate")
    t = sub.add_parser("timeline")
    t.add_argument("-u", "--utility")
    t.add_argument("-s", "--service")
    t.add_argument("-c", "--customer-class")
    w = sub.add_parser("why")
    w.add_argument("action_id")
    sub.add_parser("todo")
    e = sub.add_parser("export-csv")
    e.add_argument("out_dir")
    ci = sub.add_parser("census-income", help="household income by tract (Douglas + Sarpy)")
    ci.add_argument("--year", type=int, default=2024, help="ACS 5-year end year")
    ci.add_argument("--key", help="Census API key (or set CENSUS_API_KEY)")
    ci.add_argument("--raw", help="re-use a saved raw API response instead of fetching")
    sv = sub.add_parser("serve", help="run the web app")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8000)
    sv.add_argument("--reload", action="store_true")
    ap = sub.add_parser("acs-profiles", help="tract demographics + utility costs (Douglas + Sarpy)")
    ap.add_argument("--year", type=int, default=2024, help="ACS 5-year end year")
    ap.add_argument("--key", help="Census API key (or set CENSUS_API_KEY)")
    ap.add_argument("--raw", help="re-use a saved raw pull (data/acs_raw_<year>.json)")
    cw = sub.add_parser("crosswalk", help="tract -> neighborhood/ZIP weights by area overlay")
    cw.add_argument("layer", help="name for this boundary set, e.g. neighborhoods or zcta")
    cw.add_argument("--areas", required=True, help="GeoJSON or zipped shapefile of areas")
    cw.add_argument("--id-field", required=True, help="property holding the area name/code")
    cw.add_argument("--tracts", default=str(GEO_DIR / "cb_2024_31_tract_500k.zip"))
    cw.add_argument("--tract-id-field", default="GEOID")
    cw.add_argument("--all-counties", action="store_true", help="skip the Douglas/Sarpy filter")
    ru = sub.add_parser("rollup", help="area profiles + energy burden from tract profiles")
    ru.add_argument("layer")
    bl = sub.add_parser("bill", help="itemized monthly bill for a tariff")
    bl.add_argument("tariff_id")
    bl.add_argument("usage", type=float, help="usage in the tariff's unit (kWh, Ccf)")
    bl.add_argument("--month", type=int, default=7)
    args = p.parse_args(argv)

    if args.cmd == "acs-profiles":
        from .acs import run as run_acs
        tracts = run_acs(args.year, ACS_FILE, args.key, args.raw)
        print(f"Wrote {len(tracts)} tract profiles to {ACS_FILE}")
        return 0
    if args.cmd in ("crosswalk", "rollup", "bill"):
        log.info("command", extra={"ctx": {"cmd": args.cmd}})
        return {"crosswalk": cmd_crosswalk, "rollup": cmd_rollup, "bill": cmd_bill}[args.cmd](args)

    if args.cmd == "serve":
        import uvicorn
        uvicorn.run("rate_tracker.web.app:create_app", factory=True,
                    host=args.host, port=args.port, reload=args.reload)
        return 0

    if args.cmd == "census-income":
        from .census_income import run
        out = Path(__file__).resolve().parent.parent / "data" / "geo_income_tracts.json"
        tracts = run(args.year, out, args.key, args.raw)
        print(f"Wrote {len(tracts)} tracts to {out}")
        return 0

    store = Store.load()
    log.info("command", extra={"ctx": {"cmd": args.cmd}})
    handler = {"validate": cmd_validate, "timeline": cmd_timeline, "why": cmd_why,
               "todo": cmd_todo, "export-csv": cmd_export}[args.cmd]
    return handler(store, args)


if __name__ == "__main__":
    sys.exit(main())
