"""Why an idea is on the sheet, in a form an operator can argue with.

**An idea without a rationale is a tip.** The scan's output is read by somebody deciding
whether to risk money, and the only defensible thing to hand them is the chain: this is the
mechanism, this is the observation that made it fire today, this is what was measured when
the mechanism was tested, this is the trade that expresses it, and these are the conditions
under which the reasoning stops holding.

**Every number names where it came from.** :attr:`Rationale.provenance` maps each quantity
to its source — a decision-record field, a feature with its lookback, a bar at the decision
minute, or a named formula over other quantities. That is what separates a rationale from a
plausible-looking paragraph: a reader who distrusts one number can find it, and a number
with no source cannot be written down here at all.

**Invalidators are rule-derived, not editorial.** Each one is a condition computed from the
same features and thresholds the trigger used, so it is falsifiable on tomorrow's data
rather than being a caveat. They are the part of the rationale that survives contact with a
loss: an idea whose invalidator fired was wrong for a stated reason, which is the only kind
of wrong the next scan can learn from.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from xman_research.alpha.features import FeatureFrame, RegimeTag
from xman_research.alpha.library import AdmissionRecord
from xman_research.alpha.templates import ConditionerSpec, StrategyTemplate

__all__ = [
    "RATIONALE_SCHEMA_VERSION",
    "Invalidator",
    "Rationale",
    "TradeLeg",
    "TradeSpec",
    "TriggerExplanation",
    "invalidators_for",
]

#: Bumped whenever a field is removed or its meaning changes. A consumer that pins this
#: version can tell an unfamiliar sheet from a familiar one instead of silently reading a
#: field that now means something else.
RATIONALE_SCHEMA_VERSION = 1

#: How far the index may gap overnight, in multiples of the fourteen-session average true
#: range, before a short-variance thesis is treated as void. A gap that size is the risk the
#: premium is compensation for arriving all at once, which is the circumstance in which the
#: historical mean stops describing the distribution.
GAP_INVALIDATOR_ATR_MULTIPLE = 2.0


@dataclass(frozen=True, slots=True)
class TradeLeg:
    """One leg of the trade an idea proposes, priced at the decision minute."""

    trading_symbol: str
    side: str
    lots: int
    units: int
    lot_size: int
    strike: float
    option_type: str
    expiry: str
    price_at_decision_minute: float | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "trading_symbol": self.trading_symbol,
            "side": self.side,
            "lots": self.lots,
            "units": self.units,
            "lot_size": self.lot_size,
            "strike": self.strike,
            "option_type": self.option_type,
            "expiry": self.expiry,
            "price_at_decision_minute": self.price_at_decision_minute,
        }


@dataclass(frozen=True, slots=True)
class TradeSpec:
    """The position an idea proposes, and the rules that open and close it.

    ``max_loss`` is ``None`` for a short straddle and that is a statement, not a gap: the
    loss on a short call is unbounded above, so any finite figure written here would be a
    fiction. The bound an operator actually has is the margin the exchange demands and the
    gap invalidator below it; both are on the sheet.
    """

    legs: tuple[TradeLeg, ...]
    entry_rule: str
    exit_rule: str
    hold_sessions: int
    target_notional: float
    notional: float
    premium_received: float | None
    margin: Mapping[str, Any]
    max_loss: float | None
    max_loss_reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "legs": [leg.as_dict() for leg in self.legs],
            "entry_rule": self.entry_rule,
            "exit_rule": self.exit_rule,
            "hold_sessions": self.hold_sessions,
            "target_notional": self.target_notional,
            "notional": self.notional,
            "premium_received": self.premium_received,
            "margin": dict(self.margin),
            "max_loss": self.max_loss,
            "max_loss_reason": self.max_loss_reason,
        }


@dataclass(frozen=True, slots=True)
class TriggerExplanation:
    """The observation that made a template fire, or that it fires unconditionally."""

    feature: str | None
    value: float | None
    comparator: str | None
    threshold: float | None
    lookback_sessions: int | None
    unit: str | None
    description: str
    fired: bool
    strength: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "feature": self.feature,
            "value": self.value,
            "comparator": self.comparator,
            "threshold": self.threshold,
            "lookback_sessions": self.lookback_sessions,
            "unit": self.unit,
            "description": self.description,
            "fired": self.fired,
            "strength": self.strength,
        }

    @classmethod
    def unconditional(cls) -> TriggerExplanation:
        return cls(
            feature=None,
            value=None,
            comparator=None,
            threshold=None,
            lookback_sessions=None,
            unit=None,
            description=(
                "This template has no conditioner: it is the benchmark family and fires on "
                "every session it can be traded on. Its strength is one by construction, "
                "so it ranks purely on expected edge per unit of margin."
            ),
            fired=True,
            strength=1.0,
        )

    @classmethod
    def from_conditioner(
        cls, conditioner: ConditionerSpec, frame: FeatureFrame
    ) -> TriggerExplanation:
        feature = frame.get(conditioner.feature)
        value = feature.value if feature is not None else None
        description = conditioner.description or (
            feature.description if feature is not None else ""
        )
        if value is None and feature is not None and feature.reason:
            description = f"{description} The feature is unavailable today: {feature.reason}"
        return cls(
            feature=conditioner.feature,
            value=value,
            comparator=str(conditioner.comparator),
            threshold=conditioner.threshold,
            lookback_sessions=conditioner.lookback_sessions,
            unit=feature.unit if feature is not None else None,
            description=description.strip(),
            fired=conditioner.fires(value),
            strength=conditioner.strength(value),
        )


@dataclass(frozen=True, slots=True)
class Invalidator:
    """A condition that, if met, retires the reasoning behind an idea.

    ``breached`` is evaluated on the as-of session, so an idea can reach the sheet with an
    invalidator already breached only if the ranker chose to keep it — and the field then
    says so rather than the idea appearing unqualified.
    """

    name: str
    rule: str
    observed: float | None
    threshold: float | None
    breached: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "rule": self.rule,
            "observed": self.observed,
            "threshold": self.threshold,
            "breached": self.breached,
        }


def invalidators_for(
    template: StrategyTemplate,
    frame: FeatureFrame,
    *,
    expiry: dt.date | None,
    spot: float | None,
    hold_sessions: int | None = None,
) -> tuple[Invalidator, ...]:
    """The conditions under which this template's reasoning stops holding today.

    Derived from the same features the trigger read, so each is checkable against tomorrow's
    frame without any further judgement.

    ``hold_sessions`` is the hold of the trade actually being proposed. It is supplied rather
    than read off the template because a template admitted at a three-session hold proposes a
    three-session trade whatever its declared default says, and the expiry invalidator is a
    statement about the contract surviving *that* hold. Omitted, the declared default applies.
    """
    hold = template.hold_sessions if hold_sessions is None else hold_sessions
    found: list[Invalidator] = []

    gap = frame.value("overnight_gap_return")
    atr = frame.value("atr_14")
    # The average true range is in index points and the gap is a fraction, so the threshold
    # is converted at the level the index is actually trading at rather than at a long
    # average of it — the two differ by several percent after a trend, and the invalidator
    # would then be looser or tighter than it reads.
    gap_threshold: float | None = None
    if atr is not None and spot is not None and spot > 0:
        gap_threshold = GAP_INVALIDATOR_ATR_MULTIPLE * atr / spot
    found.append(
        Invalidator(
            name="overnight_gap",
            rule=(
                f"the index gaps more than {GAP_INVALIDATOR_ATR_MULTIPLE:g} times the "
                "fourteen-session average true range against the previous close; a move "
                "that size is the crash risk the variance premium pays for, arriving at "
                "once, and the historical mean no longer describes the distribution"
            ),
            observed=None if gap is None else abs(gap),
            threshold=gap_threshold,
            breached=(gap is not None and gap_threshold is not None and abs(gap) > gap_threshold),
        )
    )

    spread = frame.get("iv_minus_rv_20")
    found.append(
        Invalidator(
            name="implied_below_realised",
            rule=(
                "at-the-money implied volatility falls below trailing twenty-session "
                "realised volatility; the seller is then being paid less than the variance "
                "actually delivered, which is the mechanism running in reverse"
            ),
            observed=spread.value if spread is not None else None,
            threshold=0.0,
            breached=spread is not None and spread.value is not None and spread.value < 0.0,
        )
    )

    if template.conditioner is not None:
        conditioner = template.conditioner
        value = frame.value(conditioner.feature)
        found.append(
            Invalidator(
                name=f"{conditioner.feature}_below_threshold",
                rule=(
                    f"{conditioner.feature} stops satisfying "
                    f"{conditioner.comparator} {conditioner.threshold:g}, which is the "
                    "condition the template was measured under and the only one its "
                    "evidence describes"
                ),
                observed=value,
                threshold=conditioner.threshold,
                breached=not conditioner.fires(value),
            )
        )

    # The count is measured to the frame's nearest listed expiry. That is the contract the
    # entry rule sells, so the two normally agree — but the rule below is about the leg on
    # THIS sheet, so the count is used only once it is confirmed to describe that leg rather
    # than relying on the agreement holding.
    sessions_left = frame.value("sessions_to_nearest_expiry")
    if expiry is not None and expiry != frame.nearest_expiry:
        sessions_left = None
    found.append(
        Invalidator(
            name="contract_expires_inside_hold",
            rule=(
                "the contract sold reaches its expiry on or before the exit minute of a "
                f"{hold}-session hold; a contract is dropped from the "
                "instrument master on its own expiry date, so the buy-back cannot be "
                "expressed, the position cash-settles instead, and the observation stops "
                "being the hold the evidence measured"
            ),
            observed=sessions_left,
            threshold=float(hold),
            # `<=`, not `<`: a contract expiring ON the exit session cannot be bought back
            # at all, which is exactly the outcome this invalidator warns about.
            breached=sessions_left is not None and sessions_left <= hold,
        )
    )
    return tuple(found)


@dataclass(frozen=True, slots=True)
class Rationale:
    """The complete case for one idea, serialisable and self-describing."""

    schema_version: int
    template_id: str
    parameters: Mapping[str, float]
    """The admitted point the trade below was built at — half of what identifies it."""
    template_name: str
    underlying: str
    as_of: str
    thesis: str
    trigger: TriggerExplanation
    evidence: Mapping[str, Any]
    evidence_source: str
    admitted_by: str
    admitted_at: str
    admission_status: str
    gate_status: str | None
    trade: TradeSpec
    regime: Mapping[str, Any]
    invalidators: tuple[Invalidator, ...]
    provenance: Mapping[str, str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "template_id": self.template_id,
            "parameters": {name: float(value) for name, value in sorted(self.parameters.items())},
            "template_name": self.template_name,
            "underlying": self.underlying,
            "as_of": self.as_of,
            "thesis": self.thesis,
            "trigger": self.trigger.as_dict(),
            "evidence": dict(self.evidence),
            "evidence_source": self.evidence_source,
            "admitted_by": self.admitted_by,
            "admitted_at": self.admitted_at,
            "admission_status": self.admission_status,
            "gate_status": self.gate_status,
            "trade": self.trade.as_dict(),
            "regime": dict(self.regime),
            "invalidators": [rule.as_dict() for rule in self.invalidators],
            "provenance": dict(self.provenance),
        }

    @classmethod
    def build(
        cls,
        *,
        template: StrategyTemplate,
        admission: AdmissionRecord,
        frame: FeatureFrame,
        trigger: TriggerExplanation,
        trade: TradeSpec,
        invalidators: Sequence[Invalidator],
        regime: RegimeTag,
        parameters: Mapping[str, float] | None = None,
        extra_provenance: Mapping[str, str] | None = None,
    ) -> Rationale:
        """Assemble a rationale, carrying the evidence card through verbatim.

        The card is copied rather than summarised. A sheet that reported three of its
        fifteen fields would be choosing which measurements the reader is allowed to weigh,
        and the ones a summary drops — the cost stamps, the unverified-input list, the gate
        verdict — are exactly the ones that qualify the headline.
        """
        provenance: dict[str, str] = {
            "thesis": f"template {template.template_id} (source: alpha.templates)",
            "evidence": f"admission record for {template.template_id} <- {admission.decision_path}",
            "regime": (
                f"feature layer, implied-minus-realised tercile over "
                f"{regime.observations} trailing observations"
            ),
            "trade.legs": (
                f"contract universe of the {frame.underlying} session dated {frame.as_of}, "
                "sized by the template's target notional"
            ),
            "trade.margin": (
                "xman_research.backtest.margin.SimplifiedMarginModel — an unverified "
                "flat-percentage approximation, not a SPAN computation"
            ),
        }
        if trigger.feature is not None:
            feature = frame.get(trigger.feature)
            provenance["trigger"] = (
                f"feature {trigger.feature} over {trigger.lookback_sessions} sessions"
                + (f", {feature.description}" if feature is not None else "")
            )
        provenance.update(dict(admission.evidence.provenance))
        provenance.update(dict(extra_provenance or {}))
        return cls(
            schema_version=RATIONALE_SCHEMA_VERSION,
            template_id=template.template_id,
            parameters=dict(parameters if parameters is not None else admission.parameters),
            template_name=template.name,
            underlying=frame.underlying,
            as_of=frame.as_of.isoformat(),
            thesis=template.thesis,
            trigger=trigger,
            evidence=admission.evidence.as_dict(),
            evidence_source=admission.decision_path,
            admitted_by=admission.admitted_by,
            admitted_at=admission.admitted_at,
            admission_status=str(admission.status),
            gate_status=admission.evidence.gate_status,
            trade=trade,
            regime=regime.as_dict(),
            invalidators=tuple(invalidators),
            provenance=provenance,
        )
