"""Criterion 1, and the four outcomes: does the gate actually separate luck from edge?

The headline acceptance test of C6. Two synthetic strategies with known truth (see
``tests/validation_helpers.py``), the same market shape, the same costs, the same
benchmark, the same window, the same gate — and the only difference is that one family
has real edge and the other is 200 configurations of noise from which the best was
picked.

Both go through the full loop: walk-forward re-fitting per fold, deflation against the
trial count the log actually holds, cost-breakeven, tail metrics, and the risk-matched
increment over an always-on benchmark.

What the separation rests on, measured rather than assumed — see
``test_the_separation_is_wide_and_the_report_says_where_it_comes_from`` for the numbers.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from validation_helpers import (
    benchmark_series,
    evidence,
    fold_runner,
    genuine_family,
    overfit_family,
    trading_sessions,
)
from xman_research import DataWindow, HypothesisRecord, ManualClock, open_session
from xman_research.validation.decision import (
    GateStatus,
    HoldoutRequiredError,
    MetricNotReportedError,
    Outcome,
    ValidationConfig,
    Validator,
)
from xman_research.validation.gate import HoldoutTouchedError
from xman_research.validation.pbo import performance_matrix, probability_of_backtest_overfitting
from xman_research.validation.series import FeasibilityFacts
from xman_research.validation.statistics import BenchmarkMismatchError
from xman_research.validation.walkforward import walk_forward

IN_SAMPLE_START = dt.date(2021, 1, 4)
IN_SAMPLE_LENGTH = 1200
HOLDOUT_START = dt.date(2026, 1, 5)
HOLDOUT_LENGTH = 250
RUN_AT = dt.datetime(2026, 8, 5, 12, 0, tzinfo=dt.UTC)
RECORDED_AT = dt.datetime(2026, 8, 1, 9, 0, tzinfo=dt.UTC)

GATE_BODY = """
recorded_at = 2026-08-01T09:00:00Z
cross_epoch_justification = "The 2024-2026 breaks are cost- and calendar-side. The \
variance-premium mechanism under test is unchanged by them, and splitting the window \
per regime leaves too few sessions to deflate against. Pooled deliberately; the \
per-regime split is the first follow-up if this passes."

[thresholds]
deflated_sharpe = { at_least = 0.95 }
cost_breakeven_multiple = { at_least = 2.0 }
risk_matched_increment = { at_least = 0.0 }
max_drawdown = { at_most = 0.35 }
pbo = { at_most = 0.5 }

# The holdout is a fifth of the in-sample evidence. A deflated-Sharpe bar calibrated on
# four years is unreachable on one; these are the criteria for that run, recorded at the
# same moment as the others and not after seeing it.
[holdout_thresholds]
probabilistic_sharpe = { at_least = 0.95 }
cost_breakeven_multiple = { at_least = 2.0 }
risk_matched_increment = { at_least = 0.0 }

[not_evaluable]
max_infeasible_fraction = 0.10
max_stale_fraction = 0.20
optimistic_costs_below = 1.0
"""

THRESHOLDS = {
    "deflated_sharpe": 0.95,
    "cost_breakeven_multiple": 2.0,
    "risk_matched_increment": 0.0,
    "max_drawdown": 0.35,
    "pbo": 0.5,
}


def make_hypothesis(name: str) -> HypothesisRecord:
    return HypothesisRecord(
        name=name,
        mechanism=(
            "Index hedgers pay up for downside protection, so implied variance sits above "
            "subsequent realised variance and a short-variance position collects the "
            "difference as compensation for bearing crash risk."
        ),
        null_hypothesis=(
            "Implied minus realised variance has no positive mean after statutory costs, "
            "and the strategy does not beat the always-on benchmark risk-matched."
        ),
        thresholds=dict(THRESHOLDS),
        predictors=["iv_30d", "realised_vol_20d"],
    )


@pytest.fixture
def workspace(tmp_path: Path) -> tuple[ValidationConfig, Validator]:
    (tmp_path / "gate.toml").write_text(GATE_BODY)
    (tmp_path / "validation.toml").write_text(
        'trial_log_path = "research.db"\n'
        'gate_path = "gate.toml"\n'
        f"holdout_first_date = {HOLDOUT_START.isoformat()}\n"
    )
    config = ValidationConfig.from_file(tmp_path / "validation.toml")
    clock = ManualClock(dt.datetime(2026, 8, 6, 10, 0, tzinfo=dt.UTC))
    return config, Validator(config, clock=clock)


def log_the_search(
    config: ValidationConfig, record: HypothesisRecord, *, how_many: int, sharpes: list[float]
) -> None:
    """Write the trials the researcher actually ran, so the deflation can read them."""
    window = DataWindow(IN_SAMPLE_START, dt.date(2025, 8, 1))
    clock = ManualClock(dt.datetime(2026, 7, 1, 9, 0, tzinfo=dt.UTC), step=dt.timedelta(minutes=1))
    with open_session(config.trial_log_path, clock=clock) as session:
        session.register(record)
        for index in range(how_many):
            with session.trial(record, data_window=window, params={"variant": index}) as trial:
                trial.record_metrics(sharpe_per_period=sharpes[index % len(sharpes)])


def pbo_for(family, *, how_many: int = 12, partitions: int = 8):
    """CSCV over the configurations the family actually contains."""
    subset = dict(list(family.net.items())[:how_many])
    return probability_of_backtest_overfitting(
        performance_matrix({name: family.series(name) for name in subset}), partitions=partitions
    )


def grade_family(
    validator: Validator,
    config: ValidationConfig,
    *,
    record: HypothesisRecord,
    seed: int,
    genuine: bool,
):
    dates = trading_sessions(IN_SAMPLE_START, IN_SAMPLE_LENGTH)
    family = genuine_family(dates, seed=seed) if genuine else overfit_family(dates, seed=seed)
    log_the_search(
        config,
        record,
        how_many=len(family.net),
        sharpes=[0.02, 0.05, 0.08, 0.11, 0.14] if genuine else [0.0, 0.03, -0.02, 0.05, 0.01],
    )
    report = walk_forward(dates, run=fold_runner(family), train_length=250, test_length=50)
    chosen = family.best_on(DataWindow(dates[0], dates[-1]))
    candidate = evidence(family.series(chosen), label=f"{family.label} candidate", run_at=RUN_AT)
    naive = evidence(
        benchmark_series(dates, seed=seed + 500), label="naive always-on", run_at=RUN_AT
    )
    overfitting = pbo_for(family, how_many=40)
    verdict = validator.grade(
        candidate,
        benchmark=naive,
        hypothesis=record,
        walk_forward=report,
        overfitting=overfitting,
    )
    return verdict, report


# ------------------------------------------------------------------- criterion 1


def test_a_known_overfit_strategy_is_rejected_and_a_known_genuine_one_passes(
    workspace: tuple[ValidationConfig, Validator],
) -> None:
    """The headline criterion. Same shape, same costs, same gate; only the edge differs."""
    config, validator = workspace
    genuine_record = make_hypothesis("H1 — index variance risk premium")
    overfit_record = make_hypothesis("H1b — best of 200 entry-time variants")
    # Separate records with no parent link, so they are separate families: pooling them
    # would deflate the genuine result by the overfit search's 200 trials and the test
    # would "separate" them for a bookkeeping reason rather than a statistical one.
    assert genuine_record.id != overfit_record.id

    genuine_verdict, genuine_report = grade_family(
        validator, config, record=genuine_record, seed=11, genuine=True
    )
    overfit_verdict, overfit_report = grade_family(
        validator, config, record=overfit_record, seed=22, genuine=False
    )

    assert genuine_verdict.status is GateStatus.PASSED, genuine_verdict.summary()
    assert overfit_verdict.status is GateStatus.FAILED, overfit_verdict.summary()

    # And the deflation saw the searches the log actually holds, not a number either
    # verdict was told.
    assert genuine_verdict.deflated.selection_size == 12
    assert overfit_verdict.deflated.selection_size == 200
    assert len(genuine_report.folds) == len(overfit_report.folds) == 19


@pytest.mark.parametrize("seed", [11, 12, 13])
def test_the_separation_holds_across_seeds(
    workspace: tuple[ValidationConfig, Validator], seed: int
) -> None:
    """The claim rests on a random draw, so it is checked on three of them.

    What is robust across all three is the *separation*: the genuine family's deflated
    Sharpe is far above the noise family's, its cost-breakeven clears the 2x bar while the
    noise family's does not, and the noise family is rejected on the deflation every time.

    Two things are **not** robust, and both are stated as loose bounds here rather than
    tightened until they look clean. The genuine family does not always clear the 0.95
    deflated-Sharpe bar in absolute terms (see the next test). And a noise family's
    cost-breakeven is not always below 1x — at seed 24 the surviving selection keeps a
    slightly positive gross mean out-of-sample and reads 1.4x. It still fails the 2x bar,
    which is why the bar is where it is.
    """
    config, validator = workspace
    genuine, _ = grade_family(
        validator, config, record=make_hypothesis(f"H1 seed {seed}"), seed=seed, genuine=True
    )
    noise, _ = grade_family(
        validator, config, record=make_hypothesis(f"H1b seed {seed}"), seed=seed + 11, genuine=False
    )
    assert genuine.deflated.value - noise.deflated.value > 0.85
    assert genuine.headline.multiple > 2.0 > noise.headline.multiple
    assert genuine.tails.annualised_sharpe > 1.5
    assert noise.tails.annualised_sharpe < genuine.tails.annualised_sharpe - 1.0
    assert noise.status is GateStatus.FAILED
    assert "deflated_sharpe" in {result.threshold.metric for result in noise.failed_thresholds}


def test_a_real_two_sharpe_effect_can_still_miss_the_deflated_sharpe_bar(
    workspace: tuple[ValidationConfig, Validator],
) -> None:
    """A finding, pinned as behaviour rather than left in prose.

    Seed 13's genuine family has a *real* edge — 1.97 annualised out-of-sample over 950
    sessions, a 4.3x cost-breakeven, a 5% drawdown — and it fails, because its deflated
    Sharpe is 0.927 against a bar of 0.95. Deflated against only twelve logged trials.

    The bar is not wrong and the effect is not fake. What this shows is how *narrow* the
    band is: at four years of daily evidence, a 0.95 deflated-Sharpe threshold demands
    something close to a 2.4 annualised Sharpe, and an honest strategy at 2.0 is rejected.
    Two consequences for whoever sets thresholds on H1: the bar and the window length have
    to be chosen together, and a rejection at this margin means *not enough evidence yet*,
    not *no effect* — the right response is more history, not a new hypothesis.
    """
    config, validator = workspace
    verdict, _ = grade_family(
        validator, config, record=make_hypothesis("H1 near miss"), seed=13, genuine=True
    )
    assert verdict.status is GateStatus.FAILED
    assert 0.90 < verdict.deflated.value < 0.95
    assert verdict.tails.annualised_sharpe > 1.9
    assert verdict.headline.multiple > 4.0
    assert [result.threshold.metric for result in verdict.failed_thresholds] == ["deflated_sharpe"]


def test_the_separation_is_wide_and_the_report_says_where_it_comes_from(
    workspace: tuple[ValidationConfig, Validator],
) -> None:
    """Which criterion did the rejecting — because "it failed" is not a finding.

    The margin is enormous on the deflated Sharpe (about 0.998 against 0.000) and on the
    cost-breakeven (about 5x against 0x): the overfit family's out-of-sample series has no
    edge at all once the selection is re-made on each training block, so both the
    statistic and the economics collapse together.

    **PBO does not do the separating here**, and that is worth stating rather than hiding:
    on these synthetic families it reads low for both. See the module note in the report.
    """
    config, validator = workspace
    genuine_verdict, _ = grade_family(
        validator, config, record=make_hypothesis("H1 genuine"), seed=11, genuine=True
    )
    overfit_verdict, _ = grade_family(
        validator, config, record=make_hypothesis("H1 overfit"), seed=22, genuine=False
    )

    failed = {result.threshold.metric for result in overfit_verdict.failed_thresholds}
    assert "deflated_sharpe" in failed
    assert genuine_verdict.failed_thresholds == ()

    assert genuine_verdict.deflated.value > 0.95
    assert overfit_verdict.deflated.value < 0.05
    assert genuine_verdict.headline.multiple > 2.0
    assert overfit_verdict.headline.multiple < 1.0
    assert genuine_verdict.tails.annualised_sharpe > 1.5
    assert overfit_verdict.tails.annualised_sharpe < 0.5


# ---------------------------------------------------------- criteria 3 and 4


def test_cost_breakeven_is_reported_on_every_run(
    workspace: tuple[ValidationConfig, Validator],
) -> None:
    """Criterion 3 — including on the run that fails, where it is most informative."""
    config, validator = workspace
    for name, seed, genuine in (("g", 11, True), ("o", 22, False)):
        verdict, _ = grade_family(
            validator, config, record=make_hypothesis(f"H1 {name}"), seed=seed, genuine=genuine
        )
        assert "cost_breakeven_multiple" in verdict.metrics()
        assert "cost-breakeven" in verdict.summary()
        assert verdict.metrics()["mean_cost_drag"] > 0


def test_the_benchmark_must_run_on_the_identical_window(
    workspace: tuple[ValidationConfig, Validator],
) -> None:
    """Criterion 4 — the part of "identical cost model, data and window" code can check."""
    config, validator = workspace
    record = make_hypothesis("H1 window check")
    dates = trading_sessions(IN_SAMPLE_START, 400)
    family = genuine_family(dates, seed=3)
    log_the_search(config, record, how_many=12, sharpes=[0.1])
    candidate = evidence(family.series("cfg05"), label="candidate", run_at=RUN_AT)
    other_window = evidence(
        benchmark_series(trading_sessions(dt.date(2022, 1, 3), 400), seed=9),
        label="benchmark on another window",
        run_at=RUN_AT,
    )
    with pytest.raises(BenchmarkMismatchError, match="different window"):
        validator.grade(candidate, benchmark=other_window, hypothesis=record)


# ------------------------------------------------------- not evaluable, and precedence


def failing_feasibility_run(config: ValidationConfig, validator: Validator, **facts: int):
    record = make_hypothesis("H1 feasibility")
    dates = trading_sessions(IN_SAMPLE_START, 400)
    family = genuine_family(dates, seed=4)
    log_the_search(config, record, how_many=12, sharpes=[0.1])
    candidate = evidence(
        family.series("cfg11"),
        label="candidate",
        run_at=RUN_AT,
        feasibility=FeasibilityFacts(**facts),
    )
    naive = evidence(benchmark_series(dates, seed=99), label="naive", run_at=RUN_AT)
    return validator.grade(
        candidate, benchmark=naive, hypothesis=record, overfitting=pbo_for(family)
    )


def test_dominant_feasibility_failures_are_not_evaluable_not_a_failed_threshold(
    workspace: tuple[ValidationConfig, Validator],
) -> None:
    """Spec §6: when the market could not have taken the trades, the answer is execution."""
    config, validator = workspace
    verdict = failing_feasibility_run(
        config,
        validator,
        intents_attempted=800,
        intents_infeasible=200,
        sessions_run=400,
    )
    assert verdict.status is GateStatus.NOT_EVALUABLE
    assert len(verdict.not_evaluable_reasons) == 1
    assert "could not have been filled" in verdict.not_evaluable_reasons[0]


def test_stale_marks_make_a_run_unevaluable(
    workspace: tuple[ValidationConfig, Validator],
) -> None:
    config, validator = workspace
    verdict = failing_feasibility_run(
        config,
        validator,
        intents_attempted=800,
        intents_infeasible=0,
        sessions_run=400,
        sessions_with_stale_marks=200,
    )
    assert verdict.status is GateStatus.NOT_EVALUABLE
    assert any("stale mark" in reason for reason in verdict.not_evaluable_reasons)


def test_surviving_only_at_optimistic_costs_is_unevaluable_but_a_loser_is_not(
    workspace: tuple[ValidationConfig, Validator],
) -> None:
    """The distinction the rule turns on: could a *better cost estimate* rescue this?"""
    config, validator = workspace
    record = make_hypothesis("H1 costs")
    dates = trading_sessions(IN_SAMPLE_START, 400)
    log_the_search(config, record, how_many=12, sharpes=[0.1])
    family = genuine_family(dates, seed=5, edge=0.00045, edge_step=0.0)
    marginal = evidence(
        family.series("cfg00", drag=0.0006),
        label="marginal at modelled costs",
        run_at=RUN_AT,
        unverified_inputs=("costs.brokerage_rate_card",),
    )
    naive = evidence(benchmark_series(dates, seed=77), label="naive", run_at=RUN_AT)
    verdict = validator.grade(
        marginal, benchmark=naive, hypothesis=record, overfitting=pbo_for(family)
    )
    assert verdict.status is GateStatus.NOT_EVALUABLE
    assert any("optimistic costs" in reason for reason in verdict.not_evaluable_reasons)
    assert "UNVERIFIED INPUTS" in verdict.summary()

    losing_family = genuine_family(dates, seed=5, edge=-0.001, edge_step=0.0)
    loser = evidence(
        losing_family.series("cfg00", drag=0.0006),
        label="loses before costs",
        run_at=RUN_AT,
        unverified_inputs=("costs.brokerage_rate_card",),
    )
    losing_verdict = validator.grade(
        loser, benchmark=naive, hypothesis=record, overfitting=pbo_for(losing_family)
    )
    assert losing_verdict.status is GateStatus.FAILED
    assert losing_verdict.not_evaluable_reasons == ()


# ---------------------------------------------------------------- the four outcomes


def holdout_run(
    validator: Validator,
    config: ValidationConfig,
    *,
    record: HypothesisRecord,
    genuine: bool,
):
    dates = trading_sessions(HOLDOUT_START, HOLDOUT_LENGTH)
    family = (
        genuine_family(dates, seed=31, edge=0.0016, edge_step=0.0)
        if genuine
        else overfit_family(dates, seed=41, configurations=4)
    )
    name = next(iter(family.net))
    candidate = evidence(family.series(name), label="holdout run", run_at=RUN_AT)
    naive = evidence(benchmark_series(dates, seed=61), label="naive holdout", run_at=RUN_AT)
    return validator.grade_holdout(candidate, benchmark=naive, hypothesis=record)


def test_a_passing_run_has_no_decision_until_the_holdout_has_been_read(
    workspace: tuple[ValidationConfig, Validator],
) -> None:
    config, validator = workspace
    record = make_hypothesis("H1 decision")
    verdict, _ = grade_family(validator, config, record=record, seed=11, genuine=True)
    with pytest.raises(HoldoutRequiredError, match="no decision without it"):
        validator.decide(verdict)


def test_the_four_outcomes(workspace: tuple[ValidationConfig, Validator]) -> None:
    """Every branch of spec §6's table is reachable and named."""
    config, validator = workspace

    survives_record = make_hypothesis("H1 survives")
    in_sample, _ = grade_family(validator, config, record=survives_record, seed=11, genuine=True)
    survived = holdout_run(validator, config, record=survives_record, genuine=True)
    decision = validator.decide(in_sample, holdout=survived)
    assert decision.outcome is Outcome.PASSES_SURVIVES_HOLDOUT
    assert "Forward test" in decision.next_step
    assert survived.holdout is not None and not survived.holdout.touched

    fails_record = make_hypothesis("H1 fails holdout")
    in_sample_two, _ = grade_family(validator, config, record=fails_record, seed=11, genuine=True)
    failed_holdout = holdout_run(validator, config, record=fails_record, genuine=False)
    assert failed_holdout.status is GateStatus.FAILED
    assert (
        validator.decide(in_sample_two, holdout=failed_holdout).outcome
        is Outcome.PASSES_FAILS_HOLDOUT
    )

    overfit_record = make_hypothesis("H1 overfit decision")
    overfit_verdict, _ = grade_family(
        validator, config, record=overfit_record, seed=22, genuine=False
    )
    assert validator.decide(overfit_verdict).outcome is Outcome.FAILS_THRESHOLD

    unevaluable = failing_feasibility_run(
        config, validator, intents_attempted=800, intents_infeasible=300, sessions_run=400
    )
    assert validator.decide(unevaluable).outcome is Outcome.NOT_EVALUABLE
    assert "execution" in validator.decide(unevaluable).next_step


def test_the_holdout_is_judged_against_its_own_pre_recorded_criteria(
    workspace: tuple[ValidationConfig, Validator],
) -> None:
    """A 250-session holdout cannot clear a DSR bar set on 1200 sessions; the gate says so."""
    config, validator = workspace
    record = make_hypothesis("H1 holdout criteria")
    grade_family(validator, config, record=record, seed=11, genuine=True)
    verdict = holdout_run(validator, config, record=record, genuine=True)
    graded_metrics = {result.threshold.metric for result in verdict.threshold_results}
    assert graded_metrics == {
        "probabilistic_sharpe",
        "cost_breakeven_multiple",
        "risk_matched_increment",
    }


# --------------------------------------------------------------- holdout discipline


def test_in_sample_grading_refuses_a_window_that_reaches_into_the_holdout(
    workspace: tuple[ValidationConfig, Validator],
) -> None:
    config, validator = workspace
    record = make_hypothesis("H1 holdout guard")
    dates = trading_sessions(dt.date(2025, 9, 1), 400)  # runs past 2026-01-05
    family = genuine_family(dates, seed=6)
    log_the_search(config, record, how_many=12, sharpes=[0.1])
    candidate = evidence(family.series("cfg00"), label="candidate", run_at=RUN_AT)
    naive = evidence(benchmark_series(dates, seed=8), label="naive", run_at=RUN_AT)
    with pytest.raises(HoldoutTouchedError, match="reaches into"):
        validator.grade(candidate, benchmark=naive, hypothesis=record)


def test_the_holdout_run_is_refused_once_the_months_have_been_read(
    workspace: tuple[ValidationConfig, Validator],
) -> None:
    """The discipline is answerable, so it can be enforced rather than trusted."""
    config, validator = workspace
    record = make_hypothesis("H1 touched holdout")
    log_the_search(config, record, how_many=12, sharpes=[0.1])
    clock = ManualClock(dt.datetime(2026, 7, 2, 9, 0, tzinfo=dt.UTC))
    with (
        open_session(config.trial_log_path, clock=clock) as session,
        session.trial(record, data_window=DataWindow(dt.date(2026, 2, 1), dt.date(2026, 4, 30))),
    ):
        pass
    with pytest.raises(HoldoutTouchedError, match="already been read"):
        holdout_run(validator, config, record=record, genuine=True)


def test_a_run_that_predates_its_thresholds_is_refused_end_to_end(
    workspace: tuple[ValidationConfig, Validator],
) -> None:
    from xman_research.validation.gate import ThresholdsNotRecordedError

    config, validator = workspace
    record = make_hypothesis("H1 stale thresholds")
    dates = trading_sessions(IN_SAMPLE_START, 400)
    family = genuine_family(dates, seed=7)
    log_the_search(config, record, how_many=12, sharpes=[0.1])
    early = evidence(
        family.series("cfg05"),
        label="ran before the thresholds were written",
        run_at=RECORDED_AT - dt.timedelta(days=1),
    )
    naive = evidence(benchmark_series(dates, seed=12), label="naive", run_at=RUN_AT)
    with pytest.raises(ThresholdsNotRecordedError, match="not before"):
        validator.grade(early, benchmark=naive, hypothesis=record)


def test_the_verdict_is_a_record_worth_keeping(
    workspace: tuple[ValidationConfig, Validator],
) -> None:
    """Everything an operator needs to argue with the decision, in one dict."""
    config, validator = workspace
    record = make_hypothesis("H1 record")
    verdict, _ = grade_family(validator, config, record=record, seed=11, genuine=True)
    payload = verdict.as_dict()
    assert payload["status"] == "passed"
    assert payload["hypothesis_id"] == record.id
    assert payload["epochs"]["epoch_provenance"] == "epochs.dates_not_primary_sourced"
    assert payload["epochs"]["cross_epoch_justification"]
    assert payload["metrics"]["selection_size"] == 12
    assert payload["walk_forward"]["folds"] == 19
    assert payload["judged_series"].startswith("walk-forward out-of-sample, 19 folds")
    assert "epochs.dates_not_primary_sourced" in payload["metrics"]["unverified_inputs"]


def test_a_criterion_the_run_did_not_measure_is_refused_not_graded(
    workspace: tuple[ValidationConfig, Validator],
) -> None:
    """An unmeasured threshold is a gap in the evidence, not a property of the strategy.

    So it raises rather than landing on the fourth outcome: "not evaluable" carries the
    advice *resolve the quote-data question*, and the actual next step here is to run the
    cross-validation the gate asked for.
    """
    config, validator = workspace
    record = make_hypothesis("H1 unmeasured")
    dates = trading_sessions(IN_SAMPLE_START, 400)
    family = genuine_family(dates, seed=13)
    log_the_search(config, record, how_many=12, sharpes=[0.1])
    candidate = evidence(family.series("cfg11"), label="candidate", run_at=RUN_AT)
    naive = evidence(benchmark_series(dates, seed=14), label="naive", run_at=RUN_AT)
    with pytest.raises(MetricNotReportedError, match="requires pbo"):
        validator.grade(candidate, benchmark=naive, hypothesis=record)  # no CSCV run


def test_a_verdict_can_be_logged_back_into_the_trial_log(
    workspace: tuple[ValidationConfig, Validator],
) -> None:
    """C6's output is C4's input shape: the decision is itself a recorded evaluation."""
    config, validator = workspace
    record = make_hypothesis("H1 loggable")
    verdict, _ = grade_family(validator, config, record=record, seed=11, genuine=True)
    clock = ManualClock(dt.datetime(2026, 8, 7, 9, 0, tzinfo=dt.UTC))
    with open_session(config.trial_log_path, clock=clock) as session:
        before = session.count_family_trials(record)
        with session.trial(
            record, data_window=DataWindow(IN_SAMPLE_START, dt.date(2025, 8, 1))
        ) as trial:
            trial.record_metrics(verdict.metrics())
        assert session.count_family_trials(record) == before + 1
        logged = session.family_trials(record)[-1]
        assert logged.metrics["gate_status"] == "passed"
        assert logged.metrics["cost_breakeven_multiple"] > 2.0
