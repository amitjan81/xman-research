"""The three refusals, and the question the holdout has to be able to answer.

Each test here is about a *process* property rather than a statistical one: that a
threshold cannot be invented after the run, that a window spanning two markets cannot be
graded as one, and that "has the holdout been read" is answered from evidence in the log
rather than from anyone's recollection.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from validation_helpers import benchmark_series, evidence, trading_sessions
from xman_research import DataWindow, HypothesisRecord, ResearchSession
from xman_research.validation.decision import ValidationConfig, Validator
from xman_research.validation.gate import (
    EPOCH_BOUNDARIES,
    EPOCH_PROVENANCE_STAMP,
    CrossEpochWindowError,
    DecisionGate,
    Direction,
    GateBindingError,
    HoldoutPolicy,
    HoldoutTouchedError,
    Threshold,
    ThresholdsNotRecordedError,
    epochs_spanned,
    inspect_holdout,
)

RECORDED_AT = "2026-08-01T09:00:00+05:30"
RUN_AT = dt.datetime(2026, 8, 5, 12, 0, tzinfo=dt.UTC)
BEFORE_RECORDING = dt.datetime(2026, 7, 1, 12, 0, tzinfo=dt.UTC)


def write_gate(
    path: Path,
    *,
    recorded_at: str | None = RECORDED_AT,
    hypothesis_id: str | None = None,
    justification: str | None = None,
    body: str = """
[thresholds]
deflated_sharpe = { at_least = 0.95 }
cost_breakeven_multiple = { at_least = 2.0 }
""",
) -> Path:
    lines = []
    if recorded_at is not None:
        lines.append(f"recorded_at = {recorded_at}")
    if hypothesis_id is not None:
        lines.append(f'hypothesis_id = "{hypothesis_id}"')
    if justification is not None:
        lines.append(f'cross_epoch_justification = "{justification}"')
    path.write_text("\n".join(lines) + "\n" + body)
    return path


def hypothesis(**thresholds: float) -> HypothesisRecord:
    return HypothesisRecord(
        name="H1 — index variance risk premium",
        mechanism="Hedgers pay up for index protection, so implied sits above realised.",
        null_hypothesis="Implied minus realised has no positive mean after costs.",
        thresholds=thresholds or {"deflated_sharpe": 0.95, "cost_breakeven_multiple": 2.0},
        predictors=["iv_30d"],
    )


# ------------------------------------------------- thresholds written down beforehand


def test_a_missing_thresholds_file_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ThresholdsNotRecordedError, match="no thresholds file"):
        DecisionGate.from_file(tmp_path / "absent.toml")


def test_a_gate_without_a_recorded_at_is_refused(tmp_path: Path) -> None:
    path = write_gate(tmp_path / "gate.toml", recorded_at=None)
    with pytest.raises(ThresholdsNotRecordedError, match="no recorded_at"):
        DecisionGate.from_file(path)


def test_a_gate_with_no_thresholds_is_refused(tmp_path: Path) -> None:
    path = write_gate(tmp_path / "gate.toml", body="\n[thresholds]\n")
    with pytest.raises(ThresholdsNotRecordedError, match="records no thresholds"):
        DecisionGate.from_file(path)


def test_a_threshold_must_say_which_way_it_binds(tmp_path: Path) -> None:
    path = write_gate(
        tmp_path / "gate.toml", body="\n[thresholds]\ndeflated_sharpe = { above = 0.95 }\n"
    )
    with pytest.raises(ThresholdsNotRecordedError, match="at_least"):
        DecisionGate.from_file(path)


def test_a_run_that_predates_its_own_thresholds_is_refused(tmp_path: Path) -> None:
    """The headline refusal: thresholds written after the run are not thresholds."""
    gate = DecisionGate.from_file(write_gate(tmp_path / "gate.toml"))
    with pytest.raises(ThresholdsNotRecordedError, match="not before"):
        gate.require_recorded_before(BEFORE_RECORDING, what="the run 'candidate'")
    gate.require_recorded_before(RUN_AT, what="the run 'candidate'")  # does not raise


def test_a_run_with_no_timestamp_cannot_be_shown_to_postdate_the_thresholds(
    tmp_path: Path,
) -> None:
    gate = DecisionGate.from_file(write_gate(tmp_path / "gate.toml"))
    with pytest.raises(ThresholdsNotRecordedError, match="carries no run timestamp"):
        gate.require_recorded_before(None, what="the run 'candidate'")


def test_the_gate_must_agree_with_the_registered_hypothesis(tmp_path: Path) -> None:
    """The gate file is editable; the registered record is not. They must match."""
    record = hypothesis()
    disagreeing = DecisionGate.from_file(
        write_gate(
            tmp_path / "loose.toml",
            body="\n[thresholds]\ndeflated_sharpe = { at_least = 0.50 }\n"
            "cost_breakeven_multiple = { at_least = 2.0 }\n",
        )
    )
    with pytest.raises(GateBindingError, match=r"registered with 0\.95"):
        disagreeing.check_binding(record)

    incomplete = DecisionGate.from_file(
        write_gate(
            tmp_path / "partial.toml",
            body="\n[thresholds]\ndeflated_sharpe = { at_least = 0.95 }\n",
        )
    )
    with pytest.raises(GateBindingError, match="cost_breakeven_multiple"):
        incomplete.check_binding(record)

    agreeing = DecisionGate.from_file(write_gate(tmp_path / "gate.toml"))
    agreeing.check_binding(record)  # does not raise


def test_a_gate_bound_to_another_hypothesis_is_refused(tmp_path: Path) -> None:
    gate = DecisionGate.from_file(
        write_gate(tmp_path / "gate.toml", hypothesis_id="h_someone_elses_idea")
    )
    with pytest.raises(GateBindingError, match="bound to hypothesis"):
        gate.check_binding(hypothesis())


def test_an_unreported_metric_fails_its_threshold_rather_than_passing() -> None:
    threshold = Threshold(metric="pbo", direction=Direction.AT_MOST, value=0.5)
    result = threshold.check(None)
    assert result.missing and not result.passed
    assert "NOT REPORTED" in str(result)
    assert threshold.check(0.4).passed
    assert not threshold.check(0.6).passed


# ------------------------------------------------------------------------- epochs


def test_the_epoch_table_covers_the_six_documented_breaks() -> None:
    dates = [boundary.effective_from for boundary in EPOCH_BOUNDARIES]
    assert dates == [
        dt.date(2024, 10, 1),
        dt.date(2024, 11, 20),
        dt.date(2025, 2, 10),
        dt.date(2025, 4, 1),
        dt.date(2025, 9, 1),
        dt.date(2026, 4, 1),
    ]
    # None of them is primary-sourced yet (spec §9), and every result says so.
    assert all(boundary.confidence == "secondary" for boundary in EPOCH_BOUNDARIES)


def test_a_window_inside_one_regime_crosses_nothing() -> None:
    annotation = epochs_spanned(DataWindow(dt.date(2025, 4, 2), dt.date(2025, 8, 29)))
    assert not annotation.crosses_boundary
    assert annotation.regimes == ("2025-04-02..2025-08-29",)
    annotation.require_justification()  # does not raise


def test_a_window_opening_exactly_on_a_boundary_is_inside_the_new_regime() -> None:
    annotation = epochs_spanned(DataWindow(dt.date(2025, 9, 1), dt.date(2025, 12, 31)))
    assert not annotation.crosses_boundary


def test_a_cross_epoch_window_is_refused_without_a_recorded_justification() -> None:
    """Spec §3 C3: any 2023-2026 window necessarily spans the structural breaks."""
    annotation = epochs_spanned(DataWindow(dt.date(2024, 6, 1), dt.date(2025, 12, 31)))
    crossed = [boundary.name for boundary in annotation.boundaries_crossed]
    assert crossed == [
        "stt_rise_2024",
        "weekly_expiry_cull_2024",
        "calendar_spread_relief_removed_2025",
        "intraday_position_limits_2025",
        "nse_expiry_tuesday_2025",
    ]
    assert len(annotation.regimes) == 6
    with pytest.raises(CrossEpochWindowError, match="structural break"):
        annotation.require_justification()


def test_a_recorded_justification_permits_the_pooled_window() -> None:
    annotation = epochs_spanned(
        DataWindow(dt.date(2024, 6, 1), dt.date(2025, 12, 31)),
        justification="Cost-side breaks only; the variance premium mechanism is unchanged.",
    )
    annotation.require_justification()
    assert annotation.as_dict()["epoch_provenance"] == EPOCH_PROVENANCE_STAMP


def test_a_blank_justification_does_not_count() -> None:
    annotation = epochs_spanned(
        DataWindow(dt.date(2024, 6, 1), dt.date(2025, 12, 31)), justification="   "
    )
    with pytest.raises(CrossEpochWindowError):
        annotation.require_justification()


# ------------------------------------------------------------------------ holdout


def register(session: ResearchSession) -> HypothesisRecord:
    record = hypothesis()
    session.register(record)
    return record


def test_the_holdout_question_is_answerable_from_the_log(session: ResearchSession) -> None:
    """*Has the holdout been touched* is a query, not a recollection."""
    record = register(session)
    policy = HoldoutPolicy(first_date=dt.date(2026, 3, 1))

    status = inspect_holdout(session, record, policy=policy)
    assert not status.touched
    assert status.touching_trial_ids == ()
    assert status.furthest_window_end is None
    status.require_untouched()  # does not raise

    with session.trial(record, data_window=DataWindow(dt.date(2025, 1, 1), dt.date(2026, 2, 28))):
        pass
    assert not inspect_holdout(session, record, policy=policy).touched

    with session.trial(
        record, data_window=DataWindow(dt.date(2025, 1, 1), dt.date(2026, 4, 30))
    ) as trial:
        touching_id = trial.trial_id

    touched = inspect_holdout(session, record, policy=policy)
    assert touched.touched
    assert touched.touching_trial_ids == (touching_id,)
    assert touched.first_touch_at is not None
    assert touched.furthest_window_end == dt.date(2026, 4, 30)
    with pytest.raises(HoldoutTouchedError, match="already been read"):
        touched.require_untouched()


def test_the_holdout_answer_covers_the_whole_amendment_family(
    session: ResearchSession,
) -> None:
    """A reworded hypothesis is a different record; an *amended* one is the same family."""
    record = register(session)
    amended = record.amend(thresholds={"deflated_sharpe": 0.99, "cost_breakeven_multiple": 2.0})
    session.register(amended)
    policy = HoldoutPolicy(first_date=dt.date(2026, 3, 1))
    with session.trial(amended, data_window=DataWindow(dt.date(2026, 3, 2), dt.date(2026, 6, 30))):
        pass
    assert inspect_holdout(session, record, policy=policy).touched


def holdout_validator(tmp_path: Path, db_path: Path, record: HypothesisRecord) -> Validator:
    """A validator over the fixture's own log, with a gate bound to ``record``."""
    write_gate(tmp_path / "gate.toml", hypothesis_id=record.id)
    config_path = tmp_path / "validation.toml"
    config_path.write_text(
        f'trial_log_path = "{db_path}"\ngate_path = "gate.toml"\nholdout_first_date = 2026-03-01\n'
    )
    return Validator(ValidationConfig.from_file(config_path))


def logged_run(
    session: ResearchSession, record: HypothesisRecord, window: DataWindow
) -> tuple[str, dt.datetime]:
    """One appended trial's id and the timestamp the log's own clock stamped it with.

    ``run_at`` on the evidence must equal that timestamp: the thresholds-predate-the-run
    check reconciles the two and refuses a disagreement.
    """
    with session.trial(record, data_window=window) as trial:
        trial_id = trial.trial_id
    row = next(row for row in session.log.family_trials(record.id) if row.trial_id == trial_id)
    return trial_id, row.created_at


def test_a_separately_run_holdout_benchmark_does_not_trip_the_check(
    tmp_path: Path, db_path: Path, session: ResearchSession
) -> None:
    """Grading a holdout against a benchmark run in its own trial must still be possible.

    The risk-matched increment compares two series over the identical sessions under the
    identical cost model, so a caller whose benchmark is a *different* strategy re-runs it
    over the holdout and files a second trial in the same family with the same window.
    Exempting only the candidate would make that trial the evidence of a prior touch, and
    the grading would refuse itself after the months had already been read.
    """
    record = register(session)
    validator = holdout_validator(tmp_path, db_path, record)
    dates = trading_sessions(dt.date(2026, 3, 2), 20)
    window = DataWindow(dates[0], dates[-1])
    candidate_trial_id, candidate_at = logged_run(session, record, window)
    benchmark_trial_id, benchmark_at = logged_run(session, record, window)
    assert candidate_trial_id != benchmark_trial_id

    verdict = validator.grade_holdout(
        evidence(
            benchmark_series(dates, seed=11, label="candidate"),
            run_at=candidate_at,
            trial_id=candidate_trial_id,
        ),
        benchmark=evidence(
            benchmark_series(dates, seed=12), run_at=benchmark_at, trial_id=benchmark_trial_id
        ),
        hypothesis=record,
    )

    assert verdict.holdout is not None
    assert not verdict.holdout.touched
    assert verdict.holdout.touching_trial_ids == ()


def test_a_holdout_trial_from_an_earlier_read_still_trips_the_check(
    tmp_path: Path, db_path: Path, session: ResearchSession
) -> None:
    """The exemption is exactly three trials wide, not "any trial with this window".

    A fourth holdout row — an evaluation from some earlier session — is what the check
    exists to find, and widening the exemption must not have made it invisible.
    """
    record = register(session)
    validator = holdout_validator(tmp_path, db_path, record)
    dates = trading_sessions(dt.date(2026, 3, 2), 20)
    window = DataWindow(dates[0], dates[-1])
    earlier_trial_id, _ = logged_run(session, record, window)
    candidate_trial_id, candidate_at = logged_run(session, record, window)
    benchmark_trial_id, benchmark_at = logged_run(session, record, window)

    with pytest.raises(HoldoutTouchedError, match=earlier_trial_id):
        validator.grade_holdout(
            evidence(
                benchmark_series(dates, seed=11, label="candidate"),
                run_at=candidate_at,
                trial_id=candidate_trial_id,
            ),
            benchmark=evidence(
                benchmark_series(dates, seed=12), run_at=benchmark_at, trial_id=benchmark_trial_id
            ),
            hypothesis=record,
        )


# ----------------------------------------------------------------- configuration


def test_the_config_pins_the_log_and_resolves_relative_paths(tmp_path: Path) -> None:
    """C4's sharpest hole: which log the count comes from must not be a per-call choice."""
    write_gate(tmp_path / "gate.toml")
    config_path = tmp_path / "validation.toml"
    config_path.write_text(
        'trial_log_path = "research.db"\ngate_path = "gate.toml"\nholdout_first_date = 2026-03-01\n'
    )
    config = ValidationConfig.from_file(config_path)
    assert config.trial_log_path == tmp_path / "research.db"
    assert config.gate_path == tmp_path / "gate.toml"
    assert config.holdout_first_date == dt.date(2026, 3, 1)
    assert config.holdout_policy.first_date == dt.date(2026, 3, 1)
    assert [str(threshold) for threshold in config.gate().thresholds] == [
        "deflated_sharpe >= 0.95",
        "cost_breakeven_multiple >= 2",
    ]


def test_the_config_requires_every_pinned_value(tmp_path: Path) -> None:
    config_path = tmp_path / "validation.toml"
    config_path.write_text('trial_log_path = "research.db"\n')
    with pytest.raises(ValueError, match="gate_path, holdout_first_date"):
        ValidationConfig.from_file(config_path)


def test_a_gate_grades_the_record_thresholds_and_ignores_its_screen_criteria(
    tmp_path: Path,
) -> None:
    """The two sets are answered by different stages, so a gate carries only its own.

    A screen bar registered as a *threshold* would be one no gate could satisfy: binding
    requires the gate to carry every numeric threshold the record registered, and a gate
    naming a metric outside the measurable vocabulary is refused when it is read. Held
    apart, the gate file names only what it grades and the screen's bar is still on the
    record for a reader to see.
    """
    record = HypothesisRecord(
        name="BANKNIFTY screen",
        mechanism="Index hedgers pay up for protection, so implied sits above realised.",
        null_hypothesis="No screened structure beats the unconditional straddle.",
        thresholds={"deflated_sharpe": 0.90, "cost_breakeven_multiple": 2.0},
        screen_criteria={
            "alpha_to_advance": 0.5,
            "alpha_to_advance_definition": "the spread's Sharpe",
        },
    )
    path = tmp_path / "gate.toml"
    write_gate(
        path,
        hypothesis_id=record.id,
        body="""
[thresholds]
deflated_sharpe = { at_least = 0.90 }
cost_breakeven_multiple = { at_least = 2.0 }
""",
    )
    gate = DecisionGate.from_file(path)
    gate.check_binding(record)
    assert {threshold.metric for threshold in gate.thresholds} == {
        "deflated_sharpe",
        "cost_breakeven_multiple",
    }
