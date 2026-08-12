"""Acceptance criterion 2: every evaluation appears in the log, including from a
notebook — i.e. a plain function call, with no CLI and no blessed entrypoint."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from xman_research import (
    DataWindow,
    HypothesisRecord,
    ManualClock,
    ResearchSession,
    StaticCodeVersion,
    TrialContext,
    TrialOutcome,
    open_session,
)


def test_decorated_call_is_logged_without_any_cli(
    session: ResearchSession, h1: HypothesisRecord, window: DataWindow
) -> None:
    """The notebook path: define a function, call it, the row is there."""

    @session.evaluation(h1)
    def evaluate(data: DataWindow, *, delta: float) -> dict[str, float]:
        return {"sharpe": 1.4, "cost_breakeven_multiple": 2.6}

    result = evaluate(window, delta=0.30)

    assert result == {"sharpe": 1.4, "cost_breakeven_multiple": 2.6}
    assert session.count_trials(h1) == 1
    trial = session.trials(h1)[0]
    assert trial.params == {"delta": 0.30}
    assert trial.metrics == {"sharpe": 1.4, "cost_breakeven_multiple": 2.6}
    assert trial.data_window == window
    assert trial.outcome is TrialOutcome.COMPLETED


def test_the_hypothesis_is_registered_by_the_seam(
    session: ResearchSession, h1: HypothesisRecord, window: DataWindow
) -> None:
    """No separate register() step to forget before the first trial."""

    @session.evaluation(h1)
    def evaluate(data: DataWindow) -> dict[str, float]:
        return {"sharpe": 0.2}

    evaluate(window)
    assert session.log.get_hypothesis(h1.id).id == h1.id


def test_each_call_is_its_own_trial(
    session: ResearchSession, h1: HypothesisRecord, window: DataWindow
) -> None:
    @session.evaluation(h1)
    def evaluate(data: DataWindow, *, delta: float) -> dict[str, float]:
        return {"sharpe": delta * 3}

    for delta in (0.10, 0.20, 0.30, 0.40):
        evaluate(window, delta=delta)

    assert session.count_trials(h1) == 4
    assert [t.params["delta"] for t in session.trials(h1)] == [0.10, 0.20, 0.30, 0.40]
    assert len({t.trial_id for t in session.trials(h1)}) == 4


def test_a_raising_evaluation_is_still_a_trial(
    session: ResearchSession, h1: HypothesisRecord, window: DataWindow
) -> None:
    """Otherwise a variant could be un-tried by making it throw."""

    @session.evaluation(h1)
    def evaluate(data: DataWindow, *, delta: float) -> dict[str, float]:
        raise ValueError("no data for this window")

    with pytest.raises(ValueError, match="no data"):
        evaluate(window, delta=0.30)

    assert session.count_trials(h1) == 1
    trial = session.trials(h1)[0]
    assert trial.outcome is TrialOutcome.ERROR
    assert trial.error == "ValueError: no data for this window"
    assert trial.params == {"delta": 0.30}


def test_defaults_are_recorded_as_params(
    session: ResearchSession, h1: HypothesisRecord, window: DataWindow
) -> None:
    """What actually ran, not what was typed — an unpassed default is still a choice."""

    @session.evaluation(h1)
    def evaluate(data: DataWindow, *, delta: float = 0.25, tenor: str = "30d") -> dict[str, float]:
        return {"sharpe": 1.0}

    evaluate(window)
    assert session.trials(h1)[0].params == {"delta": 0.25, "tenor": "30d"}


def test_window_may_come_from_the_decorator(
    session: ResearchSession, h1: HypothesisRecord, window: DataWindow
) -> None:
    @session.evaluation(h1, data_window=window)
    def evaluate(*, delta: float) -> dict[str, float]:
        return {"sharpe": 1.0}

    evaluate(delta=0.3)
    assert session.trials(h1)[0].data_window == window


def test_a_call_argument_window_wins_over_the_decorator(
    session: ResearchSession, h1: HypothesisRecord, window: DataWindow
) -> None:
    other = DataWindow(date(2020, 1, 1), date(2020, 12, 31))

    @session.evaluation(h1, data_window=window)
    def evaluate(data: DataWindow) -> dict[str, float]:
        return {"sharpe": 1.0}

    evaluate(other)
    assert session.trials(h1)[0].data_window == other


def test_an_evaluation_without_a_window_is_refused(
    session: ResearchSession, h1: HypothesisRecord
) -> None:
    @session.evaluation(h1)
    def evaluate(*, delta: float) -> dict[str, float]:
        return {"sharpe": 1.0}

    with pytest.raises(ValueError, match="data window"):
        evaluate(delta=0.3)


def test_non_mapping_return_is_logged_with_a_note(
    session: ResearchSession, h1: HypothesisRecord, window: DataWindow
) -> None:
    @session.evaluation(h1)
    def evaluate(data: DataWindow) -> list[float]:
        return [1.0, 2.0]

    evaluate(window)
    trial = session.trials(h1)[0]
    assert trial.metrics == {}
    assert "not a metrics mapping" in (trial.notes or "")


def test_the_running_trial_is_injected_when_asked_for(
    session: ResearchSession, h1: HypothesisRecord, window: DataWindow
) -> None:
    """Forward-shaping: a backtester can require this token to prove it is inside a trial."""
    seen: dict[str, object] = {}

    @session.evaluation(h1)
    def evaluate(data: DataWindow, trial: TrialContext) -> dict[str, float]:
        seen["trial_id"] = trial.trial_id
        seen["hypothesis_id"] = trial.hypothesis_id
        trial.record_metrics(sharpe=1.7)
        trial.record_params(resolved_universe="NIFTY")
        return {"cost_breakeven_multiple": 3.0}

    evaluate(window)
    logged = session.trials(h1)[0]
    assert logged.trial_id == seen["trial_id"]
    assert seen["hypothesis_id"] == h1.id
    assert logged.metrics == {"sharpe": 1.7, "cost_breakeven_multiple": 3.0}
    assert logged.params["resolved_universe"] == "NIFTY"


def test_context_manager_form_logs_too(
    session: ResearchSession, h1: HypothesisRecord, window: DataWindow
) -> None:
    with session.trial(h1, data_window=window, params={"delta": 0.2}) as trial:
        trial.record_metrics({"sharpe": 0.9})

    logged = session.trials(h1)[0]
    assert logged.metrics == {"sharpe": 0.9}
    assert logged.params == {"delta": 0.2}
    assert logged.outcome is TrialOutcome.COMPLETED


def test_context_manager_logs_on_exception(
    session: ResearchSession, h1: HypothesisRecord, window: DataWindow
) -> None:
    with pytest.raises(ZeroDivisionError), session.trial(h1, data_window=window) as trial:
        trial.record_metrics(partial=1.0)
        _ = 1 / 0

    logged = session.trials(h1)[0]
    assert logged.outcome is TrialOutcome.ERROR
    assert logged.metrics == {"partial": 1.0}
    assert "ZeroDivisionError" in (logged.error or "")


def test_not_evaluable_is_expressible(
    session: ResearchSession, h1: HypothesisRecord, window: DataWindow
) -> None:
    """Spec §6's fourth outcome: survives only at optimistic costs."""
    with session.trial(h1, data_window=window) as trial:
        trial.record_metrics(cost_breakeven_multiple=0.8)
        trial.mark_not_evaluable("feasibility failures dominate")

    logged = session.trials(h1)[0]
    assert logged.outcome is TrialOutcome.NOT_EVALUABLE
    assert "feasibility failures" in (logged.notes or "")


def test_open_session_wires_a_working_default(tmp_path: Path, h1: HypothesisRecord) -> None:
    """The one-liner a notebook actually starts with."""
    session = open_session(tmp_path / "nested" / "research.db")
    try:

        @session.evaluation(h1, data_window=DataWindow(date(2024, 1, 1), date(2024, 6, 30)))
        def evaluate() -> dict[str, float]:
            return {"sharpe": 1.0}

        evaluate()
        assert session.count_trials(h1) == 1
        version = session.trials(h1)[0].code_version
        assert version.sha  # a real sha here, or "unknown" outside a checkout
    finally:
        session.log.close()


def test_open_session_accepts_injected_time_and_version(
    tmp_path: Path, h1: HypothesisRecord, window: DataWindow
) -> None:
    from datetime import UTC, datetime

    pinned = datetime(2021, 7, 1, 12, 0, tzinfo=UTC)
    session = open_session(
        tmp_path / "research.db",
        clock=ManualClock(pinned),
        code_version=StaticCodeVersion("deadbeef", dirty=True),
    )
    try:
        with session.trial(h1, data_window=window):
            pass
        trial = session.trials(h1)[0]
        assert trial.created_at == pinned
        assert trial.code_version.sha == "deadbeef"
        assert trial.code_version.dirty is True
    finally:
        session.log.close()
