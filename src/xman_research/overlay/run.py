"""One overlay run, end to end, and the section 6.3 metrics it produces.

The run is a trial in the ordinary sense this repository means it: it opens a research
session, files the hypothesis, consumes a trial token and writes a row. A sweep is
therefore several trials and the log says so, which is the point of the log.

``python -m xman_research.overlay.run --help`` runs one arm and writes its JSON.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
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
from xman_research.overlay.context import VIX_SUBSTITUTION, load_context
from xman_research.overlay.fills import AbsoluteSlippageFillModel
from xman_research.overlay.sizing import CollateralAssumption, MarginPerLotModel
from xman_research.overlay.strategy import IndexOptionOverlay, OverlayParameters
from xman_research.overlay.synthetic import SYNTHETIC_WING_STAMP, SyntheticWingStore
from xman_research.session_store import DEFAULT_CORPUS_ROOT, SessionStore
from xman_research.validation.series import RunEvidence
from xman_research.validation.statistics import annualised_sharpe_ratio, drawdown

__all__ = ["OverlayRun", "OverlayRunConfig", "decision_times", "run_overlay"]

#: The canonical research log. Every arm of every sweep lands here, by design: a sweep is
#: a multiple-testing exercise and the count is the only thing that can say so.
DEFAULT_TRIAL_LOG = Path("/home/qa/runtime/data/research/trial_log.db")

_HYPOTHESIS = HypothesisRecord(
    name="Pledge-funded index option overlay (requirements v1.0, sections 3-4)",
    mechanism=(
        "A 0.12-delta NIFTY weekly iron condor entered at 5-6 days to expiry and closed "
        "before expiry day collects the variance risk premium on both wings while capping "
        "the loss at the wing width; the position is sized against pledged collateral so "
        "the underlying portfolio is not disturbed."
    ),
    null_hypothesis=(
        "The overlay's net return on Portfolio Capital, after statutory costs and "
        "slippage, is zero or negative."
    ),
    thresholds={"annual_return_on_pc": 0.12, "max_drawdown_pct_of_pc": 0.10},
    predictors=["atm_iv_percentile", "realised_vol_5d", "short_delta"],
)


def decision_times(
    *, first: dt.time = dt.time(9, 20), last: dt.time = dt.time(15, 15), minutes: int = 15
) -> tuple[dt.time, ...]:
    """Every ``minutes``-th minute of the session, first and last included.

    ST-30 asks for intraday monitoring at least every 15 minutes, and ST-17/ST-19 are
    continuous conditions that a backtest can only evaluate where it looks. Fifteen minutes
    is therefore the coarsest grid the requirements admit, and it is used rather than a
    finer one because every decision minute is a full pass over the book for 1,250
    sessions.
    """
    stamps: list[dt.time] = []
    moment = dt.datetime.combine(dt.date(2000, 1, 1), first)
    end = dt.datetime.combine(dt.date(2000, 1, 1), last)
    while moment <= end:
        stamps.append(moment.time())
        moment += dt.timedelta(minutes=minutes)
    if stamps[-1] != last:
        stamps.append(last)
    return tuple(stamps)


@dataclass(frozen=True, slots=True)
class OverlayRunConfig:
    """One arm of the study."""

    underlying: str = "NIFTY"
    start: dt.date = dt.date(2021, 9, 20)
    end: dt.date = dt.date(2026, 9, 15)
    wing_policy: str = "observed"
    min_credit_ratio: float = 0.0010
    slippage_rupees: float = 0.25
    portfolio_capital: float = 10_000_000.0
    margin_model: MarginPerLotModel = field(default_factory=MarginPerLotModel)
    collateral: CollateralAssumption | None = None
    corpus_root: Path = DEFAULT_CORPUS_ROOT
    trial_log: Path = DEFAULT_TRIAL_LOG
    decision_interval_minutes: int = 15
    short_delta_target: float = 0.12
    """ST-6's target. The register allows 0.10-0.14; the tuning study goes outside that on
    purpose and every run says where it stands."""
    delta_band: tuple[float, float] = (0.10, 0.14)
    wing_width: float = 350.0
    entry_dte: tuple[int, ...] = (5, 6)
    entry_sessions_before: tuple[int, ...] | None = None
    profit_take: float = 0.60
    stop_multiple: float = 1.5
    max_gearing: float = 2.5
    target_utilisation: float = 0.30
    max_lots_absolute: int = 50
    """CA-15's sanity cap, allowed 1-200. Stage two of the tuning search found it binding:
    once the collateral mix stops stranding capacity, this is what stops the position."""
    cash_equivalent_fraction: float | None = None
    """CA-R2's lever: how much of the pledged portfolio sits in cash-equivalent collateral.

    ``None`` keeps the section 8 mix (15%). The 50% rule caps Margin Capacity at twice the
    cash-equivalent total, so this is the single largest determinant of position size — and
    the document's own CA-R2 recommends raising it until no non-cash collateral is stranded."""
    participation_volume_pct: float = 0.01
    """Share of a minute's printed volume one order may be. The engine's default research
    convention is 1%, and for this structure it is the binding execution constraint: four
    legs must fill in the same minute, and the far wing's minute volume is small. Arms that
    raise it are measuring how much of the result is the cap rather than the strategy."""
    participation_oi_pct: float = 0.005
    roll_trigger_delta: float = 0.28
    label: str = "observed_wings"

    def collateral_assumption(self) -> CollateralAssumption:
        if self.collateral is not None:
            return self.collateral
        if self.cash_equivalent_fraction is None:
            return CollateralAssumption(portfolio_capital=self.portfolio_capital)
        cash_equivalent = self.cash_equivalent_fraction
        return CollateralAssumption(
            portfolio_capital=self.portfolio_capital,
            non_cash_fraction=max(0.0, 1.0 - cash_equivalent),
            cash_equivalent_fraction=cash_equivalent,
        )


@dataclass(frozen=True, slots=True)
class OverlayRun:
    """What one arm produced."""

    config: OverlayRunConfig
    result: BacktestResult
    metrics: dict[str, Any]
    journal: tuple[dict[str, Any], ...]
    cycles: tuple[dict[str, Any], ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "label": self.config.label,
            "underlying": self.config.underlying,
            "window": [self.config.start.isoformat(), self.config.end.isoformat()],
            "wing_policy": self.config.wing_policy,
            "min_credit_ratio": self.config.min_credit_ratio,
            "slippage_rupees": self.config.slippage_rupees,
            "participation_volume_pct": self.config.participation_volume_pct,
            "participation_oi_pct": self.config.participation_oi_pct,
            "roll_trigger_delta": self.config.roll_trigger_delta,
            "short_delta_target": self.config.short_delta_target,
            "delta_band": list(self.config.delta_band),
            "wing_width": self.config.wing_width,
            "entry_dte": list(self.config.entry_dte),
            "entry_sessions_before": (
                None
                if self.config.entry_sessions_before is None
                else list(self.config.entry_sessions_before)
            ),
            "profit_take": self.config.profit_take,
            "stop_multiple": self.config.stop_multiple,
            "max_gearing": self.config.max_gearing,
            "target_utilisation": self.config.target_utilisation,
            "cash_equivalent_fraction": self.config.cash_equivalent_fraction,
            "max_lots_absolute": self.config.max_lots_absolute,
            "portfolio_capital": self.config.portfolio_capital,
            "margin_assumptions": self.config.margin_model.assumptions,
            "trial_id": self.result.trial_id,
            "sessions_run": self.result.sessions_run,
            "metrics": self.metrics,
            "cycles": list(self.cycles),
            "unverified_inputs": list(self.result.unverified_inputs),
        }


def run_overlay(config: OverlayRunConfig) -> OverlayRun:
    """Run one arm and return it with its metrics."""
    times = decision_times(minutes=config.decision_interval_minutes)
    # Both arms read the extended store. See IndexOptionOverlay.wing_policy: the captured
    # band follows spot, so a five-session hold needs prices for strikes that have since
    # left the band, whichever policy chose them. What the policy decides is whether the
    # *entry* may use a modelled wing at all.
    store: SessionStore = SyntheticWingStore(root=config.corpus_root, minutes=times)

    context = load_context(corpus_root=config.corpus_root, underlying=config.underlying)
    strategy = IndexOptionOverlay(
        context=context,
        params=OverlayParameters(
            min_credit_ratio=config.min_credit_ratio,
            roll_trigger_delta=config.roll_trigger_delta,
            max_lots_absolute=config.max_lots_absolute,
            short_delta_target=config.short_delta_target,
            delta_band=config.delta_band,
            wing_width=config.wing_width,
            entry_dte=config.entry_dte,
            entry_sessions_before=config.entry_sessions_before,
            profit_take=config.profit_take,
            stop_multiple=config.stop_multiple,
        ),
        collateral=config.collateral_assumption(),
        margin_model=config.margin_model,
        wing_policy=config.wing_policy,
        max_gearing=config.max_gearing,
        target_utilisation=config.target_utilisation,
    )
    resolution = store.resolve(config.underlying, config.start, config.end)
    gap_reason = None
    if not resolution.is_complete:
        gap_reason = (
            "Overlay backtest: the captured range has known holes and the arm measures the "
            f"strategy over what was captured. {resolution.summary()}"
        )
    backtest_config = BacktestConfig(
        underlying=config.underlying,
        starting_cash=config.portfolio_capital,
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
            _HYPOTHESIS,
            data_window=DataWindow(config.start, config.end),
            params={
                "arm": config.label,
                "wing_policy": config.wing_policy,
                "min_credit_ratio": config.min_credit_ratio,
                "slippage_rupees": config.slippage_rupees,
                **dict(strategy.parameters()),
            },
            notes=VIX_SUBSTITUTION,
        ) as trial:
            result = run_backtest(trial, store=store, strategy=strategy, config=backtest_config)
            metrics = overlay_metrics(
                result=result, strategy=strategy, capital=config.portfolio_capital
            )
            trial.record_metrics(metrics)
    finally:
        session.close()
    return OverlayRun(
        config=config,
        result=result,
        metrics=metrics,
        journal=strategy.journal,
        cycles=strategy.completed_cycles,
    )


def overlay_metrics(
    *, result: BacktestResult, strategy: IndexOptionOverlay, capital: float
) -> dict[str, Any]:
    """Section 6.3's metric definitions, on the engine's own equity curve.

    The denominator is Portfolio Capital throughout (RP-10), and Portfolio Capital is
    constant here because the underlying pledged portfolio is an assumption rather than a
    modelled book — so a percentage in this dictionary is a percentage of the same Rs 1
    crore on every date, which is the comparison the 12% objective is stated against.
    """
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
    net_pnl = result.net_pnl
    # Calendar years of the window, not sessions/252. The two differ by 4% over five years
    # (1,229 sessions is 4.88 "session years" against 4.99 calendar years), and mixing them
    # put two different annualised figures in one report.
    years = (result.end - result.start).days / 365.25
    facts = drawdown(returns) if sessions else None

    cycles = strategy.completed_cycles
    entries = [row for row in strategy.journal if row["outcome"] == "entered"]
    declines: dict[str, int] = {}
    for row in strategy.journal:
        if row["outcome"] == "declined":
            declines[row["rule"]] = declines.get(row["rule"], 0) + 1

    # **Per-cycle P&L comes from the engine's fills, not from the strategy's own marks.**
    # The strategy keeps a mark-based estimate because ST-32/ST-33 have to gate on
    # something while a position is open, but that estimate is pre-cost and pre-slippage.
    # Win rate, average win, profit factor and premium capture are all statistics *about
    # completed trades*, so they are computed from what the book actually received.
    realised = _pnl_by_expiry(result)
    for cycle in cycles:
        cycle["realised_pnl"] = realised.get(cycle["expiry"], 0.0)
    wins = [c for c in cycles if c["realised_pnl"] > 0]
    losses = [c for c in cycles if c["realised_pnl"] <= 0]
    gross_credit = sum(c["credit_rupees"] for c in cycles)
    costs = result.total_costs

    exits: dict[str, int] = {}
    for cycle in cycles:
        rule = cycle["exit_rule"] or "unknown"
        exits[rule] = exits.get(rule, 0) + 1

    return {
        "sessions": sessions,
        "years_observed": years,
        "net_pnl_rupees": net_pnl,
        "return_on_pc_total": net_pnl / capital if capital else None,
        # Section 6.3 asks for geometric compounding. At these magnitudes it differs from
        # the arithmetic form in the fourth decimal, but the definition is the definition.
        "return_on_pc_annualised": (
            ((1.0 + net_pnl / capital) ** (1.0 / years) - 1.0) if years > 0 and capital else None
        ),
        "sharpe_annualised": _safe_sharpe(returns) if sessions > 60 else None,
        "sortino_annualised": _sortino(returns.net) if sessions > 60 else None,
        "max_drawdown_pct_of_pc": facts.max_drawdown if facts else None,
        "drawdown_peak": facts.peak_date.isoformat() if facts else None,
        "drawdown_trough": facts.trough_date.isoformat() if facts else None,
        "calmar": (
            ((1.0 + net_pnl / capital) ** (1.0 / years) - 1.0) / facts.max_drawdown
            if facts and facts.max_drawdown > 0 and years > 0
            else None
        ),
        "entries": len(entries),
        "completed_cycles": len(cycles),
        "win_rate": len(wins) / len(cycles) if cycles else None,
        "average_win_rupees": (sum(c["realised_pnl"] for c in wins) / len(wins)) if wins else None,
        "average_loss_rupees": (
            sum(c["realised_pnl"] for c in losses) / len(losses) if losses else None
        ),
        "expectancy_rupees": (
            sum(c["realised_pnl"] for c in cycles) / len(cycles) if cycles else None
        ),
        # **Capture is reported as a mean and a median.** The median alone is a knife-edge
        # statistic here: with a win rate near 50% it sits on the boundary between a position
        # that hit its 60% target and one that did not, so it swings from 0.02 to 0.54 on a
        # few positions changing side while the money involved barely moves.
        "median_premium_capture": _median(_captures(cycles)),
        "mean_premium_capture": _mean(_captures(cycles)),
        "entry_orders_unfilled": sum(
            1 for row in strategy.journal if row["rule"] == "ST-39_entry_never_filled"
        ),
        # Realised, not the strategy's own mark-based estimate: the estimate is pre-cost and
        # pre-slippage, and it partitioned wins and losses on a different series than the one
        # it divided, which reported 2.52 where the traded numbers give 1.1.
        "profit_factor": (
            sum(c["realised_pnl"] for c in wins) / abs(sum(c["realised_pnl"] for c in losses))
            if losses and sum(c["realised_pnl"] for c in losses) != 0
            else None
        ),
        "gross_credit_rupees": gross_credit,
        "total_costs_rupees": costs.total,
        "cost_ratio": costs.total / gross_credit if gross_credit else None,
        "cost_breakdown": {
            "brokerage": costs.brokerage,
            "stt": costs.stt,
            "exchange_transaction_charge": costs.exchange_transaction_charge,
            "sebi_turnover_fee": costs.sebi_turnover_fee,
            "stt_on_exercise": costs.stt_on_exercise,
            "stamp_duty": costs.stamp_duty,
            "gst": costs.gst,
        },
        "exit_rules": exits,
        "declines": declines,
        # **What the position actually was**, not what the caps allowed. A tuning result
        # that reaches a return target by quietly running at six times the document's
        # gearing cap has not reached it under the document's rules, and the only way a
        # reader can tell is if the run reports the gearing it used.
        "allocated_gearing_mean": _mean(
            [
                row["detail"]["allocation"]["allocated_gearing"]
                for row in strategy.journal
                if row["outcome"] == "entered"
            ]
        ),
        "allocated_gearing_max": max(
            (
                row["detail"]["allocation"]["allocated_gearing"]
                for row in strategy.journal
                if row["outcome"] == "entered"
            ),
            default=None,
        ),
        "lots_mean": _mean([float(c["lots"]) for c in cycles]),
        "peak_margin_no_netting": result.peak_margin,
        "feasibility": result.feasibility_counts(),
        "stale_mark_sessions": sum(1 for row in result.daily if row.stale_marks),
    }


def _pnl_by_expiry(result: BacktestResult) -> dict[str, float]:
    """Net rupees per expiry cycle, from fills and settlements, costs included.

    The expiry is read off the trading symbol — the vendor's own format carries it — so a
    roll's replacement legs and the original legs land in the same cycle, which is what a
    "cycle P&L" means.
    """
    totals: dict[str, float] = {}
    for fill in result.fills:
        if not fill.filled:
            continue
        expiry = _expiry_of(fill.trading_symbol)
        if expiry is None:
            continue
        direction = 1.0 if fill.side is Side.SELL else -1.0
        totals[expiry] = totals.get(expiry, 0.0) + direction * fill.gross_value - fill.costs.total
    for settlement in result.settlements:
        expiry = _expiry_of(settlement.trading_symbol)
        if expiry is None:
            continue
        totals[expiry] = totals.get(expiry, 0.0) + settlement.cash_flow - settlement.costs.total
    return totals


def _expiry_of(trading_symbol: str) -> str | None:
    parts = trading_symbol.split("-")
    if len(parts) != 4:
        return None
    try:
        return dt.datetime.strptime(parts[1], "%d%b%Y").date().isoformat()
    except ValueError:
        return None


def _captures(cycles: tuple[dict[str, Any], ...] | list[dict[str, Any]]) -> list[float]:
    """Premium capture per position that actually traded."""
    return [
        cycle["realised_pnl"] / cycle["credit_rupees"]
        for cycle in cycles
        if cycle["credit_rupees"] > 0
    ]


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _safe_sharpe(returns) -> float | None:
    """Undefined rather than zero when the series never moved — an arm that never traded
    has no Sharpe, and reporting 0.0 would read as a measured result."""
    try:
        return annualised_sharpe_ratio(returns)
    except ValueError:
        return None


def _sortino(net: tuple[float, ...]) -> float | None:
    downside = [value for value in net if value < 0.0]
    if not downside or not net:
        return None
    mean = sum(net) / len(net)
    deviation = math.sqrt(sum(value * value for value in downside) / len(net))
    if deviation == 0.0:
        return None
    return mean / deviation * math.sqrt(252.0)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--underlying", default="NIFTY")
    parser.add_argument("--start", type=dt.date.fromisoformat, default=dt.date(2021, 9, 20))
    parser.add_argument("--end", type=dt.date.fromisoformat, default=dt.date(2026, 9, 15))
    parser.add_argument("--wing-policy", choices=("observed", "spec"), default="observed")
    parser.add_argument("--min-credit-ratio", type=float, default=0.0010)
    parser.add_argument("--slippage", type=float, default=0.25)
    parser.add_argument("--label", default=None)
    parser.add_argument("--no-expiry-elm", action="store_true", help="CA-12 add-on off")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    margin_model = MarginPerLotModel(include_expiry_day_elm=not args.no_expiry_elm)
    label = args.label or (
        f"{args.wing_policy}_credit{args.min_credit_ratio:.4f}_slip{args.slippage}"
    )
    config = OverlayRunConfig(
        underlying=args.underlying,
        start=args.start,
        end=args.end,
        wing_policy=args.wing_policy,
        min_credit_ratio=args.min_credit_ratio,
        slippage_rupees=args.slippage,
        margin_model=margin_model,
        label=label,
    )
    run = run_overlay(config)
    payload = run.as_dict()
    if config.wing_policy == "spec":
        payload["unverified_inputs"].append(SYNTHETIC_WING_STAMP)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, default=str))
    journal_path = args.out.with_suffix(".journal.json")
    journal_path.write_text(json.dumps(list(run.journal), indent=1, default=str))
    metrics = run.metrics
    print(
        f"{label}: cycles={metrics['completed_cycles']} "
        f"net=Rs{metrics['net_pnl_rupees']:,.0f} "
        f"return/PC={metrics['return_on_pc_total']:.2%} "
        f"annualised={metrics['return_on_pc_annualised']:.2%} "
        f"maxDD={metrics['max_drawdown_pct_of_pc']:.2%}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


_ = replace  # re-exported convenience for sweep scripts
