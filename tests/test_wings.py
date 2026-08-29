"""The stale-bar rule and the spike statistics, on a frame whose answers are known.

The spike table is the most corruptible artifact in the wings study: a wing option that
does not trade for six minutes carries its last close on every bar in between, so a naive
``pct_change`` reports six minutes of move as a one-minute spike, at exactly the strikes
the study is about. These tests pin that rule and the retracement arithmetic against a
synthetic frame rather than against live data, so a regression fails here instead of
silently inflating a published table.
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

RESEARCH_DIR = Path(__file__).resolve().parents[1] / "research" / "expiry_cas"
sys.path.insert(0, str(RESEARCH_DIR))

from wings import band_floor_bound, spike_table, traded_changes  # noqa: E402


def _minutes(*hhmm: str) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(
        [pd.Timestamp(f"2026-08-27 {t}:00").tz_localize("Asia/Kolkata") for t in hhmm]
    )


@pytest.fixture
def stale_frame() -> tuple[pd.DataFrame, pd.DataFrame]:
    """One strike that trades at 15:14 and again at 15:20, stale in between.

    The close is forward-filled across the untraded minutes, which is what the vendor
    does; volume is zero there, which is the only signal distinguishing a repeat from an
    observation.
    """
    idx = _minutes("15:14", "15:15", "15:16", "15:17", "15:18", "15:19", "15:20")
    close = pd.DataFrame({75000.0: [10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 30.0]}, index=idx)
    vol = pd.DataFrame({75000.0: [100.0, 0.0, 0.0, 0.0, 0.0, 0.0, 400.0]}, index=idx)
    return close, vol


def test_change_spans_only_traded_bars(stale_frame):
    """The single reported change is 15:14 → 15:20, and it is labelled six minutes wide."""
    close, vol = stale_frame
    changes = traded_changes(close, vol)

    assert len(changes) == 1, "a stale run must not generate a change per stale bar"
    row = changes.iloc[0]
    assert row["from_ts"].strftime("%H:%M") == "15:14"
    assert row["to_ts"].strftime("%H:%M") == "15:20"
    assert row["d_pct"] == pytest.approx(200.0)
    assert row["gap_min"] == pytest.approx(6.0), (
        "a six-minute move reported without its gap reads as a one-minute spike"
    )


def test_stale_bars_never_become_zero_change_rows(stale_frame):
    """No change is emitted between two bars where either endpoint had no volume."""
    close, vol = stale_frame
    changes = traded_changes(close, vol)
    assert (changes["from_vol"] > 0).all()
    assert (changes["to_vol"] > 0).all()


def test_single_traded_bar_yields_no_change():
    """A strike that prints once has no minute-to-minute move to report."""
    idx = _minutes("15:14", "15:15")
    close = pd.DataFrame({74700.0: [5.0, 5.0]}, index=idx)
    vol = pd.DataFrame({74700.0: [80.0, 0.0]}, index=idx)
    assert traded_changes(close, vol).empty


class _Session:
    """Minimal stand-in carrying only what :func:`spike_table` reads."""

    def __init__(self, pe_close, pe_vol, implied_spot):
        self.pe_close = pe_close
        self.pe_vol = pe_vol
        self.ce_close = pe_close
        self.ce_vol = pe_vol
        self.implied_spot = implied_spot


def test_spike_retracement_and_wing_flag():
    """A put that doubles and gives the whole move back reads as 100 % reversed."""
    idx = _minutes("15:14", "15:21", "15:30", "15:35", "15:39")
    close = pd.DataFrame({75000.0: [10.0, 20.0, 15.0, 10.0, 5.0]}, index=idx)
    vol = pd.DataFrame({75000.0: [100.0, 500.0, 100.0, 100.0, 100.0]}, index=idx)
    # Reference index 100,000 puts the strike at moneyness 0.75 — unambiguously a wing.
    spot = pd.Series([100000.0] * len(idx), index=idx)

    table = spike_table(_Session(close, vol, spot), "PE", wing_max_moneyness=0.98)
    row = table.iloc[0]

    assert row["d_pct"] == pytest.approx(100.0)
    assert row["d_rs"] == pytest.approx(10.0)
    assert row["spike_min"] == "15:21"
    assert row["reversal_15:30_pct"] == pytest.approx(50.0)
    assert row["reversal_15:35_pct"] == pytest.approx(100.0)
    # Past the pre-spike level: the retracement exceeds 100 % rather than clipping at it.
    assert row["reversal_15:39_pct"] == pytest.approx(150.0)
    assert bool(row["is_wing"])


def test_at_the_money_strike_is_not_a_wing():
    """The wing flag is moneyness-driven, so a strike at the money never qualifies."""
    idx = _minutes("15:14", "15:21")
    close = pd.DataFrame({75000.0: [10.0, 20.0]}, index=idx)
    vol = pd.DataFrame({75000.0: [100.0, 500.0]}, index=idx)
    spot = pd.Series([75000.0, 75000.0], index=idx)

    table = spike_table(_Session(close, vol, spot), "PE", wing_max_moneyness=0.98)
    assert not bool(table.iloc[0]["is_wing"])


def test_band_floor_bound_is_intrinsic_plus_time_value():
    """Below the floor the bound is pure time value; above it, intrinsic is added."""
    session = object()
    assert band_floor_bound(session, 74000.0, 74925.0, 400.0) == pytest.approx(400.0)
    assert band_floor_bound(session, 75900.0, 74925.0, 400.0) == pytest.approx(1375.0)


def test_bound_grows_one_for_one_with_strike_above_the_floor():
    """Two strikes 100 apart, both above the floor, differ by exactly 100."""
    session = object()
    lo = band_floor_bound(session, 75000.0, 74925.0, 400.0)
    hi = band_floor_bound(session, 75100.0, 74925.0, 400.0)
    assert hi - lo == pytest.approx(100.0)


def test_change_columns_are_finite_on_a_well_formed_frame():
    """No NaN leaks into the reported change columns when both endpoints traded."""
    idx = _minutes("15:14", "15:15", "15:16")
    close = pd.DataFrame({75000.0: [10.0, 12.0, 11.0]}, index=idx)
    vol = pd.DataFrame({75000.0: [10.0, 20.0, 30.0]}, index=idx)
    changes = traded_changes(close, vol)
    assert len(changes) == 2
    assert np.isfinite(changes[["d_pct", "d_rs", "gap_min"]].to_numpy()).all()


def test_expiry_window_constants_bracket_the_session():
    """The study window is the last continuous cash minute through the last option bar."""
    from wings import WINDOW_END, WINDOW_START

    assert dt.time(15, 14) == WINDOW_START
    assert dt.time(15, 39) == WINDOW_END
