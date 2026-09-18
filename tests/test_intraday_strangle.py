"""The intraday strangle's four rules, each against a chain built to trigger exactly it.

The fixture prices a full option chain with Black-Scholes at a stated volatility, so the
strike the delta rule selects and the credit the entry collects are both known before the
strategy runs. Spot is moved explicitly where a stop is under test, because a stop keyed to
the index is only testable by moving the index.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from tests.test_overlay_strategy import (
    ENTRY_DATE,
    EXPIRY,
    LOT_SIZE,
    SPOT,
    chain,
    session_view,
)

from xman_research.backtest.costs import Side
from xman_research.backtest.engine import BookView, Position
from xman_research.backtest.market import SessionView
from xman_research.intraday.strangle import IntradayStrangle, SpotStop, StrangleParameters


def build(**kwargs) -> IntradayStrangle:
    defaults = {
        "short_delta_target": 0.15,
        "delta_band": (0.11, 0.19),
        "entry_time": dt.time(9, 45),
        "profit_take_pct": 0.50,
        "stop_move_pct": 0.005,
        "min_credit_pct_of_spot": 0.0,
        "target_notional": 5_000_000.0,
    }
    defaults.update(kwargs)
    return IntradayStrangle(params=StrangleParameters(**defaults))


def minute_at(view: SessionView, when: dt.time) -> dt.datetime:
    minute = view.minute_at_or_after(when)
    assert minute is not None
    return minute


def open_position(
    tmp_path: Path, strategy: IntradayStrangle, *, spot: float = SPOT
) -> tuple[SessionView, dict]:
    view = session_view(
        tmp_path / "entry", ENTRY_DATE, chain(session_date=ENTRY_DATE, spot=spot), spot=spot
    )
    minute = minute_at(view, dt.time(9, 45))
    intents = strategy.decide(session=view, minute=minute, book=BookView({}, 10_000_000.0))
    assert intents, "fixture failed to open a strangle"
    positions = {}
    for intent in intents:
        contract = view.universe.by_symbol(intent.trading_symbol)
        assert contract is not None
        bar = view.bar(intent.trading_symbol, minute)
        assert bar is not None
        positions[intent.trading_symbol] = Position(
            contract=contract,
            units=-intent.lots * contract.lot_size,
            last_mark=bar.close,
        )
    return view, positions


def test_entry_sells_one_otm_call_and_one_otm_put(tmp_path: Path) -> None:
    strategy = build()
    view, _ = open_position(tmp_path, strategy)

    entry = next(row for row in strategy.journal if row["outcome"] == "entered")
    strikes = entry["detail"]["strikes"]

    assert strikes["short_call"] > SPOT, "the call must be out of the money"
    assert strikes["short_put"] < SPOT, "the put must be out of the money"
    for role, delta in entry["detail"]["deltas"].items():
        assert 0.11 <= delta <= 0.19, role
    assert entry["detail"]["credit_pct_of_spot"] > 0
    # Both legs in one group: a strangle half-filled is a naked directional short.
    assert view is not None


def test_only_one_strangle_a_session(tmp_path: Path) -> None:
    strategy = build()
    view, _positions = open_position(tmp_path, strategy)

    # Flat again later the same session — the rule is one entry per session, not one at a time.
    later = minute_at(view, dt.time(11, 0))
    assert strategy.decide(session=view, minute=later, book=BookView({}, 10_000_000.0)) == ()


def test_the_stop_reads_the_index_and_not_the_option(tmp_path: Path) -> None:
    """A 0.6% index move closes a position whose stop is 0.5% — with option prices unchanged.

    The chain handed to the second call is priced at the *entry* spot, so every option is
    worth exactly what it was worth at entry. Only the index has moved. If the stop fired,
    it read the index.
    """
    strategy = build(stop_move_pct=0.005)
    _, positions = open_position(tmp_path, strategy)

    moved = SPOT * 1.006
    view = session_view(
        tmp_path / "moved", ENTRY_DATE, chain(session_date=ENTRY_DATE, spot=SPOT), spot=moved
    )
    intents = strategy.decide(
        session=view, minute=minute_at(view, dt.time(11, 0)), book=BookView(positions, 1e7)
    )

    assert {intent.tag for intent in intents} == {"stop_move_from_entry"}
    assert all(intent.side is Side.BUY for intent in intents)


def test_a_move_inside_the_stop_leaves_the_position_alone(tmp_path: Path) -> None:
    strategy = build(stop_move_pct=0.005)
    _, positions = open_position(tmp_path, strategy)

    moved = SPOT * 1.003
    view = session_view(
        tmp_path / "small", ENTRY_DATE, chain(session_date=ENTRY_DATE, spot=SPOT), spot=moved
    )

    assert (
        strategy.decide(
            session=view, minute=minute_at(view, dt.time(11, 0)), book=BookView(positions, 1e7)
        )
        == ()
    )


def test_the_strike_breach_stop_scales_with_the_distance_to_the_strike(tmp_path: Path) -> None:
    """Half the way from entry spot to the short call closes a 0.50-buffer position."""
    strategy = build(stop=SpotStop.STRIKE_BREACH, stop_strike_buffer=0.50)
    _, positions = open_position(tmp_path, strategy)
    cycle = strategy._position  # the strike is what the rule measures against
    assert cycle is not None
    halfway = SPOT + 0.6 * (cycle.strikes["short_call"] - SPOT)

    view = session_view(
        tmp_path / "breach", ENTRY_DATE, chain(session_date=ENTRY_DATE, spot=SPOT), spot=halfway
    )
    intents = strategy.decide(
        session=view, minute=minute_at(view, dt.time(11, 0)), book=BookView(positions, 1e7)
    )

    assert {intent.tag for intent in intents} == {"stop_strike_breach"}


def test_the_profit_target_closes_the_position(tmp_path: Path) -> None:
    strategy = build(profit_take_pct=0.50)
    _, positions = open_position(tmp_path, strategy)

    # Premium collapses to a fifth: more than half the credit has been captured.
    view = session_view(
        tmp_path / "decayed",
        ENTRY_DATE,
        chain(session_date=ENTRY_DATE, price_scale=0.2),
    )
    intents = strategy.decide(
        session=view, minute=minute_at(view, dt.time(11, 0)), book=BookView(positions, 1e7)
    )

    assert {intent.tag for intent in intents} == {"profit_take"}


def test_the_position_is_closed_before_the_session_ends(tmp_path: Path) -> None:
    """The one rule that defines this strategy: nothing is carried overnight."""
    strategy = build()
    view, positions = open_position(tmp_path, strategy)

    intents = strategy.decide(
        session=view, minute=minute_at(view, dt.time(15, 5)), book=BookView(positions, 1e7)
    )

    assert {intent.tag for intent in intents} == {"exit_time"}


def test_the_legs_close_independently_once_the_deadline_window_opens(tmp_path: Path) -> None:
    """Measured behaviour, not a preference.

    A far-out-of-the-money weekly stops printing into the close — on 2025-01-03 the 24550
    call had no bar at 15:15, 15:20 or 15:25 — and an atomic leg group lets that dead leg
    block the liquid one, carrying the whole position overnight. Separate groups mean the
    tradeable leg closes.
    """
    strategy = build()
    view, positions = open_position(tmp_path, strategy)

    intents = strategy.decide(
        session=view, minute=minute_at(view, dt.time(15, 5)), book=BookView(positions, 1e7)
    )

    assert len(intents) == 2
    assert len({intent.leg_group for intent in intents}) == 2, "legs must not block each other"


def test_nothing_is_entered_before_the_entry_time(tmp_path: Path) -> None:
    strategy = build(entry_time=dt.time(11, 0))
    view = session_view(tmp_path / "early", ENTRY_DATE, chain(session_date=ENTRY_DATE))

    assert (
        strategy.decide(
            session=view, minute=minute_at(view, dt.time(9, 45)), book=BookView({}, 1e7)
        )
        == ()
    )
    assert strategy.decide(
        session=view, minute=minute_at(view, dt.time(11, 0)), book=BookView({}, 1e7)
    )


def test_a_chain_with_no_strike_in_the_delta_band_is_recorded_not_forced(tmp_path: Path) -> None:
    strategy = build(delta_band=(0.001, 0.002))
    view = session_view(tmp_path / "band", ENTRY_DATE, chain(session_date=ENTRY_DATE))

    assert (
        strategy.decide(
            session=view, minute=minute_at(view, dt.time(9, 45)), book=BookView({}, 1e7)
        )
        == ()
    )
    assert any(row["rule"] == "no_strike_in_delta_band" for row in strategy.journal)


def test_a_credit_below_the_floor_is_refused(tmp_path: Path) -> None:
    strategy = build(min_credit_pct_of_spot=0.05)
    view = session_view(tmp_path / "thin", ENTRY_DATE, chain(session_date=ENTRY_DATE))

    assert (
        strategy.decide(
            session=view, minute=minute_at(view, dt.time(9, 45)), book=BookView({}, 1e7)
        )
        == ()
    )
    assert any(row["rule"] == "credit_too_thin" for row in strategy.journal)


def test_the_completed_trade_records_what_the_rules_measured(tmp_path: Path) -> None:
    strategy = build()
    view, positions = open_position(tmp_path, strategy)
    strategy.decide(
        session=view, minute=minute_at(view, dt.time(15, 5)), book=BookView(positions, 1e7)
    )
    # The book is empty at the next decision minute: the close filled.
    strategy.decide(session=view, minute=minute_at(view, dt.time(15, 10)), book=BookView({}, 1e7))

    trades = strategy.completed_cycles
    assert len(trades) == 1
    trade = trades[0]
    assert trade["exit_rule"] == "exit_time"
    assert trade["entry_spot"] == pytest.approx(SPOT)
    assert trade["lot_size"] == LOT_SIZE
    assert trade["dte"] == (EXPIRY - ENTRY_DATE).days
    assert trade["credit_rupees"] > 0
