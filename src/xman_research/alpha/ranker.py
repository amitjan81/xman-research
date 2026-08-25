"""The nightly scan: which admitted templates fire tonight, and in what order.

**The scan invents nothing.** It instantiates every admitted template on every product in
the universe, asks the feature layer what today looks like, and orders the survivors. The
expectation attached to each idea is copied out of the template's admission record; nothing
here runs a backtest, and nothing here fits a parameter. A scan that re-measured nightly
would be a fresh selection over the same corpus every evening, with the trial count nowhere
recorded — which is the failure the offline loop's whole apparatus exists to prevent.

**It also imports no backtest runner, deliberately.**
:func:`~xman_research.backtest.engine.run_backtest` requires a single-use trial token, so a
scan that called it would burn a research trial every night and inflate the very count the
deflated Sharpe corrects with. Feasibility is answered by
:func:`~xman_research.backtest.execution.apply_participation_caps` against the bars of the
as-of session, which is arithmetic over observed volume and open interest and needs no
token, no calibration and no run.

**Determinism is a property, not an aspiration.** Given a corpus, a library and an as-of
date, two scans produce byte-identical sheets: candidates are visited in a fixed order,
ties break on a stated key, and the two values that legitimately vary — the wall clock and
the code version — are injected. A test pins them and compares the whole document.

**What the score is, and what it is not.** The ranking quantity is

    expected_edge x signal_strength / margin_ratio

where ``expected_edge`` is the admission card's mean return at the template's hold length
(scaled by a regime factor only where the card carries a table measured over the same
partition), ``signal_strength`` is the conditioner's saturating distance past its threshold,
and ``margin_ratio`` is the approximated margin as a fraction of the summed notional of
the position's short legs. It is
**an ordering over the ideas on one sheet**, not a forecast: the numerator's denominator is
the capital base of the offline run that measured it, the margin model underneath it is an
unverified flat-percentage approximation, and the strength curve is a convention. Two ideas
on the same sheet are comparable; the number itself does not predict a return.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from xman_research.alpha.explain import (
    Rationale,
    TradeLeg,
    TradeSpec,
    TriggerExplanation,
    invalidators_for,
)
from xman_research.alpha.features import (
    AsOfNotASessionError,
    FeatureBuilder,
    FeatureFrame,
    InsufficientHistoryError,
)
from xman_research.alpha.library import AdmissionRecord, TemplateLibrary
from xman_research.alpha.templates import StrategyTemplate, TemplateRegistry, parameter_key
from xman_research.backtest.costs import Side
from xman_research.backtest.engine import BookView, TradeIntent
from xman_research.backtest.execution import ParticipationLimits, apply_participation_caps
from xman_research.backtest.margin import MarginRequirement, ShortLeg, SimplifiedMarginModel
from xman_research.backtest.market import SessionView
from xman_research.clock import Clock, SystemClock
from xman_research.code_version import CodeVersionProvider, GitCodeVersion
from xman_research.session_store import CalendarCoverageError, SessionStore, SessionStoreError

__all__ = [
    "IDEA_SHEET_SCHEMA_VERSION",
    "SKIP_INFEASIBLE",
    "SKIP_NON_POSITIVE_EDGE",
    "SKIP_NO_ENTRY",
    "SKIP_NO_EXPECTED_EDGE",
    "SKIP_NO_FEATURES",
    "SKIP_NO_MARGIN",
    "SKIP_NO_SESSION_VIEW",
    "SKIP_PRODUCT_NOT_SUPPORTED",
    "SKIP_TEMPLATE_NOT_REGISTERED",
    "SKIP_TRIGGER_DID_NOT_FIRE",
    "Idea",
    "IdeaSheet",
    "NightlyScan",
    "SkippedCandidate",
]

IDEA_SHEET_SCHEMA_VERSION = 1

#: How the ranker names each way a candidate can drop out. Stable strings, because a
#: consumer counting "how often did open interest bind this month" needs them to be.
SKIP_TEMPLATE_NOT_REGISTERED = "template_not_registered"
SKIP_PRODUCT_NOT_SUPPORTED = "product_not_supported"
SKIP_NO_EXPECTED_EDGE = "no_expected_edge"
SKIP_TRIGGER_DID_NOT_FIRE = "trigger_did_not_fire"
SKIP_NO_SESSION_VIEW = "no_session_view"
SKIP_NO_ENTRY = "no_entry_at_decision_minute"
SKIP_INFEASIBLE = "infeasible"
SKIP_NO_MARGIN = "no_margin_estimate"
SKIP_NO_FEATURES = "no_features_for_product"
SKIP_NON_POSITIVE_EDGE = "non_positive_expected_edge"


#: Reading one product's session can fail for reasons that are about that product's corpus
#: rather than about the scan: no session on the as-of date, too little history behind it, a
#: hole the store refuses to cross, or a date the exchange calendar does not cover.
_PRODUCT_UNREADABLE = (
    AsOfNotASessionError,
    CalendarCoverageError,
    InsufficientHistoryError,
    SessionStoreError,
)


@dataclass(frozen=True, slots=True)
class SkippedCandidate:
    """A template-product pair the scan considered and did not rank, with the reason.

    **Skips are output, not silence.** A sheet with no ideas and no skips is
    indistinguishable from a scan that failed to run; a sheet that says every candidate was
    bound by the open-interest cap is a fact about the market that night.
    """

    template_id: str
    underlying: str
    reason: str
    detail: str
    parameters: Mapping[str, float] = field(default_factory=dict)
    """The admitted point this skip is about — two points are two candidates."""

    @property
    def parameter_key(self) -> str:
        return parameter_key(self.parameters)

    def as_dict(self) -> dict[str, Any]:
        return {
            "template_id": self.template_id,
            "parameters": {name: float(value) for name, value in sorted(self.parameters.items())},
            "parameter_key": self.parameter_key,
            "underlying": self.underlying,
            "reason": self.reason,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class Idea:
    """One ranked proposal, with the whole case for it attached."""

    rank: int
    template_id: str
    parameters: Mapping[str, float]
    """The admitted point this idea was built at — the trade, not the template's default."""
    underlying: str
    score: float
    expected_edge: float
    signal_strength: float
    regime_factor: float
    margin_total: float
    margin_ratio: float
    requested_lots: int
    granted_lots: int
    feasibility: tuple[Mapping[str, Any], ...]
    as_of_inside_evidence_window: bool
    rationale: Rationale

    @property
    def breached_invalidators(self) -> tuple[str, ...]:
        """Names of this idea's invalidators that are already breached on the as-of session.

        Surfaced beside the idea rather than left inside the rationale because it changes
        whether the idea should be acted on at all, and a reader scanning a ranked list
        should not have to open each rationale to find out.
        """
        return tuple(rule.name for rule in self.rationale.invalidators if rule.breached)

    @property
    def parameter_key(self) -> str:
        return parameter_key(self.parameters)

    def as_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "template_id": self.template_id,
            "parameters": {name: float(value) for name, value in sorted(self.parameters.items())},
            "parameter_key": self.parameter_key,
            "underlying": self.underlying,
            "score": self.score,
            "expected_edge": self.expected_edge,
            "signal_strength": self.signal_strength,
            "regime_factor": self.regime_factor,
            "margin_total": self.margin_total,
            "margin_ratio": self.margin_ratio,
            "requested_lots": self.requested_lots,
            "granted_lots": self.granted_lots,
            "breached_invalidators": list(self.breached_invalidators),
            "as_of_inside_evidence_window": self.as_of_inside_evidence_window,
            "feasibility": [dict(verdict) for verdict in self.feasibility],
            "rationale": self.rationale.as_dict(),
        }


@dataclass(frozen=True, slots=True)
class IdeaSheet:
    """One night's output: what fired, in what order, and what did not.

    :attr:`rests_on_unpassed_evidence` is on the sheet rather than buried in a rationale
    because it changes how the whole document should be read. A template can be admitted
    against a decision record whose pre-registered gate failed — that is a human's call and
    the library records who made it — and an operator opening the sheet is entitled to see
    on the first screen that at least one ranked idea is standing on evidence the research
    loop declined to pass.
    """

    schema_version: int
    as_of: str
    generated_at: str
    code_version: str
    universe: tuple[str, ...]
    decision_time: str
    top_n: int
    participation: Mapping[str, float]
    ideas: tuple[Idea, ...]
    skipped: tuple[SkippedCandidate, ...]
    rests_on_unpassed_evidence: bool
    rests_on_in_sample_evidence: bool
    """Whether any ranked idea's as-of session lies inside the window its edge was measured on.

    Not a look-ahead leak — every number came from sessions at or before the as-of — but a
    statistical one: an in-sample mean applied to a session that was part of the sample is
    describing data it has already seen. It sits beside the gate flag because it changes how
    the whole sheet should be read, and because a nightly scan run inside a research window
    is the normal way to be caught by it.
    """
    no_ideas_reason: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "as_of": self.as_of,
            "generated_at": self.generated_at,
            "code_version": self.code_version,
            "universe": list(self.universe),
            "decision_time": self.decision_time,
            "top_n": self.top_n,
            "participation": dict(self.participation),
            "ideas": [idea.as_dict() for idea in self.ideas],
            "skipped": [skip.as_dict() for skip in self.skipped],
            "rests_on_unpassed_evidence": self.rests_on_unpassed_evidence,
            "rests_on_in_sample_evidence": self.rests_on_in_sample_evidence,
            "no_ideas_reason": self.no_ideas_reason,
        }


class NightlyScan:
    """Ranks admitted templates across a universe for one as-of session."""

    def __init__(
        self,
        *,
        store: SessionStore,
        registry: TemplateRegistry,
        library: TemplateLibrary,
        as_of: dt.date,
        universe: Sequence[str],
        top_n: int = 10,
        participation: ParticipationLimits | None = None,
        target_notional: float | None = None,
        margin_model: SimplifiedMarginModel | None = None,
        feature_builder: FeatureBuilder | None = None,
        clock: Clock | None = None,
        code_version: CodeVersionProvider | None = None,
    ) -> None:
        if top_n < 1:
            raise ValueError(f"top_n must be at least 1, got {top_n}")
        if not universe:
            raise ValueError("universe must name at least one underlying")
        if len(set(universe)) != len(universe):
            duplicates = sorted({name for name in universe if list(universe).count(name) > 1})
            raise ValueError(
                f"universe names {duplicates} more than once; each product is scanned once "
                "and a repeat would put the same idea on the sheet twice"
            )
        self._store = store
        self._registry = registry
        self._library = library
        self._as_of = as_of
        self._universe = tuple(universe)
        self._top_n = top_n
        self._participation = participation or ParticipationLimits()
        self._target_notional = target_notional
        self._margin = margin_model or SimplifiedMarginModel()
        self._features = feature_builder or FeatureBuilder(store)
        self._clock = clock or SystemClock()
        self._code_version = code_version or GitCodeVersion()

    def run(self) -> IdeaSheet:
        """Evaluate every admitted template on every product, ranked."""
        admitted = self._library.admitted()
        ideas: list[Idea] = []
        skipped: list[SkippedCandidate] = []
        unreadable: list[Exception] = []

        for underlying in self._universe:
            try:
                frame = self._features.build(underlying, self._as_of)
                view = self._features.session_view(underlying, self._as_of)
            except _PRODUCT_UNREADABLE as error:
                # **One product's missing data must not silence the others.** A universe is a
                # list, and a corpus is onboarded one underlying at a time, so a scan that
                # aborted on the first product without a session that night would stop
                # producing ideas for the products that do have one — a total outage caused by
                # a partial one. The product is recorded as a skip against every admitted
                # template instead, so the sheet says which product was unreadable and why.
                unreadable.append(error)
                skipped.extend(
                    _skipped(admission, underlying, SKIP_NO_FEATURES, str(error))
                    for admission in admitted
                )
                continue
            for admission in admitted:
                outcome = self._evaluate(admission, underlying, frame, view)
                if isinstance(outcome, SkippedCandidate):
                    skipped.append(outcome)
                else:
                    ideas.append(outcome)

        if unreadable and len(unreadable) == len(self._universe):
            # Every product failed, so there is no partial answer to hand back. A sheet of
            # skips would look like a quiet night rather than a scan that could read nothing,
            # and the caller — a nightly wrapper, or an operator who typed a date — needs the
            # difference.
            raise unreadable[0]

        # Highest score first; ties break on template id, then the admitted point, then
        # product, so the order does not depend on which product happened to be scanned
        # first — nor, for a template admitted twice, on which point was filed first.
        ideas.sort(
            key=lambda idea: (-idea.score, idea.template_id, idea.parameter_key, idea.underlying)
        )
        ranked = tuple(
            replace(idea, rank=position + 1) for position, idea in enumerate(ideas[: self._top_n])
        )
        version = self._code_version()
        return IdeaSheet(
            schema_version=IDEA_SHEET_SCHEMA_VERSION,
            as_of=self._as_of.isoformat(),
            generated_at=self._clock.now().isoformat(),
            code_version=str(version),
            universe=self._universe,
            decision_time=self._features.decision_time.isoformat(),
            top_n=self._top_n,
            participation={
                "max_pct_of_bar_volume": self._participation.max_pct_of_bar_volume,
                "max_pct_of_open_interest": self._participation.max_pct_of_open_interest,
            },
            ideas=ranked,
            skipped=tuple(
                sorted(
                    skipped,
                    key=lambda skip: (skip.underlying, skip.template_id, skip.parameter_key),
                )
            ),
            rests_on_unpassed_evidence=any(
                idea.rationale.gate_status != "passed" for idea in ranked
            ),
            rests_on_in_sample_evidence=any(idea.as_of_inside_evidence_window for idea in ranked),
            no_ideas_reason=_no_ideas_reason(admitted, ranked, skipped),
        )

    # ------------------------------------------------------------------ one candidate

    def _evaluate(
        self,
        admission: AdmissionRecord,
        underlying: str,
        frame: FeatureFrame,
        view: SessionView | None,
    ) -> Idea | SkippedCandidate:
        template_id = admission.template_id
        if template_id not in self._registry:
            return _skipped(
                admission,
                underlying,
                SKIP_TEMPLATE_NOT_REGISTERED,
                (
                    f"the library admits {template_id!r} but no template is registered under "
                    "that id, so there is no trade to build"
                ),
            )
        template = self._registry.get(template_id)
        if underlying not in template.products:
            return _skipped(
                admission,
                underlying,
                SKIP_PRODUCT_NOT_SUPPORTED,
                (
                    f"{template_id} declares products {list(template.products)}; its evidence "
                    f"was not measured on {underlying}"
                ),
            )

        trigger = (
            TriggerExplanation.unconditional()
            if template.conditioner is None
            else TriggerExplanation.from_conditioner(template.conditioner, frame)
        )
        if not trigger.fired:
            return _skipped(
                admission,
                underlying,
                SKIP_TRIGGER_DID_NOT_FIRE,
                _trigger_detail(trigger),
            )

        card = admission.evidence
        regime_factor = card.regime_factor(frame.regime.tag)
        base_edge = card.mean_return_at_hold
        if base_edge is None:
            return _skipped(
                admission,
                underlying,
                SKIP_NO_EXPECTED_EDGE,
                (
                    f"the admission record for {template_id} carries no mean return at its "
                    "hold length, and this scan may not measure one itself"
                ),
            )
        expected_edge = base_edge * regime_factor
        if expected_edge <= 0:
            # Ranking it would put a trade at the top of a sheet that its own admission
            # evidence says loses money. The score is a ratio, so a negative numerator also
            # inverts the ordering: the worst candidate would sort best among the negatives.
            return _skipped(
                admission,
                underlying,
                SKIP_NON_POSITIVE_EDGE,
                (
                    f"the admission record for {template_id} measures a mean return at hold "
                    f"of {base_edge:.6g} (regime factor {regime_factor:g}), which is not a "
                    "positive edge to rank"
                ),
            )

        if view is None:
            return _skipped(
                admission,
                underlying,
                SKIP_NO_SESSION_VIEW,
                f"{underlying} has no readable session on {self._as_of}",
            )
        minute = frame.decision_minute
        if minute is None:
            return _skipped(
                admission,
                underlying,
                SKIP_NO_ENTRY,
                (
                    f"the {self._as_of} session ends before "
                    f"{self._features.decision_time.isoformat()}, so there is no minute to "
                    "act at"
                ),
            )

        point = self._parameters(template, admission)
        hold_sessions = template.hold_for(point)
        strategy = template.build(
            point,
            underlying,
            feature_series=self._feature_series(frame),
        )
        intents = strategy.decide(session=view, minute=minute, book=_EMPTY_BOOK)
        if not intents:
            return _skipped(
                admission,
                underlying,
                SKIP_NO_ENTRY,
                (
                    f"{template_id} proposed no entry on {self._as_of}: its own eligibility "
                    "rules refused the session — most often no listed expiry far enough out "
                    "to survive the hold, or a chain missing one side of the at-the-money "
                    "strike"
                ),
            )

        granted, verdicts, detail = _feasibility(intents, view, minute, self._participation)
        if granted <= 0:
            return _skipped(admission, underlying, SKIP_INFEASIBLE, detail)

        spot = view.spot_at(minute)
        if spot is None or spot <= 0:
            return _skipped(
                admission,
                underlying,
                SKIP_NO_MARGIN,
                f"{underlying} has no positive spot at {minute.isoformat()}",
            )

        legs, notional, premium, requirement = self._position(intents, granted, view, minute, spot)
        if requirement.total <= 0:
            return _skipped(
                admission,
                underlying,
                SKIP_NO_MARGIN,
                (
                    "the margin approximation returns zero for this position, so expected "
                    "edge per unit of margin is undefined"
                ),
            )
        margin_ratio = requirement.total / notional if notional > 0 else 0.0
        if margin_ratio <= 0:
            return _skipped(
                admission,
                underlying,
                SKIP_NO_MARGIN,
                "the position has no positive notional to express margin against",
            )
        score = expected_edge * trigger.strength / margin_ratio

        expiry = legs[0].expiry if legs else None
        trade = TradeSpec(
            legs=tuple(legs),
            entry_rule=(
                f"sell the at-the-money straddle of the nearest listed expiry at "
                f"{self._features.decision_time.isoformat()} on {self._as_of}, both legs "
                "filled together or neither"
            ),
            exit_rule=(
                f"buy both legs back at {self._features.decision_time.isoformat()} after "
                f"{hold_sessions} session(s); a contract that reaches its expiry "
                "first cash-settles instead"
            ),
            hold_sessions=hold_sessions,
            target_notional=_as_float(strategy.parameters().get("target_notional")),
            notional=notional,
            premium_received=premium,
            margin=requirement.as_dict(),
            max_loss=None,
            max_loss_reason=(
                "a short call's loss is unbounded above, so no finite maximum loss exists "
                "for this structure; the bound an operator has is the margin posted and the "
                "gap invalidator on this sheet"
            ),
        )
        rationale = Rationale.build(
            template=template,
            admission=admission,
            frame=frame,
            trigger=trigger,
            trade=trade,
            invalidators=invalidators_for(
                template,
                frame,
                expiry=dt.date.fromisoformat(expiry) if expiry else None,
                spot=spot,
                hold_sessions=hold_sessions,
            ),
            regime=frame.regime,
            parameters=point,
            extra_provenance={
                "parameters": (
                    f"the point this template is admitted at [{parameter_key(point)}], read "
                    f"from {admission.decision_path}; the ranker builds the trade there and "
                    "nowhere else"
                ),
                "expected_edge": (
                    "admission card mean_return_at_hold x regime factor "
                    f"{regime_factor:g} (see evidence.provenance for the card's own sources)"
                ),
                "signal_strength": (
                    "conditioner distance past threshold, saturating at the declared span"
                    if template.conditioner is not None
                    else "1.0 by construction: this template has no conditioner"
                ),
                "score": (
                    "expected_edge x signal_strength / margin_ratio — an ordering over this "
                    "sheet, not a predicted return"
                ),
                "feasibility": (
                    "xman_research.backtest.execution.apply_participation_caps against the "
                    f"bars of {self._as_of} at {minute.isoformat()}"
                ),
            },
        )
        return Idea(
            rank=0,
            template_id=template_id,
            parameters=point,
            underlying=underlying,
            score=score,
            expected_edge=expected_edge,
            signal_strength=trigger.strength,
            regime_factor=regime_factor,
            margin_total=requirement.total,
            margin_ratio=margin_ratio,
            requested_lots=max(intent.lots for intent in intents),
            granted_lots=granted,
            feasibility=tuple(verdict for verdict in verdicts),
            as_of_inside_evidence_window=_inside_window(self._as_of, card.window),
            rationale=rationale,
        )

    def _parameters(
        self, template: StrategyTemplate, admission: AdmissionRecord
    ) -> dict[str, float]:
        """The admitted parameter point, with the scan's notional override applied.

        **The point comes from the admission, not from the template's defaults.** The
        evidence card's expected edge was measured at one point, and building at any other
        would attach that number to a trade nothing measured — a hold-3 mean return behind a
        hold-1 proposal. An entry filed before points were recorded carries none, and the
        declared defaults are then the only point available.

        ``target_notional`` is the one parameter a scan may move: it scales the position
        without changing the trade, and every headline statistic on the card is a return
        rather than an amount. The override goes through :meth:`StrategyTemplate.resolve`,
        so a size outside the declared range is refused rather than silently built.
        """
        supplied = dict(admission.parameters)
        if self._target_notional is not None and "target_notional" in template.parameters:
            supplied["target_notional"] = self._target_notional
        return template.resolve(supplied)

    def _feature_series(self, frame: FeatureFrame) -> dict[str, dict[dt.date, float]]:
        """Every computable feature on the frame, as a one-session series each.

        The scan opens one position on one session, so one entry per feature is all a
        strategy needs — and taking them from the frame that was already built keeps the
        values the rationale reports and the values the strategy acts on the same numbers.

        Every feature is offered rather than only the conditioner's, because a strike rule
        reads one too: an at-the-money straddle needs none, and a structure widthed in
        average true ranges needs ``atr_14``. A feature whose value is ``None`` is left out
        entirely, which is what makes the strategy decline the session rather than width a
        position from a filler.
        """
        return {
            name: {frame.as_of: feature.value}
            for name, feature in frame.features.items()
            if feature.value is not None
        }

    def _position(
        self,
        intents: Sequence[TradeIntent],
        granted: int,
        view: SessionView,
        minute: dt.datetime,
        spot: float,
    ) -> tuple[list[TradeLeg], float, float | None, MarginRequirement]:
        legs: list[TradeLeg] = []
        short_legs: list[ShortLeg] = []
        premium = 0.0
        premium_known = True
        notional = 0.0
        for intent in sorted(intents, key=lambda i: i.trading_symbol):
            contract = view.universe.by_symbol(intent.trading_symbol)
            if contract is None:
                continue
            units = granted * contract.lot_size
            bar = view.bar(intent.trading_symbol, minute)
            price = bar.close if bar is not None else None
            if price is None:
                premium_known = False
            elif intent.side is Side.SELL:
                premium += price * units
            legs.append(
                TradeLeg(
                    trading_symbol=contract.trading_symbol,
                    side=str(intent.side),
                    lots=granted,
                    units=units,
                    lot_size=contract.lot_size,
                    strike=contract.strike,
                    option_type=contract.option_type,
                    expiry=contract.expiry.isoformat(),
                    price_at_decision_minute=price,
                )
            )
            if intent.side is Side.SELL:
                notional += units * spot
                short_legs.append(
                    ShortLeg(
                        quantity_units=units,
                        underlying_price=spot,
                        expires_today=contract.expiry == view.session_date,
                    )
                )
        requirement = self._margin.requirement(short_legs)
        return legs, notional, (premium if premium_known else None), requirement


#: The book a scan proposes an entry against.
#:
#: **Empty, and that is the question being asked.** The scan asks each template what it
#: would open tonight, and the only book that question can be posed against is a flat one.
#: Handing a template the operator's real positions would make the sheet a portfolio
#: decision rather than a list of candidates, and sizing against an existing book is a
#: different problem with a different owner.
_EMPTY_BOOK = BookView({}, 0.0)


def _skipped(
    admission: AdmissionRecord, underlying: str, reason: str, detail: str
) -> SkippedCandidate:
    """One skip, carrying the admission's own point.

    Written once rather than at each of the dozen refusal sites: a skip that lost the point
    would report two admissions of one template as two indistinguishable lines.
    """
    return SkippedCandidate(
        template_id=admission.template_id,
        underlying=underlying,
        reason=reason,
        detail=detail,
        parameters=admission.parameters,
    )


def _feasibility(
    intents: Sequence[TradeIntent],
    view: SessionView,
    minute: dt.datetime,
    limits: ParticipationLimits,
) -> tuple[int, tuple[Mapping[str, Any], ...], str]:
    """How many lots the market would have taken, and the verdict on every leg.

    Leg-group atomicity is applied the way the engine applies it: the whole structure takes
    the smallest size any leg was granted, and if any leg is unfillable the structure does
    not trade at all. A scan that reported per-leg sizes would be proposing half a straddle.
    """
    verdicts: list[Mapping[str, Any]] = []
    allowed = None
    blocking: list[str] = []
    for intent in sorted(intents, key=lambda i: i.trading_symbol):
        contract = view.universe.by_symbol(intent.trading_symbol)
        if contract is None:
            blocking.append(f"{intent.trading_symbol}: not in the session's instrument master")
            continue
        verdict = apply_participation_caps(
            requested_lots=intent.lots,
            lot_size=contract.lot_size,
            bar=view.bar(intent.trading_symbol, minute),
            limits=limits,
        )
        payload = dict(verdict.as_dict())
        payload["trading_symbol"] = intent.trading_symbol
        verdicts.append(payload)
        if not verdict.is_fillable:
            blocking.append(f"{intent.trading_symbol}: {verdict.reason}")
        allowed = verdict.granted_lots if allowed is None else min(allowed, verdict.granted_lots)
    granted = 0 if allowed is None or blocking else allowed
    detail = (
        "; ".join(blocking)
        if blocking
        else ("no legs to test" if allowed is None else "inside both participation caps")
    )
    return granted, tuple(verdicts), detail


def _trigger_detail(trigger: TriggerExplanation) -> str:
    if trigger.value is None:
        return (
            f"the conditioner reads {trigger.feature}, which is not available on this "
            f"session. {trigger.description}"
        )
    return (
        f"{trigger.feature} is {trigger.value:.6g} and the template requires "
        f"{trigger.comparator} {trigger.threshold:.6g}"
    )


def _no_ideas_reason(
    admitted: Sequence[AdmissionRecord],
    ideas: Sequence[Idea],
    skipped: Sequence[SkippedCandidate],
) -> str | None:
    """One sentence explaining an empty sheet, or ``None`` when it is not empty.

    An empty sheet is a legitimate and common outcome — most templates do not fire on most
    sessions — and it has to be distinguishable from a scan that failed. The reason names
    which of the two it is.
    """
    if ideas:
        return None
    if not admitted:
        return (
            "the library admits no templates, so the scan had nothing to instantiate; admit "
            "one against a decision record before expecting ideas"
        )
    counts: dict[str, int] = {}
    for skip in skipped:
        counts[skip.reason] = counts.get(skip.reason, 0) + 1
    breakdown = ", ".join(f"{reason}: {count}" for reason, count in sorted(counts.items()))
    return f"no admitted template produced a rankable idea on this session ({breakdown})"


def _as_float(value: Any) -> float | None:
    """A declared parameter as a number, or ``None`` when the strategy does not carry one.

    ``None`` rather than a zero: a template that does not size by notional has no target to
    report, and writing ``0.0`` would put a number on the sheet that contradicts the size
    the legs were actually built at.
    """
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _inside_window(as_of: dt.date, window: str | None) -> bool:
    """Whether ``as_of`` falls inside a decision record's ``start..end`` window.

    A window this cannot parse answers ``False``. The flag exists to raise a caveat when one
    is known to apply, and inventing one from an unreadable string would put a warning on a
    sheet that nothing supports.
    """
    if not window or ".." not in window:
        return False
    start, _, end = window.partition("..")
    try:
        return dt.date.fromisoformat(start) <= as_of <= dt.date.fromisoformat(end)
    except ValueError:
        return False
