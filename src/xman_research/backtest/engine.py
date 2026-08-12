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
from xman_research.backtest.margin import MarginRequirement, ShortLeg, SimplifiedMarginModel
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

    def as_dict(self) -> dict[str, Any]:
        return {
            "session_date": self.session_date.isoformat(),
            "cash": self.cash,
            "open_position_value": self.open_position_value,
            "equity": self.equity,
            "margin": self.margin.as_dict(),
            "open_positions": self.open_positions,
            "stale_marks": self.stale_marks,
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

    def provenance(self) -> dict[str, Any]:
        return {
            "underlying": self.underlying,
            "decision_time": self.decision_time.isoformat(),
            "starting_cash": self.starting_cash,
            "max_pct_of_bar_volume": self.limits.max_pct_of_bar_volume,
            "max_pct_of_open_interest": self.limits.max_pct_of_open_interest,
            "fill_model": self.fill_model.name,
            "fill_assumptions": self.fill_model.assumptions,
            "margin_assumptions": self.margin_model.assumptions,
            "settlement_rules": [rule.effective_from.isoformat() for rule in self.settlement_rules],
            "gap_reason": self.gap_reason,
        }


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

    for ref in refs:
        frame = store.load_session(ref, verify=config.verify_checksums)
        refdata = store.load_refdata(ref)
        session = SessionView.from_frame(ref.session_date, config.underlying, frame, refdata)

        minute = session.minute_at_or_after(config.decision_time)
        if minute is not None:
            intents = strategy.decide(
                session=session, minute=minute, book=BookView(positions, cash)
            )
            for intent in intents:
                record, cash = _execute(intent, session, minute, config, cash, positions)
                fills.append(record)
                total_costs = total_costs + record.costs
                unverified.update(record.costs.unverified_components)

        session_settlements, cash = _settle_expiring(session, config, cash, positions)
        for record in session_settlements:
            settlements.append(record)
            total_costs = total_costs + record.costs
            unverified.update(record.costs.unverified_components)

        daily.append(_close_of_session(session, config, cash, positions))

    # The margin approximation is never sourced well enough to be treated as verified, so
    # every run carries the flag whether or not any short leg was ever held. A run with no
    # margin exposure has a trivially correct margin number and the flag is harmless; a run
    # that quietly dropped the flag when the book happened to be flat would be the kind of
    # conditional honesty that is worse than none.
    unverified.add("margin.simplified_approximation")

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
        data_provenance=resolution.provenance(),
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


def _execute(
    intent: TradeIntent,
    session: SessionView,
    minute: dt.datetime,
    config: BacktestConfig,
    cash: float,
    positions: dict[str, Position],
) -> tuple[FillRecord, float]:
    """Ask the market whether the intent was possible, then apply it if it was."""
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
            )
        )
    return records, cash


def _close_of_session(
    session: SessionView,
    config: BacktestConfig,
    cash: float,
    positions: dict[str, Position],
) -> DailyRecord:
    """Mark the book at the session's last observed price and charge margin on it.

    A position whose contract printed no bar at all this session is carried at its last
    observed mark and counted in :attr:`DailyRecord.stale_marks`. Marking it to zero
    would be wrong in the direction that matters here: a short marked to zero hands the
    book its entire unrealised premium as profit, and every position this package's own
    strategy opens is short.
    """
    last_minute = session.minutes()[-1] if session.minutes() else None
    open_value = 0.0
    stale = 0
    short_legs: list[ShortLeg] = []
    spot = session.spot_at(last_minute) if last_minute is not None else None

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
        if position.is_short and spot is not None:
            short_legs.append(
                ShortLeg(
                    quantity_units=abs(position.units),
                    underlying_price=spot,
                    expires_today=position.contract.expiry == session.session_date,
                )
            )

    return DailyRecord(
        session_date=session.session_date,
        cash=cash,
        open_position_value=open_value,
        equity=cash + open_value,
        margin=config.margin_model.requirement(short_legs),
        open_positions=len(positions),
        stale_marks=stale,
    )
