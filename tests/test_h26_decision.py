"""H26: the amendment, the engine extension it needed, and the replay it rests on.

Nothing here reads a price from the holdout window, and nothing computes an H26 result
against the real corpus — those belong to the decision run, after the gate commit.
"""

from __future__ import annotations

import datetime as dt
import json
import tomllib
from pathlib import Path

import pytest

from xman_research import (
    DataWindow,
    HypothesisRecord,
    ManualClock,
    StaticCodeVersion,
    TrialLog,
    open_session,
)
from xman_research.backtest.engine import BacktestConfig, _decision_minutes
from xman_research.backtest.strategies import ClockSide, ClockSplitShortStraddle
from xman_research.h1.hypothesis import h1_record
from xman_research.h26.h1_replay import H1RecordDriftError, replay_h1_family
from xman_research.h26.hypothesis import (
    CLOSE_DECISION,
    OPEN_DECISION,
    THRESHOLDS,
    _h26_v1_record,
    h26_record,
)

REPO = Path(__file__).resolve().parents[1]
GATE = REPO / "research" / "h26" / "gate.toml"
VALIDATION = REPO / "research" / "h26" / "validation.toml"
H1_DECISION = REPO / "research" / "h1" / "decision.json"


def _log(path: Path) -> TrialLog:
    """A throwaway log with a pinned clock and code version, as conftest builds them."""
    return TrialLog(
        path,
        clock=ManualClock(dt.datetime(2026, 1, 1, tzinfo=dt.UTC)),
        code_version=StaticCodeVersion("0" * 40, dirty=False),
    )


def test_h26_is_an_amendment_of_h1_not_a_new_family() -> None:
    """The whole multiple-testing argument rests on this chain existing.

    H1 -> H26 v1 (pre-registered in dccb379) -> H26 v2 (the superseding correction). The
    correction must COST a trial, not save one, so it amends rather than replaces.
    """
    v1, v2 = _h26_v1_record(), h26_record()
    assert v1.parent_id == h1_record().id
    assert v2.parent_id == v1.id
    assert len({h1_record().id, v1.id, v2.id}) == 3


def test_supersession_moved_no_threshold() -> None:
    """A narrowed sample is not licence to revisit a bar."""
    assert dict(h26_record().thresholds) == dict(_h26_v1_record().thresholds)


def test_family_count_spans_h1_and_h26(tmp_path: Path) -> None:
    """An amendment must not reset the trial count — that is C4's documented hole."""
    log = _log(tmp_path / "family.db")
    replay_h1_family(log, decision_path=H1_DECISION)
    log.register_hypothesis(_h26_v1_record())
    h26 = h26_record()
    log.register_hypothesis(h26)
    assert log.count_family_trials(h26.id) == 1  # H1's replayed row, before H26 runs
    log.append_trial(
        hypothesis_id=h26.id,
        params={},
        data_window=DataWindow(dt.date(2026, 1, 1), dt.date(2026, 2, 1)),
        metrics={},
    )
    assert log.count_family_trials(h26.id) == 2
    assert log.count_family_trials(h1_record().id) == 2
    log.close()


def test_replay_is_idempotent(tmp_path: Path) -> None:
    """Re-running a decision must not inflate the family with duplicate H1 rows."""
    log = _log(tmp_path / "replay.db")
    _, first = replay_h1_family(log, decision_path=H1_DECISION)
    _, second = replay_h1_family(log, decision_path=H1_DECISION)
    assert first == 1
    assert second == 0
    assert log.count_family_trials(h1_record().id) == 1
    log.close()


def test_replay_refuses_when_h1_record_has_drifted(tmp_path: Path) -> None:
    """A drifted H1 must stop the run, never silently shrink the count."""
    payload = json.loads(H1_DECISION.read_text(encoding="utf-8"))
    payload["hypothesis_id"] = "h_0000000000000000000000000000dead"
    forged = tmp_path / "drifted.json"
    forged.write_text(json.dumps(payload), encoding="utf-8")
    log = _log(tmp_path / "drift.db")
    with pytest.raises(H1RecordDriftError):
        replay_h1_family(log, decision_path=forged)
    log.close()


def test_gate_file_and_record_agree() -> None:
    """The editable half must not become a loophole around the immutable half."""
    gate = tomllib.loads(GATE.read_text(encoding="utf-8"))
    assert gate["hypothesis_id"] == h26_record().id
    for metric, spec in gate["thresholds"].items():
        assert THRESHOLDS[metric] == next(iter(spec.values()))
    for metric, spec in gate["holdout_thresholds"].items():
        assert THRESHOLDS[f"holdout.{metric}"] == next(iter(spec.values()))


def test_holdout_boundary_is_inherited_from_h1_unchanged() -> None:
    """The sealed months stay sealed: H26 is in H1's family and must not re-cut them."""
    h1 = tomllib.loads((REPO / "research" / "h1" / "validation.toml").read_text(encoding="utf-8"))
    h26 = tomllib.loads(VALIDATION.read_text(encoding="utf-8"))
    assert h26["holdout_first_date"] == h1["holdout_first_date"] == dt.date(2026, 5, 1)


# --------------------------------------------------------------------- engine extension


def test_single_decision_provenance_is_byte_identical() -> None:
    """H1's committed run fingerprint is hashed over this dict; it must not move."""
    assert "decision_times" not in BacktestConfig().provenance()
    assert BacktestConfig().resolved_decision_times() == (dt.time(9, 20),)


def test_multi_decision_provenance_is_declared_and_sorted() -> None:
    config = BacktestConfig(decision_times=(CLOSE_DECISION, OPEN_DECISION))
    assert config.resolved_decision_times() == (OPEN_DECISION, CLOSE_DECISION)
    assert config.provenance()["decision_times"] == ["09:20:00", "15:29:00"]


def test_empty_decision_times_is_refused() -> None:
    with pytest.raises(ValueError, match="never trade"):
        BacktestConfig(decision_times=()).resolved_decision_times()


class _Minutes:
    """Minimal stand-in for SessionView's minute resolution."""

    def __init__(self, minutes: tuple[dt.datetime, ...]) -> None:
        self._minutes = minutes

    def minute_at_or_after(self, time_of_day: dt.time) -> dt.datetime | None:
        for minute in self._minutes:
            if minute.time() >= time_of_day:
                return minute
        return None


def test_decision_minutes_dedupes_on_a_short_session() -> None:
    """Two configured times resolving to one bar must not let a strategy act twice."""
    only = dt.datetime(2026, 1, 5, 15, 29)
    session = _Minutes((only,))
    config = BacktestConfig(decision_times=(OPEN_DECISION, CLOSE_DECISION))
    assert _decision_minutes(session, config) == (only,)  # type: ignore[arg-type]


def test_decision_minutes_skips_a_time_the_session_never_reached() -> None:
    morning = dt.datetime(2026, 1, 5, 9, 20)
    session = _Minutes((morning,))
    config = BacktestConfig(decision_times=(OPEN_DECISION, CLOSE_DECISION))
    assert _decision_minutes(session, config) == (morning,)  # type: ignore[arg-type]


# ------------------------------------------------------------------------- the strategy


def test_the_two_arms_are_one_class_with_one_flag() -> None:
    """Any asymmetry other than the clock side would present as a premium."""
    gap, session = (
        ClockSplitShortStraddle(hold=ClockSide.GAP),
        ClockSplitShortStraddle(hold=ClockSide.SESSION),
    )
    assert type(gap) is type(session)
    assert gap.decision_times == session.decision_times == (OPEN_DECISION, CLOSE_DECISION)
    differing = {
        key for key in gap.parameters() if gap.parameters()[key] != session.parameters()[key]
    }
    assert differing == {"hold"}


def test_reversed_clock_is_refused() -> None:
    with pytest.raises(ValueError, match="strictly before"):
        ClockSplitShortStraddle(open_time=dt.time(15, 29), close_time=dt.time(9, 20))


def test_close_decision_lands_on_a_minute_every_session_prints() -> None:
    """15:30 would silently resolve to None and the arm would simply stop trading."""
    assert dt.time(15, 29) >= CLOSE_DECISION
    assert OPEN_DECISION < CLOSE_DECISION


def test_record_pins_the_decision_minutes() -> None:
    """The minutes move real premium between arms, so they are id-bearing, not config."""
    entry = h26_record().entry_rule
    assert entry["open_decision_ist"] == OPEN_DECISION.isoformat()
    assert entry["close_decision_ist"] == CLOSE_DECISION.isoformat()
    moved = h26_record().amend(
        entry_rule={**dict(entry), "open_decision_ist": "09:25:00"},
    )
    assert moved.id != h26_record().id


def test_thresholds_are_not_inherited_from_h1() -> None:
    """Two inputs moved — the trial count and the holdout size — so the bars had to move."""
    h1 = h1_record().thresholds
    assert THRESHOLDS["deflated_sharpe"] != h1["deflated_sharpe"]
    assert THRESHOLDS["cost_breakeven_multiple"] > h1["cost_breakeven_multiple"]


def test_session_open_registers_the_family_without_error(tmp_path: Path) -> None:
    """An amendment whose parent is unregistered cannot be logged; order matters."""
    with open_session(tmp_path / "order.db") as session:
        replay_h1_family(session.log, decision_path=H1_DECISION)
        session.register(_h26_v1_record())
        record = session.register(h26_record())
        assert isinstance(record, HypothesisRecord)
        assert session.count_family_trials(record) == 1
