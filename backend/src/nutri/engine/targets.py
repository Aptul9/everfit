"""Daily targets from the active phase, the expenditure estimate and the weight."""

from dataclasses import asdict, dataclass, field
from datetime import date

from .settings import EngineParams, Guardrails, Phase


@dataclass(frozen=True)
class Flag:
    code: str
    severity: str  # "info" | "warning" | "stop"
    message: str
    source: str = ""


@dataclass(frozen=True)
class Macros:
    kcal: float
    protein: float
    carbs: float
    fat: float

    def rounded(self) -> Macros:
        return Macros(round(self.kcal), round(self.protein), round(self.carbs), round(self.fat))


@dataclass(frozen=True)
class DayTargets:
    day: date
    kind: str  # "normal" | "refeed"
    macros: Macros
    weekly_mean_kcal: float
    flags: list[Flag] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["day"] = self.day.isoformat()
        return d


def phase_mean_kcal(phase: Phase, expenditure: float, params: EngineParams) -> float:
    """The weekly-average daily target: the check-in's value if one was set,
    otherwise expenditure shifted by the energy the target rate implies."""
    if phase.kcal_target is not None:
        return phase.kcal_target
    if phase.kind == "reverse":
        return expenditure
    return expenditure + phase.rate_kg_week * params.kcal_per_kg / 7


def split_macros(kcal: float, weight: float, phase: Phase, guard: Guardrails) -> Macros:
    protein = phase.protein_g_per_kg * weight
    fat = max(phase.fat_g_per_kg, guard.fat_min_g_per_kg) * weight
    carbs = (kcal - 4 * protein - 9 * fat) / 4
    return Macros(kcal, protein, carbs, fat)


def check(
    m: Macros, weight: float, expenditure: float, bmr: float | None, guard: Guardrails, phase: Phase
) -> list[Flag]:
    flags = []
    if m.carbs < 0:
        flags.append(
            Flag(
                "carbs_negative",
                "stop",
                "Proteine e grassi superano già le calorie: il target non è fattibile.",
            )
        )
    elif m.carbs < guard.carbs_min_g_per_kg * weight:
        flags.append(
            Flag(
                "carbs_low",
                "warning",
                f"Carboidrati sotto {guard.carbs_min_g_per_kg} g/kg.",
                "Fabbisogno basale di glucosio [p. 47]",
            )
        )
    if m.kcal < guard.min_kcal_per_kg * weight:
        flags.append(
            Flag(
                "kcal_alarm",
                "stop",
                f"Sotto {guard.min_kcal_per_kg:g} kcal/kg: fermarsi e verificare gli esami.",
                "[p. 336]",
            )
        )
    if bmr is not None and m.kcal < bmr:
        flags.append(
            Flag(
                "below_bmr",
                "warning",
                f"Sotto il metabolismo basale stimato ({round(bmr)} kcal).",
                "corpus/method/02-bilancio-energetico.md, guardrail",
            )
        )
    if m.kcal > 0 and 4 * m.protein / m.kcal * 100 > guard.protein_max_pct_kcal:
        flags.append(
            Flag(
                "protein_high",
                "warning",
                f"Proteine oltre il {guard.protein_max_pct_kcal:g}% delle calorie.",
                "Tetto IOM [p. 70]",
            )
        )
    if phase.kind == "deficit" and expenditure > 0:
        deficit = (expenditure - m.kcal) / expenditure * 100
        if deficit > guard.max_deficit_pct:
            flags.append(
                Flag(
                    "deficit_high",
                    "warning",
                    f"Deficit del {deficit:.0f}%, oltre il {guard.max_deficit_pct:g}%.",
                    "[p. 25]",
                )
            )
    if phase.kind == "deficit" and -phase.rate_kg_week / weight * 100 > guard.max_loss_pct_week:
        flags.append(
            Flag(
                "rate_high",
                "warning",
                f"Ritmo oltre l'{guard.max_loss_pct_week:g}% del peso a settimana.",
                "[p. 25, p. 325]",
            )
        )
    return flags


def day_targets(
    day: date,
    phase: Phase,
    expenditure: float,
    weight: float,
    params: EngineParams,
    guard: Guardrails,
    bmr: float | None = None,
) -> DayTargets:
    """Targets for one day. Refeed days sit at expenditure, the rest absorb the
    difference, so the weekly mean is unchanged: the book counts the deficit on
    the week, not on the day [p. 326]."""
    mean = phase_mean_kcal(phase, expenditure, params)
    r = phase.refeed_days_per_week
    refeed_days = {(phase.refeed_weekday - i) % 7 for i in range(r)}
    kind = "normal"
    kcal = mean
    if r and mean < expenditure:
        if day.weekday() in refeed_days:
            kind, kcal = "refeed", expenditure
        else:
            kcal = (7 * mean - r * expenditure) / (7 - r)
    m = split_macros(kcal, weight, phase, guard)
    flags = check(split_macros(mean, weight, phase, guard), weight, expenditure, bmr, guard, phase)
    if kind == "normal" and r and kcal < guard.min_kcal_per_kg * weight:
        flags.append(
            Flag("normal_day_low", "warning", "I giorni non di ricarica scendono sotto la soglia di allarme.")
        )
    return DayTargets(day, kind, m.rounded(), round(mean), flags)
