"""Unit tests for the cross-index divergence metrics.

Every quantity here is a closed-form function of the inputs, so each test constructs a
chain whose answer is known by hand. Three failure modes drive the choices:

* a **strike splice** — letting the implied series switch strike between minutes reports
  the parity offset between strikes as a price move, so the fixed-strike rule and its
  fallback flag are pinned;
* a **beta sign or exponent slip** — checked against a hand-computed fair value at two
  different betas, since at beta = 1 an exponent bug and a ratio bug agree;
* a **band inequality flip** — a put priced above its band-bounded maximum settlement must
  be flagged and one priced below must not, and neither on a chain that does not expire.
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pandas as pd
import pytest

RESEARCH_DIR = Path(__file__).resolve().parents[1] / "research" / "expiry_cas"
sys.path.insert(0, str(RESEARCH_DIR))

from cross_index import (  # noqa: E402
    BAND,
    ImpliedIndex,
    divergence,
    implied_index,
    structural_overpricing,
)
from load import SessionData  # noqa: E402

SESSION_DATE = dt.date(2026, 8, 27)
STRIKES = [76_900.0, 77_000.0, 77_100.0]


def _ts(minute: dt.time) -> pd.Timestamp:
    return pd.Timestamp.combine(SESSION_DATE, minute).tz_localize("Asia/Kolkata")


def _chain(rows: list[tuple[dt.time, float, str, float, float]]) -> pd.DataFrame:
    """Build a chain from ``(minute, strike, type, close, volume)`` tuples."""
    return pd.DataFrame(
        [
            {
                "ts": _ts(minute),
                "strike": strike,
                "opt_type": kind,
                "close": close,
                "volume": volume,
                "expiry": SESSION_DATE,
                "spot": 77_000.0,
            }
            for minute, strike, kind, close, volume in rows
        ]
    )


def _session(chain: pd.DataFrame, expiry: dt.date = SESSION_DATE) -> SessionData:
    return SessionData(
        underlying="SENSEX",
        session_date=SESSION_DATE,
        status="published",
        chain=chain,
        index=pd.Series(dtype=float),
        spot=pd.DataFrame(),
        lot_size=20,
        front_expiry=expiry,
        parity_anchor_strike=77_000.0,
    )


def _implied(levels: dict[dt.time, float], reference: float) -> ImpliedIndex:
    """An implied-index series stated directly, for tests of the divergence algebra."""
    frame = pd.DataFrame(
        {
            "implied": list(levels.values()),
            "strike": [77_000.0] * len(levels),
            "fallback": [False] * len(levels),
        },
        index=pd.DatetimeIndex([_ts(m) for m in levels], name="ts"),
    )
    return ImpliedIndex(
        session=_session(_chain([])),
        strike=77_000.0,
        series=frame,
        reference=reference,
        reference_time=_ts(dt.time(15, 14)),
    )


# ---------------------------------------------------------------- fixed-strike series


def test_implied_index_fixes_the_most_traded_strike() -> None:
    """The strike with the most both-legs-traded minutes wins, not the nearest one."""
    rows = []
    for minute in (dt.time(15, 0), dt.time(15, 20), dt.time(15, 30)):
        rows.append((minute, 77_000.0, "CE", 60.0, 100.0))
        rows.append((minute, 77_000.0, "PE", 40.0, 100.0))
    # A neighbour that trades in only one of the three minutes must not be chosen.
    rows.append((dt.time(15, 20), 77_100.0, "CE", 10.0, 5.0))
    rows.append((dt.time(15, 20), 77_100.0, "PE", 90.0, 5.0))
    built = implied_index(_session(_chain(rows)))
    assert built is not None
    assert built.strike == 77_000.0
    assert not built.series["fallback"].any()
    assert built.series["implied"].tolist() == [77_020.0] * 3


def test_missing_minute_on_the_fixed_strike_is_filled_and_flagged() -> None:
    """A minute the fixed strike misses is filled from a neighbour and marked."""
    rows = [
        (dt.time(15, 0), 77_000.0, "CE", 60.0, 100.0),
        (dt.time(15, 0), 77_000.0, "PE", 40.0, 100.0),
        (dt.time(15, 20), 77_000.0, "CE", 60.0, 100.0),
        (dt.time(15, 20), 77_000.0, "PE", 40.0, 100.0),
        # 15:30 trades only at the neighbour, at a deliberately different parity level.
        (dt.time(15, 30), 77_100.0, "CE", 10.0, 7.0),
        (dt.time(15, 30), 77_100.0, "PE", 95.0, 7.0),
    ]
    built = implied_index(_session(_chain(rows)))
    assert built is not None
    assert built.series["fallback"].tolist() == [False, False, True]
    assert built.series["strike"].tolist() == [77_000.0, 77_000.0, 77_100.0]
    assert built.series["implied"].iloc[-1] == pytest.approx(77_015.0)


def test_zero_volume_bars_never_enter_the_series() -> None:
    """A stale close differenced against a live one would be pure staleness."""
    rows = [
        (dt.time(15, 0), 77_000.0, "CE", 60.0, 100.0),
        (dt.time(15, 0), 77_000.0, "PE", 40.0, 100.0),
        (dt.time(15, 20), 77_000.0, "CE", 60.0, 0.0),
        (dt.time(15, 20), 77_000.0, "PE", 40.0, 0.0),
    ]
    built = implied_index(_session(_chain(rows)))
    assert built is not None
    assert len(built.series) == 1


# ---------------------------------------------------------------- divergence algebra


def test_divergence_is_zero_when_both_indices_move_proportionally_at_beta_one() -> None:
    sensex = _implied({dt.time(15, 20): 77_000.0 * 1.01}, reference=77_000.0)
    nifty = _implied({dt.time(15, 20): 24_000.0 * 1.01}, reference=24_000.0)
    frame = divergence(sensex, nifty, beta=1.0)
    assert frame["d_points"].iloc[0] == pytest.approx(0.0, abs=1e-6)


def test_divergence_matches_the_hand_computed_fair_value_at_beta_below_one() -> None:
    """At beta = 0.5 a 1 % Nifty move implies roughly half a per cent on Sensex."""
    sensex = _implied({dt.time(15, 20): 77_000.0}, reference=77_000.0)
    nifty = _implied({dt.time(15, 20): 24_240.0}, reference=24_000.0)
    frame = divergence(sensex, nifty, beta=0.5)
    expected_fair = 77_000.0 * (24_240.0 / 24_000.0) ** 0.5
    assert frame["s_fair"].iloc[0] == pytest.approx(expected_fair)
    assert frame["d_points"].iloc[0] == pytest.approx(77_000.0 - expected_fair)
    assert frame["d_pct"].iloc[0] == pytest.approx(
        100.0 * (77_000.0 - expected_fair) / expected_fair
    )


def test_divergence_uses_only_minutes_live_on_both_sides() -> None:
    """A minute present on one index only is dropped, never filled from the other."""
    sensex = _implied({dt.time(15, 20): 77_000.0, dt.time(15, 30): 77_500.0}, reference=77_000.0)
    nifty = _implied({dt.time(15, 20): 24_000.0}, reference=24_000.0)
    frame = divergence(sensex, nifty, beta=1.0)
    assert len(frame) == 1
    assert frame.index[0] == _ts(dt.time(15, 20))


# --------------------------------------------------------------------- the band test


def _overpricing_session(put_price: float, expiry: dt.date = SESSION_DATE) -> pd.DataFrame:
    reference = 77_000.0
    chain = _chain([(dt.time(15, 20), 76_900.0, "PE", put_price, 50.0)])
    sensex = ImpliedIndex(
        session=_session(chain, expiry=expiry),
        strike=77_000.0,
        series=pd.DataFrame(),
        reference=reference,
        reference_time=_ts(dt.time(15, 14)),
    )
    return structural_overpricing(sensex)


def test_a_put_priced_above_its_band_bounded_maximum_is_flagged() -> None:
    # floor = 77,000 x 0.97 = 74,690, so the 76,900 put can settle at most 2,210.
    assert pytest.approx(2_210.0) == 76_900.0 - 77_000.0 * (1 - BAND)
    flagged = _overpricing_session(2_500.0)
    assert len(flagged) == 1
    assert flagged["max_settle"].iloc[0] == pytest.approx(2_210.0)


def test_a_put_priced_below_its_band_bounded_maximum_is_not_flagged() -> None:
    assert _overpricing_session(2_000.0).empty


def test_no_price_is_structurally_overpriced_on_a_chain_that_does_not_expire_today() -> None:
    """The band bounds today's close; tomorrow's gap is unbounded, so no cap applies."""
    assert _overpricing_session(2_500.0, expiry=dt.date(2026, 9, 3)).empty
