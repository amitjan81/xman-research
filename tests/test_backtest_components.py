"""Settlement, participation caps, feasibility, fills, margin and the market view.

These are the pieces the engine composes. Each is tested against a fixture small enough
to check by eye, because a defect here is invisible in an aggregate P&L number.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from conftest import IST, SESSION_MINUTES, SESSION_OPEN
from xman_research.backtest.costs import Side
from xman_research.backtest.execution import (
    BarCloseFillModel,
    Feasibility,
    ParticipationLimits,
    apply_participation_caps,
)
from xman_research.backtest.margin import ShortLeg, SimplifiedMarginModel
from xman_research.backtest.market import Bar, Contract, OptionType, SessionView
from xman_research.backtest.settlement import (
    SETTLEMENT_RULES,
    SettlementWindowError,
    settlement_rule_for,
    settlement_value,
)
from xman_research.session_store import RefData

LOT = 65
EXPIRY = dt.date(2026, 6, 9)
STRIKE = 23_000.0
SYMBOL = "NIFTY-09Jun2026-23000-CE"


def _frame(session_date: dt.date, spot_by_index: dict[int, float], base: float) -> pd.DataFrame:
    first = dt.datetime.combine(session_date, SESSION_OPEN, tzinfo=IST)
    rows = []
    for index in range(SESSION_MINUTES):
        stamp = int((first + dt.timedelta(minutes=index)).timestamp() * 1_000_000)
        value = spot_by_index.get(index, base)
        rows.append(
            {
                "minute_ts": stamp,
                "symbol": "NIFTY",
                "open": value,
                "high": value,
                "low": value,
                "close": value,
                "iv": float("nan"),
                "oi": float("nan"),
                "volume": float("nan"),
                "spot": value,
            }
        )
    return pd.DataFrame(rows)


def _refdata(session_date: dt.date) -> RefData:
    return RefData(
        session_date=session_date,
        nfo_instruments=(
            {
                "TradingSymbol": SYMBOL,
                "LookupName": "NIFTY",
                "OptionType": OptionType.CALL,
                "StrikePrice": STRIKE,
                "ExpiryDate": EXPIRY.strftime("%d/%m/%Y"),
                "LotSize": LOT,
                "TickSize": 5.0,
            },
        ),
        underlier_instruments=(),
    )


def _session(session_date: dt.date, spot_by_index: dict[int, float], base: float) -> SessionView:
    return SessionView.from_frame(
        session_date, "NIFTY", _frame(session_date, spot_by_index, base), _refdata(session_date)
    )


# ------------------------------------------------------------------------- settlement


def test_settlement_averages_the_last_half_hour_and_not_the_close() -> None:
    """Index 345 is 15:00; the window is the 30 bars from there to 15:29 inclusive.

    The last half hour ramps 23,100 -> 23,129, so its mean is 23,114.5 while the closing
    print is 23,129. A backtester that settled at the close would be 14.5 points out on
    every expiry — one direction, every time, which is a bias rather than noise.
    """
    ramp = {345 + step: 23_100.0 + step for step in range(30)}
    session = _session(EXPIRY, ramp, base=23_000.0)

    settled = settlement_value(session)

    assert settled.bars_used == 30
    assert settled.value == pytest.approx(23_114.5)
    assert session.underlying_bars()[-1].close == 23_129.0


def test_a_short_settlement_window_is_refused_rather_than_averaged() -> None:
    """Eleven bars averaged under the name of thirty is a different statistic."""
    session = _session(EXPIRY, {}, base=23_000.0)
    frame = _frame(EXPIRY, {}, 23_000.0).head(SESSION_MINUTES - 25)
    truncated = SessionView.from_frame(EXPIRY, "NIFTY", frame, _refdata(EXPIRY))

    assert settlement_value(session).bars_used == 30
    with pytest.raises(SettlementWindowError, match="fewer than the 30"):
        settlement_value(truncated)


def test_the_rule_in_force_is_selected_by_date() -> None:
    """The acceptance criterion: expiry settles against the stored formula for that date."""
    before = settlement_rule_for(dt.date(2026, 6, 9))
    after = settlement_rule_for(dt.date(2026, 8, 3))

    assert before.method == "mean_of_underlying_minute_close_over_window"
    assert before.implemented
    assert after.method == "closing_auction_session_equilibrium_price"
    assert not after.implemented


def test_a_session_under_the_closing_auction_regime_refuses_to_settle() -> None:
    """NSE changed the statistic on 3 Aug 2026 and this corpus cannot compute the new one.

    Refusing is the whole value of a dated table. Silently applying the superseded rule
    would produce a number that looks like a settlement and is not one.
    """
    session = _session(dt.date(2026, 8, 4), {}, base=23_000.0)

    with pytest.raises(SettlementWindowError, match="closing_auction_session"):
        settlement_value(session)


def test_settlement_rules_are_ordered_and_dated() -> None:
    dates = [rule.effective_from for rule in SETTLEMENT_RULES]
    assert dates == sorted(dates)
    assert all(rule.source_url for rule in SETTLEMENT_RULES)


# ------------------------------------------------------- participation caps and fills


def _bar(volume: float, open_interest: float, close: float = 100.0) -> Bar:
    return Bar(
        symbol=SYMBOL,
        minute=dt.datetime(2026, 6, 9, 9, 20, tzinfo=IST),
        open=close,
        high=close,
        low=close,
        close=close,
        volume_units=volume,
        open_interest_units=open_interest,
        iv=0.13,
        spot=23_000.0,
    )


LIMITS = ParticipationLimits(max_pct_of_bar_volume=0.01, max_pct_of_open_interest=0.005)


def test_the_volume_cap_binds_and_the_resize_is_recorded() -> None:
    """1% of 65,000 traded units = 650 units = 10 lots. 20 requested, 10 granted."""
    verdict = apply_participation_caps(
        requested_lots=20, lot_size=LOT, bar=_bar(65_000.0, 100_000_000.0), limits=LIMITS
    )

    assert verdict.verdict is Feasibility.RESIZED
    assert verdict.granted_lots == 10
    assert verdict.requested_lots == 20
    assert verdict.binding_cap == "volume"
    assert "10 allowed" in verdict.reason


def test_the_open_interest_cap_binds_independently_of_volume() -> None:
    """A frantic minute in a tiny contract: volume allows plenty, open interest does not.

    0.5% of 26,000 open units = 130 units = 2 lots, against a volume cap of 100 lots.
    """
    verdict = apply_participation_caps(
        requested_lots=20, lot_size=LOT, bar=_bar(650_000.0, 26_000.0), limits=LIMITS
    )

    assert verdict.verdict is Feasibility.RESIZED
    assert verdict.granted_lots == 2
    assert verdict.binding_cap == "open_interest"


def test_a_cap_below_one_lot_is_a_refusal_not_a_rounding() -> None:
    verdict = apply_participation_caps(
        requested_lots=1, lot_size=LOT, bar=_bar(1_000.0, 1_000.0), limits=LIMITS
    )

    assert verdict.verdict is Feasibility.CAPPED_TO_ZERO
    assert verdict.granted_lots == 0
    assert not verdict.is_fillable


def test_no_bar_and_no_volume_are_different_verdicts() -> None:
    """One says the instrument printed nothing; the other says it printed a dead minute.

    Collapsing them would lose the distinction between a capture-scope gap and a real
    liquidity fact, which is exactly the distinction spec §3 C1 is about.
    """
    absent = apply_participation_caps(requested_lots=1, lot_size=LOT, bar=None, limits=LIMITS)
    dead = apply_participation_caps(
        requested_lots=1, lot_size=LOT, bar=_bar(0.0, 500_000.0), limits=LIMITS
    )

    assert absent.verdict is Feasibility.NO_BAR
    assert dead.verdict is Feasibility.NO_LIQUIDITY


def test_a_full_size_request_inside_both_caps_is_fillable() -> None:
    verdict = apply_participation_caps(
        requested_lots=1, lot_size=LOT, bar=_bar(650_000.0, 6_500_000.0), limits=LIMITS
    )

    assert verdict.verdict is Feasibility.FILLABLE
    assert verdict.granted_lots == 1
    assert verdict.binding_cap is None


def test_slippage_is_always_adverse_in_both_directions() -> None:
    contract = Contract(
        trading_symbol=SYMBOL,
        underlying="NIFTY",
        expiry=EXPIRY,
        strike=STRIKE,
        option_type=OptionType.CALL,
        lot_size=LOT,
        tick_size=5.0,
    )
    model = BarCloseFillModel(slippage_bps=100.0)
    bar = _bar(650_000.0, 6_500_000.0, close=100.0)

    assert model.fill_price(bar=bar, side=Side.BUY, contract=contract, lots=1) == pytest.approx(101)
    assert model.fill_price(bar=bar, side=Side.SELL, contract=contract, lots=1) == pytest.approx(99)
    assert BarCloseFillModel().slippage_bps == 0.0


def test_size_does_not_move_the_price_because_the_caps_bound_it_instead() -> None:
    contract = Contract(
        trading_symbol=SYMBOL,
        underlying="NIFTY",
        expiry=EXPIRY,
        strike=STRIKE,
        option_type=OptionType.CALL,
        lot_size=LOT,
        tick_size=5.0,
    )
    model = BarCloseFillModel(slippage_bps=10.0)
    bar = _bar(650_000.0, 6_500_000.0)

    small = model.fill_price(bar=bar, side=Side.BUY, contract=contract, lots=1)
    large = model.fill_price(bar=bar, side=Side.BUY, contract=contract, lots=100)

    assert small == large


# ------------------------------------------------------------------------------ margin


def test_margin_charges_short_legs_and_ignores_longs() -> None:
    """1 lot short at 23,000: notional 65 x 23,000 = 1,495,000.

    span     10% = 149,500
    exposure  2% =  29,900
    total        = 179,400
    """
    model = SimplifiedMarginModel()
    requirement = model.requirement([ShortLeg(quantity_units=LOT, underlying_price=23_000.0)])

    assert requirement.span_component == pytest.approx(149_500.0)
    assert requirement.exposure_component == pytest.approx(29_900.0)
    assert requirement.expiry_day_elm_component == 0.0
    assert requirement.total == pytest.approx(179_400.0)
    assert model.requirement([]).total == 0.0


def test_the_expiry_day_elm_applies_only_on_the_expiry_session() -> None:
    """SEBI's 20 Nov 2024 add-on: 2% of notional on short index options on expiry day.

    2% x 1,495,000 = 29,900 on top of the 179,400 above.
    """
    model = SimplifiedMarginModel()
    expiring = model.requirement(
        [ShortLeg(quantity_units=LOT, underlying_price=23_000.0, expires_today=True)]
    )

    assert expiring.expiry_day_elm_component == pytest.approx(29_900.0)
    assert expiring.total == pytest.approx(209_300.0)


def test_the_multiplier_scales_the_whole_requirement_for_the_sensitivity_sweep() -> None:
    """The margin figure is a guess, so the honest use is a sweep. This is the knob."""
    legs = [ShortLeg(quantity_units=LOT, underlying_price=23_000.0)]
    base = SimplifiedMarginModel().requirement(legs).total
    doubled = SimplifiedMarginModel(multiplier=2.0).requirement(legs).total

    assert doubled == pytest.approx(2 * base)


def test_margin_does_not_net_a_straddle_and_says_so() -> None:
    """Two short legs cost twice one short leg here, and SPAN would not charge that.

    Pinned as a *known* overstatement rather than left implicit: it is the direction that
    understates return on capital, which is the conservative direction for H1.
    """
    model = SimplifiedMarginModel()
    one = model.requirement([ShortLeg(quantity_units=LOT, underlying_price=23_000.0)])
    two = model.requirement(
        [
            ShortLeg(quantity_units=LOT, underlying_price=23_000.0),
            ShortLeg(quantity_units=LOT, underlying_price=23_000.0),
        ]
    )

    assert two.total == pytest.approx(2 * one.total)
    assert "no portfolio netting" in model.assumptions


# ------------------------------------------------------------------------ market view


def test_atm_selection_breaks_ties_to_the_lower_strike() -> None:
    """Spot exactly between two listed strikes is not hypothetical on a round index."""
    session = _session(EXPIRY, {}, base=23_000.0)
    universe = session.universe

    assert universe.atm_strike(23_000.0, EXPIRY) == 23_000.0

    from xman_research.backtest.market import ContractUniverse

    contracts = [
        Contract(f"A-{strike}", "NIFTY", EXPIRY, strike, OptionType.CALL, LOT, 5.0)
        for strike in (22_950.0, 23_050.0)
    ]
    two_strikes = ContractUniverse("NIFTY", contracts)

    assert two_strikes.atm_strike(23_000.0, EXPIRY) == 22_950.0


def test_intrinsic_is_zero_out_of_the_money_for_both_option_types() -> None:
    call = Contract("C", "NIFTY", EXPIRY, 23_000.0, OptionType.CALL, LOT, 5.0)
    put = Contract("P", "NIFTY", EXPIRY, 23_000.0, OptionType.PUT, LOT, 5.0)

    assert call.intrinsic(23_100.0) == pytest.approx(100.0)
    assert call.intrinsic(22_900.0) == 0.0
    assert put.intrinsic(22_900.0) == pytest.approx(100.0)
    assert put.intrinsic(23_100.0) == 0.0


def test_expiry_and_lot_size_are_read_from_refdata_not_parsed_from_the_symbol() -> None:
    """The symbol is an opaque token; every attribute comes from the instrument master."""
    session = _session(EXPIRY, {}, base=23_000.0)
    contract = session.universe.by_symbol(SYMBOL)

    assert contract is not None
    assert contract.expiry == EXPIRY
    assert contract.lot_size == LOT
    assert contract.strike == STRIKE


def test_the_decision_minute_resolves_to_the_first_bar_at_or_after_it() -> None:
    session = _session(EXPIRY, {}, base=23_000.0)

    minute = session.minute_at_or_after(dt.time(9, 20))
    assert minute is not None
    assert minute.hour == 9 and minute.minute == 20
    assert session.minute_at_or_after(dt.time(23, 0)) is None
