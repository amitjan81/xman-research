"""The stage-two gate's passing branch, over a corpus small enough to make it pass.

The real corpus does not hand the gate a passing in-sample verdict, so every real-corpus
test of :func:`~xman_research.alpha.gate.run_stage_two_gate` stops at the branch where the
holdout stays sealed. That leaves the most consequential path in the module — the one that
reads the unseen months, writes the touch row, grades against the holdout thresholds and
lands on one of the four outcomes — reachable for the first time by a real research run,
which is exactly the run that pays for any defect in it.

So: a synthetic corpus, a throwaway log, and thresholds set low enough that the in-sample
verdict passes whatever the numbers turn out to be. What is asserted is that the machinery
runs and that the holdout is spent exactly once, not what it concluded.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from alpha_helpers import FLAT_SPOT, trading_days, write_corpus
from xman_research import ManualClock, StaticCodeVersion
from xman_research.alpha.features import DEFAULT_DECISION_TIME, FeatureBuilder
from xman_research.alpha.gate import DECISION_RECORD_NAME, run_stage_two_gate
from xman_research.alpha.screen import CandidateSpec, ScreeningRun, load_screen_sheet
from xman_research.alpha.templates import default_registry
from xman_research.backtest.engine import BacktestConfig
from xman_research.hypothesis import HypothesisRecord
from xman_research.session_store import SessionStore
from xman_research.trial_log import DataWindow, TrialLog
from xman_research.validation import GateStatus, Outcome
from xman_research.validation.gate import HoldoutTouchedError

#: Long enough for the twenty-session realised-volatility window to warm up, then split
#: into a screened stretch and a holdout that still carries a judgeable return series.
SESSION_COUNT = 60
SCREENED_SESSIONS = 42
LAST_SESSION = dt.date(2026, 4, 24)

#: Low enough that the in-sample verdict passes on whatever this corpus produces. A gate
#: exists to be binding; this one exists to reach the code behind it.
PERMISSIVE = {
    "deflated_sharpe": -10.0,
    "cost_breakeven_multiple": -1000.0,
    "max_drawdown": 1.0,
    "risk_matched_increment": -1000.0,
}

GATE = """
hypothesis_id = "{hypothesis_id}"
recorded_at = 2026-01-01T00:00:00Z
cross_epoch_justification = "Synthetic corpus: the windows cross the 2026 STT rise."

[thresholds]
deflated_sharpe = {{ at_least = -10.0 }}
cost_breakeven_multiple = {{ at_least = -1000.0 }}
max_drawdown = {{ at_most = 1.0 }}
risk_matched_increment = {{ at_least = -1000.0 }}

[holdout_thresholds]
deflated_sharpe = {{ at_least = -10.0 }}
cost_breakeven_multiple = {{ at_least = -1000.0 }}
max_drawdown = {{ at_most = 1.0 }}
risk_matched_increment = {{ at_least = -1000.0 }}

# The fourth outcome is decided before pass/fail, so a synthetic corpus thin enough to
# leave intents unfilled would land on NOT_EVALUABLE and never reach the holdout. These
# admit anything, which is the point here and would be indefensible anywhere else.
[not_evaluable]
max_infeasible_fraction = 1.0
max_stale_fraction = 1.0
optimistic_costs_below = -1000.0
"""


def hypothesis() -> HypothesisRecord:
    return HypothesisRecord(
        name="Synthetic screen: does a wider structure beat the at-the-money straddle",
        mechanism=(
            "Stands in for a real hypothesis so the stage-two machinery can be exercised "
            "without filing trials against one. Nothing here is a claim about markets."
        ),
        null_hypothesis="Not tested here. This record exists to bind a throwaway gate.",
        thresholds=PERMISSIVE,
    )


@pytest.fixture
def corpus(synthetic_store):
    sessions = trading_days(SESSION_COUNT, ending=LAST_SESSION)
    write_corpus(
        synthetic_store.root,
        sessions=sessions,
        spot_for=lambda index: FLAT_SPOT * (1.0 + 0.002 * (index % 5 - 2)),
        expiry=sessions[-1] + dt.timedelta(days=14),
    )
    return synthetic_store(), sessions


def screen(store: SessionStore, log_path: Path, sessions, out: Path) -> Path:
    """One screening run over the first ``SCREENED_SESSIONS`` days, written to ``out``."""
    log = TrialLog(
        log_path,
        clock=ManualClock(dt.datetime(2026, 4, 25, tzinfo=dt.UTC)),
        code_version=StaticCodeVersion("abc123", dirty=False),
    )
    try:
        sheet = ScreeningRun(
            store=store,
            registry=default_registry(),
            trial_log=log,
            hypothesis=hypothesis(),
            window=DataWindow(sessions[0], sessions[SCREENED_SESSIONS - 1]),
            benchmark=CandidateSpec("short_atm_straddle_hold_n", {"hold_sessions": (1.0,)}),
            candidates=[CandidateSpec("short_atm_straddle_hold_n", {"hold_sessions": (2.0,)})],
            config=BacktestConfig(underlying="NIFTY", decision_time=DEFAULT_DECISION_TIME),
            feature_builder=FeatureBuilder(
                store, decision_time=DEFAULT_DECISION_TIME, regime_lookback_sessions=20
            ),
            clock=ManualClock(dt.datetime(2026, 4, 25, tzinfo=dt.UTC)),
            code_version=StaticCodeVersion("abc123", dirty=False),
        ).run()
    finally:
        log.close()
    out.write_text(json.dumps(sheet.as_dict(), indent=2, default=str), encoding="utf-8")
    return out


@pytest.fixture
def staged(corpus, tmp_path: Path):
    """A screened sheet and a gate bound to its hypothesis, ready to be graded."""
    store, sessions = corpus
    sheet_path = screen(store, tmp_path / "screen.db", sessions, tmp_path / "sheet.json")
    document = json.loads(sheet_path.read_text())
    gate_path = tmp_path / "gate.toml"
    gate_path.write_text(
        GATE.format(hypothesis_id=document["provenance"]["hypothesis_id"]), encoding="utf-8"
    )
    return store, sessions, sheet_path, gate_path


def grade(staged, out_dir: Path):
    store, sessions, sheet_path, gate_path = staged
    return run_stage_two_gate(
        sheet_path=sheet_path,
        gate_path=gate_path,
        out_dir=out_dir,
        holdout_end=sessions[-1],
        store=store,
    )


def test_a_passing_in_sample_verdict_spends_the_holdout_and_writes_its_decision(
    staged, tmp_path: Path
) -> None:
    """The branch no real-corpus test reaches: passed in sample, holdout read and graded."""
    out_dir = tmp_path / "decision"
    run = grade(staged, out_dir)

    assert run.decision.in_sample.status is GateStatus.PASSED
    assert run.holdout_spent is True
    assert run.holdout_result is not None
    assert run.decision.holdout is not None
    assert run.decision.outcome in {
        Outcome.PASSES_SURVIVES_HOLDOUT,
        Outcome.PASSES_FAILS_HOLDOUT,
        Outcome.NOT_EVALUABLE,
    }

    record = json.loads((out_dir / DECISION_RECORD_NAME).read_text())
    assert record["holdout_spent"] is True
    assert record["runs"]["holdout"] is not None
    assert record["runs"]["holdout"]["template_parameters"] == pytest.approx(run.parameters)


def test_the_holdout_is_read_once_and_the_read_leaves_exactly_one_touch_row(
    staged, tmp_path: Path
) -> None:
    """One touch row, and it names the run it was written for.

    The touch is what makes the read answerable afterwards, and a second one would mean
    the holdout had been graded twice under one decision.
    """
    run = grade(staged, tmp_path / "decision")

    touches = [row for row in run.trial_rows if row["metrics"].get("holdout_touch")]
    assert len(touches) == 1
    assert run.holdout_result is not None
    assert touches[0]["metrics"]["graded_run_trial_id"] == run.holdout_result.trial_id
    assert run.trial_count == len(run.trial_rows)


def test_the_holdout_run_lies_wholly_past_the_screened_window(staged, tmp_path: Path) -> None:
    _, _, sheet_path, _ = staged
    window_end = load_screen_sheet(sheet_path).window.end

    run = grade(staged, tmp_path / "decision")

    assert run.holdout_result is not None
    assert run.holdout_result.start > window_end
    assert run.in_sample_result.end <= window_end


def test_a_second_run_over_the_same_holdout_is_refused(staged, tmp_path: Path) -> None:
    """The holdout is spendable once, and the log is what remembers that.

    The first run's holdout trials sit in the family; a second run's grading finds them
    and refuses rather than quietly grading the same months again.
    """
    grade(staged, tmp_path / "decision")

    with pytest.raises(HoldoutTouchedError, match="already been read"):
        grade(staged, tmp_path / "decision_again")
