"""The book's expenditure formulas, transcribed in corpus/tables/p024-formule-metabolismo.md.

The book gives several and refuses to pick one: "Provatele e misurate" [p. 25].
So these only seed the estimate; the weight series decides.
"""

from dataclasses import dataclass
from datetime import date

from .settings import Profile

# Lyle McDonald coefficients per activity level [p. 24]
MCDONALD = {"sedentario": (10, 11), "moderato": (12, 13), "intenso": (18, 19)}
# Height-only formula, preferred when overweight [p. 24]
HEIGHT = {"M": (700, 750), "F": (600, 650)}


@dataclass(frozen=True)
class FormulaEstimate:
    name: str
    low: float
    high: float
    source: str

    @property
    def mid(self) -> float:
        return (self.low + self.high) / 2


def bmr(profile: Profile, weight_kg: float, on: date) -> float | None:
    """Basal rate from the formula the book uses as its example [p. 23].

    The book prints the male constant (+5) only; the female one (-161) is the
    standard Mifflin-St Jeor value and is outside the book.
    """
    age = profile.age(on)
    if age is None or profile.height_cm is None:
        return None
    const = 5 if profile.sex == "M" else -161
    return 10 * weight_kg + 6.25 * profile.height_cm - 5 * age + const


def expenditure_formulas(profile: Profile, weight_kg: float) -> list[FormulaEstimate]:
    out = []
    lo, hi = MCDONALD[profile.activity]
    out.append(
        FormulaEstimate(
            "Lyle McDonald", weight_kg * 2.2 * lo, weight_kg * 2.2 * hi, "tables/p024, 4a formula [p. 24]"
        )
    )
    if profile.height_cm:
        m2 = (profile.height_cm / 100) ** 2
        lo, hi = HEIGHT[profile.sex]
        out.append(FormulaEstimate("Sulla sola altezza", m2 * lo, m2 * hi, "tables/p024, 5a formula [p. 24]"))
    return out


def prior_expenditure(profile: Profile, weight_kg: float, min_sd: float) -> tuple[float, float]:
    """Centre of the formula ranges, with an uncertainty at least `min_sd` wide."""
    est = expenditure_formulas(profile, weight_kg)
    lows = [e.low for e in est]
    highs = [e.high for e in est]
    mid = sum(e.mid for e in est) / len(est)
    spread = (max(highs) - min(lows)) / 2
    return round(mid), round(max(min_sd, spread))
