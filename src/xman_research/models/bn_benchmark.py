"""BN-M1: the unconditional BANKNIFTY short ATM straddle, run as an engine proof.

**This is a benchmark, not a candidate, and the distinction is the whole reason the module
exists.** Nothing here is graded: no gate file, no holdout is spent, no decision is
recorded. What it establishes is that the research engine — the store, the universe, the
cost stack, the margin model, the settlement rules and the lot-size audit — runs
end-to-end on an underlying that is not NIFTY, and what it costs to do so. A screening run
that later wants to claim an edge on BANKNIFTY needs a naive always-on straddle to beat,
and this is that number.

**Why a fresh record rather than an amendment of H1/M1.** ``models/m1.py`` makes minting a
fresh record the suspicious move, correctly: a new record resets the family trial count and
makes the next candidate easier to pass. It does not apply here, in one specific way that
is checkable rather than asserted. M1's family is a claim about **NIFTY's** variance risk
premium, tested on NIFTY sessions; BN-M1 is a different population and a different
instrument, so an amendment would put BANKNIFTY trials into NIFTY's family count and
deflate — or inflate — a count that exists to price NIFTY's multiple comparisons. The
family this record starts is BANKNIFTY's own, it starts at zero because no BANKNIFTY trial
has ever been run, and this run is the first entry in it. Nothing that will be graded
against a threshold reads either count today.

**The window and why it starts where it does.** The in-sample corpus runs
2024-08-01..2026-05-29 (see ``research/banknifty/README.md``); this run starts
2024-10-01, the first date the securities-transaction-tax schedule is in force. Sessions
before it are now costable — rate schedules extrapolate rather than refuse — but
extrapolating STT *understates* the charge, because STT has only ever been revised upward.
A benchmark that another run has to beat must not be flattered by construction, so the two
months are given up instead. The lot-size measurement in
:data:`~xman_research.backtest.lot_size.BANKNIFTY_LOT_SIZE_EPOCHS` does span them: reading
bars costs nothing and charges nothing.

**What a hold-to-expiry straddle means in this regime.** BANKNIFTY's weekly expiries end
on 2024-11-13; everything after is monthly. So the straddle opens on the first session
after each settlement and is held roughly twenty sessions rather than four, through a
strike ladder capped at ATM±10 (±1000 points, about 2%). The run is expected to report
stale marks and open interest that the participation caps bite on. Reporting them is the
point.

Run: ``uv run python -m xman_research.models.bn_benchmark``
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Any

from xman_research import DataWindow, open_session
from xman_research.adapter import evidence_from_result
from xman_research.backtest import BacktestConfig, ShortAtmStraddle, run_backtest
from xman_research.hypothesis import HypothesisRecord
from xman_research.session_store import SessionStore
from xman_research.validation.statistics import annualised_sharpe_ratio, cost_breakeven, drawdown

__all__ = [
    "BENCHMARK_END",
    "BENCHMARK_START",
    "GAP_REASON",
    "HOLDOUT_FIRST_DATE",
    "TRIAL_LOG_PATH",
    "bn_m1_record",
    "run_benchmark",
]

_REPO = Path(__file__).resolve().parents[3]

#: The canonical family log, shared with H1/H26/M1/M2 and living outside every worktree —
#: the same path ``research/m1/validation.toml`` names, for the same reason: a log written
#: inside a worktree vanishes with it, taking the only auditable trial count along.
TRIAL_LOG_PATH = Path("/home/qa/runtime/data/research/trial_log.db")

#: The securities-transaction-tax floor. Before this date the STT schedule extrapolates,
#: and extrapolating it undercharges — see the module docstring.
BENCHMARK_START = dt.date(2024, 10, 1)

#: The last in-sample session. 2026-06-01 onward is sealed and unread.
BENCHMARK_END = dt.date(2026, 5, 29)

#: The first sealed session. Declared here so that a run which ever reaches it fails a
#: check rather than a review.
HOLDOUT_FIRST_DATE = dt.date(2026, 6, 1)

UNDERLYING = "BANKNIFTY"

#: The gap policy, decided and written down rather than generated — the counts and the
#: dates are the ones ``SessionStore.resolve`` reports for this exact window.
GAP_REASON = (
    "BN-M1 benchmark over BANKNIFTY 2024-10-01..2026-05-29. The NSE calendar expects 407 "
    "sessions; 353 are on disk and 54 are absent. 53 of the 54 are sessions the producer "
    "captured and QUARANTINED, so no parquet was ever published: 43 for premium-below-"
    "intrinsic candles alongside a rolling-spot vs index divergence above 0.5% (clustered "
    "Apr-Jul 2025), and 10 for expiry-day convergence failure — 2024-10-09, 2024-11-13, "
    "2025-01-30, 2025-02-27, 2025-04-24, 2025-05-29, 2025-08-28, 2025-12-30, 2026-03-30 "
    "and 2026-05-26. The 54th, 2024-11-20, is in no manifest at all: NSE did not hold a "
    "session (Maharashtra state election) and the calendar this store uses expects one. "
    "\n\n"
    "THE TEN MATTER FAR MORE THAN THE FORTY-THREE, and not because of their number. Every "
    "one of them is a front-contract EXPIRY session, so for ten of the window's 27 expiry "
    "cycles the session at which the position would have cash-settled does not exist. The "
    "engine refuses to open a position it can never settle, which is correct and is not "
    "softened here: those cycles are declined at entry and counted as UNSETTLEABLE. This "
    "run therefore measures the premium over the 17 cycles the corpus can settle, not over "
    "27, and the population is quarantine-selected rather than random — expiry-day "
    "convergence failure is most likely on the expiries where the ATM straddle held the "
    "most residual value, which is not independent of what a short straddle earns there. "
    "\n\n"
    "The window is NOT narrowed to avoid the holes. Narrowing to a hole-free sub-range "
    "would fragment one benchmark into a dozen and would discard the 2024-11-13 weekly-to-"
    "monthly regime change, the 15/30/35 lot-size boundaries and the April-July 2025 "
    "cluster, all of which are the conditions a BANKNIFTY strategy would actually have "
    "traded through. Quarantined sessions are excluded, not read: accept_gaps is called "
    "without include_quarantined, so nothing the producer marked untrustworthy enters the "
    "P&L."
)


def bn_m1_record() -> HypothesisRecord:
    """BN-M1 as a hypothesis record. Deterministic: same text in, same id out."""
    return HypothesisRecord(
        name="BN-M1 — BANKNIFTY near-expiry short ATM straddle (benchmark)",
        mechanism=(
            "Index hedgers pay up for downside protection, so implied variance sits "
            "persistently above subsequently realised variance, and a short-variance "
            "position collects the difference as compensation for bearing crash risk. "
            "This is H1's mechanism applied to BANKNIFTY, whose constituents are a single "
            "sector: the claim is the same, the population is not, and a bank-index "
            "variance premium is not entitled to inherit an evidence base built on NIFTY."
        ),
        null_hypothesis=(
            "An unconditional BANKNIFTY short ATM straddle, held from entry to cash "
            "settlement and charged full statutory costs, earns no return distinguishable "
            "from zero once the frictions it actually pays are deducted."
        ),
        thresholds={
            "graded": (
                "NONE. This record is a benchmark and an engine proof, not a candidate: "
                "no gate file reads it, no holdout is spent against it, and no decision "
                "is recorded from it. A conditional BANKNIFTY strategy is graded against "
                "the number this run produces; this run is graded against nothing."
            )
        },
        entry_rule={
            "decision_time_ist": "09:20",
            "expiry": "the first listed expiry strictly after the session date",
            "strike": "the listed strike nearest spot at the decision minute",
            "legs": "short one CE and one PE at that strike, atomically",
            "sizing": (
                "n_t = floor(N* / (S_t * L_t) + 1/2), N* = 1500000 rupees of index "
                "exposure — M1 §5 unchanged, so the headline statistics do not move with "
                "the contract multiplier. That matters more on BANKNIFTY than it did on "
                "NIFTY: the multiplier the bars support changes three times inside this "
                "window (15 -> 30 -> 35 -> 30) while the refdata declares 30 throughout."
            ),
            "suppressed_when": (
                "under one trading day to expiry, either leg unlisted, either leg "
                "infeasible, n_t = 0, or the expiry session is absent from the run so the "
                "position could never settle"
            ),
        },
        exit_rule={
            "hold": (
                "to expiry, no intermediate exit. Weekly until the 2024-11-13 expiry and "
                "monthly after it, so the hold is roughly four sessions and then roughly "
                "twenty."
            ),
            "settlement": (
                "European cash settlement against the stored dated rule for the expiry "
                "date, including the corroborated proxy past the closing-auction boundary."
            ),
        },
        notes=(
            "WHY A FRESH RECORD AND NOT AN AMENDMENT OF H1 OR M1. Those records are a "
            "claim about NIFTY, and their family trial count exists to price the multiple "
            "comparisons made against NIFTY data. Amending one of them to change the "
            "underlying would put BANKNIFTY trials into NIFTY's count, which corrupts the "
            "deflation in both directions depending on which way the counts move. This "
            "record opens BANKNIFTY's own family at zero, which is the true count: no "
            "BANKNIFTY trial has been run before this one.\n\n"
            "WHAT THIS RUN IS FOR. Three things, none of them a verdict. It proves the "
            "engine is genuinely underlying-parameterised end to end. It produces the "
            "naive always-on number a conditional BANKNIFTY signal must beat. And it "
            "surfaces what the corpus does to a hold-to-expiry position on this "
            "underlying — unsettleable cycles, stale marks off the ATM+/-10 ladder, and a "
            "declared lot size that is wrong on more than half the window.\n\n"
            "WHAT IT IS NOT EVIDENCE OF. Nothing about BANKNIFTY's holdout, which is "
            "sealed at 2026-06-01 and was not read. And nothing about the premium over "
            "the full expiry cycle population: ten of the window's expiry sessions are "
            "quarantined, so those cycles are declined at entry, and the cycles that "
            "remain are the ones whose expiry-day convergence the producer could verify."
        ),
    )


def run_benchmark(*, json_out: Path | None = None) -> dict[str, Any]:
    """Run BN-M1 over the in-sample window and return its metrics payload."""
    if BENCHMARK_END >= HOLDOUT_FIRST_DATE:
        raise ValueError(
            f"benchmark window ends {BENCHMARK_END}, on or after the sealed holdout "
            f"boundary {HOLDOUT_FIRST_DATE} — this run may not read holdout sessions."
        )
    store = SessionStore()
    strategy = ShortAtmStraddle()
    config = BacktestConfig(underlying=UNDERLYING, gap_reason=GAP_REASON)
    record = bn_m1_record()
    window = DataWindow(BENCHMARK_START, BENCHMARK_END)

    with open_session(TRIAL_LOG_PATH) as session:
        session.register(record)
        with session.trial(record, data_window=window, notes="BN-M1 benchmark") as trial:
            result = run_backtest(trial, store=store, strategy=strategy, config=config)
        evidence = evidence_from_result(
            result, session=session, hypothesis_id=record.id, label="BN-M1 benchmark"
        )
        family_trials = session.count_family_trials(record)

    returns = evidence.returns
    facts = drawdown(returns)
    breakeven = cost_breakeven(evidence)
    metrics = result.metrics()
    feasibility = evidence.feasibility
    stale_fraction = (
        feasibility.sessions_with_stale_marks / feasibility.sessions_run
        if feasibility.sessions_run
        else None
    )

    payload: dict[str, Any] = {
        "hypothesis_id": record.id,
        "hypothesis_name": record.name,
        "trial_id": result.trial_id,
        "underlying": UNDERLYING,
        "window": {"start": BENCHMARK_START.isoformat(), "end": BENCHMARK_END.isoformat()},
        "holdout_first_date": HOLDOUT_FIRST_DATE.isoformat(),
        "strategy": {"name": result.strategy_name, "parameters": result.strategy_parameters},
        "family_trial_count_after_run": family_trials,
        "returns": {
            "annualised_sharpe": annualised_sharpe_ratio(returns),
            "max_drawdown": facts.max_drawdown,
            "drawdown_peak": facts.peak_date.isoformat(),
            "drawdown_trough": facts.trough_date.isoformat(),
            "sessions_under_water": facts.sessions_under_water,
            "ruined": facts.ruined,
            "n": len(returns.net),
            "capital_base": evidence.capital_base,
        },
        "pnl": {
            "net_pnl": metrics["net_pnl"],
            "final_equity": metrics["final_equity"],
            "peak_margin": metrics["peak_margin"],
            "return_on_peak_margin": metrics["return_on_peak_margin"],
        },
        "costs": {
            "total": metrics["total_costs"],
            "stt": metrics["cost_stt"],
            "stt_on_exercise": metrics["cost_stt_on_exercise"],
            "breakeven_multiple": breakeven.multiple,
            "mean_gross_per_session": breakeven.mean_gross,
        },
        "execution": {
            "sessions_run": metrics["sessions_run"],
            "fills_attempted": metrics["fills_attempted"],
            "fills_filled": metrics["fills_filled"],
            "fills_resized": metrics["fills_resized"],
            "fills_infeasible": metrics["fills_infeasible"],
            "fills_unsettleable": metrics["fills_unsettleable"],
            "fills_group_bound": metrics["fills_group_bound"],
            "settlements": metrics["settlements"],
            "positions_open_at_end": metrics["positions_open_at_end"],
            "open_at_end": list(result.open_at_end),
            "sessions_with_unmargined_shorts": metrics["sessions_with_unmargined_shorts"],
            "feasibility_counts": result.feasibility_counts(),
            "intents_attempted": feasibility.intents_attempted,
            "intents_infeasible": feasibility.intents_infeasible,
            "sessions_with_stale_marks": feasibility.sessions_with_stale_marks,
            "stale_mark_fraction": stale_fraction,
        },
        "lot_size_audit": result.data_provenance["lot_size_audit"],
        "unverified_inputs": list(result.unverified_inputs),
        "fingerprint": result.fingerprint(),
        "gap_policy": GAP_REASON,
        "data_provenance": {
            key: value for key, value in result.data_provenance.items() if key != "lot_size_audit"
        },
    }
    if json_out is not None:
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(
            json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
        )
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the BN-M1 BANKNIFTY benchmark.")
    parser.add_argument(
        "--json-out",
        default=str(_REPO / "research" / "banknifty" / "bn_m1_benchmark.json"),
        help="where to write the metrics payload",
    )
    arguments = parser.parse_args()
    payload = run_benchmark(json_out=Path(arguments.json_out))
    print(f"trial {payload['trial_id']} hypothesis {payload['hypothesis_id']}")
    print(json.dumps({k: payload[k] for k in ("returns", "pnl", "costs", "execution")}, indent=2))
    print("unverified:", payload["unverified_inputs"])


if __name__ == "__main__":
    main()
