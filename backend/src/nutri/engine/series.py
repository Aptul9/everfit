"""Weight series: smoothed trend, rate of change, projection."""

import math
from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class Fit:
    slope: float
    intercept: float
    slope_se: float
    n: int


def linfit(xs: list[float], ys: list[float]) -> Fit | None:
    """Ordinary least squares with the standard error of the slope.

    Water retention makes consecutive weigh-ins correlated, which a plain OLS
    standard error ignores and so reports too much confidence. The error is
    widened by the lag-1 autocorrelation of the residuals.
    """
    n = len(xs)
    if n < 3:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return None
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / sxx
    intercept = my - slope * mx
    res = [y - (intercept + slope * x) for x, y in zip(xs, ys, strict=True)]
    rss = sum(r * r for r in res)
    se = math.sqrt(rss / (n - 2) / sxx)
    if n > 4 and rss > 0:
        r1 = sum(a * b for a, b in zip(res, res[1:], strict=False)) / rss
        r1 = max(0.0, min(0.9, r1))
        se *= math.sqrt((1 + r1) / (1 - r1))
    return Fit(slope, intercept, se, n)


def days(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


@dataclass(frozen=True)
class TrendPoint:
    day: date
    weight: float | None
    trend: float | None


def trend_series(
    weights: dict[date, float], start: date, end: date, alpha: float, beta: float = 0.0
) -> list[TrendPoint]:
    """Smoothed weight, carried across days without a weigh-in.

    With `beta` 0 this is a plain exponential moving average, which lags behind
    a steady loss by roughly slope x (1 - alpha) / alpha: half a kilo on a normal
    cut, enough to show a trend above every recent weigh-in. A positive `beta`
    adds a smoothed slope (Holt's linear method) that removes most of that lag.

    Weigh-ins before `start` warm the filter, so a window that opens mid-series
    is not reseeded on whatever noisy value happens to fall on its first day.
    """
    level: float | None = None
    slope = 0.0
    out = []
    first = min(weights, default=start)
    for d in days(min(first, start), end):
        if level is not None:
            level += slope
        w = weights.get(d)
        if w is not None:
            if level is None:
                level = w
            else:
                prev = level - slope
                level += alpha * (w - level)
                slope += beta * ((level - prev) - slope)
        else:
            slope *= 0.98  # damp the slope across gaps so a missing week does not extrapolate wildly
        if d >= start:
            out.append(TrendPoint(d, w, None if level is None else round(level, 3)))
    return out


@dataclass(frozen=True)
class Rate:
    kg_per_week: float
    se_kg_per_week: float
    weighins: int
    span_days: int


def weight_rate(weights: dict[date, float], end: date, window_days: int) -> Rate | None:
    """Regression slope of raw weigh-ins over the window, in kg per week.

    Raw points rather than the smoothed trend: the trend lags by design, the
    regression does not, and its standard error says how much to trust it.
    """
    start = end - timedelta(days=window_days - 1)
    pts = sorted((d, w) for d, w in weights.items() if start <= d <= end)
    if len(pts) < 3:
        return None
    span = (pts[-1][0] - pts[0][0]).days
    if span < 6:
        return None
    xs = [(d - start).days for d, _ in pts]
    fit = linfit(xs, [w for _, w in pts])
    if fit is None:
        return None
    return Rate(fit.slope * 7, fit.slope_se * 7, len(pts), span)


def projection(level: float, rate: Rate, weeks: int, goal: float | None = None) -> dict:
    """Straight-line projection with a widening cone, plus the date a goal is reached."""
    cone = []
    for w in range(weeks + 1):
        center = level + rate.kg_per_week * w
        half = 1.96 * rate.se_kg_per_week * w + 0.3 * math.sqrt(w)
        cone.append(
            {
                "week": w,
                "center": round(center, 2),
                "low": round(center - half, 2),
                "high": round(center + half, 2),
            }
        )
    eta_weeks = None
    if goal is not None and rate.kg_per_week != 0:
        need = (goal - level) / rate.kg_per_week
        if need > 0:
            eta_weeks = round(need, 1)
    return {"cone": cone, "eta_weeks": eta_weeks}
