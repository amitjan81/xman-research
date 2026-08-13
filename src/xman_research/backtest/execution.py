"""Could this have been filled, and at what price — two questions, kept apart.

The spec asks for both and they are genuinely different. *What it would cost* is a
number you can always produce; *could it have been filled* is a verdict that is sometimes
"no", and a backtest that only answers the first will happily buy 400 lots of a contract
that traded eleven all day and report the cost of doing so. Feasibility is therefore not
a discount applied to a price — it is a separate, recorded answer attached to every
entry and every exit, and the engine keeps a strategy's requested size next to what the
market could actually have absorbed.

**The fill model is replaceable; the feasibility rule is not a model at all.**
FR-BT-03 asks for the cost model to sit behind a stable interface so a spread-based
model can drop in when quote data exists, and :class:`FillModel` is that interface.
Participation caps are the other kind of thing: they are arithmetic against observed
volume and open interest, they need no calibration, and making them pluggable would
mainly offer a way to turn them off.

**What the current fill model cannot know, stated plainly.** This corpus has OHLC minute
bars and no quotes. There is no bid, no ask, no spread, no depth, and no sequence of
trades within the minute. So the default model fills at the bar's close and applies a
caller-supplied slippage in basis points, and neither of those is a measurement:

* A **fill at the close** assumes the order reached the exchange at the end of the minute
  and that the closing print was available in the size requested. On a liquid ATM strike
  that is roughly true; on a far wing whose whole minute is one trade, it is fiction with
  a timestamp.
* **Slippage in basis points of premium** is a placeholder for a spread that was never
  observed. Indian index option spreads widen enormously in relative terms as premium
  falls — a two-rupee wing quoted 1.90/2.10 is a 10% round trip — so a single bps figure
  is least wrong exactly where it matters least.

This is why spec §2.1 makes the **cost-breakeven multiple the headline number and not the
Sharpe**: the honest question against an uncalibrated cost assumption is how wrong it can
be before the edge disappears. C6 computes that by re-running with the slippage scaled;
everything here exists to make that sweep mean something.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable

from xman_research.backtest.costs import Side
from xman_research.backtest.market import Bar, Contract

__all__ = [
    "BarCloseFillModel",
    "Feasibility",
    "FeasibilityVerdict",
    "FillModel",
    "ParticipationLimits",
    "apply_participation_caps",
]


class Feasibility(StrEnum):
    """The verdict on whether an intended trade could have happened.

    ``FILLABLE`` — the full requested size sits inside both caps. ``RESIZED`` — some of
    it does, and the granted size is what the caps allowed. ``NO_BAR`` — the instrument
    printed nothing in that minute, so there is no evidence any trade was possible.
    ``NO_LIQUIDITY`` — a bar exists but nothing traded in it. ``CAPPED_TO_ZERO`` — the
    caps allowed less than one lot, which is a refusal rather than a resize.
    ``SETTLED`` — not a fill at all: the exchange cash-settled the position at expiry,
    which no participant can fail to receive. ``GROUP_INCOMPLETE`` — this leg was
    fillable on its own and did not trade because a sibling leg in its
    :attr:`~xman_research.backtest.engine.TradeIntent.leg_group` was not; see that field
    for why a multi-leg intent is all-or-none.
    """

    FILLABLE = "fillable"
    RESIZED = "resized"
    NO_BAR = "no_bar"
    NO_LIQUIDITY = "no_liquidity"
    CAPPED_TO_ZERO = "capped_to_zero"
    GROUP_INCOMPLETE = "group_incomplete"
    SETTLED = "settled"


@dataclass(frozen=True, slots=True)
class ParticipationLimits:
    """How much of the observed market one run is allowed to be.

    Both caps are enforced and the binding one is recorded, because they answer different
    questions. **Volume is a flow**: how much traded in this minute, so how much could
    plausibly have been absorbed now. **Open interest is a stock**: how large the
    contract's whole outstanding position is, so how implausible a given size is in
    absolute terms regardless of how busy this particular minute was. A minute with one
    frantic print passes a volume cap and should still not support a position larger than
    a meaningful share of everything outstanding.

    The defaults are deliberately small and are **not** calibrated against anything. They
    are a research convention, not a measurement of market impact, and a result that
    depends on their exact value is a result about the caps.
    """

    max_pct_of_bar_volume: float = 0.01
    max_pct_of_open_interest: float = 0.005

    def __post_init__(self) -> None:
        if not 0.0 < self.max_pct_of_bar_volume <= 1.0:
            raise ValueError("max_pct_of_bar_volume must be in (0, 1]")
        if not 0.0 < self.max_pct_of_open_interest <= 1.0:
            raise ValueError("max_pct_of_open_interest must be in (0, 1]")


@dataclass(frozen=True, slots=True)
class FeasibilityVerdict:
    """The recorded answer to "could this have been filled", for one intended trade.

    Carries the observed liquidity as well as the decision, so a rejection can be argued
    with after the fact. ``binding_cap`` names which limit did the work — a run whose
    resizes are overwhelmingly open-interest-bound is being told something different from
    one that is volume-bound.
    """

    verdict: Feasibility
    requested_lots: int
    granted_lots: int
    binding_cap: str | None
    observed_volume_units: float
    observed_open_interest_units: float
    reason: str
    group_bound: bool = False
    """Whether a sibling leg, rather than this leg's own liquidity, decided the outcome.

    Set when leg-group atomicity refused this leg or cut it below what its own caps
    allowed. Counted on the result so the run can say how often the market let one leg of
    a structure through and not the other — a fact that changes which hypothesis was
    actually tested, and which nothing recorded before."""

    @property
    def is_fillable(self) -> bool:
        return self.granted_lots > 0

    @property
    def was_resized(self) -> bool:
        return self.verdict is Feasibility.RESIZED

    def as_dict(self) -> dict[str, object]:
        return {
            "verdict": str(self.verdict),
            "requested_lots": self.requested_lots,
            "granted_lots": self.granted_lots,
            "binding_cap": self.binding_cap,
            "observed_volume_units": self.observed_volume_units,
            "observed_open_interest_units": self.observed_open_interest_units,
            "reason": self.reason,
            "group_bound": self.group_bound,
        }


def apply_participation_caps(
    *,
    requested_lots: int,
    lot_size: int,
    bar: Bar | None,
    limits: ParticipationLimits,
) -> FeasibilityVerdict:
    """Bind a requested size against observed volume and open interest.

    Both caps are computed in **units** and floored to whole lots, because a fraction of
    a lot is not a tradable quantity and rounding up would defeat the cap it was supposed
    to respect.
    """
    if requested_lots <= 0:
        raise ValueError(f"requested_lots must be positive, got {requested_lots}")
    if lot_size <= 0:
        raise ValueError(f"lot_size must be positive, got {lot_size}")

    if bar is None:
        return FeasibilityVerdict(
            verdict=Feasibility.NO_BAR,
            requested_lots=requested_lots,
            granted_lots=0,
            binding_cap=None,
            observed_volume_units=0.0,
            observed_open_interest_units=0.0,
            reason=(
                "no bar printed for this instrument in this minute — there is no evidence "
                "any trade was possible, and inventing a price would be the whole error "
                "this verdict exists to prevent"
            ),
        )
    if not bar.has_traded:
        return FeasibilityVerdict(
            verdict=Feasibility.NO_LIQUIDITY,
            requested_lots=requested_lots,
            granted_lots=0,
            binding_cap="volume",
            observed_volume_units=bar.volume_units,
            observed_open_interest_units=bar.open_interest_units,
            reason="a bar exists but nothing traded in it",
        )

    volume_lots = int((limits.max_pct_of_bar_volume * bar.volume_units) // lot_size)
    oi_lots = int((limits.max_pct_of_open_interest * bar.open_interest_units) // lot_size)
    allowed = min(volume_lots, oi_lots)
    # Ties resolve to volume. Deterministic, and it is the tighter kind of claim: the flow
    # cap says nobody was there to trade with in this minute, which is the stronger
    # objection to a fill than the size of the outstanding book.
    binding = "volume" if volume_lots <= oi_lots else "open_interest"

    if allowed <= 0:
        return FeasibilityVerdict(
            verdict=Feasibility.CAPPED_TO_ZERO,
            requested_lots=requested_lots,
            granted_lots=0,
            binding_cap=binding,
            observed_volume_units=bar.volume_units,
            observed_open_interest_units=bar.open_interest_units,
            reason=(
                f"participation caps allow {allowed} lots: "
                f"{limits.max_pct_of_bar_volume:.4%} of {bar.volume_units:.0f} traded units "
                f"and {limits.max_pct_of_open_interest:.4%} of {bar.open_interest_units:.0f} "
                f"open units are together less than one lot of {lot_size}"
            ),
        )
    if allowed < requested_lots:
        return FeasibilityVerdict(
            verdict=Feasibility.RESIZED,
            requested_lots=requested_lots,
            granted_lots=allowed,
            binding_cap=binding,
            observed_volume_units=bar.volume_units,
            observed_open_interest_units=bar.open_interest_units,
            reason=(
                f"{requested_lots} lots requested, {allowed} allowed — bound by the {binding} cap"
            ),
        )
    return FeasibilityVerdict(
        verdict=Feasibility.FILLABLE,
        requested_lots=requested_lots,
        granted_lots=requested_lots,
        binding_cap=None,
        observed_volume_units=bar.volume_units,
        observed_open_interest_units=bar.open_interest_units,
        reason="inside both participation caps",
    )


@runtime_checkable
class FillModel(Protocol):
    """FR-BT-03's replaceable seam: what price an allowed trade gets.

    Implementations must be **pure and deterministic** — same bar, same side, same size,
    same price — and must state their assumptions in :attr:`assumptions`, which is copied
    into the backtest result so a stored number carries the execution assumption that
    produced it.
    """

    @property
    def name(self) -> str: ...

    @property
    def assumptions(self) -> str: ...

    def fill_price(self, *, bar: Bar, side: Side, contract: Contract, lots: int) -> float: ...


@dataclass(frozen=True, slots=True)
class BarCloseFillModel:
    """Fill at the bar's close, moved against the trader by ``slippage_bps``.

    The default ``slippage_bps=0.0`` is **the optimistic case, on purpose**: it makes the
    zero-slippage assumption visible in the configuration rather than hidden in a
    plausible-looking default, and it gives C6's cost-breakeven sweep a clean origin. A
    result quoted at this setting is quoted at the friendliest execution the data admits,
    which spec §6 classifies as *not evaluable* rather than as a pass.

    Slippage is applied to premium, so it is symmetric in percentage and asymmetric in
    rupees — the wing that costs two rupees is charged two paise per bps and the ATM
    straddle several. That is the wrong shape for real option spreads (see the module
    docstring) and is retained only because a bps figure is the honest minimum a
    quote-free corpus supports.
    """

    slippage_bps: float = 0.0

    def __post_init__(self) -> None:
        if self.slippage_bps < 0:
            raise ValueError("slippage_bps must be non-negative; it is always adverse")

    @property
    def name(self) -> str:
        return "bar_close"

    @property
    def assumptions(self) -> str:
        return (
            "fills at the minute bar's close with "
            f"{self.slippage_bps} bps of adverse slippage on premium; the decision is "
            "made ON the close of the same bar it fills AT, so the decision inputs at "
            "minute t include the price the trade receives — the standard backtest "
            "convention, and a half-bar of optimism that no cost figure here offsets; no "
            "quote data exists in this corpus, so no spread, depth or intra-minute "
            "sequence is modelled and none of this is calibrated against realised fills"
        )

    def fill_price(self, *, bar: Bar, side: Side, contract: Contract, lots: int) -> float:
        """Buys pay up, sells receive less. ``lots`` is unused — size has no price impact
        in this model, which is precisely what the participation caps exist to bound."""
        adjustment = 1.0 + (self.slippage_bps / 10_000.0) * (1.0 if side is Side.BUY else -1.0)
        return max(0.0, bar.close * adjustment)
