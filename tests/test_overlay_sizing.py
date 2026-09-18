"""The Capital Allocation calculator against the document's own worked example.

Requirements section 8 says the design agent MUST reproduce its numbers exactly from the
rules in section 3. That is the strongest available test of this module: the example fixes
every intermediate value, so an arithmetic slip anywhere in CA-4 .. CA-18 shows up as a
specific wrong number rather than as a plausible-looking allocation.
"""

from __future__ import annotations

import pytest

from xman_research.overlay.sizing import (
    SECTION_8_EXAMPLE,
    AllocationInputs,
    CollateralAssumption,
    MarginPerLotModel,
    allocate,
    allocation_sweep,
    worked_example,
)


def test_section_8_is_reproduced_exactly() -> None:
    record = worked_example()

    assert record.margin_capacity == pytest.approx(2_800_000.0)
    assert record.nc_stranded == pytest.approx(5_230_000.0)
    assert record.target_budget == pytest.approx(840_000.0)
    assert record.hard_ceiling_budget == pytest.approx(1_260_000.0)
    assert record.lots_by_margin == 10
    assert record.lots_by_gearing == 13
    assert record.allocated_lots == 10
    assert record.allocated_notional == pytest.approx(18_750_000.0)
    assert record.allocated_gearing == pytest.approx(1.875)
    assert record.stressed_utilisation == pytest.approx(0.374, abs=0.001)
    assert record.stress_reduced_lots == 0
    assert "NC_STRANDED" in record.flags


def test_the_fifty_percent_rule_caps_capacity_at_twice_cash_equivalent() -> None:
    """CA-4. An all-equity pledge with no cash-equivalent supports nothing."""
    collateral = CollateralAssumption(
        portfolio_capital=10_000_000.0,
        non_cash_fraction=1.0,
        cash_equivalent_fraction=0.0,
        ledger_cash=0.0,
    )

    assert collateral.margin_capacity == pytest.approx(0.0)
    assert collateral.nc_stranded == pytest.approx(collateral.nc_total)


def test_stress_reduces_lots_when_the_shocked_book_breaches_the_ceiling() -> None:
    """CA-17/CA-18: the reduction happens and says it happened."""
    inputs = AllocationInputs(
        spot=25_000.0,
        lot_size=75,
        wing_width=350.0,
        collateral=CollateralAssumption(portfolio_capital=10_000_000.0),
        margin_model=MarginPerLotModel(include_expiry_day_elm=False),
        stress_margin_shock=4.0,
    )

    record = allocate(inputs)

    assert record.stress_reduced_lots > 0
    assert "STRESS_REDUCED" in record.flags
    assert record.stressed_utilisation <= inputs.hard_ceiling_utilisation + 1e-9


def test_the_ca12_expiry_day_add_on_is_what_binds_the_position() -> None:
    """The largest unverified number in the study, pinned so a change to it is visible.

    Following CA-12 literally — worst case *including* the expiry-day ELM on both short
    legs, even though ST-4 forbids holding to expiry day — charges roughly four times the
    structure's defined risk on a NIFTY condor, and that, not the gearing cap, is what
    sets the position size.
    """
    inputs = AllocationInputs(
        spot=25_000.0, lot_size=75, wing_width=350.0, collateral=CollateralAssumption()
    )

    sweep = allocation_sweep(inputs)

    literal = sweep["ca12_literal"]
    defined_risk = sweep["defined_risk_only"]
    assert literal.margin_per_lot > 3 * defined_risk.margin_per_lot
    assert literal.allocated_lots < defined_risk.allocated_lots
    # Under the defined-risk-only assumption the gearing cap is what binds instead.
    assert defined_risk.allocated_lots == defined_risk.lots_by_gearing


def test_a_wider_wing_costs_lots_because_defined_risk_is_the_margin() -> None:
    narrow = allocate(AllocationInputs(spot=25_000.0, lot_size=75, wing_width=150.0))
    wide = allocate(AllocationInputs(spot=25_000.0, lot_size=75, wing_width=350.0))

    assert narrow.margin_per_lot < wide.margin_per_lot
    assert narrow.lots_by_margin > wide.lots_by_margin


def test_the_example_inputs_are_the_documents_and_not_a_paraphrase() -> None:
    """A guard on the fixture itself: section 8's collateral mix, verbatim."""
    collateral = SECTION_8_EXAMPLE.collateral

    assert collateral.portfolio_capital == 10_000_000.0
    assert collateral.non_cash_fraction * collateral.portfolio_capital == 8_500_000.0
    assert collateral.non_cash_haircut == 0.22
    assert collateral.cash_equivalent_fraction * collateral.portfolio_capital == 1_500_000.0
    assert collateral.cash_equivalent_haircut == 0.10
    assert collateral.ledger_cash == 50_000.0
    assert SECTION_8_EXAMPLE.hedge_cash_reserve == 180_000.0
