"""Tracts -> named neighborhoods / ZIP codes by area overlay, then roll tract profiles up.

Boundaries can be GeoJSON or a zipped shapefile (e.g. Census TIGER cartographic files).
Weights are the share of each tract's area inside each neighborhood, so households are
assumed to be spread evenly across a tract. Counts are split by weight; medians are
re-estimated from the combined bins rather than averaged.

Needs the geo extra:  pip install -e ".[geo]"
"""
import json
from pathlib import Path

from .acs import RACE, median_from_bins
from .log import get_logger

log = get_logger()
GEO_DIR = Path(__file__).resolve().parent.parent / "data" / "geo"

COUNTS = ["households", "owner_hh", "renter_hh", "population", "owner_hh_65plus", "renter_hh_65plus", *RACE]
BINNED = ["income_owner", "income_renter"]
COSTS = ["electricity", "gas", "water_sewer"]


def load_features(path: Path, id_field: str, keep: dict | None = None) -> list[tuple[str, dict, object]]:
    """[(id, properties, shapely geometry)] from .geojson/.json or a (zipped) shapefile.

    keep: optional {field: allowed values} filter, e.g. {"COUNTYFP": {"055", "153"}}.
    """
    from shapely.geometry import shape

    path = Path(path)
    if path.suffix.lower() in (".zip", ".shp"):
        import shapefile
        with shapefile.Reader(str(path)) as sf:
            rows = [(sr.record.as_dict(), sr.shape.__geo_interface__) for sr in sf.shapeRecords()]
    else:
        gj = json.loads(path.read_text(encoding="utf-8"))
        rows = [(f["properties"], f["geometry"]) for f in gj["features"]]
    out = []
    for props, geom in rows:
        if keep and any(str(props.get(k)) not in v for k, v in keep.items()):
            continue
        if id_field not in props:
            raise KeyError(f"{path.name}: no '{id_field}' field; fields are {sorted(props)}")
        if geom:
            out.append((str(props[id_field]), props, shape(geom).buffer(0)))  # buffer(0) repairs rings
    log.info("geo_loaded", extra={"ctx": {"path": str(path), "features": len(out)}})
    return out


def crosswalk(tracts: list, areas: list, min_weight: float = 0.01) -> list[dict]:
    """Rows of {geoid, area, weight}: weight = share of the tract's area inside that area.

    Slivers under min_weight (boundary noise between layers) are dropped.
    Lat/lon areas are fine here because only ratios within one small tract are used.
    """
    from shapely import STRtree

    tree = STRtree([g for _, _, g in areas])
    rows = []
    for geoid, _, tgeom in tracts:
        if tgeom.area == 0:
            continue
        for i in tree.query(tgeom, predicate="intersects"):
            area_id, _, ageom = areas[int(i)]
            w = tgeom.intersection(ageom).area / tgeom.area
            if w >= min_weight:
                rows.append({"geoid": geoid, "area": area_id, "weight": round(w, 4)})
    log.info("crosswalk_built",
             extra={"ctx": {"tracts": len(tracts), "areas": len(areas), "rows": len(rows)}})
    return rows


def _add_bins(acc: dict, bins: dict, w: float) -> None:
    for k, v in bins.items():
        acc[k] = acc.get(k, 0) + (v or 0) * w


def rollup(profiles: list[dict], xwalk: list[dict]) -> list[dict]:
    """Combine tract profiles into one profile per area using crosswalk weights."""
    by_geoid = {p["geoid"]: p for p in profiles}
    areas: dict[str, dict] = {}
    for row in xwalk:
        t = by_geoid.get(row["geoid"])
        if t is None:
            continue
        w = row["weight"]
        a = areas.setdefault(row["area"], {
            "area": row["area"], "tracts": [], **{c: 0.0 for c in COUNTS}, "_inc_x_hh": 0.0, "_inc_hh": 0.0,
            **{b: {} for b in BINNED}, "costs": {c: {"bins": {}, "charged_hh": 0.0, "not_charged_hh": 0.0}
                                                for c in COSTS}})
        a["tracts"].append({"geoid": t["geoid"], "weight": w})
        for c in COUNTS:
            a[c] += (t.get(c) or 0) * w
        if t.get("median_income") is not None and t.get("households"):
            a["_inc_x_hh"] += t["median_income"] * t["households"] * w
            a["_inc_hh"] += t["households"] * w
        for b in BINNED:
            _add_bins(a[b], (t.get(b) or {}).get("bins", {}), w)
        for c in COSTS:
            src = (t.get("costs") or {}).get(c)
            if src:
                _add_bins(a["costs"][c]["bins"], src["bins"], w)
                a["costs"][c]["charged_hh"] += (src.get("charged_hh") or 0) * w
                a["costs"][c]["not_charged_hh"] += (src.get("not_charged_hh") or 0) * w

    out = []
    for a in areas.values():
        hh, pop = a["households"], a["population"]
        res = {k: (round(v, 1) if isinstance(v, float) else v) for k, v in a.items()
               if not k.startswith("_") and k not in BINNED and k != "costs"}
        res["renter_share"] = round(a["renter_hh"] / hh, 4) if hh else None
        res["race_share"] = {r: (round(a[r] / pop, 4) if pop else None) for r in RACE}
        # no bins for all-household income here, so this one is a household-weighted mean of tract medians
        res["median_income_hhwavg"] = round(a["_inc_x_hh"] / a["_inc_hh"]) if a["_inc_hh"] else None
        res["median_income_owner_est"] = median_from_bins(a["income_owner"])
        res["median_income_renter_est"] = median_from_bins(a["income_renter"])
        res["costs"] = {c: {"median_est": median_from_bins(v["bins"]),
                            "charged_hh": round(v["charged_hh"], 1),
                            "not_charged_hh": round(v["not_charged_hh"], 1),
                            "bins": {k: round(n, 1) for k, n in v["bins"].items()}}
                        for c, v in a["costs"].items()}
        out.append(res)
    return sorted(out, key=lambda r: r["area"])
