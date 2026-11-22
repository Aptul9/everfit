"""Weekly check-in: four numbers, one verdict, at most one proposal.

The coach never changes a target on its own. It proposes; the owner accepts,
edits or rejects. When the data cannot support a decision it says so and
proposes nothing.
"""

from dataclasses import asdict, dataclass, field
from datetime import date, timedelta

from .expenditure import DayLog, Expenditure, is_complete
from .series import days, weight_rate
from .settings import EngineParams, Guardrails, Phase
from .targets import Flag, Macros, check, phase_mean_kcal, split_macros

INCREASE = {"too_fast_loss", "too_slow_gain", "reverse_step"}
DECREASE = {"too_slow_loss", "too_fast_gain"}


@dataclass(frozen=True)
class Reason:
    text: str
    ref: str = ""


@dataclass(frozen=True)
class Proposal:
    kcal_from: float
    kcal_to: float
    macros_from: Macros
    macros_to: Macros
    phase_changes: dict

    @property
    def delta(self) -> float:
        return self.kcal_to - self.kcal_from


@dataclass
class CheckinResult:
    week_start: date
    week_end: date
    weighins: int
    complete_days: int
    mean_intake: float | None
    adherence: float | None
    rate_kg_week: float | None
    rate_se: float | None
    expenditure: float
    expenditure_sd: float
    verdict: str
    headline: str
    proposal: Proposal | None
    reasons: list[Reason] = field(default_factory=list)
    flags: list[Flag] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["week_start"] = self.week_start.isoformat()
        d["week_end"] = self.week_end.isoformat()
        if self.proposal:
            d["proposal"]["delta"] = self.proposal.delta
        return d


def fmt_rate(r: float) -> str:
    return f"{r:+.2f}".replace(".", ",") + " kg/sett"


def adjusted_phase(phase: Phase, weight: float, old_kcal: float, new_kcal: float, guard: Guardrails) -> dict:
    """Phase fields after moving the mean target from `old_kcal` to `new_kcal`.

    Protein stays at the phase value. The difference goes on carbohydrates, on
    fat, or half and half, as the phase says; fat never goes below its floor.
    """
    delta = new_kcal - old_kcal
    changes: dict = {"kcal_target": round(new_kcal)}
    fat_share = {"carbs": 0.0, "fat": 1.0, "mixed": 0.5}[phase.adjust_macro]
    if fat_share:
        fat_g = phase.fat_g_per_kg * weight + delta * fat_share / 9
        fat_gkg = max(guard.fat_min_g_per_kg, fat_g / weight)
        changes["fat_g_per_kg"] = round(fat_gkg, 2)
    return changes


def run_checkin(
    week_end: date,
    logs: dict[date, DayLog],
    weights: dict[date, float],
    phase: Phase,
    exp: Expenditure,
    weight: float,
    params: EngineParams,
    guard: Guardrails,
    previous_verdicts: list[str] | None = None,
    bmr: float | None = None,
) -> CheckinResult:
    previous_verdicts = previous_verdicts or []
    week_start = week_end - timedelta(days=6)
    current = phase_mean_kcal(phase, exp.kcal, params)
    week_weights = [d for d in days(week_start, week_end) if d in weights]
    complete = [
        d
        for d in days(week_start, week_end)
        if is_complete(logs.get(d), current, params.incomplete_threshold)
    ]
    mean_intake = adherence = None
    if complete:
        mean_intake = sum(logs[d].kcal for d in complete) / len(complete) + params.logging_offset_kcal
        adherence = mean_intake / current
    rate = weight_rate(weights, week_end, params.rate_window_days)
    reasons: list[Reason] = []
    macros_now = split_macros(current, weight, phase, guard)
    flags = check(macros_now, weight, exp.kcal, bmr, guard, phase)

    def result(verdict: str, headline: str, proposal: Proposal | None = None) -> CheckinResult:
        return CheckinResult(
            week_start,
            week_end,
            len(week_weights),
            len(complete),
            None if mean_intake is None else round(mean_intake),
            None if adherence is None else round(adherence, 3),
            None if rate is None else round(rate.kg_per_week, 2),
            None if rate is None else round(rate.se_kg_per_week, 2),
            exp.kcal,
            exp.sd,
            verdict,
            headline,
            proposal,
            reasons,
            flags,
        )

    if any(f.severity == "stop" for f in flags):
        reasons.append(
            Reason(
                "Il target attuale viola un limite di sicurezza: nessuna correzione "
                "finché non si rivede la fase.",
                "[p. 336]",
            )
        )
        return result("stop", "Fermati: il target corrente è fuori dai limiti")

    if len(week_weights) < params.checkin_min_weighins or len(complete) < params.checkin_min_complete_days:
        reasons.append(
            Reason(
                f"Pesate {len(week_weights)}/7 (minimo {params.checkin_min_weighins}), "
                f"giorni completi {len(complete)}/7 (minimo {params.checkin_min_complete_days}). "
                "Con meno dati una correzione inseguirebbe il rumore."
            )
        )
        return result("insufficient_data", "Dati insufficienti: nessuna modifica")

    if rate is None:
        reasons.append(Reason("Serve almeno una settimana di pesate per misurare il ritmo."))
        return result("insufficient_data", "Ritmo non ancora misurabile")

    if abs(adherence - 1) > params.adherence_tolerance:
        side = "sopra" if adherence > 1 else "sotto"
        reasons.append(
            Reason(
                f"Hai mangiato in media {round(mean_intake)} kcal, il {abs(adherence - 1):.0%} {side} "
                f"il target di {round(current)}. Prima di cambiare il piano va seguito: la correzione "
                "si decide su un dato affidabile."
            )
        )
        return result("low_adherence", "Aderenza bassa: prima si segue il piano")

    lo, hi = phase.band_kg_week
    r = rate.kg_per_week
    se = f"{rate.se_kg_per_week:.2f}".replace(".", ",")
    reasons.append(Reason(f"Ritmo {fmt_rate(r)} (± {se}), forbice scelta {fmt_rate(lo)} / {fmt_rate(hi)}."))

    if phase.kind == "reverse":
        if r <= phase.rate_kg_week:
            verdict = "reverse_step"
            headline = "Peso sotto controllo: si sale ancora"
            reasons.append(
                Reason(
                    f"Nel reset si sale di circa {phase.reverse_step_kcal:g} kcal ogni "
                    "7-14 giorni finché il peso tiene.",
                    "[p. 319]",
                )
            )
            delta = phase.reverse_step_kcal
        else:
            reasons.append(
                Reason(
                    "Il peso sale più del tetto: si tengono le calorie per un paio di settimane.", "[p. 318]"
                )
            )
            return result("hold", "Peso in salita: si tiene")
    elif r < lo:
        verdict = "too_fast_loss" if phase.rate_kg_week <= 0 else "too_slow_gain"
    elif r > hi:
        verdict = "too_fast_gain" if phase.rate_kg_week >= 0 else "too_slow_loss"
    else:
        reasons.append(Reason("Dentro la forbice: il piano funziona, non si tocca."))
        return result("ok", "In linea: nessuna modifica")

    if verdict in DECREASE:
        streak = 1
        for v in reversed(previous_verdicts):
            if v in DECREASE or v == "hold_before_cut":
                streak += 1
            else:
                break
        if streak < params.weeks_before_cut:
            reasons.append(
                Reason(
                    f"Prima settimana fuori forbice: si tiene ancora ({streak}/{params.weeks_before_cut}). "
                    "Il peso scende a onde, una settimana non basta.",
                    "[p. 318, p. 327]",
                )
            )
            return result("hold_before_cut", "Fuori ritmo, ma si aspetta una settimana")

    if verdict != "reverse_step":
        desired = exp.kcal + phase.rate_kg_week * params.kcal_per_kg / 7
        delta = desired - current
        direction = 1 if verdict in INCREASE else -1
        if delta * direction <= 0:
            # the expenditure estimate disagrees with the scale; follow the scale
            delta = (phase.rate_kg_week - r) * params.kcal_per_kg / 7
        cap = params.max_weekly_change_kcal
        delta = max(-cap, min(cap, delta))
        delta = round(delta / 25) * 25 or 25 * direction
        reasons.append(
            Reason(
                f"Metabolismo stimato {round(exp.kcal)} ± {round(exp.sd)} kcal: per il ritmo scelto "
                f"servirebbero {round(desired)} kcal. Correzione limitata a ±{cap:g} kcal.",
                "[p. 25]",
            )
        )

    new_kcal = current + delta
    changes = adjusted_phase(phase, weight, current, new_kcal, guard)
    new_phase = phase.model_copy(update=changes)
    macros_new = split_macros(new_kcal, weight, new_phase, guard)
    new_flags = check(macros_new, weight, exp.kcal, bmr, guard, new_phase)
    if any(f.severity == "stop" for f in new_flags):
        reasons.append(Reason("La correzione porterebbe fuori dai limiti di sicurezza: non la propongo."))
        return result("stop", "Limite di sicurezza raggiunto")

    headline = {
        "too_fast_loss": "Perdi più in fretta del ritmo scelto",
        "too_slow_loss": "Perdi più lentamente del ritmo scelto",
        "too_fast_gain": "Aumenti più in fretta del ritmo scelto",
        "too_slow_gain": "Aumenti più lentamente del ritmo scelto",
        "reverse_step": "Peso sotto controllo: si sale ancora",
    }[verdict]
    if phase.duration_weeks:
        week_n = (week_end - phase.start).days // 7 + 1
        if week_n >= phase.duration_weeks:
            reasons.append(
                Reason(
                    f"Settimana {week_n} di {phase.duration_weeks}: il libro prevede 1-2 settimane in "
                    "normocalorica prima del taglio successivo.",
                    "[p. 326]",
                )
            )
    proposal = Proposal(round(current), round(new_kcal), macros_now.rounded(), macros_new.rounded(), changes)
    out = result(verdict, headline, proposal)
    out.flags = new_flags
    return out
