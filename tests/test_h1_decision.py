"""The whole loop, end to end, against the real corpus — including the holdout branch.

This is the dry run for :mod:`xman_research.h1.run_decision`, and it exists because the
real holdout is spendable exactly once. ``Validator.grade_holdout`` writes its touch row
*before* it grades, so a grading that raises leaves the months read and the log saying so;
the retry then sees the earlier touch and refuses. A **failed** holdout grading destroys the
holdout as surely as a successful one. Everything downstream of "the in-sample verdict
passed" therefore has to be exercised somewhere that is not the real thing.

So: a throwaway log, a throwaway gate bound to a throwaway hypothesis, throwaway windows —
and deliberately permissive thresholds, so the in-sample verdict passes and the holdout
branch actually executes. The point is that the machinery runs, not what it concludes; the
one real conclusion is in ``research/h1/DECISION.md``.

Skips cleanly when the corpus is absent. Everything it reads is read-only.
"""

from __future__ import annotations

import datetime as dt
import os
from pathlib import Path

import pytest

from xman_research import HypothesisRecord
from xman_research.h1.run_decision import run_h1_decision
from xman_research.session_store import DEFAULT_CORPUS_ROOT, SessionStore
from xman_research.validation import GateStatus, Outcome

CORPUS_ROOT = Path(os.environ.get("XMAN_RESEARCH_CORPUS_ROOT") or DEFAULT_CORPUS_ROOT)
UNDERLYING = "NIFTY"

pytestmark = pytest.mark.skipif(
    not (CORPUS_ROOT / UNDERLYING).is_dir(),
    reason=f"real corpus not present at {CORPUS_ROOT / UNDERLYING}",
)

#: Short windows well inside the captured range, chosen for speed. The holdout side crosses
#: 2026-04-01 (stt_rise_2026), which is why the scratch gate below carries a cross-epoch
#: justification: without one, C6 refuses the window rather than pooling two regimes quietly.
DRY_RUN_START = dt.date(2026, 2, 2)
DRY_RUN_HOLDOUT_FIRST = dt.date(2026, 3, 16)
DRY_RUN_END = dt.date(2026, 4, 10)

PERMISSIVE = {
    "deflated_sharpe": 0.0,
    "cost_breakeven_multiple": -1000.0,
    "max_drawdown": 1.0,
    "risk_matched_increment": -1000.0,
    "holdout.deflated_sharpe": 0.0,
    "holdout.cost_breakeven_multiple": -1000.0,
    "holdout.max_drawdown": 1.0,
    "holdout.risk_matched_increment": -1000.0,
}


def scratch_hypothesis() -> HypothesisRecord:
    return HypothesisRecord(
        name="H1 dry run — machinery only, not a claim about markets",
        mechanism=(
            "Stands in for H1 so the loop can be exercised without registering trials "
            "against the real hypothesis family. Registering dry-run trials there would "
            "inflate the selection count the real deflated Sharpe is computed against, "
            "which is a cost paid by the real verdict for a test's convenience."
        ),
        null_hypothesis="Not tested here. This record exists to bind a throwaway gate.",
        thresholds=PERMISSIVE,
    )


def write_config(root: Path, record: HypothesisRecord) -> Path:
    """A gate and a config in ``root``, bound to ``record`` and recorded before the run."""
    (root / "gate.toml").write_text(
        f'hypothesis_id = "{record.id}"\n'
        "recorded_at = 2026-01-01T00:00:00Z\n"
        'cross_epoch_justification = "Dry run: the window crosses the 2026 STT rise, which '
        'C5 charges at date-effective rates within the one run."\n'
        "\n[thresholds]\n"
        "deflated_sharpe = { at_least = 0.0 }\n"
        "cost_breakeven_multiple = { at_least = -1000.0 }\n"
        "max_drawdown = { at_most = 1.0 }\n"
        "risk_matched_increment = { at_least = -1000.0 }\n"
        "\n[holdout_thresholds]\n"
        "deflated_sharpe = { at_least = 0.0 }\n"
        "cost_breakeven_multiple = { at_least = -1000.0 }\n"
        "max_drawdown = { at_most = 1.0 }\n"
        "risk_matched_increment = { at_least = -1000.0 }\n",
        encoding="utf-8",
    )
    config = root / "validation.toml"
    config.write_text(
        'trial_log_path = "dry_run.db"\n'
        'gate_path = "gate.toml"\n'
        f"holdout_first_date = {DRY_RUN_HOLDOUT_FIRST.isoformat()}\n"
        f'underlying = "{UNDERLYING}"\n',
        encoding="utf-8",
    )
    return config


def dry_run(root: Path):
    record = scratch_hypothesis()
    return run_h1_decision(
        write_config(root, record),
        store=SessionStore(root=CORPUS_ROOT),
        in_sample_start=DRY_RUN_START,
        holdout_end=DRY_RUN_END,
        hypothesis=record,
    )


@pytest.fixture(scope="module")
def first(tmp_path_factory: pytest.TempPathFactory):
    return dry_run(tmp_path_factory.mktemp("h1_dry_run_a"))


def test_the_loop_closes_on_one_of_the_four_outcomes(first) -> None:
    """The MVP's definition of done: an operator can say which of spec §6's four it was."""
    assert first.decision.outcome in set(Outcome)
    assert first.decision.next_step
    assert first.decision.summary()


def test_the_holdout_branch_actually_executed(first) -> None:
    """With permissive bars the in-sample verdict passes, so the holdout must have been read.

    This is the assertion the whole file exists for. If the holdout path can only ever be
    reached by the real run, then the real run is the first execution of that code — and the
    real holdout is what pays for any defect in it.
    """
    assert first.decision.in_sample.status is GateStatus.PASSED
    assert first.holdout_spent is True
    assert first.holdout_result is not None
    assert first.decision.holdout is not None
    assert first.decision.outcome in {
        Outcome.PASSES_SURVIVES_HOLDOUT,
        Outcome.PASSES_FAILS_HOLDOUT,
        Outcome.NOT_EVALUABLE,
    }


def test_the_holdout_run_lies_wholly_inside_the_unseen_months(first) -> None:
    assert first.holdout_result is not None
    assert first.holdout_result.start >= DRY_RUN_HOLDOUT_FIRST
    assert first.in_sample_result.end < DRY_RUN_HOLDOUT_FIRST


def test_the_trial_count_is_read_from_the_log_and_includes_the_holdout_touch(first) -> None:
    """Three rows: the in-sample run, the touch the holdout read writes, and the holdout run.

    The touch entering the count is not an accident — it makes the holdout verdict slightly
    more conservative than the in-sample one, which is the right direction.
    """
    assert first.trial_count == len(first.trial_rows) == 3
    touches = [row for row in first.trial_rows if row["metrics"].get("holdout_touch")]
    assert len(touches) == 1


def test_every_metric_the_gate_named_was_measured_and_recorded(first) -> None:
    graded = {result.threshold.metric for result in first.decision.in_sample.threshold_results}

    assert graded == {
        "deflated_sharpe",
        "cost_breakeven_multiple",
        "max_drawdown",
        "risk_matched_increment",
    }
    assert not any(result.missing for result in first.decision.in_sample.threshold_results)


def test_the_candidate_is_its_own_naive_benchmark_so_the_increment_is_zero(first) -> None:
    """Stated as a test because it is a property of the MVP's expression, not an accident.

    The unconditional short ATM straddle *is* the naive always-on benchmark C6 requires, so
    the risk-matched increment is structurally zero and carries no information this round.
    A future conditional variant is what gives the criterion teeth.
    """
    assert first.decision.in_sample.increment.sharpe_difference == pytest.approx(0.0)
    assert first.decision.in_sample.increment.annualised_increment == pytest.approx(0.0)


def test_the_verdict_carries_its_caveats_rather_than_presenting_a_clean_number(first) -> None:
    stamps = first.decision.in_sample.unverified_inputs

    assert stamps, "a run over secondary-sourced rates presented no caveats at all"
    assert any("epoch" in stamp for stamp in stamps)


def test_same_inputs_same_verdict(tmp_path_factory: pytest.TempPathFactory, first) -> None:
    """Reproducibility of the decision, not just of the backtest.

    Two independent runs, two fresh logs, identical everything else. The backtest
    fingerprints must match — C5's own criterion — and so must the outcome and every graded
    number, which is the stronger claim: it says the grading is a function of the evidence
    and not of when it happened to run.
    """
    second = dry_run(tmp_path_factory.mktemp("h1_dry_run_b"))

    assert second.in_sample_result.fingerprint() == first.in_sample_result.fingerprint()
    assert second.holdout_result is not None and first.holdout_result is not None
    assert second.holdout_result.fingerprint() == first.holdout_result.fingerprint()
    assert second.decision.outcome is first.decision.outcome
    assert second.trial_count == first.trial_count

    for left, right in zip(
        second.decision.in_sample.threshold_results,
        first.decision.in_sample.threshold_results,
        strict=True,
    ):
        assert left.threshold.metric == right.threshold.metric
        assert left.observed == pytest.approx(right.observed)
        assert left.passed == right.passed
