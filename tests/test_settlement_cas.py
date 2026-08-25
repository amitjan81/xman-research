"""The post-auction settlement regime, on fixtures small enough to check by eye.

From 3 August 2026 the exchange settles index options against a Closing Auction Session
equilibrium price. That print is not in the corpus and cannot be reconstructed from minute
bars of continuous trading, so what
:mod:`xman_research.backtest.settlement` computes is a **proxy** — the last index print
inside a stated closing window — and what these tests hold is the three things that make a
proxy usable rather than a guess: it is not the superseded statistic, it refuses when it
cannot observe a close, and it is checked against an independent witness on every use.

The witness is the expiring option chain. At expiry a European option has no time value
and no discounting, so ``C - P = S - K`` exactly at every strike, and the post-auction
regime opened a print window after the cash close in which those options trade at pure
intrinsic. What the market that settles against the exchange's number believed that number
to be is not a source for the rule, and these fixtures never treat it as one; it is a
second opinion, which is enough to catch a settled value that is wrong by points.

The measurement that justified the tolerance lives in
``tests/test_settlement_real_corpus.py`` — it needs the captured sessions and cannot be
stated by a fixture.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from conftest import IST, SESSION_MINUTES, SESSION_OPEN
from xman_research.backtest.costs import Confidence
from xman_research.backtest.market import OptionType, SessionView
from xman_research.backtest.settlement import (
    METHOD_LAST_UNDERLYING_PRINT,
    SETTLEMENT_RULES,
    SettlementRule,
    SettlementWindowError,
    option_implied_settlement,
    settlement_rule_for,
    settlement_value,
)
from xman_research.session_store import RefData

#: A Tuesday under the post-auction regime, and an expiry.
EXPIRY = dt.date(2026, 8, 11)
LOT = 65
STRIKES = tuple(float(strike) for strike in range(24_300, 24_651, 50))

#: The index feed freezes for the last stretch of continuous trading and then prints the
#: close, which is what the real corpus does from 3 August 2026 onwards. The frozen value
#: and the closing print are 21 points apart, so a test that settled on the wrong one says
#: so loudly.
FROZEN = 24_450.25
CLOSING_PRINT = 24_471.70


def _stamp(session_date: dt.date, moment: dt.time) -> int:
    return int(dt.datetime.combine(session_date, moment, tzinfo=IST).timestamp() * 1_000_000)


def _row(minute_ts: int, symbol: str, price: float) -> dict[str, object]:
    return {
        "minute_ts": minute_ts,
        "symbol": symbol,
        "open": price,
        "high": price,
        "low": price,
        "close": price,
        "iv": float("nan"),
        "oi": float("nan"),
        "volume": float("nan"),
        "spot": price,
    }


def _symbol(strike: float, option_type: str) -> str:
    """The producer's spelling. The fixture plays the exchange; nothing parses this back."""
    return f"NIFTY-11Aug2026-{int(strike)}-{option_type}"


def _refdata(session_date: dt.date, expiry: dt.date = EXPIRY) -> RefData:
    return RefData(
        session_date=session_date,
        nfo_instruments=tuple(
            {
                "TradingSymbol": _symbol(strike, option_type),
                "LookupName": "NIFTY",
                "OptionType": option_type,
                "StrikePrice": strike,
                "ExpiryDate": expiry.strftime("%d/%m/%Y"),
                "LotSize": LOT,
                "TickSize": 5.0,
            }
            for strike in STRIKES
            for option_type in (OptionType.CALL, OptionType.PUT)
        ),
        underlier_instruments=(),
    )


def _index_rows(
    session_date: dt.date,
    *,
    closing_print: float | None = CLOSING_PRINT,
    last_index_minute: dt.time = dt.time(15, 29),
    late_print: tuple[dt.time, float] | None = None,
) -> list[dict[str, object]]:
    """The index's own bars: a ramp, then a frozen stretch, then the close."""
    first = dt.datetime.combine(session_date, SESSION_OPEN, tzinfo=IST)
    rows: list[dict[str, object]] = []
    for index in range(SESSION_MINUTES):
        minute = first + dt.timedelta(minutes=index)
        if minute.time() > last_index_minute:
            break
        price = FROZEN if minute.time() >= dt.time(15, 0) else FROZEN - 100.0
        if closing_print is not None and minute.time() == last_index_minute:
            price = closing_print
        rows.append(_row(int(minute.timestamp() * 1_000_000), "NIFTY", price))
    if late_print is not None:
        moment, price = late_print
        rows.append(_row(_stamp(session_date, moment), "NIFTY", price))
    return rows


def _chain_rows(
    session_date: dt.date,
    settled: float,
    *,
    minutes: tuple[dt.time, ...] | None = None,
    strikes: tuple[float, ...] = STRIKES,
) -> list[dict[str, object]]:
    """The expiring chain, trading at pure intrinsic from 15:30 to 15:39.

    The wings sit on the 0.05 tick floor exactly as the corpus's do, which is why the
    module takes a median across strikes rather than a mean.
    """
    rows: list[dict[str, object]] = []
    moments = minutes if minutes is not None else tuple(dt.time(15, 30 + o) for o in range(10))
    for moment in moments:
        stamp = _stamp(session_date, moment)
        for strike in strikes:
            rows.append(_row(stamp, _symbol(strike, OptionType.CALL), max(0.05, settled - strike)))
            rows.append(_row(stamp, _symbol(strike, OptionType.PUT), max(0.05, strike - settled)))
    return rows


def _session(
    session_date: dt.date = EXPIRY,
    *,
    index_rows: list[dict[str, object]] | None = None,
    chain_settled: float | None = CLOSING_PRINT,
    chain_rows: list[dict[str, object]] | None = None,
) -> SessionView:
    rows = _index_rows(session_date) if index_rows is None else index_rows
    if chain_rows is not None:
        rows = rows + chain_rows
    elif chain_settled is not None:
        rows = rows + _chain_rows(session_date, chain_settled)
    return SessionView.from_frame(session_date, "NIFTY", pd.DataFrame(rows), _refdata(session_date))


# --------------------------------------------------------------- the rule in the table


def test_the_rule_in_force_after_the_auction_launch_is_the_proxy_and_says_so() -> None:
    """It is implemented — and stamped UNVERIFIED, because no source states the rule.

    The tier is the whole reason a proxy is allowed to ship. ``settlement_rule_for``
    returning something implemented is what lets a hold-to-expiry model run past 3 August
    2026 at all; the tier is what stops the result being read as if the methodology were
    known. Both halves are asserted here because either one alone would be a defect.
    """
    rule = settlement_rule_for(EXPIRY)

    assert rule.effective_from == dt.date(2026, 8, 3)
    assert rule.method == METHOD_LAST_UNDERLYING_PRINT
    assert rule.implemented
    assert rule.confidence is Confidence.UNVERIFIED
    assert rule.corroboration_tolerance == 5.0
    # The stamp the engine builds from these two fields, and the field the decision gate
    # reads. Spelled out so a rename of either cannot pass silently.
    assert f"settlement.{rule.method}:{rule.confidence}" == (
        "settlement.last_underlying_print_in_closing_window:unverified"
    )


def test_an_unimplemented_rule_still_refuses() -> None:
    """The refusal machinery outlives the row that motivated it.

    The auction row shipped ``implemented=False`` and this test used to hold that exact
    row. The row is now implemented, and the behaviour it demonstrated must not leave with
    it: the *next* methodology change will arrive the same way, as a row nobody has written
    the computation for yet, and it has to refuse rather than fall through to whichever
    rule happens to precede it.
    """
    future = SettlementRule(
        effective_from=dt.date(2027, 1, 1),
        method="some_statistic_nobody_has_implemented_yet",
        window_start=dt.time(15, 0),
        window_end=dt.time(15, 30),
        expected_bars=0,
        implemented=False,
        source="a circular that has not been read",
        source_url="https://example.invalid/circular",
        confidence=Confidence.UNVERIFIED,
        note="Not implemented.",
    )
    rules = (*SETTLEMENT_RULES, future)
    session = _session(dt.date(2027, 3, 9))

    with pytest.raises(SettlementWindowError, match="nobody_has_implemented_yet"):
        settlement_value(session, rules=rules)


# ------------------------------------------------------------------ the settled value


def test_the_post_auction_session_settles_on_the_closing_print() -> None:
    """Not the 30-minute mean, which under this regime averages a frozen feed.

    The fixture's window holds 29 repeats of 24,450.25 and one close at 24,471.70: the
    superseded statistic returns 24,451, the closing print returns 24,471.70, and the
    difference is one direction on every expiry rather than noise.
    """
    session = _session()

    settled = settlement_value(session)

    assert settled.value == pytest.approx(CLOSING_PRINT)
    assert settled.bars_used == 1
    assert settled.rule.method == METHOD_LAST_UNDERLYING_PRINT
    assert settled.window_start.time() == dt.time(15, 29)

    window = [
        bar
        for bar in session.underlying_bars()
        if dt.time(15, 0) <= bar.minute.time() < dt.time(15, 30)
    ]
    superseded = sum(bar.close for bar in window) / len(window)
    assert superseded == pytest.approx(24_450.9646, abs=1e-3)
    assert abs(settled.value - superseded) > 20


def test_a_print_from_hours_after_the_close_is_not_the_close() -> None:
    """2026-08-19 in the real corpus carries an index row stamped 18:40.

    "The last print of the session" would take it, and every payoff of that day would be
    struck at whatever an out-of-hours row happened to say. The rule's closing window is
    what makes that unreachable, so this fixture puts a wild value out there and asserts
    the settled value never moves.
    """
    session = _session(index_rows=_index_rows(EXPIRY, late_print=(dt.time(18, 40), 25_500.0)))

    assert session.underlying_bars()[-1].close == 25_500.0
    settled = settlement_value(session)

    assert settled.value == pytest.approx(CLOSING_PRINT)
    assert settled.window_start.time() == dt.time(15, 29)


def test_a_session_whose_feed_stopped_before_the_close_refuses() -> None:
    """A feed that stopped at 15:20 has not observed a close, and cannot settle.

    The alternative — settle on the last thing it did print — is the failure this whole
    module is shaped against: a number that looks like a settlement, is a mid-afternoon
    price, and reports itself clean.
    """
    session = _session(index_rows=_index_rows(EXPIRY, last_index_minute=dt.time(15, 20)))

    with pytest.raises(SettlementWindowError, match="closing window"):
        settlement_value(session)


# ------------------------------------------------------------------------- the witness


def test_the_witness_is_read_from_the_chain_and_travels_with_the_result() -> None:
    """Put-call parity across the expiring chain, at the last minute it printed."""
    session = _session()

    implied = option_implied_settlement(session)
    assert implied is not None
    assert implied.minute.time() == dt.time(15, 39)
    assert implied.pairs == len(STRIKES)
    # Every strike sits on the tick floor on one side, and the floor pushes the estimate
    # one way below the settled value and the other way above it. The median cancels that
    # exactly, which is the reason it is a median; a mean of the same eight numbers would
    # inherit whichever wing the chain happens to be longer on.
    assert implied.value == pytest.approx(CLOSING_PRINT)
    assert implied.dispersion == pytest.approx(0.1)

    settled = settlement_value(session)
    assert settled.corroboration is not None
    provenance = settled.provenance()
    assert provenance["corroborated_by_option_parity"] == implied.provenance()
    assert provenance["corroboration_residual"] == pytest.approx(0.0, abs=1e-9)


def test_a_closing_print_the_chain_contradicts_does_not_settle() -> None:
    """The agreement is what licenses the proxy, so losing it withdraws the licence.

    Forty points is far outside anything the real corpus shows (0.25 at worst) and far
    inside the divergence of the superseded statistic (17 points at best), so a fixture at
    40 is unambiguously the case the tolerance exists to catch.
    """
    session = _session(chain_settled=CLOSING_PRINT + 40.0)

    with pytest.raises(SettlementWindowError, match="misses the expiring chain"):
        settlement_value(session)


def test_a_session_with_no_expiring_chain_has_no_witness_and_still_settles() -> None:
    """Corroboration is a check, not a precondition — absence of a chain is not a defect.

    A session with nothing expiring is not an expiry, and the engine settles nothing on it.
    Refusing here would turn "there was no second opinion" into "the value is wrong", which
    is a different claim and a false one. The result still carries the rule's UNVERIFIED
    stamp, so nothing about it reads as corroborated.
    """
    monday = dt.date(2026, 8, 10)
    session = SessionView.from_frame(
        monday, "NIFTY", pd.DataFrame(_index_rows(monday)), _refdata(monday)
    )

    assert option_implied_settlement(session) is None
    settled = settlement_value(session)

    assert settled.value == pytest.approx(CLOSING_PRINT)
    assert settled.corroboration is None
    assert "corroborated_by_option_parity" not in settled.provenance()


def test_the_witness_falls_back_past_a_minute_too_thin_to_be_one() -> None:
    """One strike quoting both sides is an anecdote; the median needs a chain.

    The last minute here quotes two strikes and the one before it quotes all eight, so the
    assertion is not merely that the thin minute is rejected but that the witness keeps
    looking. A chain thins out at the very end of a session — the wings stop quoting first —
    and taking the last minute unconditionally would hand the guard a two-strike opinion on
    exactly the sessions where the chain is worst.
    """
    session = _session(
        chain_rows=_chain_rows(
            EXPIRY,
            CLOSING_PRINT,
            minutes=tuple(dt.time(15, 30 + offset) for offset in range(9)),
        )
        + _chain_rows(EXPIRY, CLOSING_PRINT, minutes=(dt.time(15, 39),), strikes=STRIKES[:2]),
    )

    implied = option_implied_settlement(session)

    assert implied is not None
    assert implied.minute.time() == dt.time(15, 38)
    assert implied.pairs == len(STRIKES)
    # And the precondition still holds when no minute anywhere is thick enough.
    assert option_implied_settlement(session, minimum_pairs=len(STRIKES) + 1) is None


def test_an_expiry_whose_chain_cannot_witness_the_close_does_not_settle() -> None:
    """The guard is not optional on the one kind of session the engine settles.

    ``_settle_expiring`` is the only caller, and it fires only when a position expires that
    session — so in production every settled session is an expiry. Letting a thin chain
    mean "no check" would leave the proxy uncorroborated on exactly the sessions that pay,
    with nothing but an absent provenance key to say so. It refuses instead, and says which
    of the two cases it is in.
    """
    session = _session(
        chain_rows=_chain_rows(EXPIRY, CLOSING_PRINT, strikes=STRIKES[:2]),
    )

    assert option_implied_settlement(session) is None
    assert session.session_date in session.universe.expiries()

    with pytest.raises(SettlementWindowError, match="no put-call pair to witness"):
        settlement_value(session)


def test_an_out_of_hours_chain_print_is_not_the_witness() -> None:
    """The witness is time-bounded for the same reason the settled value is.

    A stray 18:45 chain row would otherwise become the opinion that a real closing print is
    judged against — and because the guard refuses on disagreement, a witness read from a
    junk row does not produce a wrong number, it kills the run.
    """
    session = _session(
        chain_rows=_chain_rows(EXPIRY, CLOSING_PRINT)
        + _chain_rows(EXPIRY, CLOSING_PRINT + 500.0, minutes=(dt.time(18, 45),)),
    )

    implied = option_implied_settlement(session)
    assert implied is not None
    assert implied.minute.time() == dt.time(15, 39)
    assert settlement_value(session).value == pytest.approx(CLOSING_PRINT)


def test_a_tolerance_no_method_honours_is_refused_as_a_table_defect() -> None:
    """A guard that reports itself installed and is not is worse than no guard.

    ``corroboration_tolerance`` is a field on every rule but only the closing-print method
    reads it. A future row pairing it with the window-mean method would look guarded in the
    table and be unguarded in fact, which is the failure mode this whole module is shaped
    against — so it is refused where it can still be seen, at the point of use.
    """
    guarded_mean = SettlementRule(
        effective_from=dt.date(2010, 1, 1),
        method="mean_of_underlying_minute_close_over_window",
        window_start=dt.time(15, 0),
        window_end=dt.time(15, 30),
        expected_bars=30,
        source="the pre-auction rule, with a tolerance nothing reads",
        source_url="https://example.invalid/rule",
        confidence=Confidence.CORROBORATED,
        corroboration_tolerance=5.0,
    )
    session = _session(dt.date(2026, 6, 9))

    with pytest.raises(SettlementWindowError, match="does not check one"):
        settlement_value(session, rules=(guarded_mean,))


def test_a_caller_who_asks_for_no_bars_at_all_is_still_refused() -> None:
    """``minimum_bars=0`` is not "settle on an empty window"; there is no such value."""
    session = _session(index_rows=_index_rows(EXPIRY, last_index_minute=dt.time(15, 20)))

    with pytest.raises(SettlementWindowError, match="closing window"):
        settlement_value(session, minimum_bars=0)


# --------------------------------------------------------- the pre-auction rule is intact


def test_the_pre_auction_rule_still_averages_its_window() -> None:
    """The new row must not have moved the old one — two regimes, two statistics.

    Same fixture shape, a June session date: the 30-minute mean comes back, over 30 bars,
    and the closing print is *not* what is returned.
    """
    june = dt.date(2026, 6, 9)
    session = SessionView.from_frame(
        june,
        "NIFTY",
        pd.DataFrame(_index_rows(june)),
        _refdata(june, expiry=june),
    )

    settled = settlement_value(session)

    assert settled.bars_used == 30
    assert settled.value == pytest.approx(24_450.9646, abs=1e-3)
    assert settled.value != pytest.approx(CLOSING_PRINT)
    assert settled.corroboration is None
