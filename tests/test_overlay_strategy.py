"""Section 4's rules, each against a corpus built to trigger exactly it.

The fixture plays the exchange: it writes a full option chain priced by Black-Scholes at a
stated implied volatility, so the strike ST-6 selects is one whose delta is known in
advance and the credit ST-8 measures is one the test computed itself. Every assertion here
is about a rule in the requirements, named in the test's own name.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pandas as pd
import pytest
from tests.conftest import SyntheticContract, write_synthetic_session

from xman_research.backtest.costs import Side
from xman_research.backtest.engine import BookView, Position
from xman_research.backtest.market import SessionView
from xman_research.overlay.context import DailyContext
from xman_research.overlay.greeks import bs_price, year_fraction
from xman_research.overlay.sizing import CollateralAssumption, MarginPerLotModel
from xman_research.overlay.strategy import IndexOptionOverlay, OverlayParameters

ENTRY_DATE = dt.date(2025, 6, 20)  # Friday, six days before the Thursday expiry
EXPIRY = dt.date(2025, 6, 26)
SPOT = 24_000.0
LOT_SIZE = 65


def chain(
    *,
    session_date: dt.date,
    spot: float = SPOT,
    iv: float = 0.13,
    expiry: dt.date = EXPIRY,
    span: int = 1_200,
    step: int = 50,
    price_scale: float = 1.0,
) -> list[SyntheticContract]:
    """A full chain priced by Black-Scholes, so deltas and credits are known up front."""
    t_years = year_fraction(minute_hour=9.5, days_to_expiry=(expiry - session_date).days)
    contracts: list[SyntheticContract] = []
    for offset in range(-span, span + step, step):
        strike = float(spot + offset)
        for option_type in ("CE", "PE"):
            price = bs_price(
                option_type=option_type, spot=spot, strike=strike, t_years=t_years, iv=iv
            )
            contracts.append(
                SyntheticContract(
                    strike=strike,
                    option_type=option_type,
                    expiry=expiry,
                    close=round(max(price * price_scale, 0.05), 2),
                    iv=iv,
                )
            )
    return contracts


def empty_context() -> DailyContext:
    """A context with no history: every filter that needs one is skipped, not failed.

    That is the behaviour the strategy has against a short window, and holding it here
    keeps these tests about the rules they name rather than about the filters.
    """
    return DailyContext(
        pd.DataFrame(
            {"session_date": [], "open": [], "close": [], "atm_iv": [], "expiry": [], "dte": []}
        )
    )


def build_strategy(**kwargs) -> IndexOptionOverlay:
    defaults = {
        "context": empty_context(),
        "hedge_cash_reserve": 0.0,
        "params": OverlayParameters(min_credit_ratio=0.0010),
        "collateral": CollateralAssumption(portfolio_capital=10_000_000.0),
        "margin_model": MarginPerLotModel(include_expiry_day_elm=False),
        "wing_policy": "spec",
    }
    defaults.update(kwargs)
    return IndexOptionOverlay(**defaults)


def session_view(
    store_root: Path, session_date: dt.date, contracts, *, spot: float = SPOT
) -> SessionView:
    from xman_research.session_store import SessionStore

    write_synthetic_session(
        store_root, session_date, spot=spot, contracts=contracts, lot_size=LOT_SIZE
    )
    store = SessionStore(root=store_root, manifest_path=store_root / "no-manifest.sqlite")
    ref = store.resolve("NIFTY", session_date, session_date).sessions()[0]
    return SessionView.from_frame(
        session_date, "NIFTY", store.load_session(ref), store.load_refdata(ref)
    )


def first_minute(view: SessionView) -> dt.datetime:
    minute = view.minute_at_or_after(dt.time(9, 20))
    assert minute is not None
    return minute


def test_entry_sells_the_delta_target_strikes_and_buys_both_wings(tmp_path: Path) -> None:
    """ST-5, ST-6, ST-7, ST-22 and ST-38 in one shape: four legs, one atomic group."""
    view = session_view(tmp_path / "corpus", ENTRY_DATE, chain(session_date=ENTRY_DATE))
    strategy = build_strategy()

    intents = strategy.decide(
        session=view, minute=first_minute(view), book=BookView({}, 10_000_000.0)
    )

    assert len(intents) == 4
    assert len({intent.leg_group for intent in intents}) == 1
    sells = [i for i in intents if i.side is Side.SELL]
    buys = [i for i in intents if i.side is Side.BUY]
    assert len(sells) == 2 and len(buys) == 2
    entry = next(row for row in strategy.journal if row["outcome"] == "entered")
    for role, delta in entry["detail"]["deltas"].items():
        assert 0.10 <= delta <= 0.14, role
    # ST-7: each wing sits its own width beyond its short, on the correct side.
    strikes = entry["detail"]["strikes"]
    assert strikes["long_call"] > strikes["short_call"]
    assert strikes["long_put"] < strikes["short_put"]
    assert strikes["long_call"] - strikes["short_call"] == 350.0
    assert strikes["short_put"] - strikes["long_put"] == 350.0


def test_a_thin_credit_refuses_the_week_and_says_which_rule_did(tmp_path: Path) -> None:
    """ST-8, at the top of its allowed range, which this chain's credit cannot reach.

    The credit a 0.12-delta condor collects is 0.12-0.17% of notional in the real corpus,
    so 0.35% — the parameter register's maximum — is a gate nothing passes. That is the
    honest way to exercise the rule: at the *default* of 0.20% it would also almost never
    pass, which is the finding the study reports rather than a fixture quirk."""
    view = session_view(tmp_path / "corpus", ENTRY_DATE, chain(session_date=ENTRY_DATE))
    strategy = build_strategy(params=OverlayParameters(min_credit_ratio=0.0035))

    intents = strategy.decide(
        session=view, minute=first_minute(view), book=BookView({}, 10_000_000.0)
    )

    assert intents == ()
    rules = {row["rule"] for row in strategy.journal if row["outcome"] == "declined"}
    assert "ST-8_minimum_credit" in rules


def test_entry_outside_the_dte_window_does_not_happen(tmp_path: Path) -> None:
    """ST-3: DTE 2 is neither 5 nor 6, so nothing is opened and nothing is logged as a
    refusal either — the week simply is not an entry window."""
    session_date = dt.date(2025, 6, 24)
    view = session_view(tmp_path / "corpus", session_date, chain(session_date=session_date))
    strategy = build_strategy()

    assert (
        strategy.decide(session=view, minute=first_minute(view), book=BookView({}, 10_000_000.0))
        == ()
    )
    assert strategy.journal == ()


def _open_cycle(tmp_path: Path, strategy: IndexOptionOverlay) -> tuple[SessionView, dict]:
    view = session_view(tmp_path / "corpus", ENTRY_DATE, chain(session_date=ENTRY_DATE))
    intents = strategy.decide(
        session=view, minute=first_minute(view), book=BookView({}, 10_000_000.0)
    )
    assert intents, "fixture failed to open a position"
    positions = {}
    for intent in intents:
        contract = view.universe.by_symbol(intent.trading_symbol)
        assert contract is not None
        units = intent.lots * contract.lot_size
        bar = view.bar(intent.trading_symbol, first_minute(view))
        assert bar is not None
        positions[intent.trading_symbol] = Position(
            contract=contract,
            units=-units if intent.side is Side.SELL else units,
            last_mark=bar.close,
        )
    return view, positions


def test_the_profit_target_closes_the_whole_position(tmp_path: Path) -> None:
    """ST-17: premium collapses to a tenth, which is more than 60% of the credit."""
    strategy = build_strategy()
    _, positions = _open_cycle(tmp_path, strategy)

    later_date = dt.date(2025, 6, 23)
    view = session_view(
        tmp_path / "corpus2",
        later_date,
        chain(session_date=later_date, price_scale=0.1),
    )
    intents = strategy.decide(
        session=view, minute=first_minute(view), book=BookView(positions, 10_000_000.0)
    )

    assert len(intents) == 4
    assert {intent.tag for intent in intents} == {"ST-17_profit_target"}
    # ST-22: the shorts are bought back and the wings sold, never the other way round.
    for intent in intents:
        position = positions[intent.trading_symbol]
        assert intent.side is (Side.BUY if position.units < 0 else Side.SELL)


def test_the_weekly_stop_closes_the_whole_position(tmp_path: Path) -> None:
    """ST-19: premium quadruples, which is a loss beyond 1.5x the credit."""
    strategy = build_strategy()
    _, positions = _open_cycle(tmp_path, strategy)

    later_date = dt.date(2025, 6, 23)
    view = session_view(
        tmp_path / "corpus2", later_date, chain(session_date=ENTRY_DATE, price_scale=4.0)
    )
    intents = strategy.decide(
        session=view, minute=first_minute(view), book=BookView(positions, 10_000_000.0)
    )

    assert {intent.tag for intent in intents} == {"ST-19_weekly_stop"}


def test_the_position_is_closed_the_session_before_expiry(tmp_path: Path) -> None:
    """ST-4, which the requirements fix and forbid configuring."""
    strategy = build_strategy()
    _, positions = _open_cycle(tmp_path, strategy)

    day_before = dt.date(2025, 6, 25)
    view = session_view(tmp_path / "corpus2", day_before, chain(session_date=day_before))
    minute = view.minute_at_or_after(dt.time(15, 15))
    assert minute is not None

    intents = strategy.decide(session=view, minute=minute, book=BookView(positions, 10_000_000.0))

    assert {intent.tag for intent in intents} == {"ST-4_time_exit"}


def test_before_the_deadline_the_position_is_left_alone(tmp_path: Path) -> None:
    strategy = build_strategy()
    _, positions = _open_cycle(tmp_path, strategy)

    day_before = dt.date(2025, 6, 25)
    # Priced at the entry session's time to expiry: P&L is exactly zero, so no management
    # rule has anything to act on and only the deadline could close the position.
    view = session_view(tmp_path / "corpus2", day_before, chain(session_date=ENTRY_DATE))
    minute = view.minute_at_or_after(dt.time(11, 0))
    assert minute is not None

    assert (
        strategy.decide(session=view, minute=minute, book=BookView(positions, 10_000_000.0)) == ()
    )


def test_a_roll_does_not_move_the_basis_the_stop_is_measured_against(tmp_path: Path) -> None:
    """ST-19 against ST-20.

    The first version of this code folded the roll's cash flow into the entry credit. A
    roll that costs more than the credit then made ``1.5 x credit`` negative, and the stop
    fired on the next evaluation of a position that had just been adjusted *to keep it
    open*. The basis is fixed at entry and the adjustment is carried separately.
    """
    strategy = build_strategy()
    _, positions = _open_cycle(tmp_path, strategy)
    cycle = strategy._cycle
    assert cycle is not None
    credit_at_entry = cycle.entry_credit_per_unit

    view, intents = _touch_the_call_side(tmp_path, strategy, positions)

    assert intents, "the fixture did not trigger ST-20"
    assert {intent.tag for intent in intents} == {"ST-20_roll"}
    assert cycle.pending_roll is not None
    assert cycle.entry_credit_per_unit == credit_at_entry
    assert cycle.credit_rupees > 0

    # The book now shows the rolled structure, so the next decision minute commits it.
    rolled_positions = _book_from(view, intents, positions)
    strategy.decide(
        session=view, minute=first_minute(view), book=BookView(rolled_positions, 10_000_000.0)
    )

    assert cycle.rolled
    assert cycle.pending_roll is None
    assert cycle.entry_credit_per_unit == credit_at_entry
    assert cycle.adjustment_cost_per_unit != 0.0


def test_a_roll_the_market_refused_is_not_recorded_as_a_roll(tmp_path: Path) -> None:
    """ST-20 with the engine declining the group — the state must not move.

    The roll used to rewrite the cycle's legs at the moment the *intents were emitted*.
    The engine decides afterwards, so a roll that did not fill left the cycle describing
    legs the book had never held, and the next minute unwound an intact, never-rolled
    condor while recording it as rolled. Nothing here is committed until the book says so.
    """
    strategy = build_strategy()
    _, positions = _open_cycle(tmp_path, strategy)
    cycle = strategy._cycle
    assert cycle is not None
    original_legs = dict(cycle.legs)

    view, intents = _touch_the_call_side(tmp_path, strategy, positions)
    assert intents and cycle.pending_roll is not None

    # The group did not fill: the book still holds exactly what it held before.
    follow_up = strategy.decide(
        session=view, minute=first_minute(view), book=BookView(positions, 10_000_000.0)
    )

    assert not cycle.rolled
    assert cycle.legs == original_legs
    assert cycle.adjustment_cost_per_unit == 0.0
    assert any(row["rule"] == "ST-20_roll_not_filled" for row in strategy.journal)
    # The position is not unwound as a structure mismatch — it is intact, still tested, and
    # the rule is simply re-ordered at this minute.
    assert {intent.tag for intent in follow_up} <= {"ST-20_roll"}


def test_a_roll_that_would_sell_a_modelled_strike_is_refused(tmp_path: Path) -> None:
    """The guard that keeps a fabricated price off the short side of the book.

    The roll's new short sits one wing-width further out, which is where the modelled band
    begins. A bar with no implied volatility is a modelled bar; selling it would put a
    price this package invented on the leg that earns the premium.
    """
    strategy = build_strategy()
    _, positions = _open_cycle(tmp_path, strategy)
    cycle = strategy._cycle
    assert cycle is not None

    later_date = dt.date(2025, 6, 23)
    tested_spot = 24_400.0
    chain_without_far_iv = [
        SyntheticContract(
            strike=contract.strike,
            option_type=contract.option_type,
            expiry=contract.expiry,
            close=contract.close,
            iv=contract.iv if abs(contract.strike - tested_spot) <= 500 else float("nan"),
        )
        for contract in chain(session_date=ENTRY_DATE, spot=tested_spot)
    ]
    view = session_view(tmp_path / "corpus2", later_date, chain_without_far_iv, spot=tested_spot)
    intents = strategy.decide(
        session=view, minute=first_minute(view), book=BookView(positions, 10_000_000.0)
    )

    assert intents == ()
    assert cycle.pending_roll is None
    assert cycle.roll_unpriceable
    refusals = [row for row in strategy.journal if row["rule"] == "ST-20_roll_unavailable"]
    assert refusals and refusals[-1]["detail"]["reason"] == "modelled_short"


def test_the_deadline_is_the_last_session_before_expiry_not_the_day_before(
    tmp_path: Path,
) -> None:
    """ST-4 on the trading calendar rather than on calendar arithmetic.

    Expiry Thursday 2025-06-26 with the corpus holding no session on the Wednesday: the
    last session before expiry is Tuesday the 24th, three calendar days out. Keyed on
    ``days_left == 1`` no exit is ever attempted and the position reaches expiry morning —
    which is what nine cycles of the first five-year run did.
    """
    context = DailyContext(
        pd.DataFrame(
            {
                "session_date": [dt.date(2025, 6, 20), dt.date(2025, 6, 23), dt.date(2025, 6, 24)],
                "open": [SPOT] * 3,
                "close": [SPOT] * 3,
                "atm_iv": [0.13] * 3,
                "expiry": [EXPIRY] * 3,
                "dte": [6, 3, 2],
            }
        )
    )
    strategy = build_strategy(context=context)
    _, positions = _open_cycle(tmp_path, strategy)

    last_session = dt.date(2025, 6, 24)
    view = session_view(tmp_path / "corpus2", last_session, chain(session_date=ENTRY_DATE))
    minute = view.minute_at_or_after(dt.time(14, 30))
    assert minute is not None

    intents = strategy.decide(session=view, minute=minute, book=BookView(positions, 10_000_000.0))

    assert {intent.tag for intent in intents} == {"ST-4_time_exit"}


def _touch_the_call_side(tmp_path: Path, strategy: IndexOptionOverlay, positions):
    """Move spot 400 points at the short call, which takes it past the 0.28 roll trigger.

    The chain is priced at the *entry* session's time to expiry while the strategy measures
    delta at the later session's: that asymmetry is what a held position actually faces and
    it is what decides whether the trigger is reached.
    """
    later_date = dt.date(2025, 6, 23)
    tested_spot = 24_400.0
    view = session_view(
        tmp_path / "corpus2",
        later_date,
        chain(session_date=ENTRY_DATE, spot=tested_spot),
        spot=tested_spot,
    )
    intents = strategy.decide(
        session=view, minute=first_minute(view), book=BookView(positions, 10_000_000.0)
    )
    return view, intents


def _book_from(view: SessionView, intents, previous):
    """Apply a set of intents to a book, as the engine would if every leg filled."""
    positions = dict(previous)
    for intent in intents:
        contract = view.universe.by_symbol(intent.trading_symbol)
        assert contract is not None
        units = intent.lots * contract.lot_size
        signed = -units if intent.side is Side.SELL else units
        existing = positions.get(intent.trading_symbol)
        total = signed + (existing.units if existing else 0)
        bar = view.bar(intent.trading_symbol, first_minute(view))
        assert bar is not None
        if total == 0:
            positions.pop(intent.trading_symbol, None)
        else:
            positions[intent.trading_symbol] = Position(
                contract=contract, units=total, last_mark=bar.close
            )
    return positions


def test_the_position_size_is_taken_from_the_book_not_from_the_order(tmp_path: Path) -> None:
    """M2: the participation caps resize a group, and everything in rupees follows the fill.

    18% of entry legs in the first five-year run were resized, so a credit computed on the
    lots *ordered* overstated the gross premium by 27% and fed the report's capture and
    cost-ratio figures on units the book never held.
    """
    strategy = build_strategy()
    view, positions = _open_cycle(tmp_path, strategy)
    cycle = strategy._cycle
    assert cycle is not None
    ordered_lots = cycle.lots
    assert ordered_lots > 1
    credit_at_order = cycle.credit_rupees

    # The engine granted one lot on every leg instead of the size requested.
    capped = {
        symbol: Position(
            contract=position.contract,
            units=(-1 if position.units < 0 else 1) * position.contract.lot_size,
            last_mark=position.last_mark,
        )
        for symbol, position in positions.items()
    }
    strategy.decide(
        session=view, minute=first_minute(view), book=BookView(capped, 10_000_000.0)
    )

    assert cycle.lots == 1
    assert cycle.credit_rupees == pytest.approx(credit_at_order / ordered_lots)


def test_a_week_whose_entry_never_filled_is_not_spent(tmp_path: Path) -> None:
    """M6: the expiry is marked traded when the book holds the position, not when asked for."""
    strategy = build_strategy()
    view = session_view(tmp_path / "corpus", ENTRY_DATE, chain(session_date=ENTRY_DATE))
    minute = first_minute(view)

    first = strategy.decide(session=view, minute=minute, book=BookView({}, 10_000_000.0))
    assert first, "fixture failed to order an entry"

    # Nothing filled: the book is still empty at the next decision minute.
    later = view.minute_at_or_after(dt.time(9, 35))
    assert later is not None
    strategy.decide(session=view, minute=later, book=BookView({}, 10_000_000.0))
    retry = strategy.decide(session=view, minute=later, book=BookView({}, 10_000_000.0))

    assert retry, "the week was spent on an entry that never traded"
    closed = strategy.completed_cycles
    assert closed and closed[0]["exit_rule"] == "ST-39_entry_never_filled"
