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
    HypothesisValidationError,
    LogIntegrityError,
    ManualClock,
    SchemaVersionError,
    StaticCodeVersion,
    TrialLog,
    TrialOutcome,
    UnknownHypothesisError,
)
from xman_research.trial_log import SCHEMA_VERSION


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
    """A fresh :class:`TrialLog` inherits the triggers, because they live in the file.

    Note precisely what does and does not carry across, because the obvious reading of
    this test is too generous. The trigger *definitions* are persisted, so plain UPDATE
    and DELETE are refused on any connection at all. The ``recursive_triggers`` pragma
    that makes ``INSERT OR REPLACE`` fire those same triggers is **connection-scoped and
    is not stored in the file** — every :class:`TrialLog` sets it for itself, and
    ``test_a_foreign_connection_without_the_pragma_can_still_replace`` demonstrates the
    gap that leaves, which the module docstring discloses.
    """
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


# ------------------------------------------------- INSERT OR REPLACE (finding C-1)


def _replace_trial(conn: sqlite3.Connection, row: object, *, metrics_json: str) -> None:
    """Re-insert an existing trial row's primary key with different content.

    Both the ``seq`` primary key and the ``trial_id`` unique key are reused on purpose:
    the statement has to create a genuine conflict, or ``INSERT OR REPLACE`` simply
    inserts a second row and the test would pass while proving nothing.
    """
    conn.execute(
        """
        INSERT OR REPLACE INTO trials (
            seq, trial_id, hypothesis_id, created_at, params_json, window_start,
            window_end, code_sha, code_dirty, metrics_json, outcome, error, notes
        ) SELECT seq, trial_id, hypothesis_id, created_at, params_json, window_start,
            window_end, code_sha, code_dirty, ?, outcome, error, 'REWRITTEN'
        FROM trials WHERE trial_id = ?
        """,
        (metrics_json, row.trial_id),  # type: ignore[attr-defined]
    )


def test_insert_or_replace_on_trials_is_refused(log: TrialLog, h1: HypothesisRecord) -> None:
    """The idiom that defeated append-only without anybody intending to.

    ``INSERT OR REPLACE`` resolves its conflict by deleting the existing row, and SQLite
    fires that delete's BEFORE DELETE trigger only when ``recursive_triggers`` is ON.
    With the pragma off — the default — this statement silently rewrote a logged trial's
    metrics, which is the whole property of the module gone to a common upsert.
    """
    log.register_hypothesis(h1)
    original = append(log, h1)

    with pytest.raises(AppendOnlyViolation, match="append-only"):
        _replace_trial(log._conn, original, metrics_json='{"sharpe": 99.0}')

    assert log.count_trials(h1.id) == 1
    stored = log.trials(h1.id)[0]
    assert stored.metrics == {"sharpe": 1.2}, "the logged result must be exactly as written"
    assert stored.notes is None


def test_insert_or_replace_on_hypotheses_is_refused(log: TrialLog, h1: HypothesisRecord) -> None:
    """The worse half: a registered hypothesis rewritten in place, under the same id.

    This is precisely the "change a threshold after seeing the result" move the record
    is content-addressed to prevent, and it needed neither an UPDATE nor a new id.
    """
    log.register_hypothesis(h1)

    with pytest.raises(AppendOnlyViolation, match="immutable"):
        log._conn.execute(
            """
            INSERT OR REPLACE INTO hypotheses (
                id, parent_id, name, mechanism, null_hypothesis, thresholds_json,
                predictors_json, entry_rule_json, exit_rule_json, notes, registered_at
            ) SELECT id, parent_id, name, 'A DIFFERENT MECHANISM', null_hypothesis,
                '{"deflated_sharpe": -99.0}', predictors_json, entry_rule_json,
                exit_rule_json, notes, registered_at
            FROM hypotheses WHERE id = ?
            """,
            (h1.id,),
        )

    stored = log.get_hypothesis(h1.id)
    assert stored.mechanism == h1.mechanism
    assert stored.thresholds["deflated_sharpe"] == 0.0
    assert stored.id == h1.id


def test_a_foreign_connection_without_the_pragma_can_still_replace(
    db_path: Path, clock: ManualClock, code_version: StaticCodeVersion, h1: HypothesisRecord
) -> None:
    """The disclosed limit, pinned as a test so the docstring cannot quietly go stale.

    ``recursive_triggers`` is connection-scoped and is not persisted in the file, so a
    connection this package did not open — a ``sqlite3`` shell, another program's ORM —
    starts with it OFF and can replace a row. What the package *can* still do is notice
    afterwards, because the hypothesis id is derived from the content: see the
    integrity check below.
    """
    with TrialLog(db_path, clock=clock, code_version=code_version) as log:
        log.register_hypothesis(h1)

    foreign = sqlite3.connect(str(db_path))
    try:
        with foreign:  # no PRAGMA recursive_triggers here — that is the point
            foreign.execute(
                """
                INSERT OR REPLACE INTO hypotheses (
                    id, parent_id, name, mechanism, null_hypothesis, thresholds_json,
                    predictors_json, entry_rule_json, exit_rule_json, notes, registered_at
                ) SELECT id, parent_id, name, 'A DIFFERENT MECHANISM', null_hypothesis,
                    thresholds_json, predictors_json, entry_rule_json, exit_rule_json,
                    notes, registered_at
                FROM hypotheses WHERE id = ?
                """,
                (h1.id,),
            )
        rewritten = foreign.execute(
            "SELECT mechanism FROM hypotheses WHERE id = ?", (h1.id,)
        ).fetchone()[0]
    finally:
        foreign.close()

    assert rewritten == "A DIFFERENT MECHANISM", "the file itself is not armoured"

    with (
        TrialLog(db_path, clock=clock, code_version=code_version) as reopened,
        pytest.raises(LogIntegrityError, match="does not hash to its stored id"),
    ):
        reopened.get_hypothesis(h1.id)


def test_get_hypothesis_accepts_an_untampered_record(log: TrialLog, h1: HypothesisRecord) -> None:
    """Guards the guard: the integrity check must not reject honest records."""
    log.register_hypothesis(h1)
    assert log.get_hypothesis(h1.id) == h1


# ----------------------------------------------------- schema version (finding m-13)


def test_a_foreign_schema_version_is_refused(
    db_path: Path, clock: ManualClock, code_version: StaticCodeVersion
) -> None:
    """Stamping unconditionally relabels a file this code cannot read as one it can."""
    with TrialLog(db_path, clock=clock, code_version=code_version):
        pass
    stamper = sqlite3.connect(str(db_path))
    try:
        stamper.execute("PRAGMA user_version = 7")
    finally:
        stamper.close()

    with pytest.raises(SchemaVersionError, match="schema version 7"):
        TrialLog(db_path, clock=clock, code_version=code_version)


def test_reopening_the_current_version_is_fine(
    db_path: Path, clock: ManualClock, code_version: StaticCodeVersion, h1: HypothesisRecord
) -> None:
    with TrialLog(db_path, clock=clock, code_version=code_version) as first:
        first.register_hypothesis(h1)
        append(first, h1)
    with TrialLog(db_path, clock=clock, code_version=code_version) as second:
        assert second.count_trials(h1.id) == 1


# ------------------------------------------------------- cyclic family (finding m-12)


def test_a_cyclic_parent_chain_is_refused_rather_than_counted_as_zero(
    db_path: Path, clock: ManualClock, code_version: StaticCodeVersion
) -> None:
    """A cycle used to resolve to an empty family, and an empty family counts zero.

    Zero is the most flattering answer the multiple-testing correction could possibly be
    handed, so a corrupt chain must not silently produce it. Cycles are unconstructible
    through the API — this test builds one by writing behind it with foreign keys off,
    which is exactly the "written by something else" case the guard is for.
    """
    log = TrialLog(db_path, clock=clock, code_version=code_version)
    try:
        # PRAGMA foreign_keys is a no-op inside a transaction, so it is set outside one.
        log._conn.execute("PRAGMA foreign_keys = OFF")
        for ident, parent in (("h_aaa", "h_bbb"), ("h_bbb", "h_aaa")):
            log._conn.execute(
                """
                INSERT INTO hypotheses (
                    id, parent_id, name, mechanism, null_hypothesis, thresholds_json,
                    predictors_json, entry_rule_json, exit_rule_json, notes, registered_at
                ) VALUES (?, ?, 'n', 'm', 'nh', '{}', '[]', '{}', '{}', '', ?)
                """,
                (ident, parent, "2026-08-12T09:15:00+00:00"),
            )
        log._conn.commit()

        with pytest.raises(LogIntegrityError, match="cycle"):
            log.family_ids("h_aaa")
        with pytest.raises(LogIntegrityError, match="cycle"):
            log.count_family_trials("h_aaa")
    finally:
        log.close()


# ------------------------------------- the append never loses a row (finding C-2)


def test_an_unrecognised_outcome_is_recorded_as_error_not_dropped(
    log: TrialLog, h1: HypothesisRecord
) -> None:
    """``TrialOutcome(outcome)`` used to raise here — from a ``finally``, after the run."""
    log.register_hypothesis(h1)
    record = append(log, h1, outcome="garbage")

    assert record.outcome is TrialOutcome.ERROR
    assert "garbage" in (record.notes or "")
    assert log.count_trials(h1.id) == 1
    assert log.trials(h1.id)[0].outcome is TrialOutcome.ERROR


def test_non_text_notes_and_error_do_not_cost_the_row(log: TrialLog, h1: HypothesisRecord) -> None:
    """sqlite3 refuses to bind an arbitrary object; that refusal used to delete a trial."""
    log.register_hypothesis(h1)
    append(log, h1, notes=object(), error=object())

    stored = log.trials(h1.id)[0]
    assert log.count_trials(h1.id) == 1
    assert isinstance(stored.notes, str) and "object object" in stored.notes
    assert isinstance(stored.error, str)


def test_a_circular_param_is_logged_approximately(log: TrialLog, h1: HypothesisRecord) -> None:
    """A config dict holding a back-reference is an ordinary input, not a hostile one."""
    log.register_hypothesis(h1)
    config: dict = {"name": "sweep"}
    config["self"] = config
    append(log, h1, params={"cfg": config, "delta": 0.30})

    stored = log.trials(h1.id)[0]
    assert log.count_trials(h1.id) == 1
    assert stored.params["delta"] == 0.30
    assert "circular" in stored.params["cfg"]["self"]


def test_an_unmappable_params_object_is_logged_approximately(
    log: TrialLog, h1: HypothesisRecord
) -> None:
    log.register_hypothesis(h1)
    append(log, h1, params=object())

    stored = log.trials(h1.id)[0]
    assert log.count_trials(h1.id) == 1
    assert "__unmappable__" in stored.params


def test_trial_ids_are_full_width(log: TrialLog, h1: HypothesisRecord) -> None:
    """A trial_id collision is a failed INSERT in a finally — a lost row, not a clash."""
    log.register_hypothesis(h1)
    record = append(log, h1)
    assert len(record.trial_id) == len("t_") + 32


def test_screen_criteria_round_trip_through_the_log(log: TrialLog) -> None:
    record = HypothesisRecord(
        name="BANKNIFTY screen",
        mechanism="Index hedgers pay up for protection, so implied sits above realised.",
        null_hypothesis="No screened structure beats the unconditional straddle.",
        thresholds={"deflated_sharpe": 0.90},
        screen_criteria={
            "alpha_to_advance": 0.5,
            "alpha_to_advance_definition": "the spread's Sharpe",
        },
    )
    log.register_hypothesis(record)
    read_back = log.get_hypothesis(record.id)
    assert read_back.id == record.id
    assert dict(read_back.screen_criteria) == dict(record.screen_criteria)


def test_registering_an_ungradeable_record_is_refused_however_it_was_built(
    log: TrialLog,
) -> None:
    """`from_stored` skips the vocabulary check so an older log stays readable; it is not a
    way to get a criterion nothing measures into a log as new evidence."""
    smuggled = HypothesisRecord.from_stored(
        name="BANKNIFTY screen",
        mechanism="Index hedgers pay up for protection, so implied sits above realised.",
        null_hypothesis="No screened structure beats the unconditional straddle.",
        thresholds={"alpha_to_advance": 0.5},
    )
    with pytest.raises(HypothesisValidationError, match="alpha_to_advance"):
        log.register_hypothesis(smuggled)


def test_a_record_already_in_the_log_is_re_registered_without_being_re_judged(
    log: TrialLog,
) -> None:
    """Re-registration is a no-op on a content-addressed id, and a stored record is
    evidence: a vocabulary that narrows later must not make its own log unwritable."""
    stored = HypothesisRecord.from_stored(
        name="BANKNIFTY screen",
        mechanism="Index hedgers pay up for protection, so implied sits above realised.",
        null_hypothesis="No screened structure beats the unconditional straddle.",
        thresholds={"alpha_to_advance": 0.5},
    )
    log._conn.execute(
        "INSERT INTO hypotheses (id, parent_id, name, mechanism, null_hypothesis, "
        "thresholds_json, predictors_json, entry_rule_json, exit_rule_json, notes, "
        "screen_criteria_json, registered_at) VALUES (?, NULL, ?, ?, ?, ?, '[]', '{}', "
        "'{}', '', '{}', '2026-08-25T00:00:00+00:00')",
        (
            stored.id,
            stored.name,
            stored.mechanism,
            stored.null_hypothesis,
            '{"alpha_to_advance": 0.5}',
        ),
    )
    log._conn.commit()
    assert log.register_hypothesis(stored).id == stored.id


def _write_schema_v1(path: Path) -> str:
    """A log in the shape that predates `screen_criteria_json`, holding one record."""
    record = HypothesisRecord.from_stored(
        name="BANKNIFTY screen",
        mechanism="Index hedgers pay up for protection, so implied sits above realised.",
        null_hypothesis="No screened structure beats the unconditional straddle.",
        thresholds={"alpha_to_advance": 0.5},
    )
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE hypotheses (
            id TEXT PRIMARY KEY, parent_id TEXT, name TEXT NOT NULL, mechanism TEXT NOT NULL,
            null_hypothesis TEXT NOT NULL, thresholds_json TEXT NOT NULL,
            predictors_json TEXT NOT NULL, entry_rule_json TEXT NOT NULL,
            exit_rule_json TEXT NOT NULL, notes TEXT NOT NULL DEFAULT '',
            registered_at TEXT NOT NULL
        );
        PRAGMA user_version = 1;
        """
    )
    conn.execute(
        "INSERT INTO hypotheses VALUES (?, NULL, ?, ?, ?, ?, '[]', '{}', '{}', '', ?)",
        (
            record.id,
            record.name,
            record.mechanism,
            record.null_hypothesis,
            '{"alpha_to_advance": 0.5}',
            "2026-08-25T00:00:00+00:00",
        ),
    )
    conn.commit()
    conn.close()
    return record.id


def test_a_schema_v1_log_is_brought_forward_without_its_content_moving(
    tmp_path: Path, clock: ManualClock, code_version: StaticCodeVersion
) -> None:
    """The upgrade adds a column and nothing else. A log is evidence: an id that moved
    would break the join between a record and the trials filed against it."""
    path = tmp_path / "v1.db"
    stored_id = _write_schema_v1(path)

    log = TrialLog(path, clock=clock, code_version=code_version)
    assert log.get_hypothesis(stored_id).id == stored_id
    assert dict(log.get_hypothesis(stored_id).screen_criteria) == {}
    log.close()

    with sqlite3.connect(path) as conn:
        assert int(conn.execute("PRAGMA user_version").fetchone()[0]) == SCHEMA_VERSION
        columns = {row[1] for row in conn.execute("PRAGMA table_info(hypotheses)")}
        assert "screen_criteria_json" in columns

    # Opening it again is a no-op rather than a second migration.
    reopened = TrialLog(path, clock=clock, code_version=code_version)
    assert reopened.get_hypothesis(stored_id).id == stored_id
    reopened.close()


def test_a_v1_log_that_already_has_the_column_is_stamped_without_a_second_alter(
    tmp_path: Path, clock: ManualClock, code_version: StaticCodeVersion
) -> None:
    """The column check is what makes the upgrade re-runnable on a partially applied file."""
    path = tmp_path / "half.db"
    stored_id = _write_schema_v1(path)
    with sqlite3.connect(path) as conn:
        conn.execute(
            "ALTER TABLE hypotheses ADD COLUMN screen_criteria_json TEXT NOT NULL DEFAULT '{}'"
        )
        conn.execute("PRAGMA user_version = 1")

    log = TrialLog(path, clock=clock, code_version=code_version)
    assert log.get_hypothesis(stored_id).id == stored_id
    log.close()
    with sqlite3.connect(path) as conn:
        assert int(conn.execute("PRAGMA user_version").fetchone()[0]) == SCHEMA_VERSION

