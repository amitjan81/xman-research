"""One intraday-strangle run, and the risk-versus-reward numbers the search ranks on.

The metrics here differ from the overlay's on purpose. An intraday book that is flat every
night has no gap risk and no settlement risk, so the questions worth asking of it are about
the *shape* of its P&L: how often it wins, how much it gives back when the stop fires, and
whether the worst day is survivable. Return on capital still appears, but the ranking
statistic is reward-to-risk, not return.
"""

from __future__ import annotations

import datetime as dt
import math
import statistics as st
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from xman_research import DataWindow, HypothesisRecord, open_session
from xman_research.adapter import costs_by_date, feasibility_from_result
from xman_research.backtest import (
    BacktestConfig,
    BacktestResult,
    ParticipationLimits,
    run_backtest,
)
from xman_research.backtest.costs import Side
from xman_research.intraday.dynamic import DynamicParameters, DynamicStrangle
from xman_research.intraday.strangle import IntradayStrangle, SpotStop, StrangleParameters
from xman_research.intraday.window_stats import load_window_stats
from xman_research.overlay.fills import AbsoluteSlippageFillModel
from xman_research.session_store import DEFAULT_CORPUS_ROOT, SessionStore
from xman_research.validation.series import RunEvidence
from xman_research.validation.statistics import annualised_sharpe_ratio, drawdown

__all__ = [
    "DynamicRunConfig",
    "StrangleRun",
    "StrangleRunConfig",
    "decision_grid",
    "run_dynamic",
    "run_strangle",
]

DEFAULT_TRIAL_LOG = Path("/home/qa/runtime/data/research/trial_log.db")

HYPOTHESIS = HypothesisRecord(
    name="Intraday short strangle on NIFTY weeklies, stopped on the underlying",
    mechanism=(
        "Selling out-of-the-money weekly options and closing before the session ends "
        "collects intraday time decay while a stop keyed to the index — not to the option's "
        "own quote — bounds the loss when the underlying trends."
    ),
    null_hypothesis=(
        "Intraday short premium on NIFTY weeklies is zero or negative after statutory costs "
        "and slippage, as H26 measured it at -10.5% a year for the at-the-money straddle."
    ),
    thresholds={"reward_to_risk": 1.0, "max_drawdown_pct_of_capital": 0.10},
    predictors=["short_delta", "spot_move", "time_of_day", "days_to_expiry"],
)


DYNAMIC_HYPOTHESIS = HypothesisRecord(
    name="Dynamic intraday strangle: sell each leg when NIFTY reaches its bound",
    mechanism=(
        "Selling the call only after the index has rallied to the top of a range, and the "
        "put only after it has fallen to the bottom, sells each leg richer and leaves a "
        "trending session short one side rather than both."
    ),
    null_hypothesis=(
        "Selling on touch is no better than selling both legs at a fixed time, because the "
        "bound is where a breakout begins and the premium gained is paid back in the days "
        "the range fails."
    ),
    thresholds={"reward_to_risk": 1.0, "max_drawdown_pct_of_capital": 0.10},
    predictors=["range_width", "spot_at_touch", "time_of_touch"],
)


def decision_grid(*, first: dt.time, last: dt.time, minutes: int = 5) -> tuple[dt.time, ...]:
    """Decision minutes across the session.

    Five minutes rather than fifteen: the stop reads the index, and a stop that is only
    consulted every quarter hour is not the stop the parameter claims to be. The cost is
    three times the engine work per session, which is the right trade for the one rule whose
    whole purpose is to act quickly.
    """
    stamps: list[dt.time] = []
    moment = dt.datetime.combine(dt.date(2000, 1, 1), first)
    end = dt.datetime.combine(dt.date(2000, 1, 1), last)
    while moment <= end:
        stamps.append(moment.time())
        moment += dt.timedelta(minutes=minutes)
    return tuple(stamps)


@dataclass(frozen=True, slots=True)
class StrangleRunConfig:
    underlying: str = "NIFTY"
    start: dt.date = dt.date(2021, 9, 20)
    end: dt.date = dt.date(2026, 9, 15)
    params: StrangleParameters = field(default_factory=StrangleParameters)
    capital: float = 10_000_000.0
    slippage_rupees: float = 0.25
    participation_volume_pct: float = 0.05
    participation_oi_pct: float = 0.02
    decision_minutes: int = 5
    corpus_root: Path = DEFAULT_CORPUS_ROOT
    trial_log: Path = DEFAULT_TRIAL_LOG
    label: str = "strangle"


@dataclass(frozen=True, slots=True)
class StrangleRun:
    config: StrangleRunConfig
    result: BacktestResult
    metrics: dict[str, Any]
    cycles: tuple[dict[str, Any], ...]
    journal: tuple[dict[str, Any], ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "label": self.config.label,
            "window": [self.config.start.isoformat(), self.config.end.isoformat()],
            "parameters": dict(self.config.params.__dict__)
            if hasattr(self.config.params, "__dict__")
            else {},
            "metrics": self.metrics,
            "cycles": list(self.cycles),
        }


def run_strangle(config: StrangleRunConfig) -> StrangleRun:
    # The grid starts at the entry time and runs past the exit deadline. See
    # StrangleParameters.exit_start_time for what the late-session illiquidity does.
    # **The grid runs past the exit deadline on purpose.** A close that is attempted once,
    # at the last decision minute of the session, is not a close — it is a hope. If the leg
    # group cannot fill in that one minute the position carries overnight, which is the one
    # thing this strategy exists to avoid, and the next session refuses to trade it at all
    # because the captured band has moved and the strike is no longer listed. Attempts now
    # begin at the deadline and repeat every grid step to 15:25.
    times = decision_grid(
        first=config.params.entry_time,
        last=dt.time(15, 25),
        minutes=config.decision_minutes,
    )
    store = SessionStore(root=config.corpus_root)
    strategy = IntradayStrangle(params=config.params)
    resolution = store.resolve(config.underlying, config.start, config.end)
    gap_reason = None
    if not resolution.is_complete:
        gap_reason = (
            "Intraday strangle study: the captured range has known holes and the arm "
            f"measures what was captured. {resolution.summary()}"
        )
    backtest_config = BacktestConfig(
        underlying=config.underlying,
        starting_cash=config.capital,
        decision_times=times,
        fill_model=AbsoluteSlippageFillModel(rupees_per_unit=config.slippage_rupees),
        limits=ParticipationLimits(
            max_pct_of_bar_volume=config.participation_volume_pct,
            max_pct_of_open_interest=config.participation_oi_pct,
        ),
        gap_reason=gap_reason,
    )
    session = open_session(config.trial_log)
    try:
        with session.trial(
            HYPOTHESIS,
            data_window=DataWindow(config.start, config.end),
            params={"arm": config.label, **dict(strategy.parameters())},
        ) as trial:
            result = run_backtest(trial, store=store, strategy=strategy, config=backtest_config)
            metrics = strangle_metrics(result=result, strategy=strategy, capital=config.capital)
            trial.record_metrics({k: v for k, v in metrics.items() if not isinstance(v, dict)})
    finally:
        session.close()
    return StrangleRun(
        config=config,
        result=result,
        metrics=metrics,
        cycles=strategy.completed_cycles,
        journal=strategy.journal,
    )


@dataclass(frozen=True, slots=True)
class DynamicRunConfig:
    """One run of the dynamic (sell-on-touch) variant.

    Separate from :class:`StrangleRunConfig` because the parameters are different, and
    deliberately sharing everything else — window, capital, slippage, participation caps,
    metrics — so a comparison against the static strangle is a comparison of the rule and
    not of the harness.
    """

    underlying: str = "NIFTY"
    start: dt.date = dt.date(2021, 9, 20)
    end: dt.date = dt.date(2026, 9, 15)
    params: DynamicParameters = field(default_factory=DynamicParameters)
    capital: float = 10_000_000.0
    slippage_rupees: float = 0.25
    participation_volume_pct: float = 0.05
    participation_oi_pct: float = 0.02
    decision_minutes: int = 5
    corpus_root: Path = DEFAULT_CORPUS_ROOT
    trial_log: Path = DEFAULT_TRIAL_LOG
    label: str = "dynamic"


def run_dynamic(config: DynamicRunConfig) -> StrangleRun:
    """The dynamic variant, through the same engine and the same metrics."""
    times = decision_grid(
        first=dt.time(9, 20), last=dt.time(15, 25), minutes=config.decision_minutes
    )
    store = SessionStore(root=config.corpus_root)
    strategy = DynamicStrangle(
        params=config.params,
        window_stats=load_window_stats(
            corpus_root=config.corpus_root, underlying=config.underlying
        ),
    )
    resolution = store.resolve(config.underlying, config.start, config.end)
    gap_reason = None
    if not resolution.is_complete:
        gap_reason = (
            "Dynamic strangle study: the captured range has known holes and the arm measures "
            f"what was captured. {resolution.summary()}"
        )
    backtest_config = BacktestConfig(
        underlying=config.underlying,
        starting_cash=config.capital,
        decision_times=times,
        fill_model=AbsoluteSlippageFillModel(rupees_per_unit=config.slippage_rupees),
        limits=ParticipationLimits(
            max_pct_of_bar_volume=config.participation_volume_pct,
            max_pct_of_open_interest=config.participation_oi_pct,
        ),
        gap_reason=gap_reason,
    )
    session = open_session(config.trial_log)
    try:
        with session.trial(
            DYNAMIC_HYPOTHESIS,
            data_window=DataWindow(config.start, config.end),
            params={"arm": config.label, **dict(strategy.parameters())},
        ) as trial:
            result = run_backtest(trial, store=store, strategy=strategy, config=backtest_config)
            metrics = strangle_metrics(result=result, strategy=strategy, capital=config.capital)
            trial.record_metrics({k: v for k, v in metrics.items() if not isinstance(v, dict)})
    finally:
        session.close()
    return StrangleRun(
        config=config,  # type: ignore[arg-type]
        result=result,
        metrics=metrics,
        cycles=strategy.completed_cycles,
        journal=strategy.journal,
    )


def strangle_metrics(
    *, result: BacktestResult, strategy: IntradayStrangle, capital: float
) -> dict[str, Any]:
    """Reward and risk, with the ranking statistic stated rather than implied."""
    evidence = RunEvidence.from_equity_curve(
        result.equity_curve(),
        label=result.strategy_name,
        capital_base=capital,
        cost_by_date=costs_by_date(result),
        feasibility=feasibility_from_result(result),
        unverified_inputs=result.unverified_inputs,
        peak_margin=result.peak_margin,
        trial_id=result.trial_id,
    )
    returns = evidence.returns
    sessions = len(returns.net)
    years = (result.end - result.start).days / 365.25
    facts = drawdown(returns) if sessions else None

    # **Attribution is per leg where the strategy trades legs, per session where it trades
    # positions.** The static strangle opens one position a session, so session-level
    # attribution is exact. The dynamic variant can sell a call and a put on the same session
    # at different times and close them separately — giving both legs the session's whole P&L
    # double-counted every win and every loss, and made the win rate and profit factor
    # meaningless while leaving net P&L correct. Legs carry a `symbol`; positions do not.
    cycles = [dict(cycle) for cycle in strategy.completed_cycles]
    by_leg = _pnl_by_leg(result)
    by_session = _pnl_by_session(result)
    for cycle in cycles:
        if "symbol" in cycle:
            cycle["realised_pnl"] = by_leg.get((cycle["session_date"], cycle["symbol"]), 0.0)
        else:
            cycle["realised_pnl"] = by_session.get(cycle["session_date"], 0.0)
    wins = [c["realised_pnl"] for c in cycles if c["realised_pnl"] > 0]
    losses = [c["realised_pnl"] for c in cycles if c["realised_pnl"] <= 0]

    average_win = st.mean(wins) if wins else 0.0
    average_loss = abs(st.mean(losses)) if losses else 0.0
    net = result.net_pnl

    exits: dict[str, int] = {}
    exit_pnl: dict[str, float] = {}
    for cycle in cycles:
        rule = cycle["exit_rule"] or "unknown"
        exits[rule] = exits.get(rule, 0) + 1
        exit_pnl[rule] = exit_pnl.get(rule, 0.0) + cycle["realised_pnl"]

    return {
        "sessions": sessions,
        "trades": len(cycles),
        "net_pnl_rupees": net,
        "return_on_capital_total": net / capital if capital else None,
        "return_on_capital_annualised": (
            ((1.0 + net / capital) ** (1.0 / years) - 1.0) if years > 0 and capital else None
        ),
        "max_drawdown_pct_of_capital": facts.max_drawdown if facts else None,
        "sharpe_annualised": _safe_sharpe(returns) if sessions > 60 else None,
        "win_rate": (len(wins) / len(cycles)) if cycles else None,
        "average_win_rupees": average_win,
        "average_loss_rupees": -average_loss,
        # **The ranking statistic.** Expectancy per trade divided by the average loss: how
        # much the strategy makes per unit of what it gives back when it is wrong. Scale-free,
        # so it compares parameters rather than sizes, and it is the number the owner asked
        # for when they said "best risk versus reward".
        "reward_to_risk": (
            (st.mean([c["realised_pnl"] for c in cycles]) / average_loss)
            if cycles and average_loss > 0
            else None
        ),
        "profit_factor": (sum(wins) / abs(sum(losses))) if losses and sum(losses) else None,
        "expectancy_rupees": st.mean([c["realised_pnl"] for c in cycles]) if cycles else None,
        "worst_trade_rupees": min((c["realised_pnl"] for c in cycles), default=None),
        "best_trade_rupees": max((c["realised_pnl"] for c in cycles), default=None),
        "worst_trade_pct_of_capital": (
            min((c["realised_pnl"] for c in cycles), default=0.0) / capital if capital else None
        ),
        "exit_rules": exits,
        "exit_pnl": exit_pnl,
        "total_costs_rupees": result.total_costs.total,
        "peak_margin": result.peak_margin,
        "return_on_peak_margin": (net / result.peak_margin) if result.peak_margin else None,
        "declines": _declines(strategy),
        "median_credit_pct_of_spot": _median_credit(strategy),
    }


def _pnl_by_leg(result: BacktestResult) -> dict[tuple[str, str], float]:
    """Net rupees per (session, instrument) — the unit a leg-trading strategy works in."""
    totals: dict[tuple[str, str], float] = {}
    for fill in result.fills:
        if not fill.filled:
            continue
        key = (fill.session_date.isoformat(), fill.trading_symbol)
        direction = 1.0 if fill.side is Side.SELL else -1.0
        totals[key] = totals.get(key, 0.0) + direction * fill.gross_value - fill.costs.total
    for settlement in result.settlements:
        key = (settlement.session_date.isoformat(), settlement.trading_symbol)
        totals[key] = totals.get(key, 0.0) + settlement.cash_flow - settlement.costs.total
    return totals


def _pnl_by_session(result: BacktestResult) -> dict[str, float]:
    """Net rupees per session — an intraday book opens and closes inside one."""
    totals: dict[str, float] = {}
    for fill in result.fills:
        if not fill.filled:
            continue
        key = fill.session_date.isoformat()
        direction = 1.0 if fill.side is Side.SELL else -1.0
        totals[key] = totals.get(key, 0.0) + direction * fill.gross_value - fill.costs.total
    for settlement in result.settlements:
        key = settlement.session_date.isoformat()
        totals[key] = totals.get(key, 0.0) + settlement.cash_flow - settlement.costs.total
    return totals


def _declines(strategy: IntradayStrangle) -> dict[str, int]:
    counter: dict[str, int] = {}
    for row in strategy.journal:
        if row["outcome"] == "declined":
            counter[row["rule"]] = counter.get(row["rule"], 0) + 1
    return counter


def _median_credit(strategy: IntradayStrangle) -> float | None:
    values = [
        row["detail"]["credit_pct_of_spot"]
        for row in strategy.journal
        if row["outcome"] == "entered"
    ]
    return st.median(values) if values else None


def _safe_sharpe(returns) -> float | None:
    try:
        return annualised_sharpe_ratio(returns)
    except ValueError:
        return None


_ = (replace, math, SpotStop)  # re-exported for the search scripts
