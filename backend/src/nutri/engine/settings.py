"""User-editable configuration.

Nothing the coach decides with is a constant in code: every threshold lives in
one of these models, carries its default, and names where the default comes
from. The UI renders the description and source next to each field.
"""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

Sex = Literal["M", "F"]
Activity = Literal["sedentario", "moderato", "intenso"]
AdjustMacro = Literal["carbs", "fat", "mixed"]
PhaseKind = Literal["deficit", "maintenance", "surplus", "reverse"]


def src(text: str) -> dict:
    return {"source": text}


class Profile(BaseModel):
    sex: Sex = "M"
    birth_date: date | None = None
    height_cm: float | None = Field(None, gt=100, lt=250)
    activity: Activity = Field(
        "moderato",
        description="Livello di attività per la stima iniziale del metabolismo",
        json_schema_extra=src("tables/p024 (Lyle McDonald)"),
    )
    goal_weight_kg: float | None = Field(None, gt=30, lt=250, description="Peso obiettivo, facoltativo")

    def age(self, on: date) -> int | None:
        if self.birth_date is None:
            return None
        b = self.birth_date
        return on.year - b.year - ((on.month, on.day) < (b.month, b.day))


class EngineParams(BaseModel):
    kcal_per_kg: float = Field(
        7000,
        ge=3000,
        le=9500,
        description="Energia di 1 kg di peso perso o guadagnato",
        json_schema_extra=src("Energia di 1 kg di adipe [p. 25]"),
    )
    trend_alpha: float = Field(
        0.1,
        gt=0,
        le=1,
        description="Quanto il trend segue la pesata del giorno (più basso = più liscio)",
        json_schema_extra=src("Media mobile esponenziale, The Hacker's Diet"),
    )
    trend_beta: float = Field(
        0.05,
        ge=0,
        le=0.5,
        description="Quanto il trend segue la pendenza (0 = media mobile semplice, in ritardo sul calo)",
        json_schema_extra=src("Metodo lineare di Holt"),
    )
    rate_window_days: int = Field(
        14,
        ge=7,
        le=56,
        description="Giorni usati per misurare il ritmo di variazione del peso",
        json_schema_extra=src("Trend settimanale, non la misura del giorno [p. 325]"),
    )
    expenditure_window_days: int = Field(
        28,
        ge=10,
        le=84,
        description="Giorni usati per stimare il metabolismo dai dati",
    )
    min_complete_days: int = Field(
        10,
        ge=5,
        description="Giorni di diario completi necessari per stimare il metabolismo",
    )
    min_weighins: int = Field(
        8, ge=4, description="Pesate necessarie nella finestra di stima del metabolismo"
    )
    prior_sd_kcal: float = Field(
        400,
        ge=50,
        description="Incertezza della stima iniziale da formula",
        json_schema_extra=src("Il libro: le formule vanno verificate sul peso [p. 25]"),
    )
    logging_offset_kcal: float = Field(
        0,
        ge=0,
        le=1500,
        description="Calorie mangiate ma non loggate, aggiunte a ogni giorno completo",
        json_schema_extra=src("data/story.md: quanto fidarsi del diario"),
    )
    incomplete_threshold: float = Field(
        0.6,
        ge=0,
        le=1,
        description="Sotto questa frazione del target, un giorno non segnato è incompleto",
    )
    max_weekly_change_kcal: float = Field(
        150,
        ge=25,
        le=500,
        description="Tetto della correzione proposta a ogni check-in",
        json_schema_extra=src("Tagli di 50-100 kcal ogni 7-21 giorni [p. 25]"),
    )
    checkin_min_weighins: int = Field(5, ge=2, le=7, description="Pesate minime nella settimana")
    checkin_min_complete_days: int = Field(
        5, ge=2, le=7, description="Giorni di diario completi minimi nella settimana"
    )
    adherence_tolerance: float = Field(
        0.10,
        ge=0.02,
        le=0.5,
        description="Scarto massimo tra mangiato e target per fidarsi del check-in",
    )
    weeks_before_cut: int = Field(
        2,
        ge=1,
        le=4,
        description="Settimane sotto il ritmo prima di proporre un taglio",
        json_schema_extra=src("Quando le misure deludono si tiene 2-3 settimane [p. 318]"),
    )
    plan_kcal_tolerance: float = Field(
        50, ge=10, le=300, description="Scarto ammesso tra piano alimentare e target"
    )


class Guardrails(BaseModel):
    fat_min_g_per_kg: float = Field(
        0.5,
        ge=0,
        description="Grassi minimi",
        json_schema_extra=src("corpus/external/2026-09-06-grassi-minimo.md"),
    )
    min_kcal_per_kg: float = Field(
        20,
        ge=0,
        description="Introito sotto cui fermarsi e verificare",
        json_schema_extra=src("Soglia di allarme [p. 336]"),
    )
    protein_max_pct_kcal: float = Field(
        35,
        ge=10,
        le=60,
        description="Proteine massime in percentuale delle calorie",
        json_schema_extra=src("Tetto IOM della dieta iperproteica [p. 70]"),
    )
    carbs_min_g_per_kg: float = Field(
        2.5,
        ge=0,
        description="Carboidrati sotto cui avvisare",
        json_schema_extra=src("Fabbisogno basale di glucosio 2,5-2,6 g/kg [p. 47]"),
    )
    max_deficit_pct: float = Field(
        20,
        ge=5,
        le=50,
        description="Deficit massimo rispetto al metabolismo stimato",
        json_schema_extra=src("Deficit del 10-20% [p. 25]"),
    )
    max_loss_pct_week: float = Field(
        1.0,
        ge=0.25,
        le=2,
        description="Perdita settimanale massima in percentuale del peso",
        json_schema_extra=src("0,5-1% del peso a settimana [p. 25, p. 325]"),
    )


class PhaseTemplate(BaseModel):
    id: str
    name: str
    description: str = ""
    source: str = ""
    builtin: bool = False
    kind: PhaseKind
    rate_pct_week: float = Field(description="Variazione di peso obiettivo, % a settimana")
    band_pct_week: float = Field(0.15, ge=0, description="Tolleranza attorno al ritmo")
    protein_g_per_kg: float = Field(ge=0.5, le=4)
    fat_g_per_kg: float = Field(ge=0.2, le=2.5)
    refeed_days_per_week: int = Field(0, ge=0, le=3)
    refeed_weekday: int = Field(5, ge=0, le=6, description="0 = lunedì")
    duration_weeks: int | None = Field(None, ge=1, le=52)
    adjust_macro: AdjustMacro = "carbs"
    reverse_step_kcal: float = Field(50, ge=10, le=200)


class Phase(BaseModel):
    """The active phase: a template instantiated on a start date and weight."""

    template_id: str
    name: str
    kind: PhaseKind
    modified: bool = False
    start: date
    duration_weeks: int | None = None
    rate_kg_week: float
    band_kg_week: tuple[float, float]
    protein_g_per_kg: float
    fat_g_per_kg: float
    refeed_days_per_week: int = 0
    refeed_weekday: int = 5
    adjust_macro: AdjustMacro = "carbs"
    reverse_step_kcal: float = 50
    kcal_target: float | None = Field(
        None, description="Target giornaliero medio corrente, aggiornato dai check-in"
    )

    @classmethod
    def from_template(cls, t: PhaseTemplate, start: date, weight_kg: float) -> Phase:
        rate = round(weight_kg * t.rate_pct_week / 100, 2)
        band = round(weight_kg * t.band_pct_week / 100, 2)
        return cls(
            template_id=t.id,
            name=t.name,
            kind=t.kind,
            start=start,
            duration_weeks=t.duration_weeks,
            rate_kg_week=rate,
            band_kg_week=(round(rate - band, 2), round(rate + band, 2)),
            protein_g_per_kg=t.protein_g_per_kg,
            fat_g_per_kg=t.fat_g_per_kg,
            refeed_days_per_week=t.refeed_days_per_week,
            refeed_weekday=t.refeed_weekday,
            adjust_macro=t.adjust_macro,
            reverse_step_kcal=t.reverse_step_kcal,
        )


class Settings(BaseModel):
    profile: Profile = Profile()
    engine: EngineParams = EngineParams()
    guardrails: Guardrails = Guardrails()
