"""The daily series the filters read, and the tenor bug that hid inside one of them.

ST-10's percentile is the only filter here whose first implementation was wrong in a way
that changed the study's headline numbers, so it gets the most tests: the comparison must be
same-tenor, must ignore the session being decided, and must refuse rather than guess when
there is not enough comparable history.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from xman_research.overlay.context import MINIMUM_PERCENTILE_SAMPLE, DailyContext


def frame(rows: list[tuple[dt.date, float, float, int]]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "session_date": [row[0] for row in rows],
            "open": [row[1] for row in rows],
            "close": [row[1] for row in rows],
            "atm_iv": [row[2] for row in rows],
            "expiry": [row[0] + dt.timedelta(days=row[3]) for row in rows],
            "dte": [row[3] for row in rows],
        }
    )


def alternating(count: int, *, entry_iv: float, expiry_iv: float) -> list[tuple]:
    """A corpus shaped like the real one: an expiry session, then an entry-window session."""
    rows = []
    day = dt.date(2025, 1, 6)
    for index in range(count):
        dte = 0 if index % 2 else 6
        rows.append((day, 23_000.0, expiry_iv if dte == 0 else entry_iv, dte))
        day += dt.timedelta(days=1)
    return rows


def test_the_percentile_ignores_sessions_of_a_different_tenor() -> None:
    """The bug this test exists for.

    Expiry-day at-the-money implied volatility is a fraction of mid-week's, and every entry
    session is preceded by one. Ranking a 6-day implied against a history containing 0-day
    prints said "unusually high" almost every week, which halved 92 of 142 positions in the
    first five-year run.
    """
    rows = alternating(60, entry_iv=0.13, expiry_iv=0.05)
    today = rows[-1][0] + dt.timedelta(days=1)
    rows.append((today, 23_000.0, 0.13, 6))
    context = DailyContext(frame(rows))

    same_tenor = context.iv_percentile(today, 0.13, dte_bucket=(6,))
    mixed_tenor = context.iv_percentile(today, 0.13, dte_bucket=(0, 6))

    # Against its own tenor, 0.13 is exactly the median of a constant series: nothing is
    # strictly below it, so the percentile is 0 — the honest answer for "no dispersion".
    assert same_tenor == pytest.approx(0.0)
    # Against the mixed series it looks like the 50th percentile purely because half the
    # observations are expiry-day prints.
    assert mixed_tenor is not None and mixed_tenor > 40.0


def test_the_percentile_reads_only_sessions_before_the_one_asked_about() -> None:
    rows = [
        (dt.date(2025, 1, 6) + dt.timedelta(days=index), 23_000.0, 0.10, 6)
        for index in range(MINIMUM_PERCENTILE_SAMPLE + 1)
    ]
    # The session being asked about carries a high reading that must not count itself.
    today = rows[-1][0]
    rows[-1] = (today, 23_000.0, 0.99, 6)
    context = DailyContext(frame(rows))

    assert context.iv_percentile(today, 0.20, dte_bucket=(6,)) == pytest.approx(100.0)


def test_too_little_comparable_history_returns_no_percentile() -> None:
    """An unevaluable filter is recorded as unevaluable, never as a pass."""
    rows = [
        (dt.date(2025, 1, 6) + dt.timedelta(days=index), 23_000.0, 0.12, 6)
        for index in range(MINIMUM_PERCENTILE_SAMPLE - 1)
    ]
    today = rows[-1][0] + dt.timedelta(days=1)
    rows.append((today, 23_000.0, 0.12, 6))
    context = DailyContext(frame(rows))

    assert context.iv_percentile(today, 0.12, dte_bucket=(6,)) is None


def test_an_unknown_session_has_no_percentile() -> None:
    context = DailyContext(frame(alternating(40, entry_iv=0.13, expiry_iv=0.05)))

    assert context.iv_percentile(dt.date(2030, 1, 1), 0.13) is None


def test_the_derived_series_never_read_the_session_they_describe() -> None:
    rows = [
        (dt.date(2025, 1, 6) + dt.timedelta(days=index), 23_000.0 + index * 100.0, 0.12, 6)
        for index in range(25)
    ]
    context = DailyContext(frame(rows))
    today = rows[-1][0]

    inputs = context.inputs_for(today)

    assert inputs.previous_close == pytest.approx(rows[-2][1])
    assert inputs.sma_20 == pytest.approx(sum(row[1] for row in rows[-21:-1]) / 20.0)
    # The gap is the one same-session observation, and ST-13 evaluates it on entry morning.
    assert inputs.session_open == pytest.approx(rows[-1][1])
