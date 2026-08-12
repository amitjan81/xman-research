"""Full-chain test — this PR's E2E evidence.

It plays the whole C4 loop the way a researcher at a notebook would: open a session
against a real SQLite file, write a hypothesis down (mechanism, null, thresholds),
explore variants, amend the hypothesis when a threshold looks wrong, run more variants,
and then read the trial count back for the deflated-Sharpe correction.

No CLI, no test doubles for the storage layer — a real database file on disk, opened,
closed, and reopened. Only the clock and the code-version provider are injected, which
is the whole point of injecting them.

What it asserts, in the order the acceptance criteria are written:

1. the hypothesis refuses to exist without mechanism / null / thresholds;
2. every evaluation appears — including the one that raised, and the one run through a
   bare context manager;
3. the count read back is the log's count, spans the amendment family, and there is no
   public API by which the researcher could have supplied it.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from xman_research import (
    AppendOnlyViolation,
    DataWindow,
    HypothesisRecord,
    HypothesisValidationError,
    ManualClock,
    StaticCodeVersion,
    TrialContext,
    TrialOutcome,
    open_session,
)

WINDOW = DataWindow(date(2023, 1, 1), date(2024, 12, 31))
HOLDOUT = DataWindow(date(2025, 1, 1), date(2025, 6, 30))


def test_the_whole_research_loop(tmp_path: Path) -> None:
    db_path = tmp_path / "research.db"
    clock = ManualClock(datetime(2026, 8, 12, 9, 0, tzinfo=UTC), step=timedelta(minutes=7))
    session = open_session(
        db_path,
        clock=clock,
        code_version=StaticCodeVersion("a1b2c3d4e5f60718293a4b5c6d7e8f9012345678", dirty=False),
    )

    # 1 — the record refuses to exist without the fields that carry the discipline.
    complete = {
        "name": "H1",
        "mechanism": "Hedgers pay up for index protection.",
        "null_hypothesis": "No positive mean after costs.",
        "thresholds": {"deflated_sharpe": 0.0},
    }
    for missing in ({"mechanism": " "}, {"null_hypothesis": ""}, {"thresholds": {}}):
        with pytest.raises(HypothesisValidationError):
            HypothesisRecord(**{**complete, **missing})  # type: ignore[arg-type]

    h1 = HypothesisRecord(
        name="H1 — index variance risk premium",
        mechanism=(
            "Indian index hedgers are structurally long protection and price-insensitive "
            "about it, so implied variance sits above subsequently realised variance; a "
            "short-variance position is paid for bearing the crash risk they shed."
        ),
        null_hypothesis=(
            "The implied-minus-realised spread has no positive mean net of the statutory "
            "cost stack, and the strategy does not beat an always-on short-variance "
            "benchmark on a risk-matched basis."
        ),
        thresholds={
            "deflated_sharpe": 0.0,
            "cost_breakeven_multiple": 2.0,
            "pbo_max": 0.5,
        },
        predictors=["iv_30d", "realised_vol_20d", "term_slope"],
        entry_rule={"entry_time": "09:30", "delta": 0.30},
        exit_rule={"exit_time": "15:15"},
    )

    # 2 — exploration. The notebook shape: a decorated function, called directly.
    @session.evaluation(h1)
    def evaluate(data: DataWindow, *, delta: float, tenor_days: int = 30) -> dict[str, float]:
        if delta <= 0:
            raise ValueError("delta must be positive")
        return {
            "sharpe": 0.8 + delta,
            "cost_breakeven_multiple": 1.5 + delta * 2,
            "trades": 412,
        }

    for delta in (0.10, 0.20, 0.30, 0.40):
        evaluate(WINDOW, delta=delta)

    # A run that raised is a trial too — otherwise a variant is un-tried by throwing.
    with pytest.raises(ValueError, match="delta must be positive"):
        evaluate(WINDOW, delta=-0.1)

    # And a run done through the context manager, e.g. a hand-rolled cell.
    with session.trial(h1, data_window=WINDOW, params={"delta": 0.35}) as trial:
        assert isinstance(trial, TrialContext)
        trial.record_metrics(sharpe=1.05, cost_breakeven_multiple=2.2)

    assert session.count_trials(h1) == 6
    assert session.count_family_trials(h1) == 6

    outcomes = [t.outcome for t in session.trials(h1)]
    assert outcomes.count(TrialOutcome.COMPLETED) == 5
    assert outcomes.count(TrialOutcome.ERROR) == 1

    # Every row carries who/when/what-code, from the injected providers.
    for logged in session.trials(h1):
        assert logged.code_version.sha.startswith("a1b2c3d4")
        assert logged.code_version.dirty is False
        assert logged.created_at.tzinfo is not None
        assert logged.data_window == WINDOW

    # 3 — the threshold looks wrong after exploring. Amending is a NEW record, and it
    #     does not reset the multiple-testing burden.
    h1_v2 = h1.amend(thresholds={**dict(h1.thresholds), "cost_breakeven_multiple": 2.5})
    assert h1_v2.id != h1.id and h1_v2.parent_id == h1.id

    @session.evaluation(h1_v2)
    def evaluate_v2(data: DataWindow, *, delta: float) -> dict[str, float]:
        return {"sharpe": 0.9 + delta, "cost_breakeven_multiple": 2.6}

    for delta in (0.25, 0.30, 0.35):
        evaluate_v2(WINDOW, delta=delta)

    assert session.count_trials(h1) == 6
    assert session.count_trials(h1_v2) == 3
    # The number deflated Sharpe needs, read from either end of the family.
    assert session.count_family_trials(h1) == 9
    assert session.count_family_trials(h1_v2) == 9

    # The holdout run is a trial like any other — visible, and counted.
    with session.trial(h1_v2, data_window=HOLDOUT, notes="holdout, run once") as trial:
        trial.record_metrics(sharpe=0.4, cost_breakeven_multiple=1.1)
        trial.mark_not_evaluable("survives only at optimistic costs")

    assert session.count_family_trials(h1_v2) == 10
    session.log.close()

    # 4 — the log is a file on disk, and reopening it tells the same story.
    reopened = open_session(
        db_path, clock=clock, code_version=StaticCodeVersion("later", dirty=True)
    )
    try:
        assert reopened.count_family_trials(h1) == 10
        assert reopened.count_trials(h1) == 6
        assert reopened.log.get_hypothesis(h1_v2.id).parent_id == h1.id
        assert [t.outcome for t in reopened.trials(h1_v2)][-1] is TrialOutcome.NOT_EVALUABLE

        # 5 — history cannot be rewritten, by the database's own rules.
        with pytest.raises(AppendOnlyViolation):
            reopened.log._conn.execute("DELETE FROM trials WHERE outcome = 'error'")
        with pytest.raises(AppendOnlyViolation):
            reopened.log._conn.execute("UPDATE trials SET metrics_json = '{}'")
        assert reopened.count_family_trials(h1) == 10
    finally:
        reopened.log.close()


def test_there_is_no_way_to_tell_the_platform_a_trial_count(tmp_path: Path) -> None:
    """The counterpart to the introspective test: try it as a researcher would.

    Every plausible spelling of "just take my word for it" is a TypeError, and the
    count stays whatever the log says.
    """
    session = open_session(
        tmp_path / "research.db",
        clock=ManualClock(datetime(2026, 8, 12, 9, 0, tzinfo=UTC)),
        code_version=StaticCodeVersion("sha", dirty=False),
    )
    try:
        h1 = HypothesisRecord(
            name="H1",
            mechanism="Hedgers pay up for protection.",
            null_hypothesis="No positive mean after costs.",
            thresholds={"deflated_sharpe": 0.0},
        )
        with session.trial(h1, data_window=WINDOW):
            pass

        for attempt in (
            {"n_trials": 1},
            {"trial_count": 1},
            {"trials": 1},
            {"count": 1},
        ):
            with pytest.raises(TypeError):
                session.count_family_trials(h1, **attempt)  # type: ignore[call-arg]
            with pytest.raises(TypeError):
                session.log.count_trials(h1.id, **attempt)  # type: ignore[call-arg]

        assert session.count_trials(h1) == 1
    finally:
        session.log.close()
