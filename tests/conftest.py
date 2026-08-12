"""Shared fixtures. Time and code version are pinned in every test — nothing here
touches the wall clock or the developer's git tree."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from xman_research import (
    DataWindow,
    HypothesisRecord,
    ManualClock,
    ResearchSession,
    StaticCodeVersion,
    TrialLog,
)

PINNED_START = datetime(2026, 8, 12, 9, 15, tzinfo=UTC)


@pytest.fixture
def clock() -> ManualClock:
    return ManualClock(PINNED_START, step=timedelta(seconds=1))


@pytest.fixture
def code_version() -> StaticCodeVersion:
    return StaticCodeVersion("0123456789abcdef0123456789abcdef01234567", dirty=False)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "research.db"


@pytest.fixture
def log(db_path: Path, clock: ManualClock, code_version: StaticCodeVersion) -> Iterator[TrialLog]:
    with TrialLog(db_path, clock=clock, code_version=code_version) as opened:
        yield opened


@pytest.fixture
def session(log: TrialLog) -> ResearchSession:
    return ResearchSession(log)


@pytest.fixture
def h1() -> HypothesisRecord:
    return HypothesisRecord(
        name="H1 — index variance risk premium",
        mechanism=(
            "Index hedgers pay up for downside protection, so implied variance sits "
            "persistently above subsequent realised variance; a short-variance position "
            "collects that premium as compensation for bearing crash risk."
        ),
        null_hypothesis=(
            "Implied minus realised variance has no positive mean after statutory costs, "
            "and the strategy does not beat the always-on benchmark risk-matched."
        ),
        thresholds={"deflated_sharpe": 0.0, "cost_breakeven_multiple": 2.0},
        predictors=["iv_30d", "realised_vol_20d"],
        entry_rule={"entry_time": "09:30", "delta": 0.30},
        exit_rule={"exit_time": "15:15", "stop_multiple": 2.0},
    )


@pytest.fixture
def window() -> DataWindow:
    return DataWindow(date(2023, 1, 1), date(2024, 12, 31))
