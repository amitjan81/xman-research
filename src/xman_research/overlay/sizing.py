"""The Capital Allocation Service, reduced to the part a backtest can honour.

CAS as specified reads a live broker account: holdings, pledges, haircuts, the approved
collateral list, the broker's own margin calculator. A backtest has none of those, so what
is implemented here is the *calculator* (CA-2 .. CA-18) driven by a stated collateral
assumption rather than by a broker snapshot. :func:`worked_example` reproduces requirements
section 8 exactly, and a test pins it — that is the only available proof that the
arithmetic is the document's arithmetic and not a paraphrase of it.

**Margin per lot is the largest unverified number in the whole exercise, and it decides
the answer.** CA-12 requires the worst-case margin within the position's life *including
the expiry-day additional margin on short legs*, even though ST-4 forbids holding to
expiry day. On a NIFTY condor that add-on (2% of short-leg notional, twice) is roughly
three times the structure's entire defined risk, so following CA-12 literally cuts the
position to about 9 lots where a defined-risk-only model allows 16 and the gearing cap
would bind instead. Both are computed, the literal one leads, and
:func:`allocation_sweep` reports the range, because a single confident number here would
be the assumption masquerading as a result.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

__all__ = [
    "SECTION_8_EXAMPLE",
    "AllocationInputs",
    "AllocationRecord",
    "CollateralAssumption",
    "MarginPerLotModel",
    "allocate",
    "allocation_sweep",
    "worked_example",
]


@dataclass(frozen=True, slots=True)
class CollateralAssumption:
    """The pledged book behind Portfolio Capital, as a standing assumption.

    The defaults are the requirements' own section 8 example, scaled to ``portfolio_capital``:
    85% of the portfolio in equity/equity-MF at a 22% haircut (non-cash) and 15% in liquid
    fund units at a 10% haircut (cash-equivalent), plus a token ledger balance. It is the
    only collateral mix the document states, so it is the one a backtest can claim to be
    reproducing.
    """

    portfolio_capital: float = 10_000_000.0
    non_cash_fraction: float = 0.85
    non_cash_haircut: float = 0.22
    cash_equivalent_fraction: float = 0.15
    cash_equivalent_haircut: float = 0.10
    ledger_cash: float = 50_000.0

    @property
    def nc_total(self) -> float:
        """CA-3: usable value of pledged non-cash collateral."""
        gross = self.portfolio_capital * self.non_cash_fraction
        return gross * (1.0 - self.non_cash_haircut)

    @property
    def ce_total(self) -> float:
        """CA-3: usable value of cash-equivalent collateral, ledger cash included."""
        gross = self.portfolio_capital * self.cash_equivalent_fraction
        return gross * (1.0 - self.cash_equivalent_haircut) + self.ledger_cash

    @property
    def margin_capacity(self) -> float:
        """CA-4: ``min(CE + NC, 2 x CE)`` — the 50% rule, as the document requires it."""
        return min(self.ce_total + self.nc_total, 2.0 * self.ce_total)

    @property
    def nc_stranded(self) -> float:
        """CA-5: non-cash collateral the 50% rule makes unusable."""
        return max(0.0, self.nc_total - self.ce_total)

    def stressed(
        self, *, value_shock: float = -0.07, haircut_add: float = 0.05
    ) -> CollateralAssumption:
        """CA-17's standard stress scenario applied to the collateral side."""
        return CollateralAssumption(
            portfolio_capital=self.portfolio_capital,
            non_cash_fraction=self.non_cash_fraction * (1.0 + value_shock),
            non_cash_haircut=min(self.non_cash_haircut + haircut_add, 0.95),
            cash_equivalent_fraction=self.cash_equivalent_fraction,
            cash_equivalent_haircut=min(self.cash_equivalent_haircut + haircut_add, 0.95),
            ledger_cash=self.ledger_cash,
        )


@dataclass(frozen=True, slots=True)
class MarginPerLotModel:
    """What one lot of the condor is assumed to block, and why.

    ``defined_risk_multiplier`` scales the structure's own maximum loss, which is what a
    hedged position's SPAN scenario charge converges to. ``expiry_day_elm_pct`` is SEBI's
    20 November 2024 add-on (2% of short-leg notional on expiry day); CA-12 says to include
    it in the worst case, ``include_expiry_day_elm`` is how a run says whether it did.
    """

    defined_risk_multiplier: float = 1.0
    expiry_day_elm_pct: float = 0.02
    short_legs: int = 2
    include_expiry_day_elm: bool = True

    def margin_per_lot(self, *, spot: float, lot_size: int, wing_width: float) -> float:
        defined_risk = wing_width * lot_size * self.defined_risk_multiplier
        if not self.include_expiry_day_elm:
            return defined_risk
        elm = self.expiry_day_elm_pct * spot * lot_size * self.short_legs
        return defined_risk + elm

    @property
    def assumptions(self) -> str:
        parts = [
            f"defined risk (wing width x lot size) x {self.defined_risk_multiplier:g}",
        ]
        if self.include_expiry_day_elm:
            parts.append(
                f"plus CA-12 expiry-day ELM {self.expiry_day_elm_pct:.1%} of notional on "
                f"{self.short_legs} short legs"
            )
        parts.append("UNVERIFIED: no SPAN parameter file exists in this corpus")
        return "; ".join(parts)


@dataclass(frozen=True, slots=True)
class AllocationInputs:
    """One session's worth of everything the calculator needs."""

    spot: float
    lot_size: int
    wing_width: float
    collateral: CollateralAssumption = field(default_factory=CollateralAssumption)
    margin_model: MarginPerLotModel = field(default_factory=MarginPerLotModel)
    target_utilisation: float = 0.30
    hard_ceiling_utilisation: float = 0.45
    max_gearing: float = 2.5
    max_lots_absolute: int = 50
    hedge_cash_reserve: float = 0.0
    non_strategy_blocked: float = 0.0
    stress_margin_shock: float = 0.60


@dataclass(frozen=True, slots=True)
class AllocationRecord:
    """CA-21, reduced to the fields a backtest can populate and a report can quote."""

    margin_capacity: float
    nc_stranded: float
    target_budget: float
    hard_ceiling_budget: float
    margin_per_lot: float
    lots_by_margin: int
    lots_by_gearing: int
    allocated_lots: int
    allocated_notional: float
    allocated_gearing: float
    stressed_utilisation: float
    stress_reduced_lots: int
    flags: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "margin_capacity": self.margin_capacity,
            "nc_stranded": self.nc_stranded,
            "target_budget": self.target_budget,
            "hard_ceiling_budget": self.hard_ceiling_budget,
            "margin_per_lot": self.margin_per_lot,
            "lots_by_margin": self.lots_by_margin,
            "lots_by_gearing": self.lots_by_gearing,
            "allocated_lots": self.allocated_lots,
            "allocated_notional": self.allocated_notional,
            "allocated_gearing": self.allocated_gearing,
            "stressed_utilisation": self.stressed_utilisation,
            "stress_reduced_lots": self.stress_reduced_lots,
            "flags": list(self.flags),
        }


def allocate(inputs: AllocationInputs) -> AllocationRecord:
    """CA-4 .. CA-18 in the order the document states them."""
    collateral = inputs.collateral
    capacity = collateral.margin_capacity
    flags: list[str] = []
    if collateral.nc_stranded > 0:
        flags.append("NC_STRANDED")

    target_budget = inputs.target_utilisation * capacity - inputs.non_strategy_blocked
    ceiling_budget = inputs.hard_ceiling_utilisation * capacity - inputs.non_strategy_blocked
    margin_per_lot = inputs.margin_model.margin_per_lot(
        spot=inputs.spot, lot_size=inputs.lot_size, wing_width=inputs.wing_width
    )
    usable = max(0.0, target_budget - inputs.hedge_cash_reserve)
    lots_by_margin = math.floor(usable / margin_per_lot) if margin_per_lot > 0 else 0
    notional_per_lot = inputs.spot * inputs.lot_size
    lots_by_gearing = math.floor(
        (inputs.max_gearing * collateral.portfolio_capital) / notional_per_lot
    )
    allocated = min(lots_by_margin, lots_by_gearing, inputs.max_lots_absolute)
    allocated = max(allocated, 0)

    # CA-17/CA-18: stress the collateral and the margin, then step the position down until
    # the stressed utilisation is inside the hard ceiling. The loop is the document's own
    # "reduce one lot at a time", kept literal so the recorded reduction is auditable.
    stressed_collateral = collateral.stressed()
    stressed_capacity = stressed_collateral.margin_capacity
    stressed_margin = margin_per_lot * (1.0 + inputs.stress_margin_shock)
    reduced = 0
    stressed_utilisation = 0.0
    while allocated >= 0:
        blocked = inputs.non_strategy_blocked + allocated * stressed_margin
        stressed_utilisation = blocked / stressed_capacity if stressed_capacity > 0 else math.inf
        if stressed_utilisation <= inputs.hard_ceiling_utilisation or allocated == 0:
            break
        allocated -= 1
        reduced += 1
    if reduced:
        flags.append("STRESS_REDUCED")
    if allocated == 0:
        flags.append("ZERO_ALLOCATION")

    notional = allocated * notional_per_lot
    return AllocationRecord(
        margin_capacity=capacity,
        nc_stranded=collateral.nc_stranded,
        target_budget=target_budget,
        hard_ceiling_budget=ceiling_budget,
        margin_per_lot=margin_per_lot,
        lots_by_margin=lots_by_margin,
        lots_by_gearing=lots_by_gearing,
        allocated_lots=allocated,
        allocated_notional=notional,
        allocated_gearing=notional / collateral.portfolio_capital,
        stressed_utilisation=stressed_utilisation,
        stress_reduced_lots=reduced,
        flags=tuple(flags),
    )


def allocation_sweep(inputs: AllocationInputs) -> dict[str, AllocationRecord]:
    """The same session under the margin assumptions that plausibly compete.

    Keyed by a short name that says what the assumption is, because the spread between
    them *is* the uncertainty on every return figure the run produces.
    """
    literal = inputs.margin_model
    defined_risk_only = MarginPerLotModel(
        defined_risk_multiplier=literal.defined_risk_multiplier,
        expiry_day_elm_pct=literal.expiry_day_elm_pct,
        short_legs=literal.short_legs,
        include_expiry_day_elm=False,
    )
    padded = MarginPerLotModel(
        defined_risk_multiplier=literal.defined_risk_multiplier * 1.5,
        expiry_day_elm_pct=literal.expiry_day_elm_pct,
        short_legs=literal.short_legs,
        include_expiry_day_elm=False,
    )
    from dataclasses import replace

    return {
        "ca12_literal": allocate(inputs),
        "defined_risk_only": allocate(replace(inputs, margin_model=defined_risk_only)),
        "defined_risk_x1_5": allocate(replace(inputs, margin_model=padded)),
    }


#: Requirements section 8, verbatim, as the inputs that must reproduce it.
SECTION_8_EXAMPLE = AllocationInputs(
    spot=25_000.0,
    lot_size=75,
    wing_width=350.0,
    collateral=CollateralAssumption(
        portfolio_capital=10_000_000.0,
        non_cash_fraction=0.85,
        non_cash_haircut=0.22,
        cash_equivalent_fraction=0.15,
        cash_equivalent_haircut=0.10,
        ledger_cash=50_000.0,
    ),
    hedge_cash_reserve=180_000.0,
)


def worked_example() -> AllocationRecord:
    """Section 8 with its own stated Margin Per Lot of Rs 62,000.

    The document supplies that figure from a broker margin calculator rather than deriving
    it, so reproducing the example means using it rather than this module's model — which
    is precisely why the example is worth pinning: it tests the *allocation* arithmetic
    (CA-4, CA-13, CA-14, CA-15, CA-17) independently of the margin assumption.
    """

    class _Fixed(MarginPerLotModel):
        def margin_per_lot(self, *, spot: float, lot_size: int, wing_width: float) -> float:
            return 62_000.0

    from dataclasses import replace

    return allocate(replace(SECTION_8_EXAMPLE, margin_model=_Fixed()))
