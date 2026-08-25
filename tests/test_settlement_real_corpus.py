"""The measurement that licensed the post-auction proxy, against the captured sessions.

``tests/test_settlement_cas.py`` holds the behaviour on fixtures. This file holds the
three facts only the real corpus can state, and it is why
:data:`~xman_research.backtest.settlement.SETTLEMENT_RULES` carries a proxy at all rather
than a refusal:

1. **The 15:00-15:30 index feed degrades at exactly the auction boundary.** Before
   3 August 2026 a session's thirty window bars carry 25-30 distinct closes; from
   3 August they carry 15-17, the feed freezing for ten minutes at a time. The superseded
   statistic is therefore not merely out of date — most of its inputs stopped being
   observations.
2. **The expiring chain agrees with the closing print, to a quarter of a point**, on every
   post-auction expiry the corpus reaches, while sitting 17 to 146 points from the
   superseded mean.
3. **Before the boundary the same witness agrees with the mean instead**, and misses the
   closing print by up to 52. That is the control. Without it, fact 2 would be equally
   consistent with "the chain always tracks the last print", which would say nothing about
   settlement at all.

**The measurement's far end is discovered, not written down.** The expiries come from
refdata rather than a list, and the span they are looked for in runs to whatever session
the store last holds — so tonight's capture is measured tomorrow instead of the file
staying pinned to the three expiries that happened to exist when it was written. That
matters more than it sounds: the tolerance the proxy runs on is a gap observed across
three expiries, and the only thing that widens that sample is this file noticing new ones.
The read is capped at the most recent :data:`MEASURED_SESSIONS` sessions so the file's
parquet volume stays flat as the corpus grows.

Everything here is read-only: the corpus is irreplaceable and nothing in this package
opens it for writing.
"""

from __future__ import annotations

import datetime as dt
import os
import statistics
import tempfile
from pathlib import Path

import pytest

from xman_research import DataWindow, HypothesisRecord, ResearchSession
from xman_research.backtest import (
    BacktestConfig,
    SessionView,
    option_implied_settlement,
    run_backtest,
    settlement_value,
)
from xman_research.backtest.strategies import ShortAtmStraddle
from xman_research.session_store import DEFAULT_CORPUS_ROOT, SessionStore
from xman_research.session_store.trading_calendar import TradingCalendar

CORPUS_ROOT = Path(os.environ.get("XMAN_RESEARCH_CORPUS_ROOT") or DEFAULT_CORPUS_ROOT)
UNDERLYING = "NIFTY"

#: The day the Closing Auction Session went live, and the day the feed changed shape.
AUCTION_START = dt.date(2026, 8, 3)

#: The pre-boundary control: a month of sessions, fixed, because that regime is closed and
#: its numbers will not change again.
BEFORE = (dt.date(2026, 7, 1), AUCTION_START - dt.timedelta(days=1))

#: How many post-boundary sessions to read, counted back from the newest the store holds.
#: Enough for several expiry cycles; flat as the corpus grows.
MEASURED_SESSIONS = 45

#: The end-to-end run's window is **fixed on purpose**, unlike the measurement's. A run
#: asserts on settlement counts and needs a span whose contents do not change underneath
#: it; a measurement asserts a relationship and wants every session it can get.
E2E_WINDOW = (AUCTION_START, dt.date(2026, 8, 18))

pytestmark = pytest.mark.skipif(
    not (CORPUS_ROOT / UNDERLYING).is_dir(),
    reason=f"real corpus not present at {CORPUS_ROOT / UNDERLYING}",
)


@pytest.fixture(scope="module")
def store() -> SessionStore:
    return SessionStore(root=CORPUS_ROOT)


def _refs(store: SessionStore, span: tuple[dt.date, dt.date]):
    resolution = store.resolve(UNDERLYING, *span)
    if resolution.is_complete:
        return list(resolution.sessions())
    # A span reaching for "whatever exists now" is incomplete by construction — the
    # sessions after the last capture have not been captured. That is the answer being
    # asked for here, not a hole to refuse over.
    return list(resolution.accept_gaps("settlement measurement: the shape of the feed, not a P&L"))


def _sessions(
    store: SessionStore, span: tuple[dt.date, dt.date], *, limit: int | None = None
) -> list[SessionView]:
    refs = _refs(store, span)
    if limit is not None:
        refs = refs[-limit:]
    return [
        SessionView.from_frame(
            ref.session_date, UNDERLYING, store.load_session(ref), store.load_refdata(ref)
        )
        for ref in refs
    ]


def _distinct_window_closes(session: SessionView) -> int:
    return len(
        {
            bar.close
            for bar in session.underlying_bars()
            if dt.time(15, 0) <= bar.minute.time() < dt.time(15, 30)
        }
    )


def _window_mean(session: SessionView) -> float:
    closes = [
        bar.close
        for bar in session.underlying_bars()
        if dt.time(15, 0) <= bar.minute.time() < dt.time(15, 30)
    ]
    return statistics.fmean(closes)


def _closing_print(session: SessionView) -> float:
    return max(
        (bar for bar in session.underlying_bars() if bar.minute.time() < dt.time(15, 45)),
        key=lambda bar: bar.minute,
    ).close


def _expiries(sessions: list[SessionView]) -> list[SessionView]:
    """The sessions that are themselves an expiry, per their own refdata."""
    return [session for session in sessions if session.session_date in session.universe.expiries()]


@pytest.fixture(scope="module")
def before(store: SessionStore) -> list[SessionView]:
    return _sessions(store, BEFORE)


@pytest.fixture(scope="module")
def after(store: SessionStore) -> list[SessionView]:
    """Every post-boundary session the store holds, back to at most ``MEASURED_SESSIONS``.

    The far end is the corpus's own, found by resolving a span that deliberately overshoots
    into sessions that have not happened yet and keeping what came back.
    """
    # The overshoot stops at the calendar's own coverage end: past it the store refuses
    # the range outright rather than mistake unlisted holidays for capture gaps, and that
    # refusal is a guard worth keeping rather than one to route around.
    horizon = TradingCalendar().coverage_end
    refs = _refs(store, (AUCTION_START, horizon))
    assert refs, "no sessions captured on or after the auction boundary"
    latest = max(ref.session_date for ref in refs)
    assert latest >= dt.date(2026, 8, 18), (
        f"the corpus stops at {latest}, before the three expiries this measurement needs"
    )
    return _sessions(store, (AUCTION_START, latest), limit=MEASURED_SESSIONS)


def test_the_index_feed_stops_observing_at_the_auction_boundary(
    before: list[SessionView], after: list[SessionView]
) -> None:
    """Fact 1: the settlement window's bars become repeats rather than observations.

    This is the reason the old rule could not simply be extended past 3 August with a note
    about weighting. A mean over thirty numbers of which half are the same number carried
    forward is not the statistic the rule names, whatever the exchange happens to be doing.
    """
    assert len(before) > 15 and len(after) > 10

    before_distinct = [_distinct_window_closes(session) for session in before]
    after_distinct = [_distinct_window_closes(session) for session in after]

    assert min(before_distinct) >= 25, f"pre-auction feed already stale: {before_distinct}"
    assert max(after_distinct) <= 22, f"post-auction feed not stale: {after_distinct}"
    assert max(after_distinct) < min(before_distinct)


def test_after_the_boundary_the_chain_agrees_with_the_closing_print(
    after: list[SessionView],
) -> None:
    """Fact 2, and the licence for the proxy: agreement to a fraction of a point.

    The settled value the module returns is checked against the chain here as well as
    inside :func:`settlement_value`, because the assertion worth writing down is not
    "the guard did not fire" — that is trivially true of a guard with a loose threshold —
    but the size of the residual it is guarding.
    """
    expiries = _expiries(after)
    assert len(expiries) >= 3, "the corpus should reach at least three post-auction expiries"

    for session in expiries:
        implied = option_implied_settlement(session)
        assert implied is not None, f"{session.session_date}: no expiring chain to witness"
        assert implied.pairs >= 15

        settled = settlement_value(session)
        residual = abs(settled.value - implied.value)
        superseded = abs(_window_mean(session) - implied.value)

        assert residual <= 0.5, f"{session.session_date}: closing print off by {residual}"
        assert superseded >= 15.0, (
            f"{session.session_date}: the superseded mean is only {superseded} from the "
            "chain's view, which would make the two statistics indistinguishable here"
        )
        assert residual * 30 < superseded


def test_before_the_boundary_the_chain_agrees_with_the_window_mean_instead(
    before: list[SessionView],
) -> None:
    """Fact 3, the control: the witness tracks the *statistic*, not the last price.

    One minute before expiry an option prices whatever the exchange is about to pay, so
    under the 30-minute-average regime the chain converges on the running average and
    ignores the closing print — by up to 52 points on these sessions. That is what makes
    the same witness's post-auction behaviour evidence of a changed statistic rather than
    a property of the witness.
    """
    expiries = _expiries(before)
    assert len(expiries) >= 4

    to_mean: list[float] = []
    to_print: list[float] = []
    for session in expiries:
        implied = option_implied_settlement(session)
        assert implied is not None
        to_mean.append(abs(_window_mean(session) - implied.value))
        to_print.append(abs(_closing_print(session) - implied.value))

    assert max(to_mean) <= 8.5, f"the chain did not track the window mean: {to_mean}"
    assert max(to_print) >= 15.0, f"the closing print was never far from the chain: {to_print}"
    assert statistics.fmean(to_mean) < statistics.fmean(to_print)


def test_the_out_of_hours_print_is_not_taken_for_a_close(store: SessionStore) -> None:
    """2026-08-19 carries an index row stamped 18:40. It is not the close and is not used.

    The fixture version of this lives in ``test_settlement_cas.py``; this one asserts that
    the corpus really does contain such a row, so the fixture is reproducing a hazard
    rather than inventing one.
    """
    session = _sessions(store, (dt.date(2026, 8, 19), dt.date(2026, 8, 19)))[0]

    stray = session.underlying_bars()[-1]
    assert stray.minute.time() > dt.time(16, 0), "the 18:40 row is gone; drop this test"

    settled = settlement_value(session)

    # The stray row happens to repeat the 15:29 close, so comparing *values* would pass
    # whether the window filtered it or not. What discriminates is which minute was used —
    # and the reason to hold this at all is that the next out-of-hours row need not be a
    # repeat. 2026-08-04's feed moved 151 points in its last printed minute.
    assert settled.window_start != stray.minute
    assert settled.window_start.time() < dt.time(15, 45)


def test_a_hold_to_expiry_run_crosses_the_boundary_and_stamps_the_proxy(
    store: SessionStore,
) -> None:
    """The end of the truncation, end to end: settlements land, and every result says how.

    Before this change ``settlement_value`` refused for any expiry from 3 August 2026, and
    :func:`run_backtest` does not catch that refusal — so a window reaching past the
    boundary did not produce a truncated result, it produced no result at all. This run
    covers three post-auction expiries and asserts both halves of the fix: the settlements
    exist, and ``unverified_inputs`` — the field the decision gate reads — names the proxy
    and its tier, so nothing computed through it can be read as if the methodology were
    known.
    """
    from xman_research import StaticCodeVersion, TrialLog
    from xman_research.clock import ManualClock

    window = DataWindow(*E2E_WINDOW)
    log = TrialLog(
        Path(tempfile.mkdtemp(prefix="xman_research_cas_e2e_")) / "research.db",
        clock=ManualClock(dt.datetime(2026, 8, 25, 9, 15, tzinfo=dt.UTC)),
        code_version=StaticCodeVersion("0" * 40, dirty=False),
    )
    session = ResearchSession(log)
    hypothesis = HypothesisRecord(
        name="Settlement under the closing auction regime (proxy E2E)",
        mechanism=(
            "A short straddle held to cash settlement collects the variance risk premium; "
            "under the post-3-August regime it settles against the closing print proxy."
        ),
        null_hypothesis="The premium is zero or negative after statutory costs.",
        thresholds={"deflated_sharpe": 0.0, "cost_breakeven_multiple": 2.0},
        predictors=["iv_30d", "realised_vol_20d"],
    )
    try:
        with session.trial(hypothesis, data_window=window) as trial:
            result = run_backtest(
                trial,
                store=store,
                strategy=ShortAtmStraddle(),
                config=BacktestConfig(underlying=UNDERLYING),
            )
    finally:
        session.close()

    assert result.sessions_run >= 10
    assert len(result.settlements) >= 2
    assert all(
        record.rule_method == "last_underlying_print_in_closing_window"
        for record in result.settlements
    )
    assert (
        "settlement.last_underlying_print_in_closing_window:unverified" in result.unverified_inputs
    )
