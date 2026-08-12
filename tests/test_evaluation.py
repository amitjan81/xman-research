"""Acceptance criterion 2: every evaluation appears in the log, including from a
notebook — i.e. a plain function call, with no CLI and no blessed entrypoint."""

from __future__ import annotations

import sqlite3
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
    # Type and message, plus the frame that raised. The traceback object is gone by the
    # time anyone reads the row, and "ValueError: no data" alone does not say which of
    # several similar calls in a long body produced it.
    assert trial.error is not None
    assert trial.error.startswith("ValueError: no data for this window")
    assert "in evaluate" in trial.error
    assert "test_evaluation.py:" in trial.error
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


# ------------------------------------------------------------------------------------
# Finding C-2: the append happens in a `finally`, so anything that raises there is not
# a failed trial — it is an evaluation that ran, produced a number the researcher keeps,
# and left no row. Each test below is a way that used to happen.
# ------------------------------------------------------------------------------------


def test_a_circular_reference_in_metrics_still_logs(
    session: ResearchSession, h1: HypothesisRecord, window: DataWindow
) -> None:
    """The accidental vector: a config dict with a back-reference.

    ``json_safe`` recursed forever and the RecursionError surfaced from the ``finally``,
    so the body had run, the result was in hand, and the log had zero rows.
    """
    config: dict = {"tenor": "30d"}
    config["self"] = config

    with session.trial(h1, data_window=window) as trial:
        trial.record_metrics(cfg=config, sharpe=1.3)

    assert session.count_trials(h1) == 1
    logged = session.trials(h1)[0]
    assert logged.metrics["sharpe"] == 1.3
    assert "circular" in logged.metrics["cfg"]["self"]


def test_deep_nesting_still_logs(
    session: ResearchSession, h1: HypothesisRecord, window: DataWindow
) -> None:
    """A cycle guard alone is not enough: deep *non-cyclic* nesting also blew the stack."""
    deep: object = {"leaf": 1}
    for _ in range(3000):
        deep = {"nested": deep}

    with session.trial(h1, data_window=window) as trial:
        trial.record_metrics(cfg=deep, sharpe=0.4)

    assert session.count_trials(h1) == 1
    assert session.trials(h1)[0].metrics["sharpe"] == 0.4


def test_a_wrong_typed_window_is_refused_before_the_body_runs(
    session: ResearchSession, h1: HypothesisRecord
) -> None:
    """Validation used to live only in the append, i.e. after the evaluation had run."""
    body_ran = False

    with (
        pytest.raises(TypeError, match="DataWindow"),
        session.trial(h1, data_window=("2023-01-01", "2024-12-31")) as trial,  # type: ignore[arg-type]
    ):
        body_ran = True
        trial.record_metrics(sharpe=2.5)

    assert body_ran is False, "the block must not run at all if its trial cannot be logged"
    session.register(h1)
    assert session.count_trials(h1) == 0


def test_the_identity_fields_cannot_be_reassigned_by_the_body(
    session: ResearchSession, h1: HypothesisRecord, window: DataWindow
) -> None:
    """The deliberate vector, and the sharpest one.

    Pointing ``hypothesis_id`` at an unregistered id made the append raise from the
    ``finally``: not misattribution — a complete un-log, which is precisely the "a
    researcher cannot un-try a variant" property gone. The fields are read-only now, so
    the attempt fails inside the body, is itself logged as an errored trial, and still
    increments the count.
    """
    with pytest.raises(AttributeError), session.trial(h1, data_window=window) as trial:
        trial.record_metrics(sharpe=-5.0)
        trial.hypothesis_id = "h_nonexistent"  # type: ignore[misc]

    assert session.count_trials(h1) == 1
    logged = session.trials(h1)[0]
    assert logged.hypothesis_id == h1.id
    assert logged.outcome is TrialOutcome.ERROR
    assert logged.metrics == {"sharpe": -5.0}

    for attribute, value in (("trial_id", "t_other"), ("data_window", None)):
        with pytest.raises(AttributeError), session.trial(h1, data_window=window) as trial:
            setattr(trial, attribute, value)


def test_a_garbage_outcome_still_logs(
    session: ResearchSession, h1: HypothesisRecord, window: DataWindow
) -> None:
    """``TrialOutcome("garbage")`` raised in the finally; the row went with it."""
    with session.trial(h1, data_window=window) as trial:
        trial.record_metrics(sharpe=1.1)
        trial.outcome = "garbage"  # type: ignore[assignment]

    assert session.count_trials(h1) == 1
    logged = session.trials(h1)[0]
    assert logged.outcome is TrialOutcome.ERROR
    assert "garbage" in (logged.notes or "")
    assert logged.metrics == {"sharpe": 1.1}


def test_non_text_notes_still_log(
    session: ResearchSession, h1: HypothesisRecord, window: DataWindow
) -> None:
    """sqlite3 refuses to bind an arbitrary object, and that refusal deleted the trial."""
    with session.trial(h1, data_window=window) as trial:
        trial.record_metrics(sharpe=0.8)
        trial.notes = object()  # type: ignore[assignment]

    assert session.count_trials(h1) == 1
    assert session.trials(h1)[0].metrics == {"sharpe": 0.8}


def test_metrics_are_made_safe_at_record_time_not_at_append_time(
    session: ResearchSession, h1: HypothesisRecord, window: DataWindow
) -> None:
    """Where serialisation happens decides who pays when it goes wrong.

    Recording eagerly means a value that degrades does so at the call site inside the
    body, where the ``finally`` still logs the trial — rather than in the ``finally``,
    where it costs the row. It also snapshots: a dict mutated after being recorded
    cannot change what the log says was evaluated.
    """
    mutable = {"delta": 0.30}
    with session.trial(h1, data_window=window, params={"seed": 7}) as trial:
        trial.record_params(mutable)
        mutable["delta"] = 0.99

    logged = session.trials(h1)[0]
    assert logged.params == {"seed": 7, "delta": 0.30}


# ------------------------------------------------- deferred bodies (finding m-13)


def test_an_async_evaluation_is_refused(
    session: ResearchSession, h1: HypothesisRecord, window: DataWindow
) -> None:
    """Decorating ``async def`` logged COMPLETED before a line of the body ran.

    The ``with`` block ends when the coroutine object is constructed, so the trial was
    recorded as a finished success and the real run — whenever something awaited it —
    was recorded nowhere. IPython's top-level ``await`` makes this an ordinary notebook
    shape, not an exotic one.
    """
    with pytest.raises(TypeError, match="async def"):

        @session.evaluation(h1, data_window=window)
        async def evaluate() -> dict[str, float]:  # pragma: no cover - never called
            return {"sharpe": 1.0}

    session.register(h1)
    assert session.count_trials(h1) == 0


def test_a_generator_evaluation_is_refused(
    session: ResearchSession, h1: HypothesisRecord, window: DataWindow
) -> None:
    """Same failure, different keyword: the work happens on iteration, not on call."""
    with pytest.raises(TypeError, match="generator"):

        @session.evaluation(h1, data_window=window)
        def evaluate():  # type: ignore[no-untyped-def]  # pragma: no cover - never called
            yield {"sharpe": 1.0}


def test_two_windows_are_refused_rather_than_silently_halved(
    session: ResearchSession, h1: HypothesisRecord, window: DataWindow
) -> None:
    """Walk-forward passes a train window and a test window; the first used to win.

    Filing the trial under one of them silently makes the row look comparable to rows
    it is not comparable with, which is worse than refusing.
    """
    test_window = DataWindow(date(2025, 1, 1), date(2025, 6, 30))

    @session.evaluation(h1)
    def evaluate(train: DataWindow, test: DataWindow) -> dict[str, float]:
        return {"sharpe": 1.0}

    with pytest.raises(ValueError, match="more than one DataWindow"):
        evaluate(window, test_window)

    session.register(h1)
    assert session.count_trials(h1) == 0


def test_the_session_closes_its_log(
    db_path: Path, clock: ManualClock, code_version: StaticCodeVersion, h1: HypothesisRecord
) -> None:
    with open_session(db_path, clock=clock, code_version=code_version) as opened:
        opened.register(h1)
        with opened.trial(h1, data_window=DataWindow(date(2023, 1, 1), date(2023, 6, 30))):
            pass
        assert opened.count_trials(h1) == 1

    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        opened.count_trials(h1)
