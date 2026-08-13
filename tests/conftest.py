"""Shared fixtures. Time and code version are pinned in every test — nothing here
touches the wall clock or the developer's git tree."""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

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


# --------------------------------------------------------------- C5 synthetic corpus
#
# The backtester's unit tests run against a corpus small enough to reason about by hand:
# a handful of sessions, one expiry, flat prices unless a test moves them. It is written
# in the producer's own layout — parquet plus a `.refdata` directory of instrument-master
# rows — because the store reads that layout and a fixture that fakes the reader instead
# would prove the backtester works against a mock.
#
# Session dates must be real NSE trading days: the store resolves a range through the
# exchange calendar, and a fixture on a holiday would be reported as `unexpected` rather
# than found. The dates used below are drawn from the real corpus.

IST = ZoneInfo("Asia/Kolkata")
SESSION_OPEN = time(9, 15)
SESSION_MINUTES = 375
FIXTURE_LOT_SIZE = 65


@dataclass(frozen=True)
class SyntheticContract:
    """One option to write into a synthetic session, priced flat unless overridden."""

    strike: float
    option_type: str
    expiry: date
    close: float
    volume: float = 1_300_000.0
    open_interest: float = 6_500_000.0


def _minute_stamps(session_date: date) -> list[int]:
    first = datetime.combine(session_date, SESSION_OPEN, tzinfo=IST)
    return [
        int((first + timedelta(minutes=index)).timestamp() * 1_000_000)
        for index in range(SESSION_MINUTES)
    ]


def write_synthetic_session(
    root: Path,
    session_date: date,
    *,
    underlying: str = "NIFTY",
    spot: float = 23_000.0,
    contracts: Sequence[SyntheticContract] = (),
    spot_by_minute: Mapping[int, float] | None = None,
    lot_size: int = FIXTURE_LOT_SIZE,
) -> Path:
    """Write one session in the producer's layout and return its parquet path.

    ``spot_by_minute`` overrides the underlying's close at the given minute indices, which
    is how a settlement test makes the last half hour differ from the close.
    """
    import pandas as pd

    directory = root / underlying
    directory.mkdir(parents=True, exist_ok=True)
    stamps = _minute_stamps(session_date)
    rows: list[dict[str, object]] = []
    for index, stamp in enumerate(stamps):
        value = (spot_by_minute or {}).get(index, spot)
        rows.append(
            {
                "minute_ts": stamp,
                "symbol": underlying,
                "open": value,
                "high": value,
                "low": value,
                "close": value,
                "iv": float("nan"),
                "oi": float("nan"),
                "volume": float("nan"),
                "spot": value,
                "delta": float("nan"),
                "gamma": float("nan"),
                "theta": float("nan"),
                "vega": float("nan"),
            }
        )
        for contract in contracts:
            rows.append(
                {
                    "minute_ts": stamp,
                    "symbol": synthetic_symbol(underlying, contract),
                    "open": contract.close,
                    "high": contract.close,
                    "low": contract.close,
                    "close": contract.close,
                    "iv": 0.13,
                    "oi": contract.open_interest,
                    "volume": contract.volume,
                    "spot": value,
                    "delta": 0.5,
                    "gamma": 0.0004,
                    "theta": -5.0,
                    "vega": 4.0,
                }
            )
    parquet_path = directory / f"{session_date.isoformat()}.parquet"
    pd.DataFrame(rows).to_parquet(parquet_path, index=False)

    refdata = directory / f"{session_date.isoformat()}.refdata"
    refdata.mkdir(exist_ok=True)
    (refdata / "nfo_instruments.json").write_text(
        json.dumps(
            [
                {
                    "TradingSymbol": synthetic_symbol(underlying, contract),
                    "LookupName": underlying,
                    "Exchange": "NFO",
                    "Segment": "NFO-OPT",
                    "OptionType": contract.option_type,
                    "StrikePrice": contract.strike,
                    "ExpiryDate": contract.expiry.strftime("%d/%m/%Y"),
                    "LotSize": lot_size,
                    "TickSize": 5.0,
                }
                for contract in contracts
            ]
        )
    )
    (refdata / "underlier_instruments.json").write_text(
        json.dumps(
            [
                {
                    "TradingSymbol": underlying,
                    "LookupName": underlying,
                    "Exchange": "NSE",
                    "Segment": "INDICES",
                    "LotSize": lot_size,
                    "TickSize": 5.0,
                }
            ]
        )
    )
    return parquet_path


def synthetic_symbol(underlying: str, contract: SyntheticContract) -> str:
    """Build a fixture's trading symbol.

    Composing a symbol is forbidden in production code and is exactly right here: the
    fixture is playing the role of the exchange, which is the one party entitled to
    invent them. Everything downstream still reads it back out of the instrument master.
    """
    stamp = contract.expiry.strftime("%d%b%Y")
    return f"{underlying}-{stamp}-{int(contract.strike)}-{contract.option_type}"


@pytest.fixture
def synthetic_store(tmp_path: Path):
    """A :class:`SessionStore` over a corpus root the test fills in itself."""
    from xman_research.session_store import SessionStore

    root = tmp_path / "corpus"
    root.mkdir()

    def build() -> SessionStore:
        return SessionStore(root=root, manifest_path=tmp_path / "no-manifest.sqlite")

    build.root = root  # type: ignore[attr-defined]
    return build
