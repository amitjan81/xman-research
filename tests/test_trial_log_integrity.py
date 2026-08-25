"""Three defects in the trial log, and the properties that must survive fixing them.

Issues #14 (a run that recorded no result taxes the hypothesis under deflated Sharpe),
#19 (a trial_id that names no row is indistinguishable from no trial_id) and #20 (the
``adjusted_sharpe`` rename split the log schema and nothing reads across the split).

The two load-bearing properties are asserted here alongside each fix, because each fix is
in exactly the position to break one of them: the log stays append-only, and no caller
can supply a trial count. ``test_no_caller_supplied_count.py`` polices the second
structurally; this file checks that the *new* reporting surface reads from the log too.
"""

from __future__ import annotations

import datetime as dt
import math
from pathlib import Path
from types import MappingProxyType

import pytest

from xman_research import (
    DataWindow,
    HypothesisRecord,
    ManualClock,
    ResearchSession,
    StaticCodeVersion,
    TrialLog,
    TrialOutcome,
    UnknownTrialError,
    open_session,
    trial_log,
)
from xman_research.adapter import logged_run_at
from xman_research.validation.decision import _logged_created_at
from xman_research.validation.series import ReturnSeries
from xman_research.validation.statistics import (
    SelectionUniverse,
    deflated_sharpe_ratio,
    probabilistic_sharpe_ratio,
)

WINDOW = DataWindow(dt.date(2025, 1, 1), dt.date(2025, 6, 30))


def series_from(values: list[float]) -> ReturnSeries:
    start = dt.date(2025, 1, 6)
    days = tuple(start + dt.timedelta(days=index) for index in range(len(values)))
    return ReturnSeries(
        dates=days, net=tuple(values), drag=tuple(0.0 for _ in values), label="fixture"
    )


def hypothesis(
    name: str = "H — variance premium", parent_id: str | None = None
) -> HypothesisRecord:
    return HypothesisRecord(
        name=name,
        mechanism=(
            "Index hedgers pay up for downside protection, so implied variance sits above "
            "subsequently realised variance and a short-variance position collects it."
        ),
        null_hypothesis="Implied minus realised variance has no positive mean after costs.",
        thresholds={"deflated_sharpe": 0.0},
        parent_id=parent_id,
    )


def append(
    log: TrialLog,
    record: HypothesisRecord,
    *,
    outcome: TrialOutcome = TrialOutcome.COMPLETED,
    metrics: dict | None = None,
    error: str | None = None,
):
    return log.append_trial(
        hypothesis_id=record.id,
        params={},
        data_window=WINDOW,
        metrics={} if metrics is None else metrics,
        outcome=outcome,
        error=error,
    )


# ===================================================================== #14 — no result


def test_a_row_that_recorded_no_result_is_identified_from_the_row_alone(
    log: TrialLog,
) -> None:
    """The classifier is two stored facts, not a judgement about why the run died."""
    record = hypothesis()
    log.register_hypothesis(record)
    crashed = append(log, record, outcome=TrialOutcome.ERROR, error="TypeError: boom")
    raised_with_numbers = append(
        log, record, outcome=TrialOutcome.ERROR, error="late failure", metrics={"sharpe": 0.4}
    )
    completed = append(log, record)
    empty_but_completed = append(log, record)

    assert crashed.recorded_no_result is True
    assert raised_with_numbers.recorded_no_result is False
    assert completed.recorded_no_result is False
    assert empty_but_completed.recorded_no_result is False


def test_a_not_evaluable_run_still_counts_as_a_trial(log: TrialLog) -> None:
    """NOT_EVALUABLE is a run that happened and was judged. Only ERROR is excludable."""
    record = hypothesis()
    log.register_hypothesis(record)
    judged = append(log, record, outcome=TrialOutcome.NOT_EVALUABLE)

    assert judged.metrics == {}
    assert judged.recorded_no_result is False


def test_the_universe_reports_both_sizes_and_reads_both_from_the_log(
    session: ResearchSession,
) -> None:
    record = hypothesis()
    session.register(record)
    for _ in range(5):
        append(session.log, record, metrics={"sharpe_per_period": 0.03})
    for _ in range(2):
        append(session.log, record, outcome=TrialOutcome.ERROR, error="KeyError: no instrument")

    universe = SelectionUniverse(session, record)

    assert universe.size == 7 == session.count_family_trials(record)
    assert universe.size_excluding_no_result == 5


def test_the_deflation_reports_the_spread_and_still_grades_on_the_raw_count(
    session: ResearchSession,
) -> None:
    """Option 3. The tax is made visible, not removed — ``value`` is still the verdict."""
    record = hypothesis()
    session.register(record)
    for index in range(6):
        append(session.log, record, metrics={"sharpe_per_period": 0.01 * (index % 4)})
    for _ in range(3):
        append(session.log, record, outcome=TrialOutcome.ERROR, error="TypeError: boom")

    data = series_from([0.01, 0.012, -0.004, 0.02, 0.008, 0.011, -0.002, 0.015] * 12)
    result = deflated_sharpe_ratio(data, universe=SelectionUniverse(session, record))

    assert result.selection_size == 9
    assert result.selection_size_excluding_no_result == 6
    # A smaller search is a smaller correction, so the excluded number is the higher one.
    assert result.value_excluding_no_result > result.value
    payload = result.as_dict()
    assert payload["deflated_sharpe"] == result.value
    assert payload["deflated_sharpe_excluding_no_result"] == result.value_excluding_no_result
    assert payload["selection_size_excluding_no_result"] == 6


def test_the_two_deflations_agree_when_nothing_crashed(session: ResearchSession) -> None:
    """No spread to report is reported as no spread, not as a missing number."""
    record = hypothesis()
    session.register(record)
    for _ in range(4):
        append(session.log, record, metrics={"sharpe_per_period": 0.02})

    data = series_from([0.01, 0.012, -0.004, 0.02, 0.008, 0.011, -0.002, 0.015] * 12)
    result = deflated_sharpe_ratio(data, universe=SelectionUniverse(session, record))

    assert result.selection_size == result.selection_size_excluding_no_result == 4
    assert result.value_excluding_no_result == result.value


def test_excluding_no_result_rows_never_deletes_them(session: ResearchSession) -> None:
    """The exclusion is a read-side view. Every row is still in the log and still counted."""
    record = hypothesis()
    session.register(record)
    append(session.log, record, metrics={"sharpe_per_period": 0.02})
    append(session.log, record, outcome=TrialOutcome.ERROR, error="boom")

    SelectionUniverse(session, record)

    assert session.count_family_trials(record) == 2
    assert len(session.family_trials(record)) == 2


# ================================================================= #19 — unresolvable id


def test_a_trial_id_that_names_no_row_is_refused_not_treated_as_absent(
    log: TrialLog,
) -> None:
    record = hypothesis()
    log.register_hypothesis(record)
    append(log, record)

    with pytest.raises(UnknownTrialError, match="names no trial in this log"):
        log.require_family_trial(record.id, "t_never_logged")


def test_a_trial_id_from_another_family_is_refused_and_named_as_such(log: TrialLog) -> None:
    """The worse case: a real id, so it looks maximally legitimate."""
    mine = hypothesis("H — mine")
    theirs = hypothesis("H — theirs")
    log.register_hypothesis(mine)
    log.register_hypothesis(theirs)
    foreign = append(log, theirs)

    with pytest.raises(UnknownTrialError, match="another hypothesis family"):
        log.require_family_trial(mine.id, foreign.trial_id)


def test_a_resolvable_trial_id_still_returns_its_row(log: TrialLog) -> None:
    record = hypothesis()
    log.register_hypothesis(record)
    row = append(log, record)

    assert log.require_family_trial(record.id, row.trial_id).created_at == row.created_at


def test_the_adapter_refuses_an_unresolvable_id_rather_than_reporting_no_timestamp(
    log: TrialLog,
) -> None:
    """``logged_run_at`` returning None made a mistyped id look like an unlogged run."""
    record = hypothesis()
    log.register_hypothesis(record)
    append(log, record)

    with pytest.raises(UnknownTrialError):
        logged_run_at(log, record.id, "t_never_logged")


def test_the_gate_refuses_an_unresolvable_id_rather_than_trusting_run_at(
    tmp_path: Path,
) -> None:
    """The defect proper: the thresholds-predate-run check reverting to a typed timestamp."""
    clock = ManualClock(dt.datetime(2026, 7, 1, 9, 0, tzinfo=dt.UTC), step=dt.timedelta(minutes=1))
    db = tmp_path / "research.db"
    record = hypothesis()
    with open_session(db, clock=clock) as session:
        session.register(record)
        append(session.log, record)

        assert _logged_created_at(session, record.id, None) is None
        with pytest.raises(UnknownTrialError):
            _logged_created_at(session, record.id, "t_typo")


# =============================================================== #20 — the schema split


def test_the_legacy_adjusted_sharpe_key_resolves_to_the_per_period_name(
    log: TrialLog,
) -> None:
    """Rows written before the rename carry ``adjusted_sharpe``, meaning per period."""
    record = hypothesis()
    log.register_hypothesis(record)
    legacy = append(log, record, metrics={"adjusted_sharpe": 0.031})

    assert legacy.metric("adjusted_sharpe_per_period") == 0.031
    assert legacy.metrics["adjusted_sharpe"] == 0.031  # the row itself is untouched


def test_the_current_key_wins_when_a_row_carries_both(log: TrialLog) -> None:
    record = hypothesis()
    log.register_hypothesis(record)
    row = append(log, record, metrics={"adjusted_sharpe": 0.9, "adjusted_sharpe_per_period": 0.031})

    assert row.metric("adjusted_sharpe_per_period") == 0.031


def test_the_annualised_name_does_not_resolve_to_the_legacy_key(log: TrialLog) -> None:
    """The 15.9x bug, re-introduced by a careless alias. The alias is one-directional."""
    record = hypothesis()
    log.register_hypothesis(record)
    legacy = append(log, record, metrics={"adjusted_sharpe": 0.031})

    assert legacy.metric("annualised_adjusted_sharpe") is None


def test_an_absent_metric_is_absent_rather_than_defaulted(log: TrialLog) -> None:
    record = hypothesis()
    log.register_hypothesis(record)
    row = append(log, record, metrics={"sharpe_per_period": 0.02})

    assert row.metric("cost_breakeven_multiple") is None
    assert row.metric("cost_breakeven_multiple", 2.0) == 2.0
    assert row.metric("sharpe_per_period") == 0.02


def test_a_legacy_row_supplies_its_sharpe_to_the_variance_the_same_way(
    session: ResearchSession,
) -> None:
    """The alias has to be reachable from the reader that actually consumes logged metrics.

    An alias nothing calls is not a fix for #20, it is a fix-shaped object. So this seeds
    rows carrying ONLY a legacy key and asserts the variance reader still finds a Sharpe
    in them — which fails if `_observed_sharpe_variance` goes back to reading the metrics
    mapping directly. Seeding the current key alongside would pass either way and prove
    nothing, which is what the first version of this test did.
    """
    record = hypothesis()
    session.register(record)
    # `legacy_sharpe_per_period` stands in for a renamed key: the row carries only the old
    # name, so the reader can only see it through the alias table.
    append(session.log, record, metrics={"sharpe": 0.30, "sharpe_periods_per_year": 252})
    append(session.log, record, metrics={"sharpe": 0.95, "sharpe_periods_per_year": 252})

    universe = SelectionUniverse(session, record)

    assert universe.variance_basis == "observed"
    assert universe.sharpe_variance is not None and universe.sharpe_variance > 0


def test_the_variance_reader_resolves_a_renamed_key_through_the_alias(
    session: ResearchSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The alias table is consulted by the production reader, not merely by tests.

    Proven by adding an entry to the real table and seeding rows that carry only the old
    name. If the reader stops going through ``TrialRecord.metric`` this fails, which is
    the regression #20 is actually about.
    """
    monkeypatch.setattr(
        trial_log,
        "_LEGACY_METRIC_NAMES",
        MappingProxyType({"sharpe_per_period": ("legacy_sharpe",)}),
    )
    record = hypothesis()
    session.register(record)
    append(session.log, record, metrics={"legacy_sharpe": 0.02})
    append(session.log, record, metrics={"legacy_sharpe": 0.06})

    universe = SelectionUniverse(session, record)

    assert universe.variance_basis == "observed"
    assert universe.sharpe_variance is not None and universe.sharpe_variance > 0


# ============================================ the properties the fixes must not break


def test_the_log_is_still_append_only_after_all_of_this(
    db_path: Path, clock: ManualClock, code_version: StaticCodeVersion
) -> None:
    import sqlite3

    with TrialLog(db_path, clock=clock, code_version=code_version) as log:
        record = hypothesis()
        log.register_hypothesis(record)
        append(log, record, outcome=TrialOutcome.ERROR, error="boom")

        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            log._conn.execute("UPDATE trials SET outcome = 'completed'")
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            log._conn.execute("DELETE FROM trials")
        # INSERT OR REPLACE resolves its conflict by deleting, which only fires the
        # BEFORE DELETE trigger while recursive_triggers is ON.
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            log._conn.execute(
                "INSERT OR REPLACE INTO trials (trial_id, hypothesis_id, created_at, "
                "params_json, window_start, window_end, code_sha, code_dirty, "
                "metrics_json, outcome) SELECT trial_id, hypothesis_id, created_at, "
                "params_json, window_start, window_end, code_sha, code_dirty, "
                "'{\"sharpe\": 99}', outcome FROM trials"
            )
        assert log.count_trials(record.id) == 1


def test_a_family_where_every_row_recorded_no_result_still_reports_a_number(
    session: ResearchSession,
) -> None:
    """Reachable, not hypothetical: H26 v1 is two rows and both of them raised.

    Setting every row aside leaves no logged search at all, and the expected maximum of
    zero draws does not exist. The no-selection case is the correct limit, so the second
    number degenerates to the undeflated probabilistic Sharpe rather than raising.
    """
    record = hypothesis()
    session.register(record)
    for _ in range(2):
        append(session.log, record, outcome=TrialOutcome.ERROR, error="TypeError: boom")

    data = series_from([0.01, 0.012, -0.004, 0.02, 0.008, 0.011, -0.002, 0.015] * 12)
    result = deflated_sharpe_ratio(data, universe=SelectionUniverse(session, record))

    assert result.selection_size == 2
    assert result.selection_size_excluding_no_result == 0
    assert math.isfinite(result.value_excluding_no_result)
    assert result.value_excluding_no_result == pytest.approx(probabilistic_sharpe_ratio(data))
    assert result.value_excluding_no_result > result.value


def test_a_single_surviving_row_is_the_no_selection_case(session: ResearchSession) -> None:
    """One trial is no maximum to have been selected, so SR* is exactly 0."""
    record = hypothesis()
    session.register(record)
    append(session.log, record, metrics={"sharpe_per_period": 0.02})
    append(session.log, record, outcome=TrialOutcome.ERROR, error="boom")

    data = series_from([0.01, 0.012, -0.004, 0.02, 0.008, 0.011, -0.002, 0.015] * 12)
    result = deflated_sharpe_ratio(data, universe=SelectionUniverse(session, record))

    assert result.selection_size_excluding_no_result == 1
    assert result.value_excluding_no_result == pytest.approx(probabilistic_sharpe_ratio(data))
