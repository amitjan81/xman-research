"""Produce the custom-backtest artifacts the UI draws.

One file per strategy, in the directory `xman-ui` reads. Each carries the run's parameters,
its summary, every trade it took, and for each session it traded: the index's own path that
day, both candidate bands, and where the entry and exit fell.

The strategies exported are the ones this study actually argued about, so the interface shows
a like-for-like set: the tuned static strangle, and the dynamic variants that sell each leg
only when the index comes to it.

    uv run python research/intraday/export_runs.py
"""

from __future__ import annotations

import argparse
import datetime as dt
import tempfile
from dataclasses import replace
from pathlib import Path

from xman_research.intraday import (
    DynamicParameters,
    DynamicRunConfig,
    RangeMethod,
    SpotStop,
    StrangleParameters,
    StrangleRunConfig,
    load_window_stats,
    run_dynamic,
    run_strangle,
)
from xman_research.intraday.export import DEFAULT_EXPORT_DIR, export_run
from xman_research.session_store import DEFAULT_CORPUS_ROOT

WINDOW_START = dt.date(2021, 9, 20)
WINDOW_END = dt.date(2026, 9, 15)

STATIC = StrangleParameters(
    short_delta_target=0.15,
    delta_band=(0.11, 0.19),
    stop=SpotStop.MOVE_FROM_ENTRY,
    stop_move_pct=0.0075,
    entry_time=dt.time(12, 0),
    profit_take_pct=0.90,
    exit_start_time=dt.time(14, 45),
    exit_time=dt.time(15, 0),
    allowed_dte=(0,),
)

DYNAMIC = DynamicParameters(
    short_delta_target=0.15,
    delta_band=(0.11, 0.19),
    arm_time=dt.time(10, 0),
    last_entry_time=dt.time(14, 30),
    exit_start_time=dt.time(14, 45),
    exit_time=dt.time(15, 0),
    stop_move_pct=0.0075,
    profit_take_pct=0.90,
    lookback_sessions=14,
    allowed_dte=(0,),
)

EXPORTS: list[dict] = [
    {
        "strategy_id": "static-strangle-expiry",
        "title": "Static strangle — expiry day, 12:00",
        "description": (
            "Sell the 0.15-delta call and put together at 12:00 on expiry day, stop on a "
            "0.75% NIFTY move, hold to settlement. The tuned baseline every other arm is "
            "measured against."
        ),
        "kind": "static",
        "params": STATIC,
    },
    {
        "strategy_id": "dynamic-atr-expiry",
        "title": "Dynamic strangle — 14-session ATR band, expiry day",
        "description": (
            "Sell the call only when NIFTY reaches the upper bound and the put only when it "
            "reaches the lower, where the bounds are 0.75x the average 10:00-15:00 range of "
            "the last 14 sessions, applied to the 10:00 print."
        ),
        "kind": "dynamic",
        "params": replace(DYNAMIC, range_method=RangeMethod.ATR_WINDOW, atr_multiple=0.75),
    },
    {
        "strategy_id": "dynamic-bollinger-expiry",
        "title": "Dynamic strangle — 1.5 sigma Bollinger band, expiry day",
        "description": (
            "The same sell-on-touch rule with the band set at 1.5 standard deviations of the "
            "in-window close-to-open move rather than the average range. The most consistent "
            "risk profile in the study: profit factor 3.48 in sample, 3.72 out."
        ),
        "kind": "dynamic",
        "params": replace(DYNAMIC, range_method=RangeMethod.BOLLINGER, bollinger_sigma=1.5),
    },
    {
        "strategy_id": "dynamic-atr-all-tenors",
        "title": "Dynamic strangle — ATR band, every session",
        "description": (
            "The ATR rule applied to every session rather than expiry day only. Exported "
            "because it is the arm that fails: negative in sample, positive out, which is "
            "the signature of noise rather than edge."
        ),
        "kind": "dynamic",
        "params": replace(
            DYNAMIC,
            range_method=RangeMethod.ATR_WINDOW,
            atr_multiple=0.75,
            allowed_dte=(0, 1, 2, 3, 4, 5, 6),
        ),
    },
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_EXPORT_DIR)
    parser.add_argument("--underlying", default="NIFTY")
    parser.add_argument("--only", default=None, help="comma-separated strategy ids")
    args = parser.parse_args(argv)

    stats = load_window_stats(corpus_root=DEFAULT_CORPUS_ROOT, underlying=args.underlying)
    wanted = set(args.only.split(",")) if args.only else None

    for spec in EXPORTS:
        if wanted and spec["strategy_id"] not in wanted:
            continue
        scratch = Path(tempfile.mkdtemp(prefix="xman_export_")) / "t.db"
        common = {
            "start": WINDOW_START,
            "end": WINDOW_END,
            "params": spec["params"],
            "trial_log": scratch,
            "label": spec["strategy_id"],
        }
        try:
            if spec["kind"] == "static":
                run = run_strangle(StrangleRunConfig(**common))
            else:
                run = run_dynamic(DynamicRunConfig(**common))
        except Exception as error:
            print(f"{spec['strategy_id']}: FAILED {type(error).__name__}: {error}"[:180])
            continue
        destination = export_run(
            run=run,
            strategy_id=spec["strategy_id"],
            title=spec["title"],
            description=spec["description"],
            corpus_root=DEFAULT_CORPUS_ROOT,
            underlying=args.underlying,
            window_stats=stats,
            out_dir=args.out,
        )
        size_kb = destination.stat().st_size / 1024
        print(
            f"{spec['strategy_id']:28s} trades={run.metrics['trades']:4d} "
            f"net={run.metrics['net_pnl_rupees']:>10,.0f} -> {destination.name} ({size_kb:.0f} KB)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
