"""Run every arm of the overlay study and write one JSON per arm plus a summary.

Sequential on purpose: every arm writes a trial row to the same canonical log, and the
value of that log is that the arms are counted, not that they finish quickly.

    uv run python research/overlay/sweep.py --out research/overlay/results
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from dataclasses import replace
from pathlib import Path

from xman_research.overlay.run import OverlayRunConfig, run_overlay
from xman_research.overlay.sizing import MarginPerLotModel

START = dt.date(2021, 9, 20)
END = dt.date(2026, 9, 15)


def arms() -> list[OverlayRunConfig]:
    base = OverlayRunConfig(start=START, end=END, wing_policy="spec", label="A_spec_primary")
    return [
        base,
        replace(base, wing_policy="observed", label="B_observed_wings"),
        replace(base, min_credit_ratio=0.0015, label="C_credit_015"),
        replace(base, min_credit_ratio=0.0020, label="D_credit_020_spec_default"),
        replace(base, slippage_rupees=0.0, label="E_slippage_zero"),
        replace(base, slippage_rupees=0.50, label="F_slippage_050"),
        replace(
            base,
            margin_model=MarginPerLotModel(include_expiry_day_elm=False),
            label="G_margin_defined_risk_only",
        ),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--only", default=None, help="comma-separated arm labels")
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)

    wanted = set(args.only.split(",")) if args.only else None
    summary: dict[str, object] = {}
    for config in arms():
        if wanted and config.label not in wanted:
            continue
        try:
            run = run_overlay(config)
        except Exception as error:
            # A backtest can refuse rather than return: the settlement rules decline a
            # session whose 15:00-15:30 window is a bar short, and a position that could
            # not be closed before expiry reaches exactly that. Recording the refusal and
            # continuing keeps the other arms, and the refusal itself is a finding.
            summary[config.label] = {"error": f"{type(error).__name__}: {error}"}
            (args.out / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
            print(f"{config.label}: FAILED {type(error).__name__}: {error}", flush=True)
            continue
        payload = run.as_dict()
        (args.out / f"{config.label}.json").write_text(json.dumps(payload, indent=2, default=str))
        (args.out / f"{config.label}.journal.json").write_text(
            json.dumps(list(run.journal), indent=1, default=str)
        )
        summary[config.label] = run.metrics
        metrics = run.metrics
        print(
            f"{config.label}: cycles={metrics['completed_cycles']} "
            f"net=Rs{metrics['net_pnl_rupees']:,.0f} "
            f"total={_pct(metrics['return_on_pc_total'])} "
            f"annualised={_pct(metrics['return_on_pc_annualised'])} "
            f"maxDD={_pct(metrics['max_drawdown_pct_of_pc'])} "
            f"win={_pct(metrics['win_rate'])}",
            flush=True,
        )
        (args.out / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    return 0


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2%}"


if __name__ == "__main__":
    raise SystemExit(main())
