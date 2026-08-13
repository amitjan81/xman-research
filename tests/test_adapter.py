"""The C5 -> C6 adapter, tested against the five ways it silently flatters a run.

Every assertion here corresponds to a numbered correction in
:mod:`xman_research.adapter`'s docstring, and every one of them was a real defect found by
comparing the adapter's output against what C5 itself reports about the same run. They are
tested on constructed results rather than the corpus so they run everywhere: the point is
the arithmetic of the seam, not the P&L.
"""

from __future__ import annotations

import datetime as dt
import tempfile
from pathlib import Path

import pytest

from xman_research import (
    DataWindow,
    HypothesisRecord,
    ManualClock,
    StaticCodeVersion,
    TrialLog,
)
from xman_research.adapter import (
    costs_by_date,
    evidence_from_result,
    feasibility_from_result,
    logged_run_at,
)
from xman_research.backtest import (
    BacktestResult,
    CostBreakdown,
    DailyRecord,
    Feasibility,
    FeasibilityVerdict,
    FillRecord,
    MarginRequirement,
    SettlementRecord,
    Side,
)
from xman_research.validation.series import UNIFORM_COST_STAMP, RunEvidence

STARTING_CASH = 1_000_000.0
DAY_ONE = dt.date(2026, 2, 2)
DAY_TWO = dt.date(2026, 2, 3)
DAY_THREE = dt.date(2026, 2, 4)


def costs(total: float) -> CostBreakdown:
    """A breakdown whose components sum to ``total``, split so no single field carries it."""
    share = total / 4.0
    return CostBreakdown(
        brokerage=share,
        exchange_transaction_charge=share,
        sebi_turnover_fee=0.0,
        stt=share,
        stt_on_exercise=0.0,
        stamp_duty=share,
        gst=0.0,
    )


def verdict(kind: Feasibility, *, granted: int = 1) -> FeasibilityVerdict:
    return FeasibilityVerdict(
        verdict=kind,
        requested_lots=1,
        granted_lots=granted,
        binding_cap=None,
        observed_volume_units=10_000.0,
        observed_open_interest_units=50_000.0,
        reason="constructed for the adapter tests",
    )


def fill(day: dt.date, *, cost: float, kind: Feasibility = Feasibility.FILLABLE) -> FillRecord:
    granted = 0 if kind in {Feasibility.NO_BAR, Feasibility.GROUP_INCOMPLETE} else 1
    return FillRecord(
        session_date=day,
        minute=dt.datetime.combine(day, dt.time(9, 20), tzinfo=dt.UTC),
        trading_symbol="NIFTY26FEB24000CE",
        side=Side.SELL,
        tag="entry",
        requested_lots=1,
        filled_lots=granted,
        lot_size=65,
        price=200.0,
        gross_value=13_000.0,
        costs=costs(cost),
        feasibility=verdict(kind, granted=granted),
    )


def settlement(day: dt.date, *, cost: float) -> SettlementRecord:
    return SettlementRecord(
        session_date=day,
        trading_symbol="NIFTY26FEB24000CE",
        units=65,
        settlement_value=100.0,
        intrinsic_per_unit=100.0,
        cash_flow=-6_500.0,
        costs=costs(cost),
        feasibility=verdict(Feasibility.SETTLED),
        rule_effective_from=dt.date(2025, 1, 1),
    )


def daily(day: dt.date, equity: float, *, stale: int = 0) -> DailyRecord:
    return DailyRecord(
        session_date=day,
        cash=equity,
        open_position_value=0.0,
        equity=equity,
        margin=MarginRequirement(
            span_component=100_000.0,
            exposure_component=50_000.0,
            expiry_day_elm_component=0.0,
            short_legs=2,
            notional=1_560_000.0,
        ),
        open_positions=2,
        stale_marks=stale,
    )


def build_result(
    *,
    fills: tuple[FillRecord, ...] = (),
    settlements: tuple[SettlementRecord, ...] = (),
    days: tuple[DailyRecord, ...] = (),
    trial_id: str = "t_constructed",
    unverified: tuple[str, ...] = ("epoch_table.secondary_sourced",),
) -> BacktestResult:
    total = sum(record.costs.total for record in fills) + sum(
        record.costs.total for record in settlements
    )
    return BacktestResult(
        trial_id=trial_id,
        underlying="NIFTY",
        start=days[0].session_date if days else DAY_ONE,
        end=days[-1].session_date if days else DAY_THREE,
        sessions_run=len(days),
        fills=fills,
        settlements=settlements,
        daily=days,
        total_costs=costs(total),
        config_provenance={"starting_cash": STARTING_CASH, "gap_reason": None},
        data_provenance={"underlying": "NIFTY", "missing": [], "manifest_available": False},
        strategy_name="short_atm_straddle",
        strategy_parameters={"target_notional": 1_495_000.0, "min_days_to_expiry": 1},
        unverified_inputs=unverified,
    )


def full_result() -> BacktestResult:
    return build_result(
        fills=(
            fill(DAY_ONE, cost=400.0),
            fill(DAY_ONE, cost=400.0),
            fill(DAY_TWO, cost=100.0, kind=Feasibility.GROUP_INCOMPLETE),
        ),
        settlements=(settlement(DAY_THREE, cost=1_100.0),),
        days=(
            daily(DAY_ONE, 1_000_000.0),
            daily(DAY_TWO, 1_010_000.0, stale=1),
            daily(DAY_THREE, 1_005_000.0),
        ),
    )


def adapt(result: BacktestResult, *, label: str) -> RunEvidence:
    """Adapt against a log that knows the hypothesis but holds no row for this trial.

    An unregistered hypothesis raises rather than yielding ``None``: a hypothesis id the
    log has never seen is a caller error, not a missing row, and the adapter lets that
    through rather than converting it into a silently absent timestamp.
    """
    log, record = logged_hypothesis()
    return evidence_from_result(result, session=log, hypothesis_id=record.id, label=label)


# --------------------------------------------------------------------------- costs by date


def test_costs_are_bucketed_on_the_session_that_paid_them() -> None:
    buckets = costs_by_date(full_result())

    assert buckets == pytest.approx({DAY_ONE: 800.0, DAY_TWO: 100.0, DAY_THREE: 1_100.0})


def test_settlement_costs_are_not_dropped() -> None:
    """The single largest component for a short book held to expiry lands on a settlement.

    A bucket built from fills alone would omit the STT on exercise entirely and report a
    cost-breakeven multiple several times too generous — the headline number of the MVP.
    """
    result = build_result(
        settlements=(settlement(DAY_THREE, cost=1_100.0),),
        days=(daily(DAY_ONE, 1e6), daily(DAY_TWO, 1e6), daily(DAY_THREE, 1e6)),
    )

    assert costs_by_date(result) == pytest.approx({DAY_THREE: 1_100.0})


def test_date_bucketed_costs_do_not_stamp_uniform_allocation() -> None:
    evidence = adapt(full_result(), label="x")

    assert UNIFORM_COST_STAMP not in evidence.unverified_inputs
    # The drag lands on the sessions that paid, not smeared across all of them. Dates are
    # the equity curve's second point onward, so DAY_ONE's costs are not in the series.
    assert evidence.returns.drag == pytest.approx((100.0 / STARTING_CASH, 1_100.0 / STARTING_CASH))


# ------------------------------------------------------------------------- feasibility set


def test_group_incomplete_counts_as_infeasible_and_agrees_with_c5() -> None:
    """C5's own ``metrics()`` counts it under ``fills_infeasible``. The two must not disagree."""
    result = full_result()
    facts = feasibility_from_result(result)

    assert facts.intents_infeasible == result.metrics()["fills_infeasible"] == 1


def test_settled_is_excluded_from_the_intent_denominator() -> None:
    """Cash settlement is done *to* the book, so it can never be infeasible.

    Counting it dilutes the infeasible fraction towards zero in proportion to how many
    expiries the run held through: here 1 of 3 intents, not 1 of 4.
    """
    facts = feasibility_from_result(full_result())

    assert facts.intents_attempted == 3
    assert facts.infeasible_fraction == pytest.approx(1.0 / 3.0)


def test_stale_marks_and_sessions_run_are_passed_not_defaulted() -> None:
    """Their defaults are zero, which reads as *nothing was stale* rather than *nobody said*."""
    facts = feasibility_from_result(full_result())

    assert facts.sessions_run == 3
    assert facts.sessions_with_stale_marks == 1
    assert facts.stale_fraction == pytest.approx(1.0 / 3.0)


# ------------------------------------------------------------------------------ capital base


def test_capital_base_is_starting_cash_not_peak_margin() -> None:
    """The capital base is the denominator of every return; peak margin is the flattering one."""
    result = full_result()
    evidence = adapt(result, label="x")

    assert evidence.capital_base == STARTING_CASH
    assert result.peak_margin > 0.0
    assert evidence.peak_margin == pytest.approx(result.peak_margin)
    assert evidence.capital_base != pytest.approx(result.peak_margin)
    # 1,000,000 -> 1,010,000 is +1% of the base. Denominated in peak margin it would read
    # as several times that, on the same rupees.
    assert evidence.returns.net[0] == pytest.approx(0.01)


# -------------------------------------------------------------------------------- run_at


def empty_log() -> TrialLog:
    return TrialLog(
        Path(tempfile.mkdtemp(prefix="adapter_test_")) / "log.db",
        clock=ManualClock(dt.datetime(2026, 8, 13, 9, 0, tzinfo=dt.UTC)),
        code_version=StaticCodeVersion("0" * 40, dirty=False),
    )


def logged_hypothesis() -> tuple[TrialLog, HypothesisRecord]:
    log = empty_log()
    record = HypothesisRecord(
        name="adapter fixture",
        mechanism="A record so the log has a family to file trials against.",
        null_hypothesis="Not tested here.",
        thresholds={"deflated_sharpe": 0.0},
    )
    log.register_hypothesis(record)
    return log, record


def test_run_at_comes_from_the_log_row_not_the_wall_clock() -> None:
    log, record = logged_hypothesis()
    row = log.append_trial(
        hypothesis_id=record.id,
        params={},
        data_window=DataWindow(DAY_ONE, DAY_THREE),
        metrics={},
    )
    result = build_result(
        fills=(fill(DAY_ONE, cost=400.0),),
        days=(daily(DAY_ONE, 1e6), daily(DAY_TWO, 1e6), daily(DAY_THREE, 1e6)),
        trial_id=row.trial_id,
    )

    evidence = evidence_from_result(result, session=log, hypothesis_id=record.id, label="x")

    assert evidence.run_at == row.created_at
    assert logged_run_at(log, record.id, row.trial_id) == row.created_at


def test_an_unlogged_trial_yields_no_timestamp_rather_than_a_guess() -> None:
    """C6 refuses to grade a run that cannot say when it happened. Inventing one defeats that."""
    log, record = logged_hypothesis()
    result = build_result(
        days=(daily(DAY_ONE, 1e6), daily(DAY_TWO, 1e6), daily(DAY_THREE, 1e6)),
        trial_id="t_never_logged",
    )

    assert logged_run_at(log, record.id, "t_never_logged") is None
    assert (
        evidence_from_result(result, session=log, hypothesis_id=record.id, label="x").run_at is None
    )


# ------------------------------------------------------------------------------- passthrough


def test_the_runs_own_caveats_and_fingerprint_travel_into_the_evidence() -> None:
    result = full_result()
    evidence = adapt(result, label="labelled")

    assert evidence.label == "labelled"
    assert "epoch_table.secondary_sourced" in evidence.unverified_inputs
    assert evidence.fingerprint == result.fingerprint()
    assert evidence.trial_id == result.trial_id
