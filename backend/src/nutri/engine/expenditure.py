"""Adaptive expenditure: what the weight series says you burn.

    expenditure = mean real intake - (weight slope x energy per kg)

over the complete days of a window, blended with the formula prior by the
inverse of each one's variance. Early on the prior dominates and the
uncertainty is wide; as complete days accumulate the data takes over.

A consistent logging gap does not break this: the estimate is then in the
units of what gets logged, and targets set in those units still work. Days
logged by half do break it, which is why only complete days count.
"""

import math
from dataclasses import dataclass
from datetime import date, timedelta

from .series import days, linfit
from .settings import EngineParams


@dataclass(frozen=True)
class DayLog:
    kcal: float
    protein: float = 0
    carbs: float = 0
    fat: float = 0
    marked_complete: bool | None = None


def is_complete(log: DayLog | None, reference_kcal: float, threshold: float) -> bool:
    """A day marked in either direction is taken at its word; otherwise it must
    reach `threshold` of the reference to count."""
    if log is None:
        return False
    if log.marked_complete is not None:
        return log.marked_complete
    return log.kcal >= threshold * reference_kcal


@dataclass(frozen=True)
class Expenditure:
    day: date
    kcal: float
    sd: float
    prior: float
    prior_sd: float
    data_kcal: float | None
    data_sd: float | None
    complete_days: int
    weighins: int
    mean_intake: float | None
    status: str  # "prior" | "data"


def estimate(
    day: date,
    logs: dict[date, DayLog],
    weights: dict[date, float],
    params: EngineParams,
    prior: float,
    prior_sd: float,
    reference_kcal: float | None = None,
) -> Expenditure:
    ref = reference_kcal or prior
    start = day - timedelta(days=params.expenditure_window_days - 1)
    complete = [
        logs[d].kcal + params.logging_offset_kcal
        for d in days(start, day)
        if is_complete(logs.get(d), ref, params.incomplete_threshold)
    ]
    pts = sorted((d, w) for d, w in weights.items() if start <= d <= day)
    data_kcal = data_sd = mean_intake = None
    if complete:
        mean_intake = sum(complete) / len(complete)
    if (
        len(complete) >= params.min_complete_days
        and len(pts) >= params.min_weighins
        and (pts[-1][0] - pts[0][0]).days >= 7
    ):
        fit = linfit([(d - start).days for d, _ in pts], [w for _, w in pts])
        if fit is not None:
            n = len(complete)
            sd_intake = math.sqrt(sum((k - mean_intake) ** 2 for k in complete) / (n - 1))
            data_kcal = mean_intake - fit.slope * params.kcal_per_kg
            data_sd = max(60.0, math.sqrt(sd_intake**2 / n + (fit.slope_se * params.kcal_per_kg) ** 2))
    if data_kcal is None:
        return Expenditure(
            day, prior, prior_sd, prior, prior_sd, None, None, len(complete), len(pts), mean_intake, "prior"
        )
    wp, wd = 1 / prior_sd**2, 1 / data_sd**2
    kcal = (prior * wp + data_kcal * wd) / (wp + wd)
    sd = math.sqrt(1 / (wp + wd))
    return Expenditure(
        day,
        round(kcal),
        round(sd),
        prior,
        prior_sd,
        round(data_kcal),
        round(data_sd),
        len(complete),
        len(pts),
        round(mean_intake),
        "data",
    )


def estimate_series(
    start: date,
    end: date,
    logs: dict[date, DayLog],
    weights: dict[date, float],
    params: EngineParams,
    prior: float,
    prior_sd: float,
) -> list[Expenditure]:
    """One estimate per day; each uses the previous one as its completeness reference."""
    out = []
    ref = prior
    for d in days(start, end):
        e = estimate(d, logs, weights, params, prior, prior_sd, ref)
        out.append(e)
        ref = e.kcal
    return out
