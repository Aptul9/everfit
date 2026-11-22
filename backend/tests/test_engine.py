from datetime import date, timedelta
from statistics import mean

import pytest

from nutri.engine import expenditure as ex
from nutri.engine.checkin import run_checkin
from nutri.engine.formulas import bmr, prior_expenditure
from nutri.engine.series import trend_series, weight_rate
from nutri.engine.settings import EngineParams, Guardrails, Phase, PhaseTemplate, Profile
from nutri.engine.targets import day_targets

from .sim import Person

START = date(2026, 10, 5)
PARAMS = EngineParams()
GUARD = Guardrails()

DEF = PhaseTemplate(
    id="d",
    name="Definizione",
    kind="deficit",
    rate_pct_week=-0.5,
    band_pct_week=0.15,
    protein_g_per_kg=2.0,
    fat_g_per_kg=0.8,
)


def phase(**kw) -> Phase:
    p = Phase.from_template(DEF, START, 70)
    return p.model_copy(update=kw)


def test_trend_is_smoother_than_the_scale():
    logs, weights = Person().live(START, 42, intake=2150)
    pts = trend_series(weights, START, START + timedelta(days=41), PARAMS.trend_alpha, PARAMS.trend_beta)
    raw = [p.weight for p in pts]
    tr = [p.trend for p in pts]
    jumps_raw = sum(abs(a - b) for a, b in zip(raw, raw[1:], strict=False))
    jumps_tr = sum(abs(a - b) for a, b in zip(tr, tr[1:], strict=False))
    assert jumps_tr < jumps_raw / 4


def test_trend_does_not_lag_behind_a_steady_loss():
    lags_ema, lags_holt = [], []
    for seed in range(30):
        p = Person(seed=seed)
        _, weights = p.live(START, 42, intake=2000)
        end = START + timedelta(days=41)
        ema = trend_series(weights, START, end, PARAMS.trend_alpha)[-1].trend
        holt = trend_series(weights, START, end, PARAMS.trend_alpha, PARAMS.trend_beta)[-1].trend
        true = p.weight - (2000 - p.expenditure) / p.kcal_per_kg  # weight on the last morning
        lags_ema.append(ema - true)
        lags_holt.append(holt - true)
    assert mean(lags_ema) > 0.3  # the plain average sits well above a falling weight
    assert abs(mean(lags_holt)) < 0.15


def test_rate_recovers_the_true_slope():
    p = Person()
    _, weights = p.live(START, 28, intake=2150)
    rate = weight_rate(weights, START + timedelta(days=27), 21)
    true = (2150 - 2500) / 7000 * 7
    assert rate.kg_per_week == pytest.approx(true, abs=0.15)


def _population(n=60, params=PARAMS, prior=2100, **person):
    out = []
    for seed in range(n):
        p = Person(seed=seed, **person)
        logs, weights = p.live(START, 35, intake=2200)
        out.append(
            ex.estimate(
                START + timedelta(days=34), logs, weights, params, prior=prior, prior_sd=params.prior_sd_kcal
            )
        )
    return out


def test_expenditure_converges_on_the_truth_without_bias():
    ests = _population(expenditure=2600)
    assert all(e.status == "data" for e in ests)
    assert mean(e.data_kcal for e in ests) == pytest.approx(2600, abs=50)
    # a prior 500 kcal off still pulls a little after four weeks, and only a little
    assert mean(e.kcal for e in ests) == pytest.approx(2600, abs=90)


def test_expenditure_uncertainty_is_honest():
    ests = _population(expenditure=2600)
    covered = sum(abs(e.kcal - 2600) <= 1.96 * e.sd for e in ests) / len(ests)
    assert covered >= 0.85


def test_consistent_underlogging_gives_logged_units_and_the_offset_corrects_it():
    plain = _population(expenditure=2500, underlog=200, prior=2300)
    fixed = _population(
        expenditure=2500,
        underlog=200,
        prior=2300,
        params=PARAMS.model_copy(update={"logging_offset_kcal": 200}),
    )
    assert mean(e.kcal for e in plain) == pytest.approx(2300, abs=60)
    assert mean(e.kcal for e in fixed) == pytest.approx(2500, abs=60)


def test_few_complete_days_fall_back_to_the_prior():
    p = Person()
    logs, weights = p.live(START, 21, intake=2200, skip_log=set(range(0, 21, 2)) | {1, 3, 5})
    est = ex.estimate(START + timedelta(days=20), logs, weights, PARAMS, prior=2200, prior_sd=300)
    assert est.status == "prior"
    assert est.kcal == 2200


def test_half_logged_days_are_excluded():
    logs = {START: ex.DayLog(900), START + timedelta(days=1): ex.DayLog(2100)}
    assert not ex.is_complete(logs[START], 2200, 0.6)
    assert ex.is_complete(logs[START + timedelta(days=1)], 2200, 0.6)
    assert ex.is_complete(ex.DayLog(900, marked_complete=True), 2200, 0.6)


def test_formula_prior_for_the_owner():
    prof = Profile(sex="M", birth_date=date(1999, 3, 15), height_cm=170, activity="moderato")
    mid, sd = prior_expenditure(prof, 70, 300)
    assert 1900 < mid < 2150
    assert sd >= 300
    assert bmr(prof, 70, date(2026, 11, 22)) == pytest.approx(10 * 70 + 6.25 * 170 - 5 * 27 + 5)


def test_targets_keep_the_weekly_mean_with_refeed_days():
    ph = phase(refeed_days_per_week=1, refeed_weekday=5)
    week = [day_targets(START + timedelta(days=i), ph, 2400, 70, PARAMS, GUARD) for i in range(7)]
    mean = sum(t.macros.kcal for t in week) / 7
    assert mean == pytest.approx(week[0].weekly_mean_kcal, abs=2)
    refeeds = [t for t in week if t.kind == "refeed"]
    assert len(refeeds) == 1 and refeeds[0].day.weekday() == 5
    assert refeeds[0].macros.kcal == 2400


def test_targets_hold_protein_and_the_fat_floor():
    ph = phase(fat_g_per_kg=0.3)
    t = day_targets(START, ph, 2400, 70, PARAMS, GUARD)
    assert t.macros.protein == 140
    assert t.macros.fat == 35  # 0.5 g/kg floor, not 0.3
    assert t.weekly_mean_kcal == round(2400 - 0.35 * 7000 / 7)


def test_targets_flag_the_alarm_threshold():
    ph = phase(kcal_target=1300)
    codes = {f.code for f in day_targets(START, ph, 2400, 70, PARAMS, GUARD).flags}
    assert "kcal_alarm" in codes


def _week(p: Person, intake: float, weeks: int = 3):
    logs, weights = p.live(START, 7 * weeks, intake=intake)
    end = START + timedelta(days=7 * weeks - 1)
    est = ex.estimate(end, logs, weights, PARAMS, prior=2400, prior_sd=300)
    return logs, weights, end, est


def test_checkin_in_band_changes_nothing():
    p = Person(expenditure=2400, intake_sd=80, water_sd=0.15)
    logs, weights, end, est = _week(p, intake=2050)
    r = run_checkin(end, logs, weights, phase(kcal_target=2050), est, 70, PARAMS, GUARD)
    assert r.verdict == "ok"
    assert r.proposal is None


def test_checkin_losing_too_fast_proposes_a_capped_increase():
    p = Person(expenditure=2700, intake_sd=80, water_sd=0.15)
    logs, weights, end, est = _week(p, intake=2050)
    r = run_checkin(end, logs, weights, phase(kcal_target=2050), est, 70, PARAMS, GUARD)
    assert r.verdict == "too_fast_loss"
    assert 0 < r.proposal.delta <= PARAMS.max_weekly_change_kcal
    assert r.proposal.macros_to.protein == r.proposal.macros_from.protein
    assert r.proposal.macros_to.fat == r.proposal.macros_from.fat


def test_checkin_too_slow_waits_a_week_before_cutting():
    p = Person(expenditure=2150, intake_sd=80, water_sd=0.15)
    logs, weights, end, est = _week(p, intake=2050)
    ph = phase(kcal_target=2050)
    first = run_checkin(end, logs, weights, ph, est, 70, PARAMS, GUARD)
    assert first.verdict == "hold_before_cut"
    assert first.proposal is None
    second = run_checkin(
        end, logs, weights, ph, est, 70, PARAMS, GUARD, previous_verdicts=["hold_before_cut"]
    )
    assert second.verdict == "too_slow_loss"
    assert -PARAMS.max_weekly_change_kcal <= second.proposal.delta < 0


def test_checkin_low_adherence_does_not_touch_the_plan():
    p = Person(expenditure=2400, intake_sd=80, water_sd=0.15)
    logs, weights, end, est = _week(p, intake=2500)
    r = run_checkin(end, logs, weights, phase(kcal_target=2050), est, 70, PARAMS, GUARD)
    assert r.verdict == "low_adherence"
    assert r.proposal is None


def test_checkin_without_enough_data_says_so():
    p = Person()
    logs, weights = p.live(START, 14, intake=2100, weigh_every=3)
    end = START + timedelta(days=13)
    est = ex.estimate(end, logs, weights, PARAMS, prior=2400, prior_sd=300)
    r = run_checkin(end, logs, weights, phase(kcal_target=2050), est, 70, PARAMS, GUARD)
    assert r.verdict == "insufficient_data"


def test_checkin_on_fat_moves_fat_not_carbs():
    p = Person(expenditure=2700, intake_sd=80, water_sd=0.15)
    logs, weights, end, est = _week(p, intake=2050)
    r = run_checkin(end, logs, weights, phase(kcal_target=2050, adjust_macro="fat"), est, 70, PARAMS, GUARD)
    assert r.proposal.macros_to.carbs == pytest.approx(r.proposal.macros_from.carbs, abs=1)
    assert r.proposal.macros_to.fat > r.proposal.macros_from.fat
