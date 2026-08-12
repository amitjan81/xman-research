"""A simplified margin approximation, so return on capital means something.

**Why it exists at all.** Sharpe on unlevered notional is meaningless for a short-option
strategy. Selling a NIFTY straddle collects a few hundred rupees of premium per unit and
ties up a margin many times that; quote the return against premium and it looks
spectacular, quote it against notional and it looks like nothing. Neither is the number
an operator decides with, which is the capital the exchange actually locks up.

**What it approximates, and what it therefore is not.** Real margin is SPAN plus ELM:
the exchange revalues the whole portfolio under a grid of price and volatility scenarios
and charges the worst one, plus an exposure component. That is out of scope — it needs
the SPAN parameter file, and the risk arrays are a daily artefact this corpus does not
carry. What is implemented is a flat percentage of notional per short leg, plus an
exposure percentage, with premium received **not** offsetting the requirement.

**How wrong it can be, direction first.**

* **No portfolio netting.** SPAN prices the scenario loss of the *combined* book. A short
  straddle cannot lose on both legs at once, so SPAN charges materially less than the sum
  of its legs; this model charges the sum. It therefore **overstates margin**, which
  **understates return on capital** — conservative for a short-variance hypothesis, which
  is H1, which is the direction of error to prefer. The overstatement is largest for the
  most-hedged structures and vanishes for a single naked leg.
* **No volatility scaling.** SPAN's requirement rises with volatility, and rises sharply
  in exactly the sessions a short-variance strategy loses money. A flat percentage is
  therefore most wrong when it matters most, and its error is **not** conservative there:
  it understates the capital that would have been demanded during a drawdown, and margin
  calls are a real failure mode this cannot see.
* **The expiry-day add-on is the exception that proves the rest are guesses.** SEBI's
  20 November 2024 package added 2% ELM on short index option positions on expiry day,
  and that one number has a date, a source and a worked example, so it is implemented
  (:attr:`SimplifiedMarginModel.expiry_day_elm_pct`). Nothing else here does.

**The magnitude of the total error is not claimed**, because no source for it was
established: SPAN is a scenario engine and there is no published percentage to cite.
The span figure below is labelled :attr:`~xman_research.backtest.costs.Confidence.
UNVERIFIED` and is a rule of thumb, not a measurement. The honest use is therefore a
**sweep**: report return on capital across a range of ``multiplier`` values and let the
reader see how much of the conclusion rests on the guess. A single confident-looking
percentage would be worse than the hole it papers over.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from xman_research.backtest.costs import Confidence

__all__ = [
    "MARGIN_CONFIDENCE",
    "MarginRequirement",
    "ShortLeg",
    "SimplifiedMarginModel",
]

#: Every default in this module is an unsourced rule of thumb. Surfaced on the result.
MARGIN_CONFIDENCE = Confidence.UNVERIFIED


@dataclass(frozen=True, slots=True)
class ShortLeg:
    """One short option position, for the purpose of charging margin.

    ``expires_today`` drives the expiry-day add-on, which is the one component here with a
    real source and a real effective date — see
    :attr:`SimplifiedMarginModel.expiry_day_elm_pct`.
    """

    quantity_units: int
    underlying_price: float
    expires_today: bool = False

    @property
    def notional(self) -> float:
        return self.quantity_units * self.underlying_price


@dataclass(frozen=True, slots=True)
class MarginRequirement:
    """What the approximation says a book ties up, with its components kept apart."""

    span_component: float
    exposure_component: float
    expiry_day_elm_component: float
    short_legs: int
    notional: float
    confidence: Confidence = MARGIN_CONFIDENCE

    @property
    def total(self) -> float:
        return self.span_component + self.exposure_component + self.expiry_day_elm_component

    def as_dict(self) -> dict[str, object]:
        return {
            "span_component": self.span_component,
            "exposure_component": self.exposure_component,
            "expiry_day_elm_component": self.expiry_day_elm_component,
            "total": self.total,
            "short_legs": self.short_legs,
            "notional": self.notional,
            "confidence": str(self.confidence),
        }


@dataclass(frozen=True, slots=True)
class SimplifiedMarginModel:
    """Flat-percentage-of-notional margin for short option legs.

    Long options are charged nothing: the premium is paid in full at entry and is the
    entire exposure, which the cash ledger already carries. Charging margin on them as
    well would double-count.

    ``multiplier`` scales the whole requirement and exists for the sensitivity sweep the
    module docstring argues for — it is the knob C6 turns to show how much of a return-on-
    capital claim survives a different guess.
    """

    #: **UNVERIFIED and structurally unverifiable as a percentage.** SPAN is a scenario
    #: engine — sixteen risk scenarios over price and volatility, run daily by the
    #: exchange — so there is no published percentage to cite and there never will be.
    #: Secondary sources offer 5 to 10 per cent of notional for NIFTY futures as an
    #: illustration; 10% is the top of that range, chosen because overstating margin
    #: understates return on capital, which is the conservative direction for H1.
    span_pct_of_notional: float = 0.10
    #: Exposure margin for index derivatives, corroborated at 2% of notional. Better
    #: sourced than the SPAN figure and still not a primary citation; a variant formula
    #: ("3% or 1.5 sigma, whichever is higher") could not be confirmed either way.
    exposure_pct_of_notional: float = 0.02
    #: **The one component here with a date and a worked source.** SEBI's 20 Nov 2024
    #: index-derivatives package added 2% ELM on short index option positions on expiry
    #: day. Applied only to legs whose contract expires that session. Backtests reaching
    #: before 20 Nov 2024 overcharge by this amount on expiry days; the current corpus
    #: begins well after it, so nothing in range is affected.
    expiry_day_elm_pct: float = 0.02
    multiplier: float = 1.0
    minimum_per_book: float = 0.0

    def __post_init__(self) -> None:
        for name in (
            "span_pct_of_notional",
            "exposure_pct_of_notional",
            "expiry_day_elm_pct",
            "multiplier",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be non-negative")

    @property
    def assumptions(self) -> str:
        return (
            f"span={self.span_pct_of_notional:.2%} + exposure="
            f"{self.exposure_pct_of_notional:.2%} of notional per short leg, plus "
            f"{self.expiry_day_elm_pct:.2%} expiry-day ELM on short legs expiring that "
            f"session (SEBI, 20 Nov 2024), multiplier={self.multiplier}; no portfolio "
            f"netting and no volatility scaling; the span figure is an UNVERIFIED rule of "
            f"thumb, not a SPAN computation"
        )

    def requirement(self, short_legs: Sequence[ShortLeg]) -> MarginRequirement:
        """Margin for a book of short legs, summed in the order given."""
        notional = 0.0
        expiring_notional = 0.0
        for leg in short_legs:
            notional += leg.notional
            if leg.expires_today:
                expiring_notional += leg.notional
        span = self.span_pct_of_notional * notional * self.multiplier
        exposure = self.exposure_pct_of_notional * notional * self.multiplier
        expiry_elm = self.expiry_day_elm_pct * expiring_notional * self.multiplier
        if short_legs and span + exposure < self.minimum_per_book:
            # Split the floor across the two components in their own proportion so the
            # breakdown still sums to the total and neither component is invented.
            shortfall = self.minimum_per_book - (span + exposure)
            share = span / (span + exposure) if (span + exposure) > 0 else 0.5
            span += shortfall * share
            exposure += shortfall * (1.0 - share)
        return MarginRequirement(
            span_component=span,
            exposure_component=exposure,
            expiry_day_elm_component=expiry_elm,
            short_legs=len(short_legs),
            notional=notional,
        )
