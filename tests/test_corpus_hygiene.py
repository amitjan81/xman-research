"""The corpus defects, and the proof that each one stops at the boundary.

Every case here is a defect the real files actually contain, measured by
``research/intraday/data_audit.py`` over 1,252 NIFTY sessions. The fixtures reproduce the
shape rather than inventing a hazard: out-of-hours padding that repeats one price for hours,
a spot column that disagrees with itself inside a minute, implied volatility a solver could
not produce, and a negative traded quantity.

The last test in the file is the one that matters most — it asserts against the real corpus
that the defects are *there*, so the fixtures above are reproducing something rather than
guarding against a hazard that no longer exists.
"""

from __future__ import annotations

import datetime as dt
import os
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
import pytest

from xman_research.backtest.market import SessionView
from xman_research.corpus_hygiene import (
    MAX_PLAUSIBLE_IV,
    SESSION_CLOSE,
    SESSION_OPEN,
    clean_iv,
    clean_size,
    session_rows,
    underlying_spot,
)
from xman_research.session_store import DEFAULT_CORPUS_ROOT, RefData

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
SESSION_DATE = dt.date(2026, 8, 11)
CORPUS_ROOT = Path(os.environ.get("XMAN_RESEARCH_CORPUS_ROOT") or DEFAULT_CORPUS_ROOT)


def _row(moment: dt.time, symbol: str, price: float, **overrides: object) -> dict[str, object]:
    stamp = dt.datetime.combine(SESSION_DATE, moment, tzinfo=IST)
    row: dict[str, object] = {
        "minute_ts": int(stamp.timestamp() * 1_000_000),
        "symbol": symbol,
        "open": price,
        "high": price,
        "low": price,
        "close": price,
        "iv": 0.12,
        "oi": 100.0,
        "volume": 50.0,
        "spot": price,
    }
    row.update(overrides)
    return row


# ------------------------------------------------------- defect 1: out-of-hours padding


def test_the_pre_open_padding_is_not_part_of_the_session() -> None:
    """07:06 to 09:14 is the feed talking to itself, and 09:15 is where the day starts."""
    frame = pd.DataFrame(
        [_row(dt.time(7, 6), "NIFTY", 17_745.9), _row(dt.time(9, 15), "NIFTY", 17_800.0)]
    )

    kept = session_rows(frame, SESSION_DATE)

    assert len(kept) == 1
    assert kept.spot.iloc[0] == 17_800.0


def test_the_evening_padding_is_not_part_of_the_session_but_the_auction_is() -> None:
    """The boundary is the auction's end, not the continuous close.

    A 15:39 print is the Closing Auction Session and is what
    :mod:`xman_research.backtest.settlement` settles against; a 23:00 print is padding.
    A boundary at 15:30 would have taken the settlement with it.
    """
    frame = pd.DataFrame(
        [
            _row(dt.time(15, 29), "NIFTY", 24_471.7),
            _row(dt.time(15, 39), "NIFTY", 24_472.0),
            _row(dt.time(23, 0), "NIFTY", 24_471.7),
        ]
    )

    kept = session_rows(frame, SESSION_DATE)

    assert [t for t in kept.spot] == [24_471.7, 24_472.0]
    assert dt.time(9, 15) == SESSION_OPEN
    assert dt.time(16, 0) == SESSION_CLOSE


def test_a_row_stamped_with_another_date_is_not_this_session() -> None:
    other = dt.datetime.combine(SESSION_DATE - dt.timedelta(days=1), dt.time(10, 0), tzinfo=IST)
    frame = pd.DataFrame([_row(dt.time(10, 0), "NIFTY", 24_000.0)])
    frame.loc[1] = frame.loc[0].copy()
    frame.loc[1, "minute_ts"] = int(other.timestamp() * 1_000_000)

    assert len(session_rows(frame, SESSION_DATE)) == 1
    # Without a date the hours filter still applies: 10:00 yesterday is 10:00.
    assert len(session_rows(frame)) == 2


# --------------------------------------------- defect 2: spot disagreeing within a minute


def test_the_index_own_bar_wins_over_the_snapshot_on_an_option_row() -> None:
    """One minute, three opinions, and only one of them is the index's own.

    This is the largest defect by reach — a third of sessions — and the one that silently
    moved this study's ATR bands, because they were built from whatever row sorted last.
    """
    frame = pd.DataFrame(
        [
            _row(dt.time(11, 0), "NIFTY-11Aug2026-24500-CE", 12.0, spot=24_480.0),
            _row(dt.time(11, 0), "NIFTY", 24_500.0),
            _row(dt.time(11, 0), "NIFTY-11Aug2026-24400-PE", 8.0, spot=24_515.6),
        ]
    )

    spots = underlying_spot(frame, "NIFTY", SESSION_DATE)

    assert len(spots) == 1
    assert spots.spot.iloc[0] == 24_500.0


def test_the_spot_path_is_one_print_per_minute_ascending() -> None:
    frame = pd.DataFrame(
        [
            _row(dt.time(11, 1), "NIFTY", 24_510.0),
            _row(dt.time(10, 0), "NIFTY", 24_500.0),
            _row(dt.time(7, 30), "NIFTY", 24_000.0),
        ]
    )

    spots = underlying_spot(frame, "NIFTY", SESSION_DATE)

    assert list(spots.spot) == [24_500.0, 24_510.0]


# -------------------------------------------------- defects 3 and 4: iv and size fields


@pytest.mark.parametrize("value", [0.0, -0.01, MAX_PLAUSIBLE_IV + 0.01, float("nan"), None])
def test_a_number_that_cannot_be_a_volatility_becomes_absence(value: float | None) -> None:
    assert clean_iv(value) is None


def test_a_plausible_volatility_survives() -> None:
    assert clean_iv(0.12) == pytest.approx(0.12)
    assert clean_iv(MAX_PLAUSIBLE_IV) == pytest.approx(MAX_PLAUSIBLE_IV)


@pytest.mark.parametrize("value", [-1.0, float("nan"), None])
def test_a_quantity_that_cannot_be_one_reads_as_no_quantity(value: float | None) -> None:
    """Zero, not the absolute value: a negative volume is absence of information.

    Turning -3 into 3 would manufacture a fill's worth of liquidity out of a vendor bug,
    which is exactly the kind of invention the participation cap exists to prevent.
    """
    assert clean_size(value) == 0.0


def _refdata() -> RefData:
    """One listed strike, enough for a universe the session can be built against."""
    return RefData(
        session_date=SESSION_DATE,
        nfo_instruments=tuple(
            {
                "TradingSymbol": f"NIFTY-11Aug2026-24500-{option_type}",
                "LookupName": "NIFTY",
                "OptionType": option_type,
                "StrikePrice": 24_500.0,
                "ExpiryDate": "11/08/2026",
                "LotSize": 65,
                "TickSize": 5.0,
            }
            for option_type in ("CE", "PE")
        ),
        underlier_instruments=(),
    )


# ------------------------------------------------------------- the boundary, end to end


def test_the_session_a_backtest_sees_carries_none_of_it() -> None:
    """``SessionView.from_frame`` is the one place a session becomes a backtest object."""
    frame = pd.DataFrame(
        [
            _row(dt.time(7, 6), "NIFTY", 24_000.0),
            _row(dt.time(10, 0), "NIFTY", 24_500.0),
            _row(dt.time(10, 0), "NIFTY-11Aug2026-24500-CE", 12.0, iv=0.0, volume=-3.0),
            _row(dt.time(10, 1), "NIFTY-11Aug2026-24500-CE", 12.5, iv=9.9, oi=-1.0),
            _row(dt.time(23, 0), "NIFTY", 24_000.0),
        ]
    )

    session = SessionView.from_frame(SESSION_DATE, "NIFTY", frame, _refdata())

    assert [minute.time() for minute in session.minutes()] == [dt.time(10, 0), dt.time(10, 1)]
    assert session.spot_at(session.minutes()[0]) == 24_500.0

    zero_iv = session.bar("NIFTY-11Aug2026-24500-CE", session.minutes()[0])
    assert zero_iv is not None
    assert zero_iv.iv is None, "an unsolved IV must not read as a quiet option"
    assert zero_iv.volume_units == 0.0

    wild_iv = session.bar("NIFTY-11Aug2026-24500-CE", session.minutes()[1])
    assert wild_iv is not None
    assert wild_iv.iv is None
    assert wild_iv.open_interest_units == 0.0


# ------------------------------------------------- the defects are in the real files


@pytest.mark.skipif(
    not (CORPUS_ROOT / "NIFTY").is_dir(), reason=f"real corpus not present at {CORPUS_ROOT}"
)
def test_the_real_corpus_still_contains_what_this_module_defends_against() -> None:
    """Without this, every fixture above could be guarding a hazard that no longer exists.

    2022-01-07 is the worst out-of-hours session found in the audit: 637 underlying rows
    from 07:06 to 23:00, zero volume, the price repeating. If a re-capture ever cleans it,
    this test fails and the module's premise gets re-examined rather than assumed.
    """
    path = CORPUS_ROOT / "NIFTY" / "2022-01-07.parquet"
    if not path.is_file():
        pytest.skip("the 2022-01-07 session is not in this corpus")
    frame = pq.read_table(path).to_pandas()

    kept = session_rows(frame, dt.date(2022, 1, 7))
    dropped = len(frame) - len(kept)

    assert dropped > 500, f"the out-of-hours padding is gone ({dropped} rows dropped)"
    # And what remains is a plausible exchange day rather than an over-zealous filter:
    # 09:15 to 16:00 inclusive is 406 minutes, and a full session prints most of them.
    assert 375 <= kept.minute_ts.nunique() <= 406
