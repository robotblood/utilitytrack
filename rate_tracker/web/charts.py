"""SVG geometry for the /explore charts. Templates draw; this decides where things go."""
import math


def _ticks(lo: float, hi: float, step: float) -> list[float]:
    return [lo + i * step for i in range(int(round((hi - lo) / step)) + 1)]


def usage_chart(curves: dict, usages: list[float], width: int = 880, height: int = 320) -> dict:
    """Effective cents per unit against monthly usage, one path per season and reading."""
    left, right, top, bottom = 44, 16, 12, 30
    cents = [r["cents"] for c in curves.values() for k in ("fixed_charge", "minimum_bill") for r in c[k]]
    hi = math.ceil(max(cents) / 10) * 10
    u0, u1 = usages[0], usages[-1]
    x = lambda u: round(left + (u - u0) / (u1 - u0) * (width - left - right), 1)
    y = lambda v: round(top + (hi - v) / hi * (height - top - bottom), 1)
    paths = {season: {k: " ".join(f"{'M' if i == 0 else 'L'}{x(r['usage'])},{y(r['cents'])}"
                                  for i, r in enumerate(c[k]))
                      for k in ("fixed_charge", "minimum_bill")}
             for season, c in curves.items()}
    step = 500 if u1 - u0 > 1500 else 250
    return {"width": width, "height": height, "left": left, "right": width - right, "top": top,
            "bottom": height - bottom, "paths": paths,
            "scale": {"u0": u0, "u1": u1, "x0": left, "x1": width - right, "hi": hi,
                      "y0": top, "y1": height - bottom},
            "xticks": [{"v": int(u), "x": x(u)} for u in range(int(math.ceil(u0 / step) * step),
                                                               int(u1) + 1, step)],
            "yticks": [{"v": int(v), "y": y(v)} for v in _ticks(0, hi, 10)]}



def _ring(coords, x, y) -> str:
    pts = [f"{x(lon)},{y(lat)}" for lon, lat in coords]
    return "M" + "L".join(pts) + "Z"


def tract_map(features: list[tuple[str, dict, object]], landmarks: list, width: int = 880,
              tolerance: float = 0.0004) -> dict:
    """SVG paths for tract shapes (lon/lat), plus county outlines and landmark points.

    Equirectangular with the x scale shrunk by cos(mid-latitude): close enough across one metro.
    Shapes are simplified first (~40 m) to keep the page small.
    """
    from shapely.ops import unary_union

    minx, miny, maxx, maxy = unary_union([g for _, _, g in features]).bounds
    k = math.cos(math.radians((miny + maxy) / 2))
    s = width / ((maxx - minx) * k)
    x = lambda lon: round((lon - minx) * k * s, 1)
    y = lambda lat: round((maxy - lat) * s, 1)

    def path(geom) -> str:
        polys = getattr(geom, "geoms", [geom])
        return "".join(_ring(p.exterior.coords, x, y) + "".join(_ring(i.coords, x, y) for i in p.interiors)
                       for p in polys)

    counties: dict[str, list] = {}
    for _, props, g in features:
        counties.setdefault(props.get("NAMELSADCO") or props.get("COUNTYFP"), []).append(g)
    return {"width": width, "height": round((maxy - miny) * s),
            "tracts": {gid: path(g.simplify(tolerance, preserve_topology=True)) for gid, _, g in features},
            "counties": [{"name": name, "d": path(unary_union(gs).simplify(tolerance))}
                         for name, gs in counties.items()],
            "landmarks": [{"name": n, "x": x(lon), "y": y(lat)} for n, lon, lat in landmarks]}


def scatter_scale(points: list[dict], width: int = 880, height: int = 420) -> dict:
    """Axes for monthly energy cost (y) against median income (x), plus 6% and 10% burden rays."""
    left, right, top, bottom = 52, 20, 26, 34  # top room for the burden-line labels
    incomes = [v for p in points for v in p["income"].values() if v]
    xhi = math.ceil(max(incomes) / 50000 - 0.01) * 50000  # 250,001 is ACS's top code for "$250,000+"
    yhi = math.ceil(max(p["cost"] for p in points) / 100) * 100
    x = lambda v: round(left + v / xhi * (width - left - right), 1)
    y = lambda v: round(top + (yhi - v) / yhi * (height - top - bottom), 1)
    rays = []
    for rate in (0.06, 0.10):
        inc = min(xhi, yhi * 12 / rate)  # where cost = rate x income / 12 leaves the plot
        rays.append({"rate": rate, "x2": x(inc), "y2": y(inc * rate / 12), "x0": x(0), "y0": y(0)})
    return {"width": width, "height": height, "left": left, "right": width - right, "top": top,
            "bottom": height - bottom, "rays": rays,
            "scale": {"xhi": xhi, "yhi": yhi, "x0": left, "x1": width - right,
                      "y0": top, "y1": height - bottom},
            "xticks": [{"v": v, "x": x(v)} for v in range(0, xhi + 1, 50000)],
            "yticks": [{"v": v, "y": y(v)} for v in range(0, yhi + 1, 100)]}
