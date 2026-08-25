"""A synthetic corpus small enough to reason about, shared by the alpha tests.

Written in the producer's own layout through ``conftest.write_synthetic_session``, so the
session store reads it the same way it reads the captured corpus. Session dates are real
NSE trading days — the store resolves a range through the exchange calendar, and a fixture
on a holiday is reported as unexpected rather than found.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from conftest import SyntheticContract, write_synthetic_session
from xman_research.session_store import TradingCalendar

FLAT_SPOT = 23_000.0
STEP = 230.0
FIXTURE_IV = 0.13
LOT_SIZE = 65

#: 15:20 IST is 365 minutes after the 09:15 open, so this is the index of the decision
#: minute in the fixture's per-minute series and everything above it is the future.
DECISION_MINUTE_INDEX = 365


def trading_days(count: int, *, ending: dt.date) -> list[dt.date]:
    days = TradingCalendar().trading_days(ending - dt.timedelta(days=count * 3), ending)
    return list(days[-count:])


def contracts(expiry: dt.date, strikes: Sequence[float]) -> list[SyntheticContract]:
    return [
        SyntheticContract(strike=strike, option_type=option_type, expiry=expiry, close=200.0)
        for strike in strikes
        for option_type in ("CE", "PE")
    ]


def write_corpus(
    root: Path,
    *,
    sessions: Sequence[dt.date],
    spot_for: Callable[[int], float],
    expiry: dt.date,
    spot_by_minute: Mapping[int, float] | None = None,
    spot_by_minute_on: dt.date | None = None,
    volume: float | None = None,
    open_interest: float | None = None,
) -> None:
    """Write ``sessions`` at the prices ``spot_for`` gives, all quoting one expiry.

    ``volume`` and ``open_interest`` override the fixture's liquidity, which is how a test
    makes the participation caps bind.
    """
    strikes = [FLAT_SPOT + STEP * offset for offset in range(-4, 5)]
    for index, session_date in enumerate(sessions):
        legs = contracts(expiry, strikes)
        if volume is not None or open_interest is not None:
            legs = [
                SyntheticContract(
                    strike=leg.strike,
                    option_type=leg.option_type,
                    expiry=leg.expiry,
                    close=leg.close,
                    volume=leg.volume if volume is None else volume,
                    open_interest=leg.open_interest if open_interest is None else open_interest,
                )
                for leg in legs
            ]
        write_synthetic_session(
            root,
            session_date,
            spot=spot_for(index),
            contracts=legs,
            spot_by_minute=spot_by_minute if spot_by_minute_on == session_date else None,
            lot_size=LOT_SIZE,
        )
