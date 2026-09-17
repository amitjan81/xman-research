"""The corpus as it must be read, not as it was captured.

A captured session file is a vendor artifact, and this one carries four defects that do not
raise an error — they move a result quietly, which is worse. Every reader of a session file
goes through this module so that each defect is neutralised in exactly one place, and so
that a future defect has an obvious home rather than four.

**What is wrong with the raw files** (measured over 1,252 NIFTY sessions,
``research/intraday/data_audit.py``):

1. *The index feed pads outside market hours.* On 208 sessions (16.6%) the file carries
   underlying rows stamped as early as 05:38 and as late as 23:00 — zero volume, no open
   interest, and the same price repeated for hundreds of minutes. No option rows accompany
   them (the Closing Auction Session, which runs past 15:30, is market and is kept).
   Anything that reads a session's *first* or *last* print, or iterates its minutes
   from the beginning, reads the padding instead of the market: an opening-range band drawn
   from 07:06, a daily "open" that is not the open.
2. *The spot column disagrees with itself inside a minute.* On 436 sessions (34.8%) the
   ``spot`` stamped on each option row is that row's own snapshot, so a single minute holds
   several — a median of 4.2 index points apart, up to 35.6. There is exactly one authority
   for where the index was, and it is the index's own bar.
3. *Implied volatility is sometimes not a volatility.* 8.9% of option rows carry IV at or
   below zero (a solver that did not converge on a tick-floor wing), and 224 sessions carry
   IV above 300%. Most call sites already guard ``iv > 0``; the ones that did not were
   admitting a zero into an average that gated whether to trade at all.
4. *Volume is occasionally negative.* Rare, and meaningless — a negative traded quantity is
   absence of information, not a quantity.

**The rule this module applies: drop, never repair.** A row outside session hours is
discarded, not moved; an unusable IV becomes ``None``, not an interpolated guess; a negative
volume becomes "did not trade", not its absolute value. Manufacturing a plausible value is
how a backtest comes to trade on data the market never produced.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd

__all__ = [
    "CONTINUOUS_CLOSE",
    "IST",
    "MAX_PLAUSIBLE_IV",
    "SESSION_CLOSE",
    "SESSION_OPEN",
    "clean_iv",
    "clean_size",
    "ist_stamps",
    "session_rows",
    "underlying_spot",
]

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))

#: The exchange day, continuous session through the Closing Auction Session. The continuous
#: session ends at 15:30 but the auction runs past it, and
#: :data:`xman_research.backtest.settlement.LATEST_WITNESS_MINUTE` settles on prints inside
#: it — so the boundary that separates market from padding is the auction's end, not the
#: continuous close. Anything outside this is feed padding: zero volume, no open interest,
#: one price repeated for hours.
SESSION_OPEN = dt.time(9, 15)
SESSION_CLOSE = dt.time(16, 0)

#: Where continuous trading stops. For callers measuring what the index *did* rather than
#: where it settled; the auction's equilibrium print is not a minute of trading.
CONTINUOUS_CLOSE = dt.time(15, 30)

#: Above this, the number is a solver artefact rather than a volatility. 300% annualised is
#: already far beyond anything NIFTY has printed on an expiry afternoon.
MAX_PLAUSIBLE_IV = 3.0


def ist_stamps(frame: pd.DataFrame) -> pd.Series:
    """The frame's ``minute_ts`` as timezone-aware IST timestamps."""
    return pd.to_datetime(frame.minute_ts, unit="us", utc=True).dt.tz_convert(IST)


def session_rows(frame: pd.DataFrame, session_date: dt.date | None = None) -> pd.DataFrame:
    """Only the rows that belong to this trading session.

    Drops the out-of-hours padding (defect 1) and, when ``session_date`` is given, any row
    stamped with a different date. Returns the frame unchanged when it is empty, so callers
    can filter first and check emptiness once.
    """
    if frame.empty:
        return frame
    stamps = ist_stamps(frame)
    keep = (stamps.dt.time >= SESSION_OPEN) & (stamps.dt.time <= SESSION_CLOSE)
    if session_date is not None:
        keep &= stamps.dt.date == session_date
    return frame[keep]


def underlying_spot(
    frame: pd.DataFrame, underlying: str, session_date: dt.date | None = None
) -> pd.DataFrame:
    """The index's own price path: one row per minute, ``minute_ts`` and ``spot``, ascending.

    **The index's own bar is the only authority for spot** (defect 2). The ``spot`` column on
    an option row is that row's snapshot and is not consistent across a minute, so it is used
    only where the underlying did not print — which, across the captured corpus, is never.
    """
    inside = session_rows(frame, session_date)
    if inside.empty:
        return inside.loc[:, [c for c in ("minute_ts", "spot") if c in inside.columns]]
    own = inside[inside.symbol == underlying]
    source = own if not own.empty else inside
    spots = source.dropna(subset=["spot"])
    if spots.empty:
        return spots.loc[:, ["minute_ts", "spot"]]
    return (
        spots.groupby("minute_ts", as_index=False)
        .spot.last()
        .sort_values("minute_ts")
        .reset_index(drop=True)
    )


def clean_iv(value: float | None) -> float | None:
    """An implied volatility, or ``None`` where the number cannot be one (defect 3)."""
    if value is None:
        return None
    number = float(value)
    if number != number or number <= 0.0 or number > MAX_PLAUSIBLE_IV:
        return None
    return number


def clean_size(value: float | None) -> float:
    """A traded quantity or open interest, with the nonsensical read as absence (defect 4)."""
    if value is None:
        return 0.0
    number = float(value)
    if number != number or number < 0.0:
        return 0.0
    return number
