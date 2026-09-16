"""Parameter search for the intraday short strangle: strike, stop, entry, profit.

Coordinate search around a base configuration, run in parallel, ranked on **reward-to-risk**
rather than on return — the owner's question is which parameters give the best risk versus
reward, and a return ranking would simply pick whichever configuration happened to carry the
largest position.

**The null is not zero.** H26 measured intraday short premium on this corpus at -10.5% a
year, so a configuration has to beat a negative prior before it is interesting — and the ones
that clear zero by a little are the ones to distrust most, because that is what a search over
thirty configurations produces from noise.

**Every row reports how many trades failed to close intraday.** A strangle that carries
overnight is not this strategy; it is the strategy H26 found *does* make money, and a search
that quietly counted those trades would rediscover H26's result and call it an intraday
edge.

    uv run python research/intraday/search.py --out research/intraday/results --stage 1
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

from xman_research.intraday import SpotStop, StrangleParameters, StrangleRunConfig, run_strangle

WINDOW_START = dt.date(2021, 9, 20)
WINDOW_END = dt.date(2026, 9, 15)
IN_SAMPLE_END = dt.date(2025, 3, 31)

BASE = StrangleParameters(
    short_delta_target=0.15,
    delta_band=(0.11, 0.19),
    stop=SpotStop.MOVE_FROM_ENTRY,
    stop_move_pct=0.005,
    entry_time=dt.time(9, 45),
    profit_take_pct=0.50,
)


def stage_one() -> list[StrangleRunConfig]:
    """One lever at a time, around the base."""
    specs: list[StrangleRunConfig] = []

    def add(params: StrangleParameters, label: str) -> None:
        specs.append(
            StrangleRunConfig(start=WINDOW_START, end=WINDOW_END, params=params, label=label)
        )

    # 1. Which strike to sell.
    for target in (0.08, 0.12, 0.15, 0.20, 0.25):
        add(
            replace(BASE, short_delta_target=target, delta_band=(target - 0.04, target + 0.04)),
            f"strike_d{target:.2f}",
        )

    # 2. The stop, on the index.
    for move in (0.003, 0.005, 0.0075, 0.010, 0.015):
        add(replace(BASE, stop_move_pct=move), f"stop_move{move * 100:.2f}pct")
    for buffer in (0.50, 0.75, 1.00):
        add(
            replace(BASE, stop=SpotStop.STRIKE_BREACH, stop_strike_buffer=buffer),
            f"stop_strike{int(buffer * 100)}",
        )

    # 3. When to enter.
    for hour, minute in ((9, 20), (9, 45), (10, 15), (11, 0), (12, 0), (13, 0)):
        add(replace(BASE, entry_time=dt.time(hour, minute)), f"entry_{hour:02d}{minute:02d}")

    # 4. When to book.
    for take in (0.25, 0.40, 0.50, 0.70, 0.90):
        add(replace(BASE, profit_take_pct=take), f"take{int(take * 100)}")

    # And the tenor, which conditions all four.
    for name, dtes in (
        ("dte_all", (0, 1, 2, 3, 4, 5, 6)),
        ("dte_0_expiry_day", (0,)),
        ("dte_1_2", (1, 2)),
        ("dte_3_4", (3, 4)),
        ("dte_5_6", (5, 6)),
    ):
        add(replace(BASE, allowed_dte=dtes), name)

    seen: set[str] = set()
    unique: list[StrangleRunConfig] = []
    for spec in specs:
        if spec.label in seen:
            continue
        seen.add(spec.label)
        unique.append(spec)
    return unique


def _run(config: StrangleRunConfig) -> dict[str, Any]:
    scratch = Path(tempfile.mkdtemp(prefix="xman_strangle_")) / "t.db"
    try:
        run = run_strangle(replace(config, trial_log=scratch))
        metrics = run.metrics
        return {
            "label": config.label,
            "trades": metrics["trades"],
            "annualised": metrics["return_on_capital_annualised"],
            "maxdd": metrics["max_drawdown_pct_of_capital"],
            "win_rate": metrics["win_rate"],
            "reward_to_risk": metrics["reward_to_risk"],
            "profit_factor": metrics["profit_factor"],
            "expectancy": metrics["expectancy_rupees"],
            "worst_trade_pct": metrics["worst_trade_pct_of_capital"],
            "sharpe": metrics["sharpe_annualised"],
            "carried_overnight": metrics["exit_rules"].get("carried_overnight_forced_close", 0),
            "exit_rules": metrics["exit_rules"],
            "exit_pnl": metrics["exit_pnl"],
            "median_credit_pct_of_spot": metrics["median_credit_pct_of_spot"],
        }
    except Exception as error:  # noqa: BLE001 — one configuration must not end the search
        return {"label": config.label, "error": f"{type(error).__name__}: {error}"[:200]}


def _line(row: dict[str, Any]) -> str:
    if "error" in row:
        return f"{row['label']:22s} FAILED {row['error'][:70]}"

    def pct(value: float | None) -> str:
        return "  n/a " if value is None else f"{value:6.2%}"

    return (
        f"{row['label']:22s} n={row['trades']:4d} {pct(row['annualised'])}/yr "
        f"dd {pct(row['maxdd'])} win {pct(row['win_rate'])} "
        f"R:R {row['reward_to_risk'] or 0:5.2f} PF {row['profit_factor'] or 0:5.2f} "
        f"worst {pct(row['worst_trade_pct'])} carried {row['carried_overnight']}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--stage", type=int, default=1)
    parser.add_argument("--workers", type=int, default=14)
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)

    specs = stage_one()
    results: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for row in pool.map(_run, specs):
            results.append(row)
            (args.out / f"stage{args.stage}.json").write_text(
                json.dumps(results, indent=2, default=str)
            )
            print(_line(row), flush=True)
    print(f"\n{len(results)} configurations; null to beat is H26's -10.5%/yr intraday")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
