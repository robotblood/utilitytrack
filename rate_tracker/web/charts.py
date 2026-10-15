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

