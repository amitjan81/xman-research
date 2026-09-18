"""Slippage in rupees per unit, because an option spread is not a percentage.

:class:`~xman_research.backtest.execution.BarCloseFillModel` charges slippage in basis
points of premium. That is the right shape for an underlying and the wrong one for this
book: the structure's two long wings trade at Rs 5-20 and its two short legs at Rs 20-30,
so a bps charge makes the wing's slippage a fraction of a paisa while the real cost of
crossing a NIFTY weekly far-OTM spread is a tick or two whatever the premium is. Charging
it in bps understates the leg that is traded most often and costs most to cross.

So this model charges a flat rupee amount per unit per leg, adverse in both directions,
and the run sweeps it. At the default of Rs 0.25 a four-leg condor round trip costs
Rs 2.00 per unit against a net credit of roughly Rs 25 — about 8% of the credit, which is
in the range a retail operator crossing the spread on both ends should expect.

None of this is calibrated: the corpus carries no quotes, so no spread is observable. It
is a stated assumption with a sweep attached, which is the most a quote-free corpus
supports.
"""

from __future__ import annotations

from dataclasses import dataclass

from xman_research.backtest.costs import Side
from xman_research.backtest.market import Bar, Contract

__all__ = ["AbsoluteSlippageFillModel"]


@dataclass(frozen=True, slots=True)
class AbsoluteSlippageFillModel:
    """Fill at the bar close, moved against the trader by a flat rupee amount per unit."""

    rupees_per_unit: float = 0.25

    def __post_init__(self) -> None:
        if self.rupees_per_unit < 0:
            raise ValueError("rupees_per_unit must be non-negative; slippage is always adverse")

    @property
    def name(self) -> str:
        return "bar_close_absolute_slippage"

    @property
    def assumptions(self) -> str:
        return (
            f"fills at the minute bar's close with Rs {self.rupees_per_unit} per unit of "
            "adverse slippage on every leg, charged in rupees rather than basis points "
            "because the structure's long wings are single-digit-rupee options; the "
            "decision is made ON the close of the bar it fills AT; no quote data exists in "
            "this corpus, so the figure is an assumption with a sweep, not a measurement"
        )

    def fill_price(self, *, bar: Bar, side: Side, contract: Contract, lots: int) -> float:
        adjustment = self.rupees_per_unit if side is Side.BUY else -self.rupees_per_unit
        return max(0.05, bar.close + adjustment)
