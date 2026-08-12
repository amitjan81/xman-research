"""The log itself: append-only enforcement, provenance, and the counts."""

from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from xman_research import (
    AppendOnlyViolation,
    DataWindow,
    HypothesisRecord,
    ManualClock,
    StaticCodeVersion,
    TrialLog,
    TrialOutcome,
    UnknownHypothesisError,
)


def append(log: TrialLog, hypothesis: HypothesisRecord, **overrides: object) -> object:
    payload: dict = {
        "hypothesis_id": hypothesis.id,
        "params": {"delta": 0.30},
        "data_window": DataWindow(date(2023, 1, 1), date(2024, 12, 31)),
        "metrics": {"sharpe": 1.2},
    }
    payload.update(overrides)
    return log.append_trial(**payload)


# ------------------------------------------------------------- append-only


def test_update_on_trials_is_refused_by_the_database(log: TrialLog, h1: HypothesisRecord) -> None:
    log.register_hypothesis(h1)
    append(log, h1)
    with pytest.raises(AppendOnlyViolation, match="append-only"):
        log._conn.execute("UPDATE trials SET metrics_json = '{\"sharpe\": 99}'")
    assert log.count_trials(h1.id) == 1
    assert log.trials(h1.id)[0].metrics["sharpe"] == 1.2


def test_delete_on_trials_is_refused_by_the_database(log: TrialLog, h1: HypothesisRecord) -> None:
    log.register_hypothesis(h1)
    append(log, h1)
    with pytest.raises(AppendOnlyViolation, match="append-only"):
        log._conn.execute("DELETE FROM trials")
    assert log.count_trials(h1.id) == 1


def test_append_only_violation_is_the_sqlite_integrity_error(log: TrialLog) -> None:
    assert AppendOnlyViolation is sqlite3.IntegrityError


def test_hypothesis_rows_are_immutable_too(log: TrialLog, h1: HypothesisRecord) -> None:
    log.register_hypothesis(h1)
    with pytest.raises(AppendOnlyViolation, match="immutable"):
        log._conn.execute("UPDATE hypotheses SET thresholds_json = '{}'")
    with pytest.raises(AppendOnlyViolation, match="immutable"):
        log._conn.execute("DELETE FROM hypotheses")


def test_enforcement_survives_a_reopen(
    db_path: Path, clock: ManualClock, code_version: StaticCodeVersion, h1: HypothesisRecord
) -> None:
    """The triggers live in the file, so a fresh connection inherits them."""
    with TrialLog(db_path, clock=clock, code_version=code_version) as first:
        first.register_hypothesis(h1)
        append(first, h1)

    with TrialLog(db_path, clock=clock, code_version=code_version) as second:
        assert second.count_trials(h1.id) == 1
        with pytest.raises(AppendOnlyViolation):
            second._conn.execute("DELETE FROM trials")


# ---------------------------------------------------------------- registration


def test_registration_is_idempotent(log: TrialLog, h1: HypothesisRecord) -> None:
    log.register_hypothesis(h1)
    log.register_hypothesis(h1)
    rows = log._conn.execute("SELECT COUNT(*) AS n FROM hypotheses").fetchone()
    assert rows["n"] == 1


def test_hypothesis_round_trips(log: TrialLog, h1: HypothesisRecord) -> None:
    log.register_hypothesis(h1)
    restored = log.get_hypothesis(h1.id)
    assert restored.id == h1.id
    assert restored.mechanism == h1.mechanism
    assert restored.thresholds == dict(h1.thresholds)
    assert restored.predictors == h1.predictors


def test_trial_against_an_unregistered_hypothesis_is_refused(
    log: TrialLog, h1: HypothesisRecord
) -> None:
    with pytest.raises(UnknownHypothesisError):
        append(log, h1)


def test_counting_an_unregistered_hypothesis_is_an_error_not_zero(
    log: TrialLog, h1: HypothesisRecord
) -> None:
    """Silently returning 0 would understate the trial count — the exact failure mode."""
    with pytest.raises(UnknownHypothesisError):
        log.count_trials(h1.id)


def test_amendment_requires_its_parent_to_be_registered(
    log: TrialLog, h1: HypothesisRecord
) -> None:
    with pytest.raises(UnknownHypothesisError, match="parent"):
        log.register_hypothesis(h1.amend(thresholds={"deflated_sharpe": 0.5}))


# ------------------------------------------------------------------ the row


def test_row_carries_injected_time_and_code_version(log: TrialLog, h1: HypothesisRecord) -> None:
    log.register_hypothesis(h1)
    trial = append(log, h1)
    stored = log.trials(h1.id)[0]

    assert stored.trial_id == trial.trial_id
    assert stored.created_at == datetime(2026, 8, 12, 9, 15, 1, tzinfo=UTC)
    assert stored.code_version.sha == "0123456789abcdef0123456789abcdef01234567"
    assert stored.code_version.dirty is False
    assert stored.params == {"delta": 0.30}
    assert stored.metrics == {"sharpe": 1.2}
    assert stored.data_window == DataWindow(date(2023, 1, 1), date(2024, 12, 31))
    assert stored.outcome is TrialOutcome.COMPLETED


def test_a_dirty_tree_is_marked_dirty(
    db_path: Path, clock: ManualClock, h1: HypothesisRecord
) -> None:
    with TrialLog(
        db_path, clock=clock, code_version=StaticCodeVersion("abc123", dirty=True)
    ) as log:
        log.register_hypothesis(h1)
        append(log, h1)
        assert log.trials(h1.id)[0].code_version.dirty is True


def test_a_naive_clock_is_refused(db_path: Path, h1: HypothesisRecord) -> None:
    naive = type("NaiveClock", (), {"now": lambda self: datetime(2026, 8, 12, 9, 0)})()
    log = TrialLog(db_path, clock=naive, code_version=StaticCodeVersion())
    with pytest.raises(ValueError, match="timezone-aware"):
        log.register_hypothesis(h1)
    log.close()


def test_error_outcome_is_stored(log: TrialLog, h1: HypothesisRecord) -> None:
    log.register_hypothesis(h1)
    append(log, h1, outcome=TrialOutcome.ERROR, error="ValueError: no data", metrics={})
    stored = log.trials(h1.id)[0]
    assert stored.outcome is TrialOutcome.ERROR
    assert stored.error == "ValueError: no data"


def test_params_survive_exotic_values(log: TrialLog, h1: HypothesisRecord) -> None:
    """A param that JSON cannot encode must not cost us the trial row."""
    log.register_hypothesis(h1)
    append(log, h1, params={"model": object(), "when": date(2024, 5, 1), "legs": {"b", "a"}})
    stored = log.trials(h1.id)[0].params
    assert stored["when"] == "2024-05-01"
    assert stored["legs"] == ["a", "b"]
    assert "object object at" in stored["model"]


class _NumericWrapper:
    """Stands in for `np.int64` — not an `int` subclass, unwraps via `.item()`."""

    def __init__(self, value: object) -> None:
        self._value = value

    def item(self) -> object:
        return self._value


def test_numeric_wrappers_are_stored_as_numbers(log: TrialLog, h1: HypothesisRecord) -> None:
    """A metric computed by pandas/numpy must land as a number, not as its repr.

    `metrics` is the column deflated Sharpe reads. `np.float64` survives because it
    subclasses `float`; `np.int64` and `np.float32` do not, and would otherwise be
    stored as the string "np.int64(412)" without anybody noticing.
    """
    log.register_hypothesis(h1)
    append(
        log,
        h1,
        metrics={"trades": _NumericWrapper(412), "sharpe": _NumericWrapper(1.25)},
    )
    stored = log.trials(h1.id)[0].metrics
    assert stored == {"trades": 412, "sharpe": 1.25}


def test_a_hostile_unwrapper_still_lands_the_row(log: TrialLog, h1: HypothesisRecord) -> None:
    class Exploding:
        def item(self) -> object:
            raise RuntimeError("no")

    log.register_hypothesis(h1)
    append(log, h1, metrics={"weird": Exploding()})
    assert "Exploding object at" in log.trials(h1.id)[0].metrics["weird"]


def test_duplicate_trial_id_is_refused(log: TrialLog, h1: HypothesisRecord) -> None:
    log.register_hypothesis(h1)
    append(log, h1, trial_id="t_fixed")
    with pytest.raises(sqlite3.IntegrityError):
        append(log, h1, trial_id="t_fixed")
    assert log.count_trials(h1.id) == 1


def test_data_window_must_be_a_window(log: TrialLog, h1: HypothesisRecord) -> None:
    log.register_hypothesis(h1)
    with pytest.raises(TypeError, match="DataWindow"):
        append(log, h1, data_window=("2023-01-01", "2024-12-31"))


def test_data_window_refuses_a_reversed_span() -> None:
    with pytest.raises(ValueError, match="precedes"):
        DataWindow(date(2024, 12, 31), date(2023, 1, 1))


def test_trials_are_returned_in_append_order(log: TrialLog, h1: HypothesisRecord) -> None:
    log.register_hypothesis(h1)
    for index in range(5):
        append(log, h1, params={"delta": index / 10})
    deltas = [trial.params["delta"] for trial in log.trials(h1.id)]
    assert deltas == [0.0, 0.1, 0.2, 0.3, 0.4]


# ------------------------------------------------------------------- counting


def test_count_trials_counts_only_this_hypothesis(log: TrialLog, h1: HypothesisRecord) -> None:
    other = h1.amend(name="H1 variant")
    log.register_hypothesis(h1)
    log.register_hypothesis(other)
    append(log, h1)
    append(log, h1)
    append(log, other)

    assert log.count_trials(h1.id) == 2
    assert log.count_trials(other.id) == 1


def test_family_count_spans_the_amendment_tree(log: TrialLog, h1: HypothesisRecord) -> None:
    log.register_hypothesis(h1)
    child_a = h1.amend(thresholds={"deflated_sharpe": 0.5})
    child_b = h1.amend(entry_rule={"entry_time": "10:00", "delta": 0.25})
    log.register_hypothesis(child_a)
    log.register_hypothesis(child_b)
    grandchild = child_a.amend(exit_rule={"exit_time": "14:00"})
    log.register_hypothesis(grandchild)

    append(log, h1)
    for _ in range(3):
        append(log, child_a)
    append(log, child_b)
    for _ in range(2):
        append(log, grandchild)

    assert log.count_trials(h1.id) == 1
    assert log.count_trials(child_a.id) == 3

    # Read from any member of the family, get the whole selection universe.
    for member in (h1, child_a, child_b, grandchild):
        assert log.count_family_trials(member.id) == 7
        assert len(log.family_ids(member.id)) == 4


def test_unrelated_hypotheses_are_separate_families(log: TrialLog, h1: HypothesisRecord) -> None:
    h2 = HypothesisRecord(
        name="H2 — overnight gap",
        mechanism="Overnight risk is borne by fewer participants, so it is compensated.",
        null_hypothesis="Overnight returns have no positive mean after costs.",
        thresholds={"deflated_sharpe": 0.0},
    )
    log.register_hypothesis(h1)
    log.register_hypothesis(h2)
    append(log, h1)
    append(log, h2)
    append(log, h2)

    assert log.count_family_trials(h1.id) == 1
    assert log.count_family_trials(h2.id) == 2


def test_counts_survive_a_reopen(
    db_path: Path, clock: ManualClock, code_version: StaticCodeVersion, h1: HypothesisRecord
) -> None:
    with TrialLog(db_path, clock=clock, code_version=code_version) as first:
        first.register_hypothesis(h1)
        child = h1.amend(thresholds={"deflated_sharpe": 0.5})
        first.register_hypothesis(child)
        append(first, h1)
        append(first, child)

    with TrialLog(db_path, clock=clock, code_version=code_version) as second:
        assert second.count_family_trials(h1.id) == 2


def test_clock_is_never_the_wall_clock(
    db_path: Path, code_version: StaticCodeVersion, h1: HypothesisRecord
) -> None:
    """Every timestamp comes from the injected clock, so history can be replayed.

    Pinned to a moment years in the past: if any code path reached for
    ``datetime.now()`` instead, this row would carry today's date.
    """
    pinned = datetime(2019, 3, 4, 5, 6, 7, tzinfo=UTC)
    with TrialLog(db_path, clock=ManualClock(pinned), code_version=code_version) as log:
        log.register_hypothesis(h1)
        append(log, h1)
        stamped = log.trials(h1.id)[0].created_at

    assert stamped == pinned
    assert stamped < datetime.now(UTC) - timedelta(days=365)
