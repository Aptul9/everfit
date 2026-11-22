"""A synthetic person, so the engine can be tested before a real series exists."""

import random
from dataclasses import dataclass, field
from datetime import date, timedelta

from nutri.engine.expenditure import DayLog


@dataclass
class Person:
    expenditure: float = 2500
    weight: float = 72.0
    kcal_per_kg: float = 7000
    intake_sd: float = 150
    water_sd: float = 0.35
    underlog: float = 0
    seed: int = 7
    rng: random.Random = field(init=False)

    def __post_init__(self):
        self.rng = random.Random(self.seed)

    def live(
        self, start: date, n_days: int, intake: float, weigh_every: int = 1, skip_log: set[int] | None = None
    ):
        logs: dict[date, DayLog] = {}
        weights: dict[date, float] = {}
        water = 0.0
        skip_log = skip_log or set()
        for i in range(n_days):
            d = start + timedelta(days=i)
            eaten = self.rng.gauss(intake, self.intake_sd)
            water = 0.6 * water + self.rng.gauss(0, self.water_sd)
            if i % weigh_every == 0:
                weights[d] = round(self.weight + water, 1)
            if i not in skip_log:
                logs[d] = DayLog(eaten - self.underlog, marked_complete=True)
            self.weight += (eaten - self.expenditure) / self.kcal_per_kg
        return logs, weights
