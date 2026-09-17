"""The owner's specification: a 14-session ATR band on the 10:00-15:00 window.

Trade only between 10:00 and 15:00 — avoiding the opening auction's jitter and the closing
half hour, where the far legs stop printing. Draw the band from the average range the index
has covered *inside that same window* over the last fourteen sessions, applied to the 10:00
print. Sell the call when the upper bound is touched, the put when the lower is. Run it on
expiry days and on every other day, and compare.

A Bollinger variant is run beside it: same window, same lookback, but the band is a multiple
of the standard deviation of the in-window close-to-open move rather than the mean range. The
two differ in what they treat as normal — ATR asks how far the index travels, Bollinger asks
how far it ends up — and on a mean-reverting session those are very different numbers.

The tuned static strangle is the control throughout, so a difference is the rule and not the
harness.

    uv run python research/intraday/atr_search.py --out research/intraday/results --split
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

ALL_TENORS = (0, 1, 2, 3, 4, 5, 6)

#: The owner's window: nothing before 10:00, everything closed by 15:00.
BASE = DynamicParameters(
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

STATIC_CONTROL = StrangleParameters(
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


def specs(window: tuple[dt.date, dt.date]) -> list[tuple[str, Any]]:
    start, end = window
    jobs: list[tuple[str, Any]] = [
        ("CONTROL_static_expiry", StrangleRunConfig(start=start, end=end, params=STATIC_CONTROL)),
        (
            "CONTROL_static_alltenor",
            StrangleRunConfig(
                start=start, end=end, params=replace(STATIC_CONTROL, allowed_dte=ALL_TENORS)
            ),
        ),
    ]

    def dynamic(params: DynamicParameters, label: str) -> None:
        jobs.append((label, DynamicRunConfig(start=start, end=end, params=params, label=label)))

    for tenor_label, tenors in (("exp", (0,)), ("all", ALL_TENORS)):
        for multiple in (0.5, 0.75, 1.0):
            dynamic(
                replace(
                    BASE,
                    range_method=RangeMethod.ATR_WINDOW,
                    atr_multiple=multiple,
                    allowed_dte=tenors,
                ),
                f"atr{multiple:g}_{tenor_label}",
            )
        for sigma in (1.0, 1.5, 2.0):
            dynamic(
                replace(
                    BASE,
                    range_method=RangeMethod.BOLLINGER,
                    bollinger_sigma=sigma,
                    allowed_dte=tenors,
                ),
                f"boll{sigma:g}_{tenor_label}",
            )
    # The stop, at the ATR band that trades most, because a leg sold on touch is already
    # at an adverse price and may want more room than the static rule's 0.75%.
    for stop in (0.005, 0.010, 0.015):
        dynamic(
            replace(
                BASE,
                range_method=RangeMethod.ATR_WINDOW,
                atr_multiple=0.75,
                stop_move_pct=stop,
                allowed_dte=ALL_TENORS,
            ),
            f"atr0.75_stop{stop * 100:.2f}_all",
        )
    return jobs


def _run(job: tuple[str, Any]) -> dict[str, Any]:
    label, config = job
    scratch = Path(tempfile.mkdtemp(prefix="xman_atr_")) / "t.db"
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
        }
    except Exception as error:
        return {"label": label, "error": f"{type(error).__name__}: {error}"[:150]}


def _line(row: dict[str, Any]) -> str:
    if "error" in row:
        return f"{row['label']:28s} FAILED {row['error'][:60]}"

    def pct(value: float | None) -> str:
        return "  n/a " if value is None else f"{value:7.2%}"

    return (
        f"{row['label']:28s} n={row['trades']:4d} net {row['net']:>10,.0f} "
        f"margin {pct(row['on_margin'])} dd {pct(row['maxdd'])} "
        f"win {pct(row['win_rate'])} PF {row['profit_factor'] or 0:5.2f} "
        f"worst {pct(row['worst_trade_pct'])}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--split", action="store_true")
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
    jobs = [
        (f"{tag}_{label}", config) for tag, window in windows for label, config in specs(window)
    ]

    results: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for row in pool.map(_run, jobs):
            results.append(row)
            (args.out / "atr_bands.json").write_text(json.dumps(results, indent=2, default=str))
            print(_line(row), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
