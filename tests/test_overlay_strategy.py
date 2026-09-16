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
    open*. The basis is now fixed at entry and the adjustment is carried separately.
    """
    strategy = build_strategy()
    _, positions = _open_cycle(tmp_path, strategy)
    cycle = strategy._cycle
    assert cycle is not None
    credit_at_entry = cycle.entry_credit_per_unit

    # Spot runs 400 points at the call side. The short call's delta goes past the 0.28 roll
    # trigger while the position's loss stays inside the 1.5x stop, so ST-20 fires and
    # ST-19 does not — the only state in which this invariant can be observed at all. Note
    # the chain is priced at the *entry* session's time to expiry while the strategy
    # measures delta at the later session's: that is the real asymmetry of a held position
    # and it is what decides whether the trigger is reached.
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

    assert cycle.rolled, "the fixture did not actually trigger ST-20"
    assert {intent.tag for intent in intents} == {"ST-20_roll_close", "ST-20_roll_open"}
    assert cycle.entry_credit_per_unit == credit_at_entry
    assert cycle.credit_rupees > 0
    # The roll cost something, and that something is carried where it belongs.
    assert cycle.adjustment_cost_per_unit != 0.0
