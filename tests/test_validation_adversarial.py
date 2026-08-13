"""The gate attacked, rather than exercised.

Every acceptance test in ``test_overfit_vs_genuine.py`` hands the validator a consistent
set of inputs and checks it grades them correctly. That is necessary and it is not the
same job as this file's, which hands it *inconsistent* inputs — a walk-forward report
belonging to a different run, a holdout read for the second time, a threshold on a metric
nobody computes — and checks it refuses.

The distinction is not academic. C1 in review was a hole that let a single mismatched
argument defeat the holdout boundary, the epoch check and the verdict's own window at
once, and it survived a complete acceptance suite precisely because no test ever passed a
report that did not belong to its candidate.
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
    trading_sessions,
)
from xman_research import DataWindow, HypothesisRecord, ManualClock, open_session
from xman_research.validation.decision import (
    HypothesisMismatchError,
    JudgedSeriesMismatchError,
    ValidationConfig,
    Validator,
)
from xman_research.validation.gate import (
    HOLDOUT_THRESHOLD_PREFIX,
    DecisionGate,
    GateBindingError,
    GateVocabularyError,
    HoldoutTouchedError,
    ThresholdsNotRecordedError,
)
from xman_research.validation.pbo import performance_matrix, probability_of_backtest_overfitting
from xman_research.validation.series import FeasibilityFacts
from xman_research.validation.walkforward import walk_forward

IN_SAMPLE_START = dt.date(2021, 1, 4)
HOLDOUT_START = dt.date(2026, 1, 5)
RUN_AT = dt.datetime(2026, 8, 5, 12, 0, tzinfo=dt.UTC)

GATE_BODY = """
recorded_at = 2026-08-01T09:00:00Z
cross_epoch_justification = "Cost- and calendar-side breaks only; mechanism unchanged."

[thresholds]
deflated_sharpe = { at_least = 0.95 }
cost_breakeven_multiple = { at_least = 2.0 }
pbo = { at_most = 0.5 }

[holdout_thresholds]
probabilistic_sharpe = { at_least = 0.95 }
cost_breakeven_multiple = { at_least = 2.0 }
"""

THRESHOLDS = {"deflated_sharpe": 0.95, "cost_breakeven_multiple": 2.0, "pbo": 0.5}


def make_hypothesis(name: str, **extra: float) -> HypothesisRecord:
    return HypothesisRecord(
        name=name,
        mechanism="Index hedgers pay up for protection, so implied sits above realised.",
        null_hypothesis="Implied minus realised has no positive mean after costs.",
        thresholds={**THRESHOLDS, **extra},
        predictors=["iv_30d"],
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


def log_the_search(config: ValidationConfig, record: HypothesisRecord, *, how_many: int) -> None:
    clock = ManualClock(dt.datetime(2026, 7, 1, 9, 0, tzinfo=dt.UTC), step=dt.timedelta(minutes=1))
    with open_session(config.trial_log_path, clock=clock) as session:
        session.register(record)
        for index in range(how_many):
            with session.trial(
                record,
                data_window=DataWindow(IN_SAMPLE_START, dt.date(2025, 8, 1)),
                params={"variant": index},
            ) as trial:
                trial.record_metrics(sharpe_per_period=[0.02, 0.05, 0.08][index % 3])


def pbo_for(family, *, how_many: int = 12, partitions: int = 8):
    subset = dict(list(family.net.items())[:how_many])
    return probability_of_backtest_overfitting(
        performance_matrix({name: family.series(name) for name in subset}), partitions=partitions
    )


# --------------------------------------------------------------------------- C1


def test_a_walk_forward_report_from_other_sessions_is_refused(
    workspace: tuple[ValidationConfig, Validator],
) -> None:
    """C1. One mismatched argument used to defeat three refusals at once.

    The candidate's window is innocent — 2021-01-04..2025-08-08, comfortably short of the
    2026-01-05 boundary — so ``grade()``'s holdout check passes and the epoch annotation
    is taken from a window that crosses four breaks. The walk-forward report is built on
    sessions running to **2027-07-09**, eighteen months into the holdout. Because
    ``_grade`` replaces the judged series with ``walk_forward.out_of_sample`` and nothing
    re-derived its window, every statistic in the resulting verdict — the deflated Sharpe,
    the breakeven, the tails, the increment, the PSR — came from months the candidate
    never covered, the benchmark was ``restricted_to`` the leaky window so it read holdout
    months too, and the verdict reported the innocent range. It graded PASSED.
    """
    config, validator = workspace
    record = make_hypothesis("H1 leaky walk-forward")
    log_the_search(config, record, how_many=12)

    innocent_dates = trading_sessions(IN_SAMPLE_START, 1200)
    leaky_dates = trading_sessions(IN_SAMPLE_START, 1700)  # runs to 2027-07-09
    assert leaky_dates[-1] > HOLDOUT_START

    leaky_family = genuine_family(leaky_dates, seed=11)
    innocent_family = genuine_family(innocent_dates, seed=11)
    report = walk_forward(
        leaky_dates, run=fold_runner(leaky_family), train_length=250, test_length=50
    )
    chosen = innocent_family.best_on(DataWindow(innocent_dates[0], innocent_dates[-1]))
    candidate = evidence(innocent_family.series(chosen), label="innocent candidate", run_at=RUN_AT)
    naive = evidence(benchmark_series(leaky_dates, seed=511), label="naive", run_at=RUN_AT)

    assert candidate.window.end < HOLDOUT_START
    assert report.out_of_sample.window.end > HOLDOUT_START

    with pytest.raises(JudgedSeriesMismatchError, match="not inside the run"):
        validator.grade(
            candidate,
            benchmark=naive,
            hypothesis=record,
            walk_forward=report,
            overfitting=pbo_for(leaky_family, how_many=40),
        )


def test_the_verdict_reports_the_window_it_actually_judged(
    workspace: tuple[ValidationConfig, Validator],
) -> None:
    """The other half of C1: the record must not name a window it did not judge.

    Containment makes the leak impossible; it does not make the two windows equal. The
    first training block is never scored, so the judged series always opens later than
    the run does — and a verdict that prints the run's window beside statistics computed
    on the folds misleads a reader who has no way to see the difference.
    """
    config, validator = workspace
    record = make_hypothesis("H1 window reporting")
    log_the_search(config, record, how_many=12)
    dates = trading_sessions(IN_SAMPLE_START, 600)
    family = genuine_family(dates, seed=11)
    report = walk_forward(dates, run=fold_runner(family), train_length=250, test_length=50)
    chosen = family.best_on(DataWindow(dates[0], dates[-1]))
    candidate = evidence(family.series(chosen), label="candidate", run_at=RUN_AT)
    naive = evidence(benchmark_series(dates, seed=91), label="naive", run_at=RUN_AT)

    verdict = validator.grade(
        candidate,
        benchmark=naive,
        hypothesis=record,
        walk_forward=report,
        overfitting=pbo_for(family),
    )
    assert verdict.window == str(report.out_of_sample.window)
    assert verdict.candidate_window == str(candidate.window)
    assert verdict.window != verdict.candidate_window
    assert verdict.as_dict()["candidate_window"] == verdict.candidate_window
    # And the epochs are annotated from the judged series, not from the run's window.
    assert verdict.epochs.as_dict()["window"] == verdict.window


# ----------------------------------------------------------------------- M1


def test_grading_the_holdout_records_the_read_and_refuses_a_second_one(
    workspace: tuple[ValidationConfig, Validator],
) -> None:
    """M1. The most consequential read in the system used to leave no trace.

    Before this, the same holdout could be graded twice and both runs passed: the check
    asked the log a question the grading never answered into.
    """
    config, validator = workspace
    record = make_hypothesis("H1 holdout touch")
    log_the_search(config, record, how_many=12)

    dates = trading_sessions(HOLDOUT_START, 250)
    family = genuine_family(dates, seed=31, edge=0.0016, edge_step=0.0)
    name = next(iter(family.net))
    candidate = evidence(family.series(name), label="holdout run", run_at=RUN_AT)
    naive = evidence(benchmark_series(dates, seed=61), label="naive holdout", run_at=RUN_AT)

    with open_session(config.trial_log_path) as session:
        before = session.count_family_trials(record)
    first = validator.grade_holdout(candidate, benchmark=naive, hypothesis=record)
    assert first.holdout is not None and not first.holdout.touched

    with open_session(config.trial_log_path) as session:
        after = session.family_trials(record)
        assert len(after) == before + 1
        touch = after[-1]
        assert touch.metrics["holdout_touch"] is True
        assert touch.data_window.start >= HOLDOUT_START
        assert "holdout read" in (touch.notes or "")

    with pytest.raises(HoldoutTouchedError, match="already been read"):
        validator.grade_holdout(candidate, benchmark=naive, hypothesis=record)


def test_a_malformed_holdout_run_leaves_no_touch_record(
    workspace: tuple[ValidationConfig, Validator],
) -> None:
    """Ordering matters: a read that never happened must not be recorded as one."""
    config, validator = workspace
    record = make_hypothesis("H1 malformed holdout")
    log_the_search(config, record, how_many=12)
    dates = trading_sessions(dt.date(2025, 10, 1), 250)  # straddles the boundary
    family = genuine_family(dates, seed=32)
    candidate = evidence(family.series("cfg00"), label="mixed window", run_at=RUN_AT)
    naive = evidence(benchmark_series(dates, seed=62), label="naive", run_at=RUN_AT)

    with open_session(config.trial_log_path) as session:
        before = session.count_family_trials(record)
    with pytest.raises(HoldoutTouchedError, match="mixes seen and unseen"):
        validator.grade_holdout(candidate, benchmark=naive, hypothesis=record)
    with open_session(config.trial_log_path) as session:
        assert session.count_family_trials(record) == before


def test_the_backtest_that_produced_the_holdout_evidence_does_not_block_it(
    workspace: tuple[ValidationConfig, Validator],
) -> None:
    """M1's other half: the honest workflow used to deadlock.

    C4 requires every evaluation to go through the log. So the backtest that produced the
    holdout ``RunEvidence`` is a logged trial whose window reaches past the boundary — and
    ``inspect_holdout`` found that very trial and refused. The only workflow that worked
    was running the holdout backtest *outside* the log, i.e. C6's discipline required
    breaking C4's.
    """
    config, validator = workspace
    record = make_hypothesis("H1 honest workflow")
    log_the_search(config, record, how_many=12)
    dates = trading_sessions(HOLDOUT_START, 250)
    family = genuine_family(dates, seed=31, edge=0.0016, edge_step=0.0)
    name = next(iter(family.net))

    # The holdout backtest itself, logged as C4 requires.
    clock = ManualClock(dt.datetime(2026, 8, 3, 9, 0, tzinfo=dt.UTC))  # after recorded_at
    with (
        open_session(config.trial_log_path, clock=clock) as session,
        session.trial(
            record, data_window=DataWindow(dates[0], dates[-1]), params={"run": "holdout"}
        ) as trial,
    ):
        producing_trial_id = trial.trial_id
        producing_run_at = None
    with open_session(config.trial_log_path) as session:
        producing_run_at = next(
            row.created_at
            for row in session.family_trials(record)
            if row.trial_id == producing_trial_id
        )

    candidate = evidence(
        family.series(name),
        label="holdout run",
        run_at=producing_run_at,
        trial_id=producing_trial_id,
    )
    naive = evidence(benchmark_series(dates, seed=61), label="naive holdout", run_at=RUN_AT)
    verdict = validator.grade_holdout(candidate, benchmark=naive, hypothesis=record)
    assert verdict.holdout is not None and not verdict.holdout.touched
    assert verdict.trial_id == producing_trial_id


# ----------------------------------------------------------------------- M2 / M3 / M6


def test_the_holdout_bar_is_bound_to_the_immutable_record(tmp_path: Path) -> None:
    """M2. The holdout bar lived only in an editable file, with nothing to reconcile it.

    So an operator who had already seen the in-sample verdict could soften the one
    criterion that decides the most consequential run in the loop — the exact move
    ``check_binding`` exists to stop, left open on the worst possible run.
    """
    path = tmp_path / "gate.toml"
    path.write_text(GATE_BODY)
    gate = DecisionGate.from_file(path)
    record = make_hypothesis(
        "H1 bound holdout", **{f"{HOLDOUT_THRESHOLD_PREFIX}probabilistic_sharpe": 0.95}
    )
    gate.check_binding(record)  # agrees — does not raise

    softened = tmp_path / "softened.toml"
    softened.write_text(
        GATE_BODY.replace(
            "probabilistic_sharpe = { at_least = 0.95 }",
            "probabilistic_sharpe = { at_least = 0.50 }",
        )
    )
    with pytest.raises(GateBindingError, match=r"registered with 0\.95"):
        DecisionGate.from_file(softened).check_binding(record)

    dropped = tmp_path / "dropped.toml"
    dropped.write_text(GATE_BODY.replace("probabilistic_sharpe = { at_least = 0.95 }\n", ""))
    with pytest.raises(GateBindingError, match=r"\[holdout_thresholds\] does not carry it"):
        DecisionGate.from_file(dropped).check_binding(record)


def test_an_empty_holdout_block_is_refused_when_the_fallback_cannot_work(
    tmp_path: Path,
) -> None:
    """M3. The documented fallback was unreachable, and said nothing about it.

    ``grade_holdout`` passes no CSCV result, so an in-sample set naming ``pbo`` makes the
    "left empty, the in-sample thresholds are used" fallback raise every single time.
    """
    path = tmp_path / "gate.toml"
    path.write_text(GATE_BODY.split("[holdout_thresholds]")[0])
    with pytest.raises(ThresholdsNotRecordedError, match="records no \\[holdout_thresholds\\]"):
        DecisionGate.from_file(path)

    # Without a holdout-uncomputable metric in force, the fallback is legitimate.
    workable = tmp_path / "workable.toml"
    workable.write_text(
        "recorded_at = 2026-08-01T09:00:00Z\n"
        "[thresholds]\ncost_breakeven_multiple = { at_least = 2.0 }\n"
    )
    gate = DecisionGate.from_file(workable)
    assert gate.thresholds_in_force(holdout=True) == gate.thresholds


def test_a_threshold_on_a_metric_nobody_computes_is_caught_at_load(tmp_path: Path) -> None:
    """M6. It used to survive to grade time and be reported as the run's fault."""
    path = tmp_path / "gate.toml"
    path.write_text(
        "recorded_at = 2026-08-01T09:00:00Z\n[thresholds]\nsortino = { at_least = 1.0 }\n"
    )
    with pytest.raises(GateVocabularyError, match="sortino"):
        DecisionGate.from_file(path)


def test_the_two_adjusted_sharpes_no_longer_share_a_name() -> None:
    """M6. A factor of sqrt(252) = 15.9 used to sit under one label."""
    from xman_research.validation.gate import MEASURED_METRICS
    from xman_research.validation.statistics import tail_metrics

    dates = trading_sessions(IN_SAMPLE_START, 300)
    tails = tail_metrics(genuine_family(dates, seed=11).series("cfg00"))
    logged = tails.as_dict()
    assert logged["adjusted_sharpe_per_period"] == tails.adjusted_sharpe
    assert logged["annualised_adjusted_sharpe"] == tails.annualised_adjusted_sharpe
    assert "adjusted_sharpe" not in logged
    assert "annualised_adjusted_sharpe" in MEASURED_METRICS
    assert "adjusted_sharpe" not in MEASURED_METRICS


# ----------------------------------------------------------------------- M4 / M5 / M7


def test_the_benchmarks_caveats_reach_the_verdict(
    workspace: tuple[ValidationConfig, Validator],
) -> None:
    """M4. Spec §3 requires the benchmark under the *identical* cost model.

    So a caveat on the benchmark is as verdict-relevant as one on the candidate — the
    risk-matched increment is judged against it — and it used to be dropped entirely.
    """
    config, validator = workspace
    record = make_hypothesis("H1 benchmark stamps")
    log_the_search(config, record, how_many=12)
    dates = trading_sessions(IN_SAMPLE_START, 400)
    family = genuine_family(dates, seed=11)
    candidate = evidence(family.series("cfg11"), label="clean candidate", run_at=RUN_AT)
    naive = evidence(
        benchmark_series(dates, seed=93),
        label="naive",
        run_at=RUN_AT,
        unverified_inputs=("costs.uniformly_allocated",),
    )
    verdict = validator.grade(
        candidate, benchmark=naive, hypothesis=record, overfitting=pbo_for(family)
    )
    assert "benchmark:costs.uniformly_allocated" in verdict.unverified_inputs
    assert "UNVERIFIED INPUTS" in verdict.summary()


def test_a_run_that_reported_no_feasibility_says_so(
    workspace: tuple[ValidationConfig, Validator],
) -> None:
    """M5. All-zero feasibility facts read as a run where nothing went wrong."""
    config, validator = workspace
    record = make_hypothesis("H1 silent feasibility")
    log_the_search(config, record, how_many=12)
    dates = trading_sessions(IN_SAMPLE_START, 400)
    family = genuine_family(dates, seed=11)
    candidate = evidence(
        family.series("cfg11"),
        label="candidate",
        run_at=RUN_AT,
        feasibility=FeasibilityFacts(),
    )
    naive = evidence(benchmark_series(dates, seed=94), label="naive", run_at=RUN_AT)
    verdict = validator.grade(
        candidate, benchmark=naive, hypothesis=record, overfitting=pbo_for(family)
    )
    assert "feasibility.not_reported" in verdict.unverified_inputs
    assert verdict.metrics()["unverified_inputs"].count("feasibility.not_reported") == 1


def test_a_run_at_that_disagrees_with_the_log_is_refused(
    workspace: tuple[ValidationConfig, Validator],
) -> None:
    """M7. ``run_at`` is caller-typed; the log's ``created_at`` is not.

    The thresholds-predate-the-run check rests on that timestamp, so trusting the free
    field over the authoritative one made the check bypassable by typing a later date.
    """
    config, validator = workspace
    record = make_hypothesis("H1 timestamp")
    log_the_search(config, record, how_many=12)
    dates = trading_sessions(IN_SAMPLE_START, 400)
    family = genuine_family(dates, seed=11)
    with open_session(config.trial_log_path) as session:
        logged = session.family_trials(record)[0]

    candidate = evidence(
        family.series("cfg11"),
        label="candidate",
        run_at=RUN_AT,  # not what the log says
        trial_id=logged.trial_id,
    )
    naive = evidence(benchmark_series(dates, seed=95), label="naive", run_at=RUN_AT)
    with pytest.raises(ThresholdsNotRecordedError, match="run_at is a field the caller"):
        validator.grade(candidate, benchmark=naive, hypothesis=record, overfitting=pbo_for(family))


# ----------------------------------------------------------------------- m4 / m5


def test_a_decision_refuses_verdicts_on_two_different_hypotheses(
    workspace: tuple[ValidationConfig, Validator],
) -> None:
    """m4. Pairing one idea's holdout evidence with another's in-sample case."""
    config, validator = workspace
    first = make_hypothesis("H1 alpha")
    second = make_hypothesis("H1 beta")
    log_the_search(config, first, how_many=12)
    log_the_search(config, second, how_many=12)
    dates = trading_sessions(IN_SAMPLE_START, 400)
    family = genuine_family(dates, seed=11)
    naive = evidence(benchmark_series(dates, seed=96), label="naive", run_at=RUN_AT)
    in_sample = validator.grade(
        evidence(family.series("cfg11"), label="a", run_at=RUN_AT),
        benchmark=naive,
        hypothesis=first,
        overfitting=pbo_for(family),
    )
    other = validator.grade(
        evidence(family.series("cfg11"), label="b", run_at=RUN_AT),
        benchmark=naive,
        hypothesis=second,
        overfitting=pbo_for(family),
    )
    with pytest.raises(HypothesisMismatchError, match="filed under"):
        validator.decide(in_sample, holdout=other)


def test_overlapping_folds_are_refused_before_any_fold_runs() -> None:
    """m5. It used to raise anyway — after paying for every backtest in the series."""
    from xman_research.validation.series import SeriesError

    dates = trading_sessions(IN_SAMPLE_START, 400)
    family = genuine_family(dates, seed=11)
    calls = 0

    runner = fold_runner(family)

    def counting_runner(split):
        nonlocal calls
        calls += 1
        return runner(split)

    with pytest.raises(SeriesError, match="guaranteed to fail"):
        walk_forward(dates, run=counting_runner, train_length=250, test_length=50, step=25)
    assert calls == 0
