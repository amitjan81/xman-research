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

**Cross-session inputs are supplied, not computed.** A strategy sees one
:class:`~xman_research.backtest.market.SessionView` at a time, so neither a condition
involving trailing realised volatility nor a strike rule widthed in average true ranges is
representable inside :meth:`Strategy.decide`. Templates that need either take pre-computed
series through :meth:`StrategyTemplate.build`, keyed by feature name, and refuse to enter
when the one they need is absent — the safe direction, since the unsafe one is a
conditional strategy silently trading unconditionally, or a structure widthed by a guess.
"""

from __future__ import annotations

import datetime as dt
import math
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
    "ATR_14",
    "DAY_OF_WEEK",
    "EMA20_Z_ABS",
    "HOLD_SESSIONS",
    "IRON_CONDOR_HOLD_N",
    "MAX_HOLD_SESSIONS",
    "MIN_HOLD_SESSIONS",
    "OVERNIGHT_GAP_SIGMAS",
    "SESSIONS_TO_NEAREST_EXPIRY",
    "SHORT_ATM_STRADDLE_HOLD_N",
    "SHORT_ATM_STRADDLE_IV_RV",
    "SHORT_ATM_STRANGLE_HOLD_N",
    "Comparator",
    "ConditionerSpec",
    "FeatureSeries",
    "HoldNIronCondor",
    "HoldNShortStraddle",
    "HoldNShortStrangle",
    "HoldNSpread",
    "LegRule",
    "ParameterRange",
    "StrategyTemplate",
    "StrengthShape",
    "TemplateRegistry",
    "UnknownTemplateError",
    "default_registry",
    "parameter_key",
    "shipped_templates",
]

#: A hold is measured in whole sessions and is bounded at both ends. Below one there is no
#: overnight exposure to hold, and above five the front weekly contract cannot survive the
#: hold on this corpus, so the position would cash-settle and the observation would stop
#: being a hold-N at all.
MIN_HOLD_SESSIONS = 1
MAX_HOLD_SESSIONS = 5

#: The parameter name under which a template declares a variable hold. Spelled once so a
#: template, its builder and :meth:`StrategyTemplate.hold_for` cannot disagree.
HOLD_SESSIONS = "hold_sessions"

#: Feature names the shipped conditioners and strike rules read. Declared here rather than in
#: :mod:`xman_research.alpha.features` because that module imports this one, and a template
#: and its feature supplier must not be able to disagree about the spelling.
ATM_IV_MINUS_RV20 = "iv_minus_rv_20"
ATR_14 = "atr_14"
EMA20_Z_ABS = "ema20_z_abs"
OVERNIGHT_GAP_SIGMAS = "overnight_gap_sigmas"
SESSIONS_TO_NEAREST_EXPIRY = "sessions_to_nearest_expiry"
DAY_OF_WEEK = "day_of_week"


def parameter_value_key(value: float) -> str:
    """One parameter value as it appears inside a :func:`parameter_key`.

    ``repr`` of the float, which is its shortest round-tripping spelling: the string
    parses back to the identical float, so a key can be read apart into the point it names
    and that point keys back to the same string. A fixed-precision format cannot promise
    that — six significant digits maps ``1234567.0`` and ``1234568.0`` onto one key, and
    ``target_notional`` ranges over rupee values where that collision is reachable.

    It is also what an equality test on a parameter value must go through, so that "the
    same point" means one thing in the library, the ledger and the ranker rather than
    three.
    """
    return repr(float(value))


def parameter_key(params: Mapping[str, float]) -> str:
    """A canonical name for one parameter point, stable across dict orderings.

    **The identity of an admission is the template id plus this key**, so the same string
    has to come out of a screened instance, an admission record and a nightly candidate.
    Spelled once here, through :func:`parameter_value_key`, so that a point read back from
    JSON as ``3.0`` names the same key as the ``3`` that was written — two spellings of one
    hold would otherwise register as two admissions of one template.

    Compare only points that have been through :meth:`StrategyTemplate.resolve`. A grid
    point carries the names the researcher listed and a resolved one carries every declared
    parameter, so keying the two against each other reports a mismatch that is an artefact
    of which defaults were spelled out.
    """
    return ",".join(
        f"{name}={parameter_value_key(value)}" for name, value in sorted(params.items())
    )


class UnknownTemplateError(KeyError):
    """A template id that no registry holds."""


class Comparator(StrEnum):
    """Which side of the threshold makes a conditioner fire.

    ``WITHIN`` is the two-sided form and is the only one that reads
    :attr:`ConditionerSpec.upper_threshold`. It exists because two of the shipped
    conditioners — sessions-to-expiry and weekday — name a *band* rather than a half-line,
    and expressing a band as two conditioners would make every consumer of
    :attr:`StrategyTemplate.conditioner` handle a collection to serve two cases.
    """

    AT_LEAST = "at_least"
    AT_MOST = "at_most"
    WITHIN = "within"


class StrengthShape(StrEnum):
    """How a fired conditioner's distance is turned into a strength in ``[0, 1]``.

    ``EXCESS_OVER_SPAN`` scales how far the value sits past the threshold.
    ``TANH_OF_MAGNITUDE`` reads the value's own magnitude through ``tanh(|value| / span)``,
    which is the right shape when the threshold is a gate and the value itself — not its
    distance past the gate — is what the strength should track. ``GATE_ONLY`` returns one
    whenever the test fires, for a conditioner whose feature carries no notion of *more*:
    a weekday is not a quantity, so any curve over it would be an invented ordering, and a
    distance-based shape would score it zero forever — which the ranker multiplies through
    to a permanent zero score.

    Both are **conventions, not measurements**, in exactly the sense
    :class:`ConditionerSpec` states for the span: nothing establishes that a value twice as
    large is twice as good, and the shape exists so two conditioners on different feature
    scales can be ordered and sized against each other at all.
    """

    EXCESS_OVER_SPAN = "excess_over_span"
    TANH_OF_MAGNITUDE = "tanh_of_magnitude"
    GATE_ONLY = "gate_only"


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
    upper_threshold: float | None = None
    """The band's far edge. Required by :attr:`Comparator.WITHIN` and refused by the others."""
    strength_shape: StrengthShape = StrengthShape.EXCESS_OVER_SPAN
    sizes_position: bool = False
    """Whether :meth:`strength` scales the exposure, rather than only ordering ideas.

    A conditioner that sizes is making a stronger claim than one that gates: it asserts the
    edge grows with the feature, not merely that it exists past a threshold. The flag is on
    the spec so that claim travels into every rationale and every screening row, instead of
    being a property of which strategy class happened to be built.
    """

    def __post_init__(self) -> None:
        if self.saturation_span <= 0:
            raise ValueError(f"saturation_span must be positive, got {self.saturation_span}")
        if self.lookback_sessions < 1:
            raise ValueError(f"lookback_sessions must be at least 1, got {self.lookback_sessions}")
        if self.comparator is Comparator.WITHIN:
            if self.upper_threshold is None:
                raise ValueError(
                    f"conditioner on {self.feature} compares WITHIN but names no "
                    "upper_threshold; a band with one edge is a half-line under the wrong name"
                )
            if self.upper_threshold < self.threshold:
                raise ValueError(
                    f"conditioner on {self.feature} declares a band [{self.threshold}, "
                    f"{self.upper_threshold}] whose upper edge is below its lower one"
                )
            if (
                self.upper_threshold == self.threshold
                and self.strength_shape is not StrengthShape.GATE_ONLY
            ):
                raise ValueError(
                    f"conditioner on {self.feature} declares the single-point band "
                    f"[{self.threshold}, {self.threshold}] under {self.strength_shape}. A "
                    "band with no interior has zero depth, so a depth-based strength is "
                    "identically zero and the ranker would score every such idea at zero "
                    "forever. Use GATE_ONLY for a feature that has no notion of `more`."
                )
        elif self.upper_threshold is not None:
            raise ValueError(
                f"conditioner on {self.feature} compares {self.comparator} and also names an "
                "upper_threshold, which nothing reads. Use WITHIN for a band."
            )

    def fires(self, value: float | None) -> bool:
        """Whether ``value`` satisfies the test. A missing feature never fires."""
        if value is None:
            return False
        if self.comparator is Comparator.AT_LEAST:
            return value >= self.threshold
        if self.comparator is Comparator.AT_MOST:
            return value <= self.threshold
        assert self.upper_threshold is not None
        return self.threshold <= value <= self.upper_threshold

    def strength(self, value: float | None) -> float:
        """How hard the conditioner fired, in ``[0, 1]``, under :attr:`strength_shape`.

        Zero when the test does not fire, so an unfired candidate cannot score above a
        fired one on strength alone.

        For a band, the distance measured is the depth *inside* the band — the smaller of
        the two edge distances — so a value hugging either edge is weak and one in the
        middle is strong.
        """
        if not self.fires(value) or value is None:
            return 0.0
        if self.strength_shape is StrengthShape.GATE_ONLY:
            return 1.0
        if self.strength_shape is StrengthShape.TANH_OF_MAGNITUDE:
            return math.tanh(abs(value) / self.saturation_span)
        if self.comparator is Comparator.AT_LEAST:
            excess = value - self.threshold
        elif self.comparator is Comparator.AT_MOST:
            excess = self.threshold - value
        else:
            assert self.upper_threshold is not None
            excess = min(value - self.threshold, self.upper_threshold - value)
        return min(1.0, max(0.0, excess / self.saturation_span))

    def as_dict(self) -> dict[str, Any]:
        return {
            "feature": self.feature,
            "comparator": str(self.comparator),
            "threshold": self.threshold,
            "upper_threshold": self.upper_threshold,
            "saturation_span": self.saturation_span,
            "strength_shape": str(self.strength_shape),
            "sizes_position": self.sizes_position,
            "lookback_sessions": self.lookback_sessions,
            "description": self.description,
        }


# ------------------------------------------------------------------ the shipped strategies


@dataclass(frozen=True, slots=True)
class LegRule:
    """One leg of a structure: where its strike sits, which right, and which side.

    ``atr_offset`` is measured in fourteen-session average true ranges away from the spot at
    the decision minute, so a structure keeps the same *risk* width as volatility changes
    rather than the same number of index points. Zero puts the leg at the money and needs no
    average true range at all, which is why the at-the-money straddle can be built from a
    session view alone while the wider structures cannot.
    """

    atr_offset: float
    option_type: str
    side: Side

    def as_dict(self) -> dict[str, Any]:
        return {
            "atr_offset": self.atr_offset,
            "option_type": self.option_type,
            "side": str(self.side),
        }


_STRADDLE_LEGS = (
    LegRule(atr_offset=0.0, option_type=OptionType.CALL, side=Side.SELL),
    LegRule(atr_offset=0.0, option_type=OptionType.PUT, side=Side.SELL),
)


def _structure_intents(
    *,
    session: SessionView,
    minute: dt.datetime,
    legs: Sequence[LegRule],
    target_notional: float,
    min_calendar_days_to_expiry: int,
    group_prefix: str,
    atr: float | None,
) -> Sequence[TradeIntent]:
    """Every leg of one structure on the nearest listed expiry, or nothing at all.

    The expiry is never rolled forward. A later contract would be a different trade with a
    different variance exposure, and on this corpus it carries no bars at all, so rolling
    would swap a stated refusal for a position priced from nothing.

    Every refusal below is a refusal to trade rather than a substitution, and each one is a
    fact about the session: no listed expiry far enough out, a broken underlying series, no
    average true range to width the structure with, a chain missing a strike the rule asks
    for, two legs that round onto the same contract, or a targeted exposure under half a
    contract. Returning the legs that *did* resolve would open a structure the template
    never described — a naked short where a spread was intended — which is what the
    all-or-nothing return and ``leg_group`` prevent between them.

    **The strike ladder is coarser than the rule.** ``atm_strike`` returns the nearest
    listed strike to the price the rule asks for, so a half-ATR offset in a calm market can
    round onto the at-the-money rung. The collision check turns that into a refusal rather
    than into a strangle silently traded as a straddle, or a condor whose wing sits on its
    own short strike and defines no risk at all.
    """
    expiry = session.universe.nearest_expiry(session.session_date)
    if expiry is None:
        return ()
    if (expiry - session.session_date).days < min_calendar_days_to_expiry:
        return ()
    spot = session.spot_at(minute)
    if spot is None or spot <= 0:
        return ()
    needs_width = any(leg.atr_offset != 0.0 for leg in legs)
    if needs_width and (atr is None or atr <= 0):
        return ()
    width = atr if atr is not None else 0.0

    resolved: list[tuple[LegRule, Contract, float]] = []
    claimed: dict[float, float] = {}
    taken: set[tuple[float, str]] = set()
    for leg in legs:
        strike = session.universe.atm_strike(spot + leg.atr_offset * width, expiry)
        if strike is None:
            return ()
        # Two legs the rule places at *different* distances from spot, landing on one rung,
        # are not the structure the template names. Keyed on the strike alone rather than on
        # the contract: a strangle's call and put never share an option type, so a key that
        # included it would let both legs collapse onto the at-the-money rung and trade a
        # straddle under the strangle's name — with the strangle's evidence attached.
        if claimed.get(strike, leg.atr_offset) != leg.atr_offset:
            return ()
        claimed[strike] = leg.atr_offset
        key = (strike, leg.option_type)
        if key in taken:
            return ()
        taken.add(key)
        contract = session.universe.get(expiry, strike, leg.option_type)
        if contract is None:
            return ()
        resolved.append((leg, contract, strike))

    lots = lots_for_notional(
        target_notional=target_notional, spot=spot, lot_size=resolved[0][1].lot_size
    )
    if lots <= 0:
        return ()
    shape = "-".join(f"{strike:g}{leg.option_type}" for leg, _, strike in resolved)
    group = f"{group_prefix}:{expiry.isoformat()}:{shape}"
    return tuple(
        TradeIntent(
            trading_symbol=contract.trading_symbol,
            side=leg.side,
            lots=lots,
            tag="entry",
            leg_group=group,
        )
        for leg, contract, _ in resolved
    )


def _exit_intents(session: SessionView, book: BookView, group: str) -> Sequence[TradeIntent]:
    """Close every open leg, as one group.

    Grouped for the same reason the entry is: closing one leg and not the other leaves the
    remainder naked, and on a defined-risk structure it is the *long* wing whose loss turns
    the position unbounded. The opposite failure — nothing closes, and the position is
    carried a session further than the hold says — is recorded by the engine as
    ``GROUP_INCOMPLETE`` rather than absorbed, so a run can report how often its holds were
    not the length it claims.

    **A leg the session's instrument master no longer lists is skipped.** No closing order
    can be expressed against a contract that is not in the universe — the engine refuses a
    composed trading symbol outright, and it is right to, because composing one is how a
    backtest comes to trade an instrument that was never listed. The position stays open and
    the exchange cash-settles it, which the run's settlement count reports.

    **A skipped leg leaves no `GROUP_INCOMPLETE`.** It is left out of the group rather than
    refused inside it, so the engine sees a complete group of whatever remains; the run's
    settlement count is the only trace that a leg went to cash settlement instead.

    Two conditions, and the second is not redundant. A contract expiring on the session date
    is dropped from that session's master, so the universe check alone would catch it; the
    explicit expiry check states the rule the corpus is expected to follow, and keeps the
    behaviour correct for a master that lists an expiring contract on its last day. Holds
    longer than a session meet the other case routinely: a weekly contract can leave the
    master a session or two before the date it expires on.
    """
    intents: list[TradeIntent] = []
    session_date = session.session_date
    for position in book.positions():
        if position.contract.expiry == session_date:
            continue
        if session.universe.by_symbol(position.contract.trading_symbol) is None:
            continue
        lots = abs(position.units) // position.contract.lot_size
        if lots <= 0:
            continue
        intents.append(
            TradeIntent(
                trading_symbol=position.contract.trading_symbol,
                side=Side.BUY if position.is_short else Side.SELL,
                lots=lots,
                tag="exit",
                leg_group=group,
            )
        )
    return tuple(intents)


@dataclass(slots=True)
class HoldNSpread:
    """Sell a short-variance structure, close it at the decision minute N sessions later.

    **The exit is a clock, not an expiry**, which is the whole difference from
    :class:`~xman_research.backtest.strategies.ShortAtmStraddle`. Holding to settlement
    measures the premium over a full variance cycle; holding a fixed number of sessions
    measures the premium over a window a nightly scan can actually promise an operator, and
    the two are different populations with different tails.

    **Cross-session inputs are supplied, not computed.** ``feature_series`` maps a feature
    name to ``{session_date: value}``, and every value must have been computed from sessions
    at or before its own date — :mod:`xman_research.alpha.features` is the supplier that
    guarantees it. Computing them here is impossible: a strategy sees one
    :class:`~xman_research.backtest.market.SessionView` and the shortest of these features
    spans fourteen.

    A session whose required feature is absent does not enter. That is the safe direction in
    both roles the series plays. For a conditioner, the alternative is a conditional
    strategy trading unconditionally on every session whose feature failed to compute, which
    makes it the benchmark family wearing a conditional name — and the benchmark is
    precisely what its evidence claims it beats. For a strike rule, the alternative is a
    structure widthed by a guess.

    **One decision minute per session is assumed.** The counter advances on a change of
    session date, so a second decision minute in the same session neither ages the position
    nor, after an exit, prevents a re-entry that same day. Configure the engine with a
    single decision time for this strategy.

    **The hold counter is per-instance run state**, so an instance belongs to exactly one
    run. :meth:`StrategyTemplate.build` mints a fresh one per call, which is what keeps a
    second run from inheriting the first's position age.

    ``min_calendar_days_to_expiry`` is a conservative conversion from a hold measured in
    *sessions* to a guard expressed in *calendar days* — the strategy cannot see the
    exchange calendar from a single session view. A holiday can still defeat it (a Friday
    entry whose Monday is shut reaches expiry on Tuesday), and in that residual case the
    contract cash-settles instead of being closed: the observation is then a
    hold-to-settlement, and the run's non-zero settlement count is the flag that says so.
    """

    hold_sessions: int = 1
    target_notional: float = 1_500_000.0
    min_calendar_days_to_expiry: int = 4
    conditioner: ConditionerSpec | None = None
    feature_series: Mapping[str, Mapping[dt.date, float]] = field(default_factory=dict)
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
    def structure(self) -> str:
        """The trade shape, as it appears in this strategy's name and its leg groups."""
        raise NotImplementedError

    def legs(self) -> tuple[LegRule, ...]:
        """Where this structure's strikes sit, relative to spot."""
        raise NotImplementedError

    @property
    def name(self) -> str:
        conditioned = f"_on_{self.conditioner.feature}" if self.conditioner else ""
        return f"hold_{self.hold_sessions}_{self.structure}{conditioned}"

    def parameters(self) -> Mapping[str, Any]:
        return {
            HOLD_SESSIONS: self.hold_sessions,
            "target_notional": self.target_notional,
            "min_calendar_days_to_expiry": self.min_calendar_days_to_expiry,
            "structure": self.structure,
            "legs": [leg.as_dict() for leg in self.legs()],
            "conditioner": self.conditioner.as_dict() if self.conditioner else None,
            "supplied_feature_series": {
                name: len(series) for name, series in sorted(self.feature_series.items())
            },
        }

    def decide(
        self, *, session: SessionView, minute: dt.datetime, book: BookView
    ) -> Sequence[TradeIntent]:
        if book.is_flat:
            self._sessions_held = 0
            self._last_counted = None
            if not self._may_enter(session.session_date):
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
        return _exit_intents(session, book, f"{self._group_prefix()}-exit")

    def feature(self, name: str, session_date: dt.date) -> float | None:
        """The supplied value of ``name`` on ``session_date``, or ``None`` if there is none."""
        return self.feature_series.get(name, {}).get(session_date)

    def _group_prefix(self) -> str:
        return f"hold-{self.hold_sessions}-{self.structure}"

    def _may_enter(self, session_date: dt.date) -> bool:
        if self.conditioner is None:
            return True
        return self.conditioner.fires(self.feature(self.conditioner.feature, session_date))

    def _notional_for(self, session_date: dt.date) -> float:
        """The exposure to target on this session, after any conditioner that sizes.

        A conditioner sizes only when its spec says so, and the multiplier is the same
        ``strength`` the ranker orders ideas by — one convention, used in both places, so a
        rationale's stated strength and the exposure actually taken cannot disagree.
        """
        if self.conditioner is None or not self.conditioner.sizes_position:
            return self.target_notional
        value = self.feature(self.conditioner.feature, session_date)
        return self.target_notional * self.conditioner.strength(value)

    def _entry(self, *, session: SessionView, minute: dt.datetime) -> Sequence[TradeIntent]:
        notional = self._notional_for(session.session_date)
        if notional <= 0:
            return ()
        return _structure_intents(
            session=session,
            minute=minute,
            legs=self.legs(),
            target_notional=notional,
            min_calendar_days_to_expiry=self.min_calendar_days_to_expiry,
            group_prefix=self._group_prefix(),
            atr=self.feature(ATR_14, session.session_date),
        )


@dataclass(slots=True)
class HoldNShortStraddle(HoldNSpread):
    """Sell the at-the-money call and put, buy them back ``hold_sessions`` later.

    The benchmark family. It needs no supplied average true range because both its legs sit
    at the money, so it is the one structure here that can be run over a corpus for which no
    feature layer has been built.
    """

    @property
    def structure(self) -> str:
        return "short_atm_straddle"

    def legs(self) -> tuple[LegRule, ...]:
        return _STRADDLE_LEGS


@dataclass(slots=True)
class HoldNShortStrangle(HoldNSpread):
    """Sell a call and a put ``atr_multiple`` average true ranges either side of spot.

    Against the straddle it trades a lower premium for a wider band of index outcomes that
    expire worthless. Which of the two is better paid is exactly the question the screening
    harness exists to measure, and the answer is a property of the corpus rather than of the
    shape.

    Both legs are short and undefended, so the loss is unbounded in both directions — see
    :class:`HoldNIronCondor` for the defined-risk form of the same view.
    """

    atr_multiple: float = 1.0

    def __post_init__(self) -> None:
        # Spelled with explicit arguments rather than as a zero-argument ``super()``. A
        # dataclass declared with ``slots=True`` is rebuilt as a new class object, and the
        # zero-argument form closes over the original one, so it raises at call time.
        super(HoldNShortStrangle, self).__post_init__()
        if self.atr_multiple <= 0:
            raise ValueError(
                "atr_multiple must be positive: at zero both legs sit at the money and the "
                f"strangle is a straddle under another name, got {self.atr_multiple}"
            )

    @property
    def structure(self) -> str:
        return "short_atm_strangle"

    def legs(self) -> tuple[LegRule, ...]:
        return (
            LegRule(atr_offset=self.atr_multiple, option_type=OptionType.CALL, side=Side.SELL),
            LegRule(atr_offset=-self.atr_multiple, option_type=OptionType.PUT, side=Side.SELL),
        )


@dataclass(slots=True)
class HoldNIronCondor(HoldNSpread):
    """A short strangle with long wings ``wing_atr_multiple`` further out on each side.

    The wings cap the loss, which changes what the position *is* rather than merely how much
    it makes: the tail an unhedged short-variance book is paid to warehouse is precisely the
    part the wings give away. It is therefore not a cheaper strangle but a different claim —
    that the premium collected between the short strikes survives paying for the insurance —
    and it is the only structure here whose worst session is knowable in advance.
    """

    atr_multiple: float = 1.0
    wing_atr_multiple: float = 1.0

    def __post_init__(self) -> None:
        # Spelled with explicit arguments rather than as a zero-argument ``super()``. A
        # dataclass declared with ``slots=True`` is rebuilt as a new class object, and the
        # zero-argument form closes over the original one, so it raises at call time.
        super(HoldNIronCondor, self).__post_init__()
        if self.atr_multiple <= 0:
            raise ValueError(f"atr_multiple must be positive, got {self.atr_multiple}")
        if self.wing_atr_multiple <= 0:
            raise ValueError(
                "wing_atr_multiple must be positive: a wing at or inside its own short "
                f"strike defines no risk, got {self.wing_atr_multiple}"
            )

    @property
    def structure(self) -> str:
        return "iron_condor"

    def legs(self) -> tuple[LegRule, ...]:
        far = self.atr_multiple + self.wing_atr_multiple
        return (
            LegRule(atr_offset=self.atr_multiple, option_type=OptionType.CALL, side=Side.SELL),
            LegRule(atr_offset=-self.atr_multiple, option_type=OptionType.PUT, side=Side.SELL),
            LegRule(atr_offset=far, option_type=OptionType.CALL, side=Side.BUY),
            LegRule(atr_offset=-far, option_type=OptionType.PUT, side=Side.BUY),
        )


def _check_hold(hold_sessions: int) -> None:
    if not MIN_HOLD_SESSIONS <= hold_sessions <= MAX_HOLD_SESSIONS:
        raise ValueError(
            f"hold_sessions must be between {MIN_HOLD_SESSIONS} and {MAX_HOLD_SESSIONS}, "
            f"got {hold_sessions}"
        )


# ------------------------------------------------------------------------ the template


#: A supplied feature series, keyed by feature name then by the session it describes.
FeatureSeries = Mapping[str, Mapping[dt.date, float]]

TemplateBuilder = Callable[[Mapping[str, float], str, FeatureSeries | None], Strategy]


@dataclass(frozen=True, slots=True)
class StrategyTemplate:
    """One trade shape the scan may instantiate, with the range it was measured over.

    A template is a trade *shape*, and carries no claim about any product: :meth:`build`
    instantiates it for whatever underlying the corpus can supply, which is what lets a
    stage-1 screen measure the shape on a product no evidence covers yet. Evidence scope
    belongs to an admission instead — an
    :class:`~xman_research.alpha.library.AdmissionRecord` names the product its evidence was
    measured on, and the ranker builds only the (template, product) pairs it admits.

    :attr:`hold_sessions` is the hold this template trades **at its declared defaults**. A
    template that lets the hold vary declares it as a parameter as well, and
    :meth:`hold_for` is then the only honest answer for a given parameter point — the field
    would describe a different trade. ``__post_init__`` refuses a declared ``hold_sessions``
    parameter whose default disagrees with the field, so the two cannot drift.
    """

    template_id: str
    name: str
    thesis: str
    hold_sessions: int
    parameters: Mapping[str, ParameterRange]
    conditioner: ConditionerSpec | None
    builder: TemplateBuilder

    def __post_init__(self) -> None:
        if not self.template_id.strip():
            raise ValueError("template_id must be non-empty")
        if not self.thesis.strip():
            raise ValueError(
                f"template {self.template_id} states no thesis. The mechanism is what an "
                "operator reads before risking money on the idea, and a template that "
                "cannot state one has nothing to rank."
            )
        _check_hold(self.hold_sessions)
        declared = self.parameters.get(HOLD_SESSIONS)
        if declared is not None:
            if int(declared.default) != self.hold_sessions:
                raise ValueError(
                    f"template {self.template_id} declares hold_sessions defaulting to "
                    f"{declared.default:g} and a hold_sessions field of {self.hold_sessions}. "
                    "The field is what the ranker reads and the default is what an "
                    "unparameterised build produces; two different holds under one name is "
                    "evidence attached to the wrong trade."
                )
            _check_hold(int(declared.low))
            _check_hold(int(declared.high))

    def hold_for(self, params: Mapping[str, float] | None = None) -> int:
        """The hold this template trades at ``params`` — the field, unless it varies."""
        resolved = self.resolve(params)
        return int(resolved.get(HOLD_SESSIONS, self.hold_sessions))

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
        feature_series: FeatureSeries | None = None,
    ) -> Strategy:
        """A runnable strategy for one product at one point in the declared ranges.

        ``feature_series`` carries every cross-session input the built strategy may need —
        a conditioner's feature, a strike rule's average true range — keyed by feature name.
        A template whose shape or conditioner spans sessions refuses to enter without it;
        see :class:`HoldNSpread` for why the series is supplied rather than computed.
        """
        if underlying is None:
            raise ValueError(
                f"template {self.template_id} was asked to build without an underlying. A "
                "template names no default product — the caller decides which product to "
                "instantiate the shape for, and the corpus decides whether it exists."
            )
        return self.builder(self.resolve(params), underlying, feature_series)

    def as_dict(self) -> dict[str, Any]:
        return {
            "template_id": self.template_id,
            "name": self.name,
            "thesis": self.thesis,
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


# ------------------------------------------------------------------- the shipped templates

_TARGET_NOTIONAL = ParameterRange(
    low=100_000.0,
    high=50_000_000.0,
    default=1_500_000.0,
    unit="INR",
    description=(
        "Rupees of underlying index exposure the structure aims at. Sizing in money rather "
        "than lots keeps every headline statistic invariant to the exchange's contract "
        "multiplier."
    ),
)

#: The hold every shipped template declares. Its default is one session, which is the hold
#: the ranker instantiates and therefore the hold every admission record describes; the
#: screening harness moves it inside the declared range to ask whether a longer one is
#: better paid.
_HOLD_SESSIONS_RANGE = ParameterRange(
    low=float(MIN_HOLD_SESSIONS),
    high=float(MAX_HOLD_SESSIONS),
    default=1.0,
    unit="sessions",
    description=(
        "Sessions the structure is held before it is closed at the decision minute. The "
        "declared ceiling is five, but what is *reachable* is narrower and is a fact about "
        "the exchange rather than about this range: NIFTY expires weekly, so no session sits "
        "more than six calendar days from the nearest expiry, and an entry demands "
        "`hold + 3` days of headroom. A hold of three therefore enters only on the session "
        "furthest from expiry, and holds of four and five never enter at all — a grid naming "
        "one produces an instance the sheet reports as `never_entered` rather than a "
        "measured row. Rolling to a later expiry would reach them and is refused: it is a "
        "different trade with a different variance exposure."
    ),
)

#: The hold both the field and the parameter carry by default. One number, referenced twice,
#: so ``StrategyTemplate.__post_init__``'s consistency check cannot be satisfied by accident.
_DEFAULT_HOLD_SESSIONS = int(_HOLD_SESSIONS_RANGE.default)

#: Calendar days of expiry headroom demanded beyond the hold. Three days covers one weekend;
#: a holiday inside the hold can still defeat it, and :class:`HoldNSpread` documents what
#: happens when it does.
_EXPIRY_HEADROOM_DAYS = 3

_ATR_MULTIPLE = ParameterRange(
    low=0.25,
    high=3.0,
    default=1.0,
    unit="ATR14 multiples",
    description=(
        "How far from spot the short strikes sit, in fourteen-session average true ranges. "
        "No value guarantees distinct strikes — the ladder is coarser than the rule, so a "
        "small multiple in a calm market rounds both legs onto one rung and the structure "
        "refuses that session outright. Above three the premium collected is negligible."
    ),
)

_WING_ATR_MULTIPLE = ParameterRange(
    low=0.25,
    high=3.0,
    default=1.0,
    unit="ATR14 multiples",
    description=(
        "How far beyond each short strike its protective wing sits, in fourteen-session "
        "average true ranges. This is the width of the defined risk."
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

_EMA_BAND_THRESHOLD = ParameterRange(
    low=0.0,
    high=3.0,
    default=0.5,
    unit="ATR multiples",
    description=(
        "How far the index must sit from its twenty-session exponential average, in units "
        "of twice the fourteen-session average true range, before the template fires."
    ),
)

_GAP_SIGMAS = ParameterRange(
    low=0.0,
    high=5.0,
    default=1.5,
    unit="per-session standard deviations",
    description=(
        "How large the overnight gap must be, against the per-session standard deviation "
        "implied by trailing realised volatility, before the template fires."
    ),
)

_EXPIRY_DISTANCE_LOW = ParameterRange(
    low=0.0,
    high=20.0,
    default=1.0,
    unit="sessions",
    description="The near edge of the sessions-to-expiry band the template trades inside.",
)

_EXPIRY_DISTANCE_HIGH = ParameterRange(
    low=0.0,
    high=20.0,
    default=3.0,
    unit="sessions",
    description="The far edge of the sessions-to-expiry band the template trades inside.",
)

_WEEKDAY = ParameterRange(
    low=0.0,
    high=4.0,
    default=1.0,
    unit="weekday index, Monday 0",
    description="The single weekday the template trades on.",
)

#: The band a fired conditioner's strength saturates over, for the implied-realised spread.
#: Six volatility points past the threshold is the whole usable range on this corpus.
_IV_RV_SPAN = 0.06

#: ``tanh(|z| / 2)`` is the band conditioner's sizing curve: it reaches about 0.76 at two
#: average-true-range multiples and flattens beyond, so an extreme dislocation sizes little
#: differently from a large one. The shape is a convention, like every saturation span here.
_EMA_BAND_SPAN = 2.0


@dataclass(frozen=True, slots=True)
class _Shape:
    """One structure, and how to build it at a parameter point.

    Kept separate from :class:`StrategyTemplate` because a shape is crossed with every
    conditioner: writing the eighteen resulting templates by hand would mean eighteen copies
    of one thesis, which is eighteen places for the thesis and the code to disagree.
    """

    slug: str
    name: str
    thesis: str
    parameters: Mapping[str, ParameterRange]
    make: Callable[[Mapping[str, float], ConditionerSpec | None, FeatureSeries | None], Strategy]


@dataclass(frozen=True, slots=True)
class _ConditionerKind:
    """One feature test a shape can be gated on, and the parameters that place it."""

    slug: str
    name: str
    thesis: str
    parameters: Mapping[str, ParameterRange]
    make: Callable[[Mapping[str, float]], ConditionerSpec]


def _hold_and_headroom(params: Mapping[str, float]) -> tuple[int, int]:
    hold = int(params[HOLD_SESSIONS])
    return hold, hold + _EXPIRY_HEADROOM_DAYS


def _make_straddle(
    params: Mapping[str, float],
    conditioner: ConditionerSpec | None,
    series: FeatureSeries | None,
) -> Strategy:
    hold, headroom = _hold_and_headroom(params)
    return HoldNShortStraddle(
        hold_sessions=hold,
        target_notional=params["target_notional"],
        min_calendar_days_to_expiry=headroom,
        conditioner=conditioner,
        feature_series=dict(series or {}),
    )


def _make_strangle(
    params: Mapping[str, float],
    conditioner: ConditionerSpec | None,
    series: FeatureSeries | None,
) -> Strategy:
    hold, headroom = _hold_and_headroom(params)
    return HoldNShortStrangle(
        hold_sessions=hold,
        target_notional=params["target_notional"],
        min_calendar_days_to_expiry=headroom,
        conditioner=conditioner,
        feature_series=dict(series or {}),
        atr_multiple=params["atr_multiple"],
    )


def _make_condor(
    params: Mapping[str, float],
    conditioner: ConditionerSpec | None,
    series: FeatureSeries | None,
) -> Strategy:
    hold, headroom = _hold_and_headroom(params)
    return HoldNIronCondor(
        hold_sessions=hold,
        target_notional=params["target_notional"],
        min_calendar_days_to_expiry=headroom,
        conditioner=conditioner,
        feature_series=dict(series or {}),
        atr_multiple=params["atr_multiple"],
        wing_atr_multiple=params["wing_atr_multiple"],
    )


_SHAPES = (
    _Shape(
        slug="short_atm_straddle",
        name="Short ATM straddle, held N sessions",
        thesis=(
            "One side of the Indian index-option market persistently demands convexity: "
            "index hedgers and structured-product desks buy downside protection with price "
            "insensitivity, and the inventory has to be warehoused by someone who is "
            "compensated for bearing crash risk. The compensation shows up as implied "
            "variance sitting above subsequently realised variance. Selling an "
            "at-the-money straddle and buying it back a fixed number of sessions later "
            "collects that spread over exactly the window an operator can be promised, "
            "rather than over a full expiry cycle whose tail is dominated by the "
            "settlement print."
        ),
        parameters={"target_notional": _TARGET_NOTIONAL},
        make=_make_straddle,
    ),
    _Shape(
        slug="short_atm_strangle",
        name="Short strangle at ±k ATR, held N sessions",
        thesis=(
            "The same variance risk premium the at-the-money straddle collects is priced "
            "across the whole strike ladder, and the wings of an index surface carry a "
            "further premium of their own: demand for out-of-the-money protection is what "
            "makes the skew. Selling a call and a put a fixed number of average true ranges "
            "either side of spot collects both, and trades a smaller premium for a band of "
            "index outcomes wide enough that most holds end with neither leg in the money. "
            "Widthing in average true ranges rather than index points keeps that band the "
            "same size in risk as volatility changes."
        ),
        parameters={"target_notional": _TARGET_NOTIONAL, "atr_multiple": _ATR_MULTIPLE},
        make=_make_strangle,
    ),
    _Shape(
        slug="iron_condor",
        name="Iron condor at ±k ATR with w-ATR wings, held N sessions",
        thesis=(
            "A short strangle is paid to warehouse an unbounded tail, and how much of that "
            "payment is compensation for the tail rather than edge is unanswerable from a "
            "strangle's own returns. Buying a wing beyond each short strike removes the "
            "tail and its payment together, leaving a position whose worst session is known "
            "at entry. The claim under test is that the premium collected between the short "
            "strikes survives paying for the insurance — a strictly harder claim than the "
            "strangle's, and the only one here an operator can size against a stated "
            "maximum loss."
        ),
        parameters={
            "target_notional": _TARGET_NOTIONAL,
            "atr_multiple": _ATR_MULTIPLE,
            "wing_atr_multiple": _WING_ATR_MULTIPLE,
        },
        make=_make_condor,
    ),
)


_CONDITIONER_KINDS = (
    _ConditionerKind(
        slug="iv_rv",
        name="on the implied-minus-realised spread",
        thesis=(
            "The variance risk premium is not constant: it is the price of warehousing "
            "convexity, and that price rises when hedging demand spikes relative to how "
            "much the index has actually been moving. The observable proxy is the gap "
            "between at-the-money implied volatility and trailing realised volatility — "
            "when implied sits well above realised, the seller is being paid more per unit "
            "of risk borne than usual."
        ),
        parameters={"iv_rv_threshold": _IV_RV_THRESHOLD},
        make=lambda params: ConditionerSpec(
            feature=ATM_IV_MINUS_RV20,
            comparator=Comparator.AT_LEAST,
            threshold=params["iv_rv_threshold"],
            saturation_span=_IV_RV_SPAN,
            lookback_sessions=20,
            description=(
                "ATM implied volatility at the decision minute minus close-to-close "
                "realised volatility over the trailing twenty sessions, both annualised."
            ),
        ),
    ),
    _ConditionerKind(
        slug="ema_atr_band",
        name="on distance from the twenty-session average",
        thesis=(
            "An index far from its own moving average has already moved, and a move that "
            "has happened is realised variance the option premium was sold against. Short "
            "variance entered after such a move is entered at a higher implied level into a "
            "market with less left to travel. This conditioner both gates on the distance "
            "and sizes with it, which is the stronger claim of the two: it asserts the edge "
            "grows with the dislocation rather than merely existing past a threshold."
        ),
        parameters={"ema_band_threshold": _EMA_BAND_THRESHOLD},
        make=lambda params: ConditionerSpec(
            feature=EMA20_Z_ABS,
            comparator=Comparator.AT_LEAST,
            threshold=params["ema_band_threshold"],
            saturation_span=_EMA_BAND_SPAN,
            strength_shape=StrengthShape.TANH_OF_MAGNITUDE,
            sizes_position=True,
            lookback_sessions=60,
            description=(
                "Magnitude of the index's distance from its twenty-session exponential "
                "average, in units of twice the fourteen-session average true range. "
                "Exposure is scaled by tanh of that magnitude over two."
            ),
        ),
    ),
    _ConditionerKind(
        slug="post_gap",
        name="after an outsized overnight gap",
        thesis=(
            "An overnight gap is variance that arrived while the option could not be "
            "hedged, and it repices the whole surface at the open. The session after a "
            "large gap therefore opens with implied volatility marked to an event already "
            "in the past, which is the cleanest form of the premium a short-variance book "
            "collects. Measuring the gap in per-session standard deviations rather than "
            "index points makes the threshold mean the same thing in a calm market and a "
            "violent one."
        ),
        parameters={"gap_sigmas": _GAP_SIGMAS},
        make=lambda params: ConditionerSpec(
            feature=OVERNIGHT_GAP_SIGMAS,
            comparator=Comparator.AT_LEAST,
            threshold=params["gap_sigmas"],
            saturation_span=2.0,
            lookback_sessions=20,
            description=(
                "Magnitude of the overnight gap against the per-session standard deviation "
                "implied by twenty-session realised volatility."
            ),
        ),
    ),
    _ConditionerKind(
        slug="expiry_distance",
        name="inside a band of sessions to expiry",
        thesis=(
            "Time decay is not spread evenly across an option's life: the share of an "
            "at-the-money premium that decays per session rises as expiry approaches, and "
            "so does the gamma the seller is short. Those two move in opposite directions "
            "for a short-variance book, so there is a band of sessions-to-expiry where the "
            "trade is best paid, and it is neither the first nor the last. A band rather "
            "than a threshold is the honest shape of that claim."
        ),
        parameters={
            "expiry_distance_low": _EXPIRY_DISTANCE_LOW,
            "expiry_distance_high": _EXPIRY_DISTANCE_HIGH,
        },
        make=lambda params: ConditionerSpec(
            feature=SESSIONS_TO_NEAREST_EXPIRY,
            comparator=Comparator.WITHIN,
            threshold=params["expiry_distance_low"],
            upper_threshold=params["expiry_distance_high"],
            saturation_span=2.0,
            lookback_sessions=1,
            description=(
                "Exchange trading days from the as-of session to the nearest listed expiry, "
                "the as-of session excluded."
            ),
        ),
    ),
    _ConditionerKind(
        slug="day_of_week",
        name="on one weekday",
        thesis=(
            "The NSE index-option cycle is weekly, so a session's weekday and its position "
            "inside the expiry cycle are the same fact. A weekday conditioner is therefore "
            "a calendar restatement of the expiry-distance one, and it is shipped alongside "
            "so the two can be screened against each other: if the edge is really about "
            "time to expiry, the weekday version should not beat it."
        ),
        parameters={"weekday": _WEEKDAY},
        make=lambda params: ConditionerSpec(
            feature=DAY_OF_WEEK,
            comparator=Comparator.WITHIN,
            threshold=params["weekday"],
            upper_threshold=params["weekday"],
            saturation_span=1.0,
            strength_shape=StrengthShape.GATE_ONLY,
            lookback_sessions=1,
            description="The as-of session's weekday, Monday zero.",
        ),
    ),
)


def _template_for(shape: _Shape, kind: _ConditionerKind | None) -> StrategyTemplate:
    """One shape, optionally gated by one conditioner, as a registrable template."""
    parameters: dict[str, ParameterRange] = {
        HOLD_SESSIONS: _HOLD_SESSIONS_RANGE,
        **dict(shape.parameters),
    }
    if kind is not None:
        parameters.update(kind.parameters)

    def builder(
        params: Mapping[str, float], underlying: str, series: FeatureSeries | None
    ) -> Strategy:
        del underlying
        return shape.make(params, kind.make(params) if kind else None, series)

    if kind is None:
        return StrategyTemplate(
            template_id=f"{shape.slug}_hold_n",
            name=shape.name,
            thesis=(
                f"{shape.thesis} It is unconditional on purpose: this is the benchmark "
                "family, and every conditional version of the same structure has to beat it "
                "on a risk-matched basis before its own evidence means anything."
            ),
            hold_sessions=_DEFAULT_HOLD_SESSIONS,
            parameters=parameters,
            conditioner=None,
            builder=builder,
        )
    return StrategyTemplate(
        template_id=f"{shape.slug}_{kind.slug}",
        name=f"{shape.name} — {kind.name}",
        thesis=(
            f"{shape.thesis} {kind.thesis} This template trades that structure and holds it "
            "for the same number of sessions as its unconditional sibling, differing in one "
            "respect only: it enters solely on sessions where the conditioner fires. The "
            "claim under test is therefore about the conditioner alone, and it is tested "
            "against the unconditional version of itself."
        ),
        hold_sessions=_DEFAULT_HOLD_SESSIONS,
        parameters=parameters,
        # The spec is placed at the parameters' declared defaults. A build at other
        # parameters carries a differently-placed spec of the same kind; this one is what
        # the ranker reads to explain an idea, and the ranker builds at defaults.
        conditioner=kind.make({name: r.default for name, r in parameters.items()}),
        builder=builder,
    )


def shipped_templates() -> tuple[StrategyTemplate, ...]:
    """Every shape crossed with every conditioner, plus each shape unconditioned."""
    return tuple(
        _template_for(shape, kind) for shape in _SHAPES for kind in (None, *_CONDITIONER_KINDS)
    )


SHORT_ATM_STRADDLE_HOLD_N = _template_for(_SHAPES[0], None)
SHORT_ATM_STRADDLE_IV_RV = _template_for(_SHAPES[0], _CONDITIONER_KINDS[0])
SHORT_ATM_STRANGLE_HOLD_N = _template_for(_SHAPES[1], None)
IRON_CONDOR_HOLD_N = _template_for(_SHAPES[2], None)


def default_registry() -> TemplateRegistry:
    """The shipped templates, in a registry of their own.

    A fresh registry per call rather than a module-level singleton: a registry is mutable,
    and a shared one lets a test that registers a template change what a later test sees.
    """
    return TemplateRegistry(shipped_templates())
