"""Strategy templates: the only things the nightly scan is allowed to propose.

**A template is Python code, registered explicitly, and adding one is a pull request.**
The alternative — a scan that composes strategies at run time from a parameter space — is
a search, and a search run nightly against the same corpus is a multiple-comparisons
machine whose trial count nobody records. Every number the scan attaches to an idea comes
from an admission record produced by the offline discovery loop, so a strategy the scan
could invent overnight would be a strategy with no evidence. The trade is stated rather
than hidden: statistical honesty is bought with the loss of overnight novelty.

**What a template owns and what it does not.** It owns the *shape* of a trade — which
instrument, which strike rule, how long it is held, and what condition makes it fire. It
does not own the decision to trade it: that is the ranker's, and the ranker will only
consider a template whose :class:`~xman_research.alpha.library.AdmissionRecord` says the
offline loop has already measured it.

**Cross-session conditioners are supplied, not computed.** A strategy sees one
:class:`~xman_research.backtest.market.SessionView` at a time, so a condition involving
trailing realised volatility is unrepresentable inside :meth:`Strategy.decide`. Templates
whose conditioner spans sessions therefore take a pre-computed series through
:meth:`StrategyTemplate.build`, and refuse to enter when none is supplied — the safe
direction, since the unsafe one is a conditional strategy silently trading unconditionally
and being compared against the benchmark family as though it were still conditional.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from xman_research.backtest.costs import Side
from xman_research.backtest.engine import BookView, Strategy, TradeIntent
from xman_research.backtest.market import Contract, OptionType, SessionView
from xman_research.backtest.strategies import lots_for_notional

__all__ = [
    "ATM_IV_MINUS_RV20",
    "MAX_HOLD_SESSIONS",
    "MIN_HOLD_SESSIONS",
    "Comparator",
    "ConditionedShortStraddle",
    "ConditionerSpec",
    "HoldNShortStraddle",
    "ParameterRange",
    "StrategyTemplate",
    "TemplateRegistry",
    "UnknownTemplateError",
    "default_registry",
]

#: A hold is measured in whole sessions and is bounded at both ends. Below one there is no
#: overnight exposure to hold, and above five the front weekly contract cannot survive the
#: hold on this corpus, so the position would cash-settle and the observation would stop
#: being a hold-N at all.
MIN_HOLD_SESSIONS = 1
MAX_HOLD_SESSIONS = 5

#: The feature name the shipped conditional template reads. Declared here so the template
#: and :mod:`xman_research.alpha.features` cannot disagree about the spelling.
ATM_IV_MINUS_RV20 = "iv_minus_rv_20"


class UnknownTemplateError(KeyError):
    """A template id that no registry holds."""


class Comparator(StrEnum):
    """Which side of the threshold makes a conditioner fire."""

    AT_LEAST = "at_least"
    AT_MOST = "at_most"


@dataclass(frozen=True, slots=True)
class ParameterRange:
    """A declared range for one template parameter, with the value used when none is given.

    The range is enforced at :meth:`StrategyTemplate.build`. It is not a suggestion: a
    parameter outside it names a strategy the offline loop never measured, so the
    admission evidence the ranker is about to attach would describe something else.
    """

    low: float
    high: float
    default: float
    unit: str = ""
    description: str = ""

    def __post_init__(self) -> None:
        if self.low > self.high:
            raise ValueError(f"low {self.low} must not exceed high {self.high}")
        if not self.low <= self.default <= self.high:
            raise ValueError(
                f"default {self.default} lies outside the declared range [{self.low}, {self.high}]"
            )

    def check(self, name: str, value: float) -> float:
        if not self.low <= value <= self.high:
            raise ValueError(
                f"{name}={value} lies outside the declared range [{self.low}, {self.high}]"
            )
        return float(value)

    def as_dict(self) -> dict[str, Any]:
        return {
            "low": self.low,
            "high": self.high,
            "default": self.default,
            "unit": self.unit,
            "description": self.description,
        }


@dataclass(frozen=True, slots=True)
class ConditionerSpec:
    """The feature test that makes a template fire, and how hard.

    ``saturation_span`` converts distance past the threshold into a strength in ``[0, 1]``.
    It is a **ranking convention, not a measurement**: nothing establishes that an idea
    twice as far past its threshold is twice as good, and the span exists so that two
    templates measured on different feature scales can be ordered against each other at
    all. A ranking that is sensitive to its exact value is a ranking about the span, which
    is why the value travels into every rationale.
    """

    feature: str
    comparator: Comparator
    threshold: float
    saturation_span: float
    lookback_sessions: int
    description: str = ""

    def __post_init__(self) -> None:
        if self.saturation_span <= 0:
            raise ValueError(f"saturation_span must be positive, got {self.saturation_span}")
        if self.lookback_sessions < 1:
            raise ValueError(f"lookback_sessions must be at least 1, got {self.lookback_sessions}")

    def fires(self, value: float | None) -> bool:
        """Whether ``value`` satisfies the test. A missing feature never fires."""
        if value is None:
            return False
        if self.comparator is Comparator.AT_LEAST:
            return value >= self.threshold
        return value <= self.threshold

    def strength(self, value: float | None) -> float:
        """Distance past the threshold, scaled to ``[0, 1]`` and saturating at the span.

        Zero when the test does not fire, so an unfired candidate cannot score above a
        fired one on strength alone.
        """
        if not self.fires(value) or value is None:
            return 0.0
        excess = (
            value - self.threshold
            if self.comparator is Comparator.AT_LEAST
            else self.threshold - value
        )
        return min(1.0, max(0.0, excess / self.saturation_span))

    def as_dict(self) -> dict[str, Any]:
        return {
            "feature": self.feature,
            "comparator": str(self.comparator),
            "threshold": self.threshold,
            "saturation_span": self.saturation_span,
            "lookback_sessions": self.lookback_sessions,
            "description": self.description,
        }


# ------------------------------------------------------------------ the shipped strategies


def _entry_intents(
    *,
    session: SessionView,
    minute: dt.datetime,
    target_notional: float,
    min_calendar_days_to_expiry: int,
    group_prefix: str,
) -> Sequence[TradeIntent]:
    """A short ATM straddle of the nearest listed expiry if it survives the hold, else nothing.

    The expiry is never rolled forward. A later contract would be a different trade with a
    different variance exposure, and on this corpus it carries no bars at all, so rolling
    would swap a stated refusal for a position priced from nothing.

    Every refusal below is a refusal to trade rather than a substitution, and each one is
    a fact about the session: no listed expiry far enough out, a broken underlying series,
    a chain missing one side of the ATM strike, or a targeted exposure under half a
    contract. Returning a single leg on the last of those would open a naked directional
    position under a market-neutral template's name, which is what ``leg_group`` and this
    guard exist between them to prevent.
    """
    expiry = session.universe.nearest_expiry(session.session_date)
    if expiry is None:
        return ()
    if (expiry - session.session_date).days < min_calendar_days_to_expiry:
        return ()
    spot = session.spot_at(minute)
    if spot is None or spot <= 0:
        return ()
    strike = session.universe.atm_strike(spot, expiry)
    if strike is None:
        return ()
    group = f"{group_prefix}:{expiry.isoformat()}:{strike:g}"
    legs: list[Contract] = []
    for option_type in (OptionType.CALL, OptionType.PUT):
        contract = session.universe.get(expiry, strike, option_type)
        if contract is None:
            return ()
        legs.append(contract)
    lots = lots_for_notional(target_notional=target_notional, spot=spot, lot_size=legs[0].lot_size)
    if lots <= 0:
        return ()
    return tuple(
        TradeIntent(
            trading_symbol=contract.trading_symbol,
            side=Side.SELL,
            lots=lots,
            tag="entry",
            leg_group=group,
        )
        for contract in legs
    )


def _exit_intents(book: BookView, session_date: dt.date, group: str) -> Sequence[TradeIntent]:
    """Buy back every short, as one group.

    Grouped for the same reason the entry is: closing one leg and not the other leaves a
    naked short. The opposite failure — neither leg closes, and the position is carried a
    session further than the hold says — is recorded by the engine as ``GROUP_INCOMPLETE``
    rather than absorbed, so a run can report how often its holds were not the length it
    claims.

    A contract expiring on ``session_date`` is skipped: the instrument master drops it on
    its own expiry date, so no buy-back can be expressed and the exchange cash-settles it.
    """
    intents: list[TradeIntent] = []
    for position in book.positions():
        if not position.is_short:
            continue
        if position.contract.expiry == session_date:
            continue
        lots = abs(position.units) // position.contract.lot_size
        if lots <= 0:
            continue
        intents.append(
            TradeIntent(
                trading_symbol=position.contract.trading_symbol,
                side=Side.BUY,
                lots=lots,
                tag="exit",
                leg_group=group,
            )
        )
    return tuple(intents)


@dataclass(slots=True)
class HoldNShortStraddle:
    """Sell an ATM straddle, buy it back at the decision minute ``hold_sessions`` later.

    **The exit is a clock, not an expiry**, which is the whole difference from
    :class:`~xman_research.backtest.strategies.ShortAtmStraddle`. Holding to settlement
    measures the premium over a full variance cycle; holding a fixed number of sessions
    measures the premium over a window a nightly scan can actually promise an operator,
    and the two are different populations with different tails.

    **One decision minute per session is assumed.** The counter advances on a change of
    session date, so a second decision minute in the same session neither ages the position
    nor, after an exit, prevents a re-entry that same day. Configure the engine with a single
    decision time for this strategy.

    **The hold counter is per-instance run state**, so an instance belongs to exactly one
    run. :meth:`StrategyTemplate.build` mints a fresh one per call, which is what keeps a
    second run from inheriting the first's position age.

    ``min_calendar_days_to_expiry`` is a conservative conversion from a hold measured in
    *sessions* to a guard expressed in *calendar days* — the strategy cannot see the
    exchange calendar from a single session view. A holiday can still defeat it (a Friday
    entry whose Monday is shut reaches expiry on Tuesday), and in that residual case the
    contract cash-settles instead of being bought back: the observation is then a
    hold-to-settlement, and the run's non-zero settlement count is the flag that says so.
    """

    hold_sessions: int = 1
    target_notional: float = 1_500_000.0
    min_calendar_days_to_expiry: int = 4
    _sessions_held: int = field(default=0, init=False, repr=False)
    _last_counted: dt.date | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        _check_hold(self.hold_sessions)
        if self.target_notional <= 0:
            raise ValueError(f"target_notional must be positive, got {self.target_notional}")
        if self.min_calendar_days_to_expiry < 1:
            raise ValueError(
                "min_calendar_days_to_expiry must be at least 1: a contract expiring on "
                "the entry session cannot be held overnight at all."
            )

    @property
    def name(self) -> str:
        return f"hold_{self.hold_sessions}_short_atm_straddle"

    def parameters(self) -> Mapping[str, Any]:
        return {
            "hold_sessions": self.hold_sessions,
            "target_notional": self.target_notional,
            "min_calendar_days_to_expiry": self.min_calendar_days_to_expiry,
        }

    def decide(
        self, *, session: SessionView, minute: dt.datetime, book: BookView
    ) -> Sequence[TradeIntent]:
        if book.is_flat:
            self._sessions_held = 0
            self._last_counted = None
            if not self._may_enter(session=session, minute=minute):
                return ()
            intents = self._entry(session=session, minute=minute)
            if intents:
                self._last_counted = session.session_date
            return intents
        if self._last_counted is None:
            # First sight of a book this instance did not open. The engine always starts a
            # run flat so this is unreachable through it, but anchoring the counter here
            # keeps "a held position is eventually exited" true for any caller.
            self._last_counted = session.session_date
        elif session.session_date > self._last_counted:
            self._sessions_held += 1
            self._last_counted = session.session_date
        if self._sessions_held < self.hold_sessions:
            return ()
        return _exit_intents(book, session.session_date, f"hold-{self.hold_sessions}-exit")

    def _may_enter(self, *, session: SessionView, minute: dt.datetime) -> bool:
        """Hook for the conditional subclass. Unconditional here, by design."""
        del session, minute
        return True

    def _entry(self, *, session: SessionView, minute: dt.datetime) -> Sequence[TradeIntent]:
        return _entry_intents(
            session=session,
            minute=minute,
            target_notional=self.target_notional,
            min_calendar_days_to_expiry=self.min_calendar_days_to_expiry,
            group_prefix=f"hold-{self.hold_sessions}",
        )


@dataclass(slots=True)
class ConditionedShortStraddle(HoldNShortStraddle):
    """A hold-N short straddle that enters only on sessions its conditioner fires.

    **The feature series is handed in, not computed.** ``signal_by_session`` maps a session
    date to the conditioner's feature value on that date, and it must have been computed
    from sessions at or before that date — :mod:`xman_research.alpha.features` is the
    supplier that guarantees it. Computing it here is impossible: the trailing realised
    volatility in the shipped conditioner spans twenty sessions and a strategy sees one.

    A session absent from the series does not enter. That is the safe direction: the
    alternative is a conditional strategy trading unconditionally on every session whose
    feature failed to compute, which makes it the benchmark family wearing a conditional
    name — and the benchmark is precisely what its evidence claims it beats.
    """

    conditioner: ConditionerSpec | None = None
    signal_by_session: Mapping[dt.date, float] = field(default_factory=dict)

    @property
    def name(self) -> str:
        feature = self.conditioner.feature if self.conditioner else "unconditional"
        return f"hold_{self.hold_sessions}_short_atm_straddle_on_{feature}"

    def parameters(self) -> Mapping[str, Any]:
        # The base call is spelled out rather than written as ``super()``. A dataclass
        # declared with ``slots=True`` is rebuilt as a new class object, and the zero-argument
        # ``super()`` in a method body closes over the original one, so it raises at call time.
        base = dict(HoldNShortStraddle.parameters(self))
        base["conditioner"] = self.conditioner.as_dict() if self.conditioner else None
        base["signal_sessions"] = len(self.signal_by_session)
        return base

    def _may_enter(self, *, session: SessionView, minute: dt.datetime) -> bool:
        del minute
        if self.conditioner is None:
            return True
        return self.conditioner.fires(self.signal_by_session.get(session.session_date))


def _check_hold(hold_sessions: int) -> None:
    if not MIN_HOLD_SESSIONS <= hold_sessions <= MAX_HOLD_SESSIONS:
        raise ValueError(
            f"hold_sessions must be between {MIN_HOLD_SESSIONS} and {MAX_HOLD_SESSIONS}, "
            f"got {hold_sessions}"
        )


# ------------------------------------------------------------------------ the template


TemplateBuilder = Callable[[Mapping[str, float], str, Mapping[dt.date, float] | None], Strategy]


@dataclass(frozen=True, slots=True)
class StrategyTemplate:
    """One trade shape the scan may instantiate, with the range it was measured over.

    ``products`` lists the underlyings the template is valid for, and :meth:`build` refuses
    any other. A template measured on NIFTY says nothing about BANKNIFTY, and letting the
    scan instantiate it there would attach NIFTY's admission evidence to a product that
    never appeared in it.
    """

    template_id: str
    name: str
    thesis: str
    products: tuple[str, ...]
    hold_sessions: int
    parameters: Mapping[str, ParameterRange]
    conditioner: ConditionerSpec | None
    builder: TemplateBuilder

    def __post_init__(self) -> None:
        if not self.template_id.strip():
            raise ValueError("template_id must be non-empty")
        if not self.products:
            raise ValueError(
                f"template {self.template_id} lists no products; a template valid for "
                "nothing can only ever produce ideas with no evidence behind them"
            )
        if not self.thesis.strip():
            raise ValueError(
                f"template {self.template_id} states no thesis. The mechanism is what an "
                "operator reads before risking money on the idea, and a template that "
                "cannot state one has nothing to rank."
            )
        _check_hold(self.hold_sessions)

    def resolve(self, params: Mapping[str, float] | None = None) -> dict[str, float]:
        """Fill defaults and enforce every declared range. Unknown names are refused."""
        supplied = dict(params or {})
        unknown = sorted(set(supplied) - set(self.parameters))
        if unknown:
            raise ValueError(
                f"template {self.template_id} declares no parameter(s) {unknown}; "
                f"declared: {sorted(self.parameters)}"
            )
        return {
            name: declared.check(name, supplied.get(name, declared.default))
            for name, declared in self.parameters.items()
        }

    def build(
        self,
        params: Mapping[str, float] | None = None,
        underlying: str | None = None,
        *,
        signal_by_session: Mapping[dt.date, float] | None = None,
    ) -> Strategy:
        """A runnable strategy for one product at one point in the declared ranges.

        ``signal_by_session`` is required by templates with a cross-session conditioner and
        ignored by those without one — see :class:`ConditionedShortStraddle` for why the
        series is supplied rather than computed.
        """
        product = underlying if underlying is not None else self.products[0]
        if product not in self.products:
            raise ValueError(
                f"template {self.template_id} is valid for {list(self.products)} and was "
                f"asked to build for {product}; its admission evidence was measured on the "
                "former and says nothing about the latter"
            )
        return self.builder(self.resolve(params), product, signal_by_session)

    def as_dict(self) -> dict[str, Any]:
        return {
            "template_id": self.template_id,
            "name": self.name,
            "thesis": self.thesis,
            "products": list(self.products),
            "hold_sessions": self.hold_sessions,
            "parameters": {name: declared.as_dict() for name, declared in self.parameters.items()},
            "conditioner": self.conditioner.as_dict() if self.conditioner else None,
        }


class TemplateRegistry:
    """Templates by id, in registration order.

    Registration is explicit and a duplicate id is refused rather than overwritten: the id
    is the key an admission record points at, so silently replacing one would re-point
    every existing admission at a different trade.
    """

    def __init__(self, templates: Sequence[StrategyTemplate] = ()) -> None:
        self._templates: dict[str, StrategyTemplate] = {}
        for template in templates:
            self.register(template)

    def register(self, template: StrategyTemplate) -> StrategyTemplate:
        if template.template_id in self._templates:
            raise ValueError(
                f"template id {template.template_id!r} is already registered; ids are the "
                "key admission records point at and cannot be reused"
            )
        self._templates[template.template_id] = template
        return template

    def get(self, template_id: str) -> StrategyTemplate:
        try:
            return self._templates[template_id]
        except KeyError:
            raise UnknownTemplateError(
                f"no template registered as {template_id!r}; registered: {sorted(self._templates)}"
            ) from None

    def __contains__(self, template_id: object) -> bool:
        return template_id in self._templates

    def __len__(self) -> int:
        return len(self._templates)

    def __iter__(self):
        return iter(self._templates.values())

    def ids(self) -> tuple[str, ...]:
        return tuple(self._templates)

    def for_product(self, underlying: str) -> tuple[StrategyTemplate, ...]:
        return tuple(t for t in self._templates.values() if underlying in t.products)


# ------------------------------------------------------------------- the shipped templates

_TARGET_NOTIONAL = ParameterRange(
    low=100_000.0,
    high=50_000_000.0,
    default=1_500_000.0,
    unit="INR",
    description=(
        "Rupees of underlying index exposure the straddle aims at. Sizing in money rather "
        "than lots keeps every headline statistic invariant to the exchange's contract "
        "multiplier."
    ),
)

_IV_RV_THRESHOLD = ParameterRange(
    low=0.0,
    high=0.30,
    default=0.03,
    unit="annualised volatility points",
    description=(
        "How far ATM implied volatility must exceed trailing 20-session realised "
        "volatility before the template fires."
    ),
)


#: The hold both shipped templates trade, shared by each template and its builder so the
#: declared length and the built strategy's length cannot drift apart.
_SHIPPED_HOLD_SESSIONS = 1

#: Calendar days of expiry headroom demanded for a hold of N sessions. Three days beyond
#: the hold covers one weekend; a holiday inside the hold can still defeat it, and
#: :class:`HoldNShortStraddle` documents what happens when it does.
_EXPIRY_HEADROOM_DAYS = 3


def _build_hold_n(
    params: Mapping[str, float], underlying: str, signal: Mapping[dt.date, float] | None
) -> Strategy:
    del underlying, signal
    return HoldNShortStraddle(
        hold_sessions=_SHIPPED_HOLD_SESSIONS,
        target_notional=params["target_notional"],
        min_calendar_days_to_expiry=_SHIPPED_HOLD_SESSIONS + _EXPIRY_HEADROOM_DAYS,
    )


def _build_iv_rv(
    params: Mapping[str, float], underlying: str, signal: Mapping[dt.date, float] | None
) -> Strategy:
    del underlying
    return ConditionedShortStraddle(
        hold_sessions=_SHIPPED_HOLD_SESSIONS,
        target_notional=params["target_notional"],
        min_calendar_days_to_expiry=_SHIPPED_HOLD_SESSIONS + _EXPIRY_HEADROOM_DAYS,
        conditioner=ConditionerSpec(
            feature=ATM_IV_MINUS_RV20,
            comparator=Comparator.AT_LEAST,
            threshold=params["iv_rv_threshold"],
            saturation_span=0.06,
            lookback_sessions=20,
        ),
        signal_by_session=dict(signal or {}),
    )


SHORT_ATM_STRADDLE_HOLD_N = StrategyTemplate(
    template_id="short_atm_straddle_hold_n",
    name="Short ATM straddle, held N sessions",
    thesis=(
        "One side of the Indian index-option market persistently demands convexity: index "
        "hedgers and structured-product desks buy downside protection with price "
        "insensitivity, and the inventory has to be warehoused by someone who is "
        "compensated for bearing crash risk. The compensation shows up as implied variance "
        "sitting above subsequently realised variance. Selling an at-the-money straddle and "
        "buying it back a fixed number of sessions later collects that spread over exactly "
        "the window an operator can be promised, rather than over a full expiry cycle whose "
        "tail is dominated by the settlement print. It is unconditional on purpose: this is "
        "the benchmark family, and every conditional short-variance template has to beat it "
        "on a risk-matched basis before its own evidence means anything."
    ),
    products=("NIFTY",),
    hold_sessions=_SHIPPED_HOLD_SESSIONS,
    parameters={"target_notional": _TARGET_NOTIONAL},
    conditioner=None,
    builder=_build_hold_n,
)

SHORT_ATM_STRADDLE_IV_RV = StrategyTemplate(
    template_id="short_atm_straddle_iv_rv",
    name="Short ATM straddle on the implied-minus-realised spread",
    thesis=(
        "The variance risk premium is not constant: it is the price of warehousing "
        "convexity, and that price rises when hedging demand spikes relative to how much "
        "the index has actually been moving. The observable proxy is the gap between "
        "at-the-money implied volatility and trailing realised volatility — when implied "
        "sits well above realised, the seller is being paid more per unit of risk borne "
        "than usual. This template trades the same short at-the-money straddle as the "
        "benchmark family and holds it for the same number of sessions, differing in one "
        "respect only: it enters solely on sessions where that spread clears a threshold. "
        "The claim under test is therefore about the conditioner alone, and it is tested "
        "against the unconditional version of itself."
    ),
    products=("NIFTY",),
    hold_sessions=_SHIPPED_HOLD_SESSIONS,
    parameters={"target_notional": _TARGET_NOTIONAL, "iv_rv_threshold": _IV_RV_THRESHOLD},
    conditioner=ConditionerSpec(
        feature=ATM_IV_MINUS_RV20,
        comparator=Comparator.AT_LEAST,
        threshold=_IV_RV_THRESHOLD.default,
        saturation_span=0.06,
        lookback_sessions=20,
        description=(
            "ATM implied volatility at the decision minute minus close-to-close realised "
            "volatility over the trailing twenty sessions, both annualised."
        ),
    ),
    builder=_build_iv_rv,
)


def default_registry() -> TemplateRegistry:
    """The shipped templates, in a registry of their own.

    A fresh registry per call rather than a module-level singleton: a registry is mutable,
    and a shared one lets a test that registers a template change what a later test sees.
    """
    return TemplateRegistry((SHORT_ATM_STRADDLE_HOLD_N, SHORT_ATM_STRADDLE_IV_RV))
