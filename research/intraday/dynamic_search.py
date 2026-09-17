"""Does selling each leg on touch beat selling both at a fixed time?

The control is the static strangle at its tuned parameters, run on the identical window
through the identical harness. Everything else here varies only how the range is drawn and
how far the index has to run past a bound before the leg is stopped.

**What the first smoke test suggested, and what this is checking.** On 24 legs over six
months the dynamic version won 75% of its trades and still lost money: profit factor 0.75,
four stop-outs costing more than seventeen profit-takes made. That is the shape adverse
selection produces — you sell the call exactly where a breakout begins, so the wins are
ordinary and the losses are not. Whether it survives a five-year sample is the question.

    uv run python research/intraday/dynamic_search.py --out research/intraday/results
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import tempfile
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from pathlib import Path
from typing import Any

from xman_research.intraday import (
    DynamicParameters,
    DynamicRunConfig,
    RangeMethod,
    SpotStop,
    StrangleParameters,
    StrangleRunConfig,
    run_dynamic,
    run_strangle,
)

WINDOW_START = dt.date(2021, 9, 20)
WINDOW_END = dt.date(2026, 9, 15)
IN_SAMPLE_END = dt.date(2025, 3, 31)

#: The tuned static strangle, as the control every dynamic arm is measured against.
STATIC = StrangleParameters(
    short_delta_target=0.15,
    delta_band=(0.11, 0.19),
    stop=SpotStop.MOVE_FROM_ENTRY,
    stop_move_pct=0.0075,
    entry_time=dt.time(12, 0),
    profit_take_pct=0.90,
    allowed_dte=(0,),
)

BASE = DynamicParameters(
    short_delta_target=0.15,
    delta_band=(0.11, 0.19),
    stop_move_pct=0.0075,
    profit_take_pct=0.90,
    allowed_dte=(0,),
)


def specs(window: tuple[dt.date, dt.date]) -> list[tuple[str, Any]]:
    start, end = window
    jobs: list[tuple[str, Any]] = [
        ("CONTROL_static_1200", StrangleRunConfig(start=start, end=end, params=STATIC)),
    ]

    def dynamic(params: DynamicParameters, label: str) -> None:
        jobs.append((label, DynamicRunConfig(start=start, end=end, params=params, label=label)))

    for until in (dt.time(10, 0), dt.time(10, 30), dt.time(11, 0)):
        dynamic(
            replace(BASE, range_method=RangeMethod.OPENING_RANGE, opening_range_until=until),
            f"dyn_openrange_{until.hour:02d}{until.minute:02d}",
        )
    for width in (0.003, 0.004, 0.006, 0.008):
        dynamic(
            replace(BASE, range_method=RangeMethod.PERCENT_FROM_OPEN, range_width_pct=width),
            f"dyn_pct{width * 100:.1f}",
        )
    for multiple in (0.75, 1.0, 1.5):
        dynamic(
            replace(BASE, range_method=RangeMethod.IV_MOVE, iv_move_multiple=multiple),
            f"dyn_ivmove{multiple:g}",
        )
    # The stop, at the best-guess range, because a leg sold on touch is already adverse.
    for stop in (0.005, 0.0075, 0.010, 0.015):
        dynamic(
            replace(
                BASE,
                range_method=RangeMethod.OPENING_RANGE,
                opening_range_until=dt.time(10, 0),
                stop_move_pct=stop,
            ),
            f"dyn_stop{stop * 100:.2f}",
        )
    # And an all-tenor arm, since a dynamic rule has more sessions to work with.
    dynamic(
        replace(
            BASE,
            range_method=RangeMethod.OPENING_RANGE,
            opening_range_until=dt.time(10, 0),
            allowed_dte=(0, 1, 2, 3, 4, 5, 6),
        ),
        "dyn_all_tenors",
    )
    return jobs


def _run(job: tuple[str, Any]) -> dict[str, Any]:
    label, config = job
    scratch = Path(tempfile.mkdtemp(prefix="xman_dyn_")) / "t.db"
    try:
        config = replace(config, trial_log=scratch)
        run = run_dynamic(config) if isinstance(config, DynamicRunConfig) else run_strangle(config)
        metrics = run.metrics
        return {
            "label": label,
            "trades": metrics["trades"],
            "net": metrics["net_pnl_rupees"],
            "on_margin": metrics["return_on_peak_margin"],
            "maxdd": metrics["max_drawdown_pct_of_capital"],
            "win_rate": metrics["win_rate"],
            "profit_factor": metrics["profit_factor"],
            "worst_trade_pct": metrics["worst_trade_pct_of_capital"],
            "exit_rules": metrics["exit_rules"],
            "exit_pnl": metrics["exit_pnl"],
        }
    except Exception as error:
        return {"label": label, "error": f"{type(error).__name__}: {error}"[:160]}


def _line(row: dict[str, Any]) -> str:
    if "error" in row:
        return f"{row['label']:24s} FAILED {row['error'][:70]}"

    def pct(value: float | None) -> str:
        return "  n/a " if value is None else f"{value:7.2%}"

    return (
        f"{row['label']:24s} n={row['trades']:4d} net {row['net']:>10,.0f} "
        f"margin {pct(row['on_margin'])} dd {pct(row['maxdd'])} "
        f"win {pct(row['win_rate'])} PF {row['profit_factor'] or 0:5.2f} "
        f"worst {pct(row['worst_trade_pct'])}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--split", action="store_true", help="run in-sample and holdout")
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)

    windows = (
        [
            ("IS", (WINDOW_START, IN_SAMPLE_END)),
            ("OOS", (IN_SAMPLE_END + dt.timedelta(days=1), WINDOW_END)),
        ]
        if args.split
        else [("FULL", (WINDOW_START, WINDOW_END))]
    )
    jobs: list[tuple[str, Any]] = []
    for tag, window in windows:
        for label, config in specs(window):
            jobs.append((f"{tag}_{label}", config))

    results: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for row in pool.map(_run, jobs):
            results.append(row)
            (args.out / "dynamic.json").write_text(json.dumps(results, indent=2, default=str))
            print(_line(row), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
