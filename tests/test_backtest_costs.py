"""The statutory stack, against values computed by hand rather than by the code.

Every expected number below is written out as arithmetic in the comment above it. That is
the whole point of the exercise: a test that asserts ``charge(trade).total == charge(
trade).total`` passes forever while the rate table is wrong, and a rate table that is
wrong scales every result the platform will ever produce by a constant that looks like
alpha.
"""

from __future__ import annotations

import datetime as dt

import pytest

from xman_research.backtest.costs import (
    EXCHANGE_TRANSACTION_CHARGE,
    EXERCISE_STT_RULE,
    STT_ON_SELL_PREMIUM,
    ChargeableTrade,
    Confidence,
    CostBreakdown,
    FlatPerOrderBrokerage,
    RateSchedule,
    Side,
    StatutoryCostStack,
    StatutoryRate,
    TradeKind,
    extrapolation_message,
)

LOT = 65
PREMIUM = 100.0
UNITS = LOT  # one lot
TURNOVER = PREMIUM * UNITS  # 6,500.00


@pytest.fixture
def stack() -> StatutoryCostStack:
    return StatutoryCostStack(brokerage=FlatPerOrderBrokerage(rupees_per_order=20.0))


EXTRAPOLATED_STT = "costs.rate_extrapolated:stt.sell_option_premium"


def _extrapolated(costs: CostBreakdown) -> list[str]:
    return sorted(
        name for name in costs.unverified_components if name.startswith("costs.rate_extrapolated:")
    )


def _sell(trade_date: dt.date) -> ChargeableTrade:
    return ChargeableTrade(
        trade_date=trade_date,
        kind=TradeKind.TRADE,
        side=Side.SELL,
        quantity_units=UNITS,
        price=PREMIUM,
    )


def test_a_sell_before_1_oct_2024_is_charged_the_latest_rate_and_stamped(
    stack: StatutoryCostStack,
) -> None:
    """This date used to refuse, and the refusal was dropping 772 of 1,233 sessions.

    Owner decision of 2026-08-20: use the data. The rate charged is the schedule's
    **latest** entry (0.15%), not its earliest (0.1%) and not a guessed historical value —
    and the session is stamped so the verdict says which way to distrust it.
    """
    costs = stack.charge(_sell(dt.date(2024, 9, 30)))

    assert costs.stt == pytest.approx(0.0015 * UNITS * PREMIUM)
    assert EXTRAPOLATED_STT in costs.unverified_components
    # Only that one schedule. 2024-09-30 sits inside every other schedule's coverage, so
    # nothing else may claim to have been extrapolated — a stamp that over-reports is as
    # useless as one that under-reports.
    assert _extrapolated(costs) == [EXTRAPOLATED_STT]
    # The exchange charge is the genuine PRE-2024 rate. Filling an unknown end must never
    # overwrite a known middle; this is the assertion that catches a flattened schedule.
    assert costs.exchange_transaction_charge == pytest.approx(0.0005 * UNITS * PREMIUM)


@pytest.mark.parametrize(
    ("on", "expected_stt_rate"),
    [
        (dt.date(2024, 10, 1), 0.001),
        (dt.date(2026, 3, 31), 0.001),
        (dt.date(2026, 4, 1), 0.0015),
    ],
)
def test_extrapolation_does_not_flatten_the_dated_history_we_do_have(
    stack: StatutoryCostStack, on: dt.date, expected_stt_rate: float
) -> None:
    """Both sides of the 1 Apr 2026 STT change still apply on their own dates, unstamped."""
    costs = stack.charge(_sell(on))

    assert costs.stt == pytest.approx(expected_stt_rate * UNITS * PREMIUM)
    assert _extrapolated(costs) == []


def test_every_date_across_the_five_year_corpus_window_prices_without_refusing(
    stack: StatutoryCostStack,
) -> None:
    """The owner's actual requirement: five years of data, all of it costable.

    Walks every calendar date from the first captured session to past the last one, rather
    than sampling — a schedule boundary is exactly the kind of thing a sample steps over.
    """
    on, end = dt.date(2021, 6, 1), dt.date(2026, 12, 31)
    priced = 0
    while on <= end:
        costs = stack.charge(_sell(on))
        assert costs.total > 0.0
        priced += 1
        on += dt.timedelta(days=1)

    assert priced == 2040


def test_sell_on_the_day_the_1_oct_2024_change_takes_effect(stack: StatutoryCostStack) -> None:
    """The same trade one day later, at the amended rates.

    STT       0.1%     x 6,500 = 6.50
    exchange  0.03503% x 6,500 = 2.276950
    SEBI      0.0001%  x 6,500 = 0.0065
    brokerage                  = 20
    GST       18% x (20 + 2.276950 + 0.0065) = 18% x 22.28345 = 4.011021
    total                                    = 32.794471

    The rate change is effective ON 1 October, not after it — a schedule that treated
    ``effective_from`` as exclusive would charge the old rate for a whole day and nothing
    downstream would notice.
    """
    costs = stack.charge(_sell(dt.date(2024, 10, 1)))

    assert costs.stt == pytest.approx(6.50)
    assert costs.exchange_transaction_charge == pytest.approx(2.276950)
    assert costs.gst == pytest.approx(4.011021)
    assert costs.total == pytest.approx(32.794471)


def test_the_stt_change_is_a_step_not_a_ramp(stack: StatutoryCostStack) -> None:
    """A step, asserted at the boundary the table can still defend.

    The 1 Oct 2024 step used to be measured against the deleted 0.0625% entry. The
    1 Apr 2026 boundary is measured instead: both sides of it are CORROBORATED, both are
    inside the corpus, and it makes the same point about a dated schedule -- the rate
    changes on a date rather than easing across one.
    """
    before = stack.charge(_sell(dt.date(2026, 3, 31))).stt
    after = stack.charge(_sell(dt.date(2026, 4, 1))).stt

    assert after / before == pytest.approx(0.0015 / 0.001)


def test_the_1_april_2026_stt_rise_is_charged_too(stack: StatutoryCostStack) -> None:
    """The corpus straddles this one, so it is not a hypothetical.

    STT 0.15% x 6,500 = 9.75
    """
    assert stack.charge(_sell(dt.date(2026, 3, 31))).stt == pytest.approx(6.50)
    assert stack.charge(_sell(dt.date(2026, 4, 1))).stt == pytest.approx(9.75)


def test_a_buy_pays_stamp_duty_and_no_stt(stack: StatutoryCostStack) -> None:
    """STT on option premium is sell-side; stamp duty is buy-side. Neither is symmetric.

    stamp 0.003% x 6,500 = 0.195
    """
    costs = stack.charge(
        ChargeableTrade(
            trade_date=dt.date(2026, 1, 6),
            kind=TradeKind.TRADE,
            side=Side.BUY,
            quantity_units=UNITS,
            price=PREMIUM,
        )
    )

    assert costs.stt == 0.0
    assert costs.stamp_duty == pytest.approx(0.195)


def test_gst_is_not_charged_on_stt_or_stamp_duty(stack: StatutoryCostStack) -> None:
    """GST rides on the service components only, and the ratio proves it exactly."""
    costs = stack.charge(_sell(dt.date(2026, 1, 6)))
    service_charges = costs.brokerage + costs.exchange_transaction_charge + costs.sebi_turnover_fee

    assert costs.gst == pytest.approx(0.18 * service_charges)
    assert costs.gst < 0.18 * costs.total


# ----------------------------------------------------------------- expiry settlement

SETTLE_VALUE = 23_000.0
INTRINSIC = 50.0


def _settlement(side: Side) -> ChargeableTrade:
    return ChargeableTrade(
        trade_date=dt.date(2026, 6, 9),
        kind=TradeKind.SETTLEMENT,
        side=side,
        quantity_units=UNITS,
        price=INTRINSIC,
        notional_price=SETTLE_VALUE,
    )


def test_the_long_holder_pays_exercise_stt_on_intrinsic(stack: StatutoryCostStack) -> None:
    """A settled long, on 2026-06-09, when the exercise rate is 0.15%.

    exercise STT 0.15%  x 50 x 65        = 4.875
    SEBI fee     0.0001% x 23,000 x 65   = 1.49500   (notional base, not intrinsic)
    GST          18% x 1.49500           = 0.269100
    premium STT                          = 0 (this is not a sale of premium)
    total                                = 6.639100
    """
    costs = stack.charge(_settlement(Side.SELL))

    assert costs.stt_on_exercise == pytest.approx(4.875)
    assert costs.stt == 0.0
    assert costs.sebi_turnover_fee == pytest.approx(1.49500)
    assert costs.exchange_transaction_charge == 0.0
    assert costs.stamp_duty == 0.0
    assert costs.brokerage == 0.0
    assert costs.total == pytest.approx(6.639100)


def test_the_assigned_short_pays_no_exercise_stt(stack: StatutoryCostStack) -> None:
    """The attribution that flatters H1, asserted in the direction that would catch it.

    A short assigned at expiry pays the SEBI fee on notional and nothing else. If this
    ever starts charging exercise STT, a short-variance backtest gets *more* expensive,
    which is the safe direction; if the long ever stops paying it, every long-option
    hypothesis gets cheaper, which is not. Both are pinned.
    """
    costs = stack.charge(_settlement(Side.BUY))

    assert costs.stt_on_exercise == 0.0
    assert costs.sebi_turnover_fee == pytest.approx(1.49500)
    assert costs.total == pytest.approx(1.495 + 0.18 * 1.495)
    assert EXERCISE_STT_RULE.payer is Side.SELL


def test_the_exercise_stt_base_is_intrinsic_not_premium(stack: StatutoryCostStack) -> None:
    """Doubling the premium changes nothing; doubling intrinsic doubles the charge."""
    doubled_intrinsic = stack.charge(
        ChargeableTrade(
            trade_date=dt.date(2026, 6, 9),
            kind=TradeKind.SETTLEMENT,
            side=Side.SELL,
            quantity_units=UNITS,
            price=INTRINSIC * 2,
            notional_price=SETTLE_VALUE,
        )
    )

    assert doubled_intrinsic.stt_on_exercise == pytest.approx(2 * 4.875)


def test_a_settlement_without_a_notional_price_is_refused() -> None:
    """The SEBI fee's base at settlement is notional; defaulting it would be wrong twice."""
    with pytest.raises(ValueError, match="notional_price"):
        ChargeableTrade(
            trade_date=dt.date(2026, 6, 9),
            kind=TradeKind.SETTLEMENT,
            side=Side.SELL,
            quantity_units=UNITS,
            price=INTRINSIC,
        )


def test_an_out_of_the_money_settlement_costs_nothing_but_the_notional_fee(
    stack: StatutoryCostStack,
) -> None:
    """Zero intrinsic means zero exercise STT — an OTM option is not exercised."""
    costs = stack.charge(
        ChargeableTrade(
            trade_date=dt.date(2026, 6, 9),
            kind=TradeKind.SETTLEMENT,
            side=Side.SELL,
            quantity_units=UNITS,
            price=0.0,
            notional_price=SETTLE_VALUE,
        )
    )

    assert costs.stt_on_exercise == 0.0


# ------------------------------------------------------------------- schedule mechanics


def test_a_date_before_the_schedule_starts_takes_the_latest_entry() -> None:
    schedule = RateSchedule(
        name="test.schedule",
        entries=(
            StatutoryRate(
                effective_from=dt.date(2020, 1, 1),
                rate=0.01,
                base="turnover",
                side="both",
                source="fixture",
                source_url="",
                confidence=Confidence.CONFIRMED,
            ),
        ),
    )

    assert schedule.rate_at(dt.date(2020, 1, 1)) == 0.01
    assert schedule.lookup(dt.date(2020, 1, 1)).extrapolated is False
    assert schedule.lookup(dt.date(2020, 1, 1)).stamp is None

    before = schedule.lookup(dt.date(2019, 12, 31))
    assert before.rate == 0.01
    assert before.extrapolated is True
    assert before.stamp == "costs.rate_extrapolated:test.schedule"


def test_extrapolation_reaches_for_the_latest_entry_not_the_nearest_one() -> None:
    """The distinguishing test: with two entries, a pre-schedule date takes the LATER one.

    A nearest-entry clamp would return 0.01 here and every other assertion in this file
    would still pass, so this is the only test that pins the owner's "latest value" rule.
    """
    schedule = RateSchedule(
        name="test.two_entry",
        entries=(
            StatutoryRate(
                effective_from=dt.date(2020, 1, 1),
                rate=0.01,
                base="turnover",
                side="both",
                source="fixture",
                source_url="",
                confidence=Confidence.CONFIRMED,
            ),
            StatutoryRate(
                effective_from=dt.date(2022, 1, 1),
                rate=0.03,
                base="turnover",
                side="both",
                source="fixture",
                source_url="",
                confidence=Confidence.CONFIRMED,
            ),
        ),
    )

    assert schedule.lookup(dt.date(2019, 12, 31)).rate == 0.03
    assert schedule.rate_at(dt.date(2021, 6, 1)) == 0.01
    assert schedule.rate_at(dt.date(2030, 1, 1)) == 0.03
    # A date past the last entry is NOT extrapolation: a rate is in force until amended.
    assert schedule.lookup(dt.date(2030, 1, 1)).extrapolated is False


def test_the_extrapolation_message_states_both_directions_of_the_error() -> None:
    """The stamp points at this text, and half of it would be misleading on its own."""
    message = extrapolation_message(STT_ON_SELL_PREMIUM)

    assert "OVERSTATES" in message
    assert "conservative" in message
    assert "SUPPRESS" in message


def test_the_extrapolation_message_does_not_claim_every_schedule_overcharges() -> None:
    """The NSE transaction charge FELL in 2024, so extrapolating it UNDERcharges.

    An earlier draft of ``extrapolation_message`` asserted module-wide that these charges
    "have only ever been revised upward". That is false for this schedule — 0.05% became
    0.03503% on 1 Oct 2024 — and a stamp telling a reader they were overcharged when they
    were undercharged is worse than no stamp, because it invites exactly the wrong
    correction. The direction must be derived from the schedule, never asserted globally.
    """
    assert (
        EXCHANGE_TRANSACTION_CHARGE.entries[-1].rate < EXCHANGE_TRANSACTION_CHARGE.entries[0].rate
    )
    message = extrapolation_message(EXCHANGE_TRANSACTION_CHARGE)

    assert "DOWNWARD" in message
    assert "NOT conservative" in message
    assert "OVERSTATES" not in message
    assert "flatters" in message


def test_unverified_rates_are_reported_on_every_breakdown(stack: StatutoryCostStack) -> None:
    """A number computed with a guessed rate must say so, all the way to the result."""
    costs = stack.charge(_sell(dt.date(2026, 1, 6)))

    assert not costs.is_fully_verified
    # The tier travels with the name, so C6 can tell a CORROBORATED rate from a guess.
    assert "stt.sell_option_premium:corroborated" in costs.unverified_components


def test_confirmed_rates_do_not_raise_the_flag() -> None:
    """The flag has to be capable of being clean, or it means nothing when it is dirty."""
    confirmed = RateSchedule(
        name="confirmed.everything",
        entries=(
            StatutoryRate(
                effective_from=dt.date(2020, 1, 1),
                rate=0.0,
                base="turnover",
                side="both",
                source="fixture",
                source_url="",
                confidence=Confidence.CONFIRMED,
            ),
        ),
    )
    stack = StatutoryCostStack(
        brokerage=FlatPerOrderBrokerage(rupees_per_order=0.0),
        stt_sell_premium=confirmed,
        stt_exercise=confirmed,
        exchange_charge=confirmed,
        sebi_fee=confirmed,
        stamp_duty=confirmed,
        gst=confirmed,
    )

    assert stack.charge(_sell(dt.date(2026, 1, 6))).is_fully_verified


def test_stamp_duty_is_confirmed_and_stt_is_not() -> None:
    """The confidence field is data, and the report quotes it; pin what it currently says."""
    from xman_research.backtest.costs import STAMP_DUTY

    assert STAMP_DUTY.at(dt.date(2026, 1, 6)).confidence is Confidence.CONFIRMED
    assert STT_ON_SELL_PREMIUM.at(dt.date(2026, 1, 6)).confidence is Confidence.CORROBORATED


def test_totals_add_component_by_component(stack: StatutoryCostStack) -> None:
    first = stack.charge(_sell(dt.date(2026, 1, 6)))
    second = stack.charge(_sell(dt.date(2026, 4, 1)))
    combined = stack.charge_all([_sell(dt.date(2026, 1, 6)), _sell(dt.date(2026, 4, 1))])

    assert combined.stt == pytest.approx(first.stt + second.stt)
    assert combined.total == pytest.approx(first.total + second.total)


def test_brokerage_is_per_order_and_a_resize_does_not_multiply_it() -> None:
    """One (symbol, side, decision) is one order however many lots survive the caps."""
    brokerage = FlatPerOrderBrokerage(rupees_per_order=20.0)
    one_lot = ChargeableTrade(
        trade_date=dt.date(2026, 1, 6),
        kind=TradeKind.TRADE,
        side=Side.SELL,
        quantity_units=LOT,
        price=PREMIUM,
    )
    ten_lots = ChargeableTrade(
        trade_date=dt.date(2026, 1, 6),
        kind=TradeKind.TRADE,
        side=Side.SELL,
        quantity_units=LOT * 10,
        price=PREMIUM,
    )

    assert brokerage.charge(one_lot) == 20.0
    assert brokerage.charge(ten_lots) == 20.0
