"""The backtest itself: one logged trial, one run, one reproducible answer.

**The entrypoint requires a :class:`~xman_research.evaluation.TrialContext`, and the
token is single-use.** C4's review named the hole this closes. Automatic trial logging
sees function calls, so one decorated evaluation whose body sweeps two hundred parameter
values is *one* logged trial containing a two-hundred-way selection — and that selection
is precisely the burden deflated Sharpe corrects for. A trial count understated by two
orders of magnitude does not make DSR slightly optimistic; it makes it wrong in the
direction of passing. Demanding the token proves the caller is inside a trial; burning it
means the sweep must mint two hundred trials, which is the true number, which is the
number the log then reports.

**What the token proves, and what it does not.** :class:`TrialContext` is publicly
constructible, and the log row is appended in a ``finally`` *after* the body returns, so
at the moment a backtest runs there is no row to look up. The gate therefore proves "a
``TrialContext`` was minted and this is the first backtest against it in this process" —
not "a row exists in the log". That is the strongest claim available at this point in the
lifecycle, and overclaiming it would be worse than the gap.

**The token is consumed before the run, not after.** A failed backtest still burns it. The
alternative — release on failure — hands back a retry loop, and a retry loop is a sweep
with extra steps: raise on the variants you dislike, keep the one you like, log one trial.
Re-running after a genuine bug costs a fresh trial row, and that is the correct price.

**The window comes from the token, not from the configuration.** There is no ``start`` or
``end`` in :class:`BacktestConfig`. If a caller could state the window twice, the two
could disagree, and the trial row would then be filed under a range the backtest did not
run — a row that looks comparable with every other row and is not. Taking it from
``trial.data_window`` makes the disagreement unrepresentable.

**Determinism.** No wall clock (the clock is injected and reaches nothing that affects a
number), no randomness anywhere, no iteration over an unordered container: sessions run
in date order, positions are visited in trading-symbol order, and cost components are
summed in a fixed declared order. :meth:`BacktestResult.fingerprint` reduces the whole
run to one hash so "same inputs reproduce the result" is a single assertion rather than a
tour of the output.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Protocol, runtime_checkable

from xman_research._canonical import json_safe
from xman_research.backtest.costs import (
    ZERO_COST,
    ChargeableTrade,
    Confidence,
    CostBreakdown,
    Side,
    StatutoryCostStack,
    TradeKind,
)
from xman_research.backtest.execution import (
    BarCloseFillModel,
    Feasibility,
    FeasibilityVerdict,
    FillModel,
    ParticipationLimits,
    apply_participation_caps,
)
from xman_research.backtest.lot_size import (
    LotSizeAudit,
    LotSizeContradictionError,
    audit_lot_size,
    audit_sessions,
)
from xman_research.backtest.margin import (
    MARGIN_CONFIDENCE,
    MarginRequirement,
    ShortLeg,
    SimplifiedMarginModel,
)
from xman_research.backtest.market import Contract, SessionView
from xman_research.backtest.settlement import (
    SETTLEMENT_RULES,
    SettlementRule,
    settlement_value,
)
from xman_research.evaluation import TrialContext
from xman_research.session_store import SessionStore

__all__ = [
    "BacktestConfig",
    "BacktestResult",
    "BookView",
    "DailyRecord",
    "FillRecord",
    "SettlementRecord",
    "Strategy",
    "TokenAlreadyUsedError",
    "TradeIntent",
    "run_backtest",
]


class TokenAlreadyUsedError(Exception):
    """A second backtest was attempted against a trial token that has already run one."""


#: Trial ids that have already run a backtest **in this process**. Deliberately module
#: state: the property being enforced is per-token, and the token has ``__slots__`` with
#: no ``__weakref__``, so it cannot be tracked by identity in a weak set. Trial ids are
#: minted with uuid4, so two tests never collide and the set never needs clearing.
_CONSUMED_TRIAL_IDS: set[str] = set()


@runtime_checkable
class Strategy(Protocol):
    """A trading rule, called once per session at the configured decision minute.

    **Once per session is the MVP's deliberate narrowing.** Intraday signal evaluation is
    a loop over 375 minutes rather than one, and H1 — a variance risk premium harvested by
    holding a short position across days — does not need it. What the shape must not do is
    make intraday impossible later, and it does not: the engine already resolves bars by
    minute, so widening this to a minute loop is a change to the caller of
    :meth:`decide`, not to anything below it.
    """

    @property
    def name(self) -> str: ...

    def parameters(self) -> Mapping[str, Any]: ...

    def decide(
        self, *, session: SessionView, minute: dt.datetime, book: BookView
    ) -> Sequence[TradeIntent]: ...


@dataclass(frozen=True, slots=True)
class TradeIntent:
    """What a strategy wants to do, before the market is asked whether it could.

    ``lots`` is always positive; direction lives in ``side``. ``tag`` is free text that
    travels to the fill record — "entry", "exit", "roll" — so a feasibility failure can be
    attributed to the part of the strategy that suffered it.
    """

    trading_symbol: str
    side: Side
    lots: int
    tag: str = "entry"
    leg_group: str | None = None
    """Legs sharing a non-``None`` value fill together at one size, or not at all.

    **Without this, a multi-leg structure has no atomicity and the engine cannot notice.**
    Intents were executed independently: a straddle whose CE was fillable and whose PE
    came back ``NO_LIQUIDITY`` left a *naked short call* held to expiry, and a straddle
    whose two legs hit different participation caps left an unbalanced one — both under a
    market-neutral hypothesis's name, both with no flag, no metric and nothing C6 could
    condition on. The strategy cannot prevent it either: ``ShortAtmStraddle`` guards that
    both legs are *listed*, which is a different question from whether both *fill*.

    The rule the engine enforces is: if any leg in the group is unfillable, none of them
    trade (:attr:`~xman_research.backtest.execution.Feasibility.GROUP_INCOMPLETE`); and
    if the caps grant different sizes across the group, all legs take the smallest, so the
    structure shrinks but stays balanced. Shrinking is preferred to refusing because a
    smaller straddle is still the hypothesis, whereas half a straddle is not. Every leg
    the group altered is marked
    :attr:`~xman_research.backtest.execution.FeasibilityVerdict.group_bound`.

    ``None`` means the intent stands alone and is executed exactly as before.
    """

    def __post_init__(self) -> None:
        if self.lots <= 0:
            raise ValueError(f"lots must be positive, got {self.lots}; direction is `side`")


@dataclass(frozen=True, slots=True)
class Position:
    """A signed position in one contract. Negative units are short.

    ``last_mark`` is the most recent observed price per unit — the fill price at entry,
    then each session's last printed close. It exists so an unmarkable session can carry
    the position forward at its last known value instead of at zero. Marking to zero is
    not the conservative choice it looks like: for a **short** position a zero mark
    removes a negative from the book and equity *rises* by the whole unrealised premium.
    Since the only strategy shipped here is short-only, the tempting simplification is
    precisely the one that flatters the result.
    """

    contract: Contract
    units: int
    last_mark: float

    @property
    def is_short(self) -> bool:
        return self.units < 0


class BookView:
    """What a strategy is allowed to see about its own book: positions and cash.

    Read-only by construction — there is no method here that changes anything. A strategy
    that could mutate the book directly would be able to trade without a feasibility
    verdict, which is the one thing the engine exists to prevent.
    """

    def __init__(self, positions: Mapping[str, Position], cash: float) -> None:
        self._positions = dict(positions)
        self._cash = cash

    @property
    def cash(self) -> float:
        return self._cash

    @property
    def is_flat(self) -> bool:
        return not self._positions

    def positions(self) -> tuple[Position, ...]:
        """Open positions in trading-symbol order."""
        return tuple(self._positions[symbol] for symbol in sorted(self._positions))

    def position(self, trading_symbol: str) -> Position | None:
        return self._positions.get(trading_symbol)


@dataclass(frozen=True, slots=True)
class FillRecord:
    """One attempted trade and its verdict — recorded whether or not it filled."""

    session_date: dt.date
    minute: dt.datetime
    trading_symbol: str
    side: Side
    tag: str
    requested_lots: int
    filled_lots: int
    lot_size: int
    price: float
    gross_value: float
    costs: CostBreakdown
    feasibility: FeasibilityVerdict

    @property
    def filled(self) -> bool:
        return self.filled_lots > 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "session_date": self.session_date.isoformat(),
            "minute": self.minute.isoformat(),
            "trading_symbol": self.trading_symbol,
            "side": str(self.side),
            "tag": self.tag,
            "requested_lots": self.requested_lots,
            "filled_lots": self.filled_lots,
            "lot_size": self.lot_size,
            "price": self.price,
            "gross_value": self.gross_value,
            "costs": self.costs.as_dict(),
            "feasibility": self.feasibility.as_dict(),
        }


@dataclass(frozen=True, slots=True)
class SettlementRecord:
    """One position cash-settled at expiry.

    Carries its own feasibility verdict — always :attr:`Feasibility.SETTLED` — because the
    acceptance criterion asks that *every* entry and exit carry one, and a settlement is
    an exit. It is the one exit nobody can fail to receive: the exchange performs it, and
    no participation cap applies.
    """

    session_date: dt.date
    trading_symbol: str
    units: int
    settlement_value: float
    intrinsic_per_unit: float
    cash_flow: float
    costs: CostBreakdown
    feasibility: FeasibilityVerdict
    rule_effective_from: dt.date
    rule_method: str = ""
    rule_confidence: str = ""
    """The settlement rule's own confidence tier, carried so it can reach the result.

    It could not before: the engine collected ``unverified_inputs`` from
    :class:`CostBreakdown` alone, so the settlement methodology — CORROBORATED, and
    computing an *unweighted* mean of minute closes where the exchange's rule is
    volume-weighted — was invisible to the one field C6 reads to decide whether a result
    is evaluable. It shapes every held-to-expiry payoff, which is all of them for the
    strategy shipped here."""

    def as_dict(self) -> dict[str, Any]:
        return {
            "session_date": self.session_date.isoformat(),
            "trading_symbol": self.trading_symbol,
            "units": self.units,
            "settlement_value": self.settlement_value,
            "intrinsic_per_unit": self.intrinsic_per_unit,
            "cash_flow": self.cash_flow,
            "costs": self.costs.as_dict(),
            "feasibility": self.feasibility.as_dict(),
            "rule_effective_from": self.rule_effective_from.isoformat(),
            "rule_method": self.rule_method,
            "rule_confidence": self.rule_confidence,
        }


@dataclass(frozen=True, slots=True)
class DailyRecord:
    """End-of-session state: the series C6 computes its statistics from."""

    session_date: dt.date
    cash: float
    open_position_value: float
    equity: float
    margin: MarginRequirement
    open_positions: int
    stale_marks: int = 0
    """Open positions carried at a previous session's price because none printed today.

    A non-zero value means that session's equity is partly an estimate. It is counted
    rather than silently absorbed, so C6 can refuse to compute a return series over a
    stretch where the marks went stale."""
    unmargined_shorts: int = 0
    """Short legs charged no margin because the underlying printed no bar this session.

    The same failure class as :attr:`stale_marks` and it was silent: margin is a
    percentage of *underlying* notional, so with no spot the leg contributes nothing and
    the session's margin simply reads lower — which flatters
    :attr:`BacktestResult.return_on_peak_margin`, whose denominator this is. Counted for
    the same reason ``stale_marks`` is: a zero that means "not measured" must not be
    readable as a zero that means "none required"."""

    def as_dict(self) -> dict[str, Any]:
        return {
            "session_date": self.session_date.isoformat(),
            "cash": self.cash,
            "open_position_value": self.open_position_value,
            "equity": self.equity,
            "margin": self.margin.as_dict(),
            "open_positions": self.open_positions,
            "stale_marks": self.stale_marks,
            "unmargined_shorts": self.unmargined_shorts,
        }


@dataclass(frozen=True, slots=True)
class BacktestConfig:
    """Everything about a run except the window, which comes from the trial token.

    ``gap_reason`` is the only way past a range with missing sessions, and it is passed
    straight to :meth:`Resolution.accept_gaps` — the store's rule, not a second one. Left
    ``None``, an incomplete range raises and the run does not happen.
    """

    underlying: str = "NIFTY"
    decision_time: dt.time = dt.time(9, 20)
    starting_cash: float = 1_000_000.0
    limits: ParticipationLimits = field(default_factory=ParticipationLimits)
    fill_model: FillModel = field(default_factory=BarCloseFillModel)
    margin_model: SimplifiedMarginModel = field(default_factory=SimplifiedMarginModel)
    cost_stack: StatutoryCostStack = field(default_factory=StatutoryCostStack)
    settlement_rules: tuple[SettlementRule, ...] = SETTLEMENT_RULES
    gap_reason: str | None = None
    verify_checksums: bool = False
    decision_times: tuple[dt.time, ...] | None = None
    """Every minute-of-day the strategy is asked to decide, or ``None`` for just one.

    **One decision per session was an assumption, not a law, and it excluded a whole class
    of hypothesis.** A question about *when* a return accrues — H26's overnight/intraday
    split is the worked case — cannot be asked at all with one observation point per day:
    separating the close-to-open return from the open-to-close return requires the book to
    be actionable at both ends of the session. No strategy can work around it, because
    :func:`run_backtest` and not the strategy owns the clock.

    ``None`` means ``(decision_time,)`` and is the default, so every run written before
    this field existed behaves *identically* — see :meth:`resolved_decision_times`. That
    equivalence is load-bearing rather than polite: H1's decision is committed with a run
    fingerprint taken over this very provenance dict, and a key that appeared in it
    unconditionally would silently invalidate the one result this repository has already
    published. Hence the conditional key in :meth:`provenance`.
    """

    def resolved_decision_times(self) -> tuple[dt.time, ...]:
        """The decision times actually used: ascending, deduplicated.

        Sorted rather than taken in the order given, so the book is always acted on
        chronologically — a strategy handed its close decision before its open decision
        would be reasoning about a book from the future.
        """
        if self.decision_times is None:
            return (self.decision_time,)
        if not self.decision_times:
            raise ValueError(
                "decision_times is empty: a run with no decision minute could never "
                "trade, and would report a flat book as a result rather than as a "
                "misconfiguration. Pass None for the single-decision default."
            )
        return tuple(sorted(set(self.decision_times)))

    def provenance(self) -> dict[str, Any]:
        provenance: dict[str, Any] = {
            "underlying": self.underlying,
            "decision_time": self.decision_time.isoformat(),
            "starting_cash": self.starting_cash,
            "max_pct_of_bar_volume": self.limits.max_pct_of_bar_volume,
            "max_pct_of_open_interest": self.limits.max_pct_of_open_interest,
            "fill_model": self.fill_model.name,
            "fill_assumptions": self.fill_model.assumptions,
            "margin_assumptions": self.margin_model.assumptions,
            "settlement_rules": [rule.effective_from.isoformat() for rule in self.settlement_rules],
            # Every rate the stack could apply, with its source and confidence. Without
            # this a stored result could not say which rates produced it — the method
            # existed, was JSON-safe and deterministic, and nothing called it, so the
            # provenance it was written for never reached a single run.
            "cost_schedules": [dict(entry) for entry in self.cost_stack.schedule_provenance()],
            "gap_reason": self.gap_reason,
        }
        # Present only when a run actually asked for more than one decision minute. See
        # the field docstring: an unconditional key would change the provenance dict of
        # every single-decision run, and the fingerprint hashed over it, retroactively
        # breaking H1's committed record for a run whose behaviour did not change.
        if self.decision_times is not None:
            provenance["decision_times"] = [
                value.isoformat() for value in self.resolved_decision_times()
            ]
        return provenance


@dataclass(frozen=True)
class BacktestResult:
    """What one run produced, and everything needed to argue with it.

    **No timestamp reaches the fingerprint.** The store's ``resolved_at`` travels in
    :attr:`data_provenance` because a provenance record that cannot say when the files
    were read is worth less than one that can — but :meth:`fingerprint` drops it, and it
    is the only field so dropped. Nothing else here is clock-derived. When the run itself
    happened is the trial log's business, and it is recorded there.
    """

    trial_id: str
    underlying: str
    start: dt.date
    end: dt.date
    sessions_run: int
    fills: tuple[FillRecord, ...]
    settlements: tuple[SettlementRecord, ...]
    daily: tuple[DailyRecord, ...]
    total_costs: CostBreakdown
    config_provenance: dict[str, Any]
    data_provenance: dict[str, Any]
    strategy_name: str
    strategy_parameters: dict[str, Any]
    unverified_inputs: tuple[str, ...]

    @property
    def final_equity(self) -> float:
        return self.daily[-1].equity if self.daily else 0.0

    @property
    def net_pnl(self) -> float:
        return self.final_equity - float(self.config_provenance["starting_cash"])

    @property
    def peak_margin(self) -> float:
        return max((record.margin.total for record in self.daily), default=0.0)

    @property
    def return_on_peak_margin(self) -> float | None:
        """Net P&L over the largest margin the book ever required.

        ``None`` when the book never held a short leg — a return on zero capital is not a
        large number, it is not a number. See :mod:`xman_research.backtest.margin` for how
        approximate the denominator is.
        """
        peak = self.peak_margin
        return None if peak <= 0 else self.net_pnl / peak

    def feasibility_counts(self) -> dict[str, int]:
        """How many intents landed in each verdict, entries and exits together."""
        counts: dict[str, int] = {}
        for verdict in Feasibility:
            counts[str(verdict)] = 0
        for fill in self.fills:
            counts[str(fill.feasibility.verdict)] += 1
        for settled in self.settlements:
            counts[str(settled.feasibility.verdict)] += 1
        return counts

    def resized_fills(self) -> tuple[FillRecord, ...]:
        """Every fill a participation cap cut down — the record the criterion asks for."""
        return tuple(fill for fill in self.fills if fill.feasibility.was_resized)

    def metrics(self) -> dict[str, Any]:
        """The scalar summary that goes into the trial log row.

        Deliberately excludes anything C6 owns: no Sharpe, no deflated Sharpe, no
        cost-breakeven multiple. The backtester's job is to produce an honest P&L series
        and the frictions that shaped it; computing a statistic *and* judging it in the
        same component is how a backtest starts grading itself.
        """
        counts = self.feasibility_counts()
        return {
            "sessions_run": self.sessions_run,
            "fills_attempted": len(self.fills),
            "fills_filled": sum(1 for fill in self.fills if fill.filled),
            "fills_resized": len(self.resized_fills()),
            "fills_infeasible": (
                counts[str(Feasibility.NO_BAR)]
                + counts[str(Feasibility.NO_LIQUIDITY)]
                + counts[str(Feasibility.CAPPED_TO_ZERO)]
                + counts[str(Feasibility.GROUP_INCOMPLETE)]
            ),
            # Legs whose outcome was decided by a sibling rather than by their own
            # liquidity. Non-zero means the market let part of a structure through and not
            # the rest, which changes which hypothesis the run actually tested.
            "fills_group_bound": sum(1 for fill in self.fills if fill.feasibility.group_bound),
            "sessions_with_unmargined_shorts": sum(
                1 for record in self.daily if record.unmargined_shorts
            ),
            "settlements": len(self.settlements),
            "net_pnl": self.net_pnl,
            "final_equity": self.final_equity,
            "total_costs": self.total_costs.total,
            "cost_stt": self.total_costs.stt,
            "cost_stt_on_exercise": self.total_costs.stt_on_exercise,
            "peak_margin": self.peak_margin,
            "return_on_peak_margin": self.return_on_peak_margin,
            "unverified_inputs": list(self.unverified_inputs),
            "fingerprint": self.fingerprint(),
        }

    def equity_curve(self) -> tuple[tuple[dt.date, float], ...]:
        """The series C6 turns into returns."""
        return tuple((record.session_date, record.equity) for record in self.daily)

    def as_dict(self) -> dict[str, Any]:
        return {
            "trial_id": self.trial_id,
            "underlying": self.underlying,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "sessions_run": self.sessions_run,
            "strategy_name": self.strategy_name,
            "strategy_parameters": self.strategy_parameters,
            "config": self.config_provenance,
            "data": self.data_provenance,
            "fills": [fill.as_dict() for fill in self.fills],
            "settlements": [settled.as_dict() for settled in self.settlements],
            "daily": [record.as_dict() for record in self.daily],
            "total_costs": self.total_costs.as_dict(),
            "unverified_inputs": list(self.unverified_inputs),
        }

    def fingerprint(self) -> str:
        """A hash over everything the run produced, excluding the trial id.

        The trial id is excluded on purpose: two runs of identical inputs necessarily
        carry different trial ids — the token is single-use — so including it would make
        the reproducibility criterion impossible to satisfy rather than hard to violate.
        ``resolved_at`` is excluded from the data provenance for the same reason, and is
        the only field so excluded.

        **It covers input *content* only via the manifest's sha256s.** The digests reach
        this hash through :attr:`data_provenance`, so when the manifest is available two
        runs over different bytes cannot collide. When it is not — ``manifest_available:
        False`` — the provenance names files and dates but nothing derived from their
        contents, and two runs over materially different bytes at the same paths would
        fingerprint identically. The hash is then a statement about the run, not about the
        data underneath it.
        """
        payload = self.as_dict()
        payload.pop("trial_id")
        data = dict(payload["data"])
        data.pop("resolved_at", None)
        payload["data"] = data
        canonical = json.dumps(json_safe(payload), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()


def run_backtest(
    trial: TrialContext,
    *,
    store: SessionStore,
    strategy: Strategy,
    config: BacktestConfig | None = None,
) -> BacktestResult:
    """Run ``strategy`` over the trial's window and return what happened.

    ``trial`` is positional and first because it is not optional in any sense — the
    signature should read as "a backtest is something a trial does".
    """
    config = config if config is not None else BacktestConfig()
    _consume_token(trial)

    window = trial.data_window
    resolution = store.resolve(config.underlying, window.start, window.end)
    if config.gap_reason is not None:
        refs = resolution.accept_gaps(config.gap_reason)
    else:
        refs = resolution.sessions()

    cash = config.starting_cash
    positions: dict[str, Position] = {}
    fills: list[FillRecord] = []
    settlements: list[SettlementRecord] = []
    daily: list[DailyRecord] = []
    total_costs = ZERO_COST
    unverified: set[str] = set()
    audits: list[LotSizeAudit] = []

    for ref in refs:
        frame = store.load_session(ref, verify=config.verify_checksums)
        refdata = store.load_refdata(ref)
        # Before anything is sized: does this session's declared lot size survive contact
        # with its own bars? See xman_research.backtest.lot_size for the December 2025
        # regime this found, and for why the refusal is not overridable.
        audit = audit_lot_size(
            session_date=ref.session_date,
            underlying=config.underlying,
            frame=frame,
            refdata=refdata,
        )
        if audit.contradicts_declared:
            raise LotSizeContradictionError(audit.failure_message(), audit)
        audits.append(audit)
        if audit.non_conforming_symbols:
            unverified.add(
                f"corpus.open_interest_not_divisible_by_lot_size:{Confidence.UNVERIFIED}"
            )
        session = SessionView.from_frame(ref.session_date, config.underlying, frame, refdata)

        # **Margin is measured before settlement, not after.** _settle_expiring removes
        # every position expiring today, and a margin computed on what remains can never
        # see an expiry-day leg — which made the 2% expiry-day ELM, the one margin
        # component with a date and a worked source, structurally unreachable outside its
        # own unit tests. It also understated the truth on its own terms: a short straddle
        # held 09:20 to 15:30 on expiry day had the exchange demanding SPAN + exposure +
        # ELM all day, while the book recorded zero. peak_margin is the ROC denominator.
        #
        # **With several decision minutes it is measured at each and the largest kept.**
        # A book that is short all day and flat by the close ties up margin all day, and
        # reading it once at the end would report zero for a session that was margined
        # throughout — the same understatement the paragraph above was written about,
        # arriving through a different door. For a single decision minute this reduces to
        # exactly one measurement taken after that minute, which is what it always was.
        margin: MarginRequirement | None = None
        unmargined = 0
        for minute in _decision_minutes(session, config):
            # The strategy sees the session truncated at its decision minute, never the
            # whole day. See SessionView.through for why this is the engine's job.
            intents = strategy.decide(
                session=session.through(minute), minute=minute, book=BookView(positions, cash)
            )
            session_fills, cash = _execute_all(intents, session, minute, config, cash, positions)
            for record in session_fills:
                fills.append(record)
                total_costs = total_costs + record.costs
                unverified.update(record.costs.unverified_components)
            step_margin, step_unmargined = _margin_for_session(session, config, positions)
            if margin is None or step_margin.total > margin.total:
                margin, unmargined = step_margin, step_unmargined

        if margin is None:
            # No decision minute resolved — the session ended before the strategy's first
            # decision time. The book still carries whatever it carried in, and it is
            # still margined; this is the pre-existing behaviour for that case.
            margin, unmargined = _margin_for_session(session, config, positions)

        session_settlements, cash = _settle_expiring(session, config, cash, positions)
        for record in session_settlements:
            settlements.append(record)
            total_costs = total_costs + record.costs
            unverified.update(record.costs.unverified_components)
            unverified.add(_settlement_rule_input(record))

        daily.append(_close_of_session(session, config, cash, positions, margin, unmargined))

    # The margin approximation is never sourced well enough to be treated as verified, so
    # every run carries the flag whether or not any short leg was ever held. A run with no
    # margin exposure has a trivially correct margin number and the flag is harmless; a run
    # that quietly dropped the flag when the book happened to be flat would be the kind of
    # conditional honesty that is worse than none.
    unverified.add(f"margin.simplified_approximation:{MARGIN_CONFIDENCE}")

    result = BacktestResult(
        trial_id=trial.trial_id,
        underlying=config.underlying,
        start=window.start,
        end=window.end,
        sessions_run=len(refs),
        fills=tuple(fills),
        settlements=tuple(settlements),
        daily=tuple(daily),
        total_costs=total_costs,
        config_provenance=config.provenance(),
        data_provenance={**resolution.provenance(), "lot_size_audit": audit_sessions(audits)},
        strategy_name=strategy.name,
        strategy_parameters=dict(strategy.parameters()),
        unverified_inputs=tuple(sorted(unverified)),
    )

    trial.record_params(
        backtest_token_consumed=True,
        strategy=strategy.name,
        **{f"strategy.{key}": value for key, value in sorted(result.strategy_parameters.items())},
    )
    trial.record_metrics(result.metrics())
    if result.unverified_inputs:
        trial.add_note("computed with unverified inputs: " + ", ".join(result.unverified_inputs))
    return result


def _consume_token(trial: TrialContext) -> None:
    """Burn the token, or refuse the run. See the module docstring for why, at length."""
    if not isinstance(trial, TrialContext):
        raise TypeError(
            f"a backtest needs a TrialContext, got {type(trial).__name__}. Run it inside "
            "session.trial(...) or a @session.evaluation(...) body so the trial is logged."
        )
    if trial.trial_id in _CONSUMED_TRIAL_IDS:
        raise TokenAlreadyUsedError(
            f"trial {trial.trial_id} has already run a backtest. One token, one run: a "
            "token reused across a parameter sweep would log 200 evaluations as one "
            "trial, and the trial count is what deflated Sharpe corrects with. Open a "
            "new trial per backtest — that is the true count."
        )
    _CONSUMED_TRIAL_IDS.add(trial.trial_id)


def _decision_minutes(session: SessionView, config: BacktestConfig) -> tuple[dt.datetime, ...]:
    """The minutes this session's strategy is actually asked to decide at.

    Each configured time-of-day resolves through
    :meth:`SessionView.minute_at_or_after`, which is why a session that ends early simply
    yields fewer decisions instead of raising: "the market shut before your close
    decision" is a fact about the session, and the run should record a missed decision
    rather than invent a minute that never printed.

    **Deduplicated, and that matters on short sessions.** Two configured times can resolve
    to the same printed minute — an open decision at 09:15 and a close decision at 15:25
    both land on the only bar of a one-minute session. Asking the strategy twice at one
    minute would let it act twice on one observation, opening and closing a position
    against a single price, which is not a round trip anyone could have made.
    """
    minutes: list[dt.datetime] = []
    for time_of_day in config.resolved_decision_times():
        minute = session.minute_at_or_after(time_of_day)
        if minute is not None and minute not in minutes:
            minutes.append(minute)
    return tuple(minutes)


@dataclass(frozen=True, slots=True)
class _Proposal:
    """One intent, priced and judged, before its leg group has had its say."""

    intent: TradeIntent
    contract: Contract
    bar: Any
    verdict: FeasibilityVerdict


def _execute_all(
    intents: Sequence[TradeIntent],
    session: SessionView,
    minute: dt.datetime,
    config: BacktestConfig,
    cash: float,
    positions: dict[str, Position],
) -> tuple[list[FillRecord], float]:
    """Judge every intent, then let each leg group decide as one.

    Two passes, and the order matters: nothing may be applied to the book until every leg
    of its group has a verdict, because the group's answer depends on all of them. Doing
    it in one pass is what allowed a half-filled straddle.
    """
    records: list[FillRecord] = []
    for group in _group_intents(intents):
        proposals = [_propose(intent, session, minute, config) for intent in group]
        grant = _group_grant(proposals)
        for proposal in proposals:
            record, cash = _apply(proposal, grant, session, minute, config, cash, positions)
            records.append(record)
    return records, cash


def _group_intents(intents: Sequence[TradeIntent]) -> list[list[TradeIntent]]:
    """Intents bucketed by leg group, in first-appearance order.

    An intent with no ``leg_group`` becomes its own single-member group, so the atomicity
    rule below reduces to exactly the previous behaviour for it rather than to a special
    case that has to be maintained separately.
    """
    groups: dict[Any, list[TradeIntent]] = {}
    for index, intent in enumerate(intents):
        key = intent.leg_group if intent.leg_group is not None else ("", index)
        groups.setdefault(key, []).append(intent)
    return list(groups.values())


def _group_grant(proposals: Sequence[_Proposal]) -> int:
    """The one size the whole group trades at: zero, or the smallest any leg was granted."""
    if any(not proposal.verdict.is_fillable for proposal in proposals):
        return 0
    return min(proposal.verdict.granted_lots for proposal in proposals)


def _apply(
    proposal: _Proposal,
    grant: int,
    session: SessionView,
    minute: dt.datetime,
    config: BacktestConfig,
    cash: float,
    positions: dict[str, Position],
) -> tuple[FillRecord, float]:
    """Book one leg at the size its group settled on."""
    intent, contract, bar = proposal.intent, proposal.contract, proposal.bar
    verdict = proposal.verdict
    if grant < verdict.granted_lots:
        blocked = intent.leg_group or ""
        if grant <= 0:
            verdict = replace(
                verdict,
                verdict=Feasibility.GROUP_INCOMPLETE,
                granted_lots=0,
                group_bound=True,
                reason=(
                    f"this leg was fillable, but leg group '{blocked}' had a leg that was "
                    "not, so none of them traded — filling this one alone would leave an "
                    "unbalanced or naked position under the structure's name"
                ),
            )
        else:
            verdict = replace(
                verdict,
                verdict=Feasibility.RESIZED,
                granted_lots=grant,
                group_bound=True,
                reason=(
                    f"cut from {verdict.granted_lots} lots to {grant} to match the "
                    f"smallest size any leg of group '{blocked}' was granted, so the "
                    "structure stays balanced"
                ),
            )

    if not verdict.is_fillable or bar is None:
        return (
            FillRecord(
                session_date=session.session_date,
                minute=minute,
                trading_symbol=intent.trading_symbol,
                side=intent.side,
                tag=intent.tag,
                requested_lots=intent.lots,
                filled_lots=0,
                lot_size=contract.lot_size,
                price=0.0,
                gross_value=0.0,
                costs=ZERO_COST,
                feasibility=verdict,
            ),
            cash,
        )
    return _book(intent, contract, bar, verdict, session, minute, config, cash, positions)


def _propose(
    intent: TradeIntent,
    session: SessionView,
    minute: dt.datetime,
    config: BacktestConfig,
) -> _Proposal:
    """Ask the market whether the intent was possible. Changes nothing."""
    contract = session.universe.by_symbol(intent.trading_symbol)
    if contract is None:
        raise KeyError(
            f"{intent.trading_symbol} is not in the instrument master for "
            f"{session.session_date}. A strategy must choose contracts from "
            "session.universe; composing a trading symbol is how a backtest trades an "
            "instrument that was never listed."
        )
    bar = session.bar(intent.trading_symbol, minute)
    verdict = apply_participation_caps(
        requested_lots=intent.lots,
        lot_size=contract.lot_size,
        bar=bar,
        limits=config.limits,
    )
    if bar is None and not session.has_bars_for(intent.trading_symbol):
        # Distinguishable and worth distinguishing: an instrument that printed nothing all
        # session is almost always a capture-scope gap on this corpus — capture ran with
        # the expiry ladder pinned to the front contract, so the instrument master lists
        # contracts the bar file has never carried. Reporting that as "no evidence any
        # trade was possible" would blame the market for a decision made in the pipeline.
        verdict = replace(
            verdict,
            reason=(
                f"{intent.trading_symbol} printed no bar at any minute this session — on "
                "this corpus that is usually capture scope (front expiry only, spec 3 C1) "
                "rather than a market fact, and the two must not be read the same way"
            ),
        )
    return _Proposal(intent=intent, contract=contract, bar=bar, verdict=verdict)


def _book(
    intent: TradeIntent,
    contract: Contract,
    bar: Any,
    verdict: FeasibilityVerdict,
    session: SessionView,
    minute: dt.datetime,
    config: BacktestConfig,
    cash: float,
    positions: dict[str, Position],
) -> tuple[FillRecord, float]:
    """Apply a granted fill to cash and the book."""
    lots = verdict.granted_lots
    units = lots * contract.lot_size
    price = config.fill_model.fill_price(bar=bar, side=intent.side, contract=contract, lots=lots)
    costs = config.cost_stack.charge(
        ChargeableTrade(
            trade_date=session.session_date,
            kind=TradeKind.TRADE,
            side=intent.side,
            quantity_units=units,
            price=price,
            orders=1,
        )
    )
    gross = price * units
    signed = units if intent.side is Side.BUY else -units
    cash = cash + (-gross if intent.side is Side.BUY else gross) - costs.total

    existing = positions.get(intent.trading_symbol)
    net = (existing.units if existing else 0) + signed
    if net == 0:
        positions.pop(intent.trading_symbol, None)
    else:
        positions[intent.trading_symbol] = Position(contract=contract, units=net, last_mark=price)

    return (
        FillRecord(
            session_date=session.session_date,
            minute=minute,
            trading_symbol=intent.trading_symbol,
            side=intent.side,
            tag=intent.tag,
            requested_lots=intent.lots,
            filled_lots=lots,
            lot_size=contract.lot_size,
            price=price,
            gross_value=gross,
            costs=costs,
            feasibility=verdict,
        ),
        cash,
    )


def _settle_expiring(
    session: SessionView,
    config: BacktestConfig,
    cash: float,
    positions: dict[str, Position],
) -> tuple[list[SettlementRecord], float]:
    """Cash-settle every open position whose contract expires today.

    Runs **after** the decision minute, so a position opened on expiry morning settles the
    same evening — which is what happens, and which a 0DTE hypothesis depends on.
    """
    expiring = sorted(
        symbol
        for symbol, position in positions.items()
        if position.contract.expiry == session.session_date
    )
    if not expiring:
        return [], cash

    settled = settlement_value(session, rules=config.settlement_rules)
    records: list[SettlementRecord] = []
    for symbol in expiring:
        position = positions.pop(symbol)
        intrinsic = position.contract.intrinsic(settled.value)
        units = abs(position.units)
        # Closing a long is a SELL, closing a short is a BUY — the side convention that
        # decides who pays exercise STT. See TradeKind.SETTLEMENT.
        side = Side.SELL if position.units > 0 else Side.BUY
        costs = config.cost_stack.charge(
            ChargeableTrade(
                trade_date=session.session_date,
                kind=TradeKind.SETTLEMENT,
                side=side,
                quantity_units=units,
                price=intrinsic,
                orders=1,
                notional_price=settled.value,
            )
        )
        cash_flow = intrinsic * position.units - costs.total
        cash += cash_flow
        records.append(
            SettlementRecord(
                session_date=session.session_date,
                trading_symbol=symbol,
                units=position.units,
                settlement_value=settled.value,
                intrinsic_per_unit=intrinsic,
                cash_flow=cash_flow,
                costs=costs,
                feasibility=FeasibilityVerdict(
                    verdict=Feasibility.SETTLED,
                    requested_lots=units // position.contract.lot_size,
                    granted_lots=units // position.contract.lot_size,
                    binding_cap=None,
                    observed_volume_units=0.0,
                    observed_open_interest_units=0.0,
                    reason=(
                        "cash-settled by the exchange against the "
                        f"{settled.rule.method} of {settled.bars_used} underlying bars; "
                        "no participation cap applies to a settlement"
                    ),
                ),
                rule_effective_from=settled.rule.effective_from,
                rule_method=settled.rule.method,
                rule_confidence=str(settled.rule.confidence),
            )
        )
    return records, cash


def _settlement_rule_input(record: SettlementRecord) -> str:
    """The settlement methodology as a tiered ``unverified_inputs`` entry."""
    return f"settlement.{record.rule_method}:{record.rule_confidence}"


def _margin_for_session(
    session: SessionView,
    config: BacktestConfig,
    positions: Mapping[str, Position],
) -> tuple[MarginRequirement, int]:
    """Margin on the book as it stood *during* the session, and the legs it could not price.

    Called before :func:`_settle_expiring`, so a leg expiring today is still here and its
    2% ELM add-on is charged — the whole reason this is a separate function rather than a
    line inside :func:`_close_of_session`.

    The underlying's spot is taken from the last bar the **index itself** printed, not
    from whatever instrument happened to print in the session's final minute. A short leg
    held on a session where the index printed nothing at all cannot be margined; it is
    counted in the second return value rather than contributing zero.
    """
    underlying_bars = session.underlying_bars()
    spot = underlying_bars[-1].close if underlying_bars else None
    short_legs: list[ShortLeg] = []
    unmargined = 0
    for symbol in sorted(positions):
        position = positions[symbol]
        if not position.is_short:
            continue
        if spot is None:
            unmargined += 1
            continue
        short_legs.append(
            ShortLeg(
                quantity_units=abs(position.units),
                underlying_price=spot,
                expires_today=position.contract.expiry == session.session_date,
            )
        )
    return config.margin_model.requirement(short_legs), unmargined


def _close_of_session(
    session: SessionView,
    config: BacktestConfig,
    cash: float,
    positions: dict[str, Position],
    margin: MarginRequirement,
    unmargined_shorts: int,
) -> DailyRecord:
    """Mark the surviving book at the session's last observed price.

    ``margin`` is computed by :func:`_margin_for_session` **before** settlement and passed
    in, because by the time this runs every position expiring today has already been
    removed. Marking is the other way round — the marks that matter are the ones on
    positions still held — so the two are measured at different moments on purpose.

    A position whose contract printed no bar at all this session is carried at its last
    observed mark and counted in :attr:`DailyRecord.stale_marks`. Marking it to zero
    would be wrong in the direction that matters here: a short marked to zero hands the
    book its entire unrealised premium as profit, and every position this package's own
    strategy opens is short.
    """
    open_value = 0.0
    stale = 0

    for symbol in sorted(positions):
        position = positions[symbol]
        mark: float | None = None
        for minute in reversed(session.minutes()):
            bar = session.bar(symbol, minute)
            if bar is not None:
                mark = bar.close
                break
        if mark is None:
            mark = position.last_mark
            stale += 1
        else:
            positions[symbol] = replace(position, last_mark=mark)
        open_value += mark * position.units

    return DailyRecord(
        session_date=session.session_date,
        cash=cash,
        open_position_value=open_value,
        equity=cash + open_value,
        margin=margin,
        open_positions=len(positions),
        stale_marks=stale,
        unmargined_shorts=unmargined_shorts,
    )
