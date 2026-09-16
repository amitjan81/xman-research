"""Render the report's tables from the arm JSONs, so no number in it is typed by hand.

    uv run python research/overlay/report_tables.py --results research/overlay/results
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

ARM_TITLES = {
    "A_spec_primary": "A — specified 350pt wings (modelled where unprinted)",
    "B_observed_wings": "B — wings that printed at entry (100-400pt, per side)",
    "C_credit_015": "C — minimum credit 0.15% of notional",
    "D_credit_020_spec_default": "D — minimum credit 0.20% (the document's default)",
    "E_slippage_zero": "E — zero slippage",
    "F_slippage_050": "F — slippage Rs 0.50 per unit per leg",
    "G_margin_defined_risk_only": "G — margin = defined risk only (no CA-12 ELM)",
    "H_relaxed_participation_caps": "H — diagnostic: participation caps 5% volume / 2% OI",
    "I_no_roll_relaxed_caps": "I — diagnostic: H, with ST-20 rolls switched off",
}


def pct(value: float | None, digits: int = 2) -> str:
    return "n/a" if value is None else f"{value * 100:.{digits}f}%"


def rupees(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:,.0f}"


def headline_table(runs: dict[str, dict[str, Any]]) -> str:
    header = (
        "| Arm | Cycles | Net P&L | Return on PC | Annualised | Max DD | Win rate | "
        "Sharpe | Cost ratio |\n"
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|"
    )
    lines = [header]
    for label, payload in runs.items():
        metrics = payload.get("metrics", payload)
        if "error" in metrics:
            lines.append(f"| {ARM_TITLES.get(label, label)} | — | FAILED: {metrics['error']} |")
            continue
        sharpe = metrics.get("sharpe_annualised")
        lines.append(
            f"| {ARM_TITLES.get(label, label)} "
            f"| {metrics['completed_cycles']} "
            f"| {rupees(metrics['net_pnl_rupees'])} "
            f"| {pct(metrics['return_on_pc_total'])} "
            f"| {pct(metrics['return_on_pc_annualised'])} "
            f"| {pct(metrics['max_drawdown_pct_of_pc'])} "
            f"| {pct(metrics['win_rate'], 1)} "
            f"| {'n/a' if sharpe is None else f'{sharpe:.2f}'} "
            f"| {pct(metrics['cost_ratio'], 1)} |"
        )
    return "\n".join(lines)


def exit_table(metrics: dict[str, Any]) -> str:
    rules = metrics.get("exit_rules", {})
    total = sum(rules.values()) or 1
    lines = ["| Closed by | Cycles | Share |", "|---|---:|---:|"]
    for rule, count in sorted(rules.items(), key=lambda item: -item[1]):
        lines.append(f"| `{rule}` | {count} | {count / total:.0%} |")
    return "\n".join(lines)


def decline_table(journal: list[dict[str, Any]]) -> str:
    """Declines counted once per session, not once per decision minute."""
    seen: set[tuple[str, str]] = set()
    counter: Counter[str] = Counter()
    for row in journal:
        if row["outcome"] != "declined":
            continue
        key = (row["session_date"], row["rule"])
        if key in seen:
            continue
        seen.add(key)
        counter[row["rule"]] += 1
    lines = ["| Rule | Entry sessions it refused |", "|---|---:|"]
    for rule, count in counter.most_common():
        lines.append(f"| `{rule}` | {count} |")
    return "\n".join(lines)


def _decisions(results: Path, arm: str) -> list[dict[str, Any]]:
    """The arm's decisions, from whichever form is on disk.

    A run writes the full per-decision-minute journal; the committed artefact is the
    per-session digest, because the journal is 700KB of repetition and regenerable. Both
    shapes answer the only question this module asks of them — which rule refused which
    entry session — so both are accepted.
    """
    digest = results / f"{arm}.decisions.json"
    if digest.is_file():
        payload = json.loads(digest.read_text())
        return [
            {"session_date": date, **entry}
            for date, entries in payload["sessions"].items()
            for entry in entries
        ]
    journal = results / f"{arm}.journal.json"
    if journal.is_file():
        return json.loads(journal.read_text())
    return []


def cost_table(metrics: dict[str, Any]) -> str:
    breakdown = metrics["cost_breakdown"]
    total = metrics["total_costs_rupees"] or 1
    lines = ["| Component | Rupees | Share of costs |", "|---|---:|---:|"]
    for name, value in sorted(breakdown.items(), key=lambda item: -item[1]):
        lines.append(f"| {name.replace('_', ' ')} | {rupees(value)} | {value / total:.0%} |")
    lines.append(f"| **total** | **{rupees(metrics['total_costs_rupees'])}** | 100% |")
    return "\n".join(lines)


def wing_width_table(cycles: list[dict[str, Any]]) -> str:
    widths = Counter(int(cycle["wing_width"]) for cycle in cycles)
    lines = ["| Wing width (worse side) | Cycles |", "|---|---:|"]
    for width, count in sorted(widths.items()):
        lines.append(f"| {width} pts | {count} |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--arm", default="A_spec_primary", help="arm for the detail tables")
    args = parser.parse_args(argv)

    runs: dict[str, dict[str, Any]] = {}
    for label in ARM_TITLES:
        path = args.results / f"{label}.json"
        if path.is_file():
            runs[label] = json.loads(path.read_text())

    print("## Headline\n")
    print(headline_table(runs))

    detail = runs.get(args.arm)
    if detail is None:
        return 0
    metrics = detail["metrics"]
    print(f"\n## {ARM_TITLES.get(args.arm, args.arm)} — detail\n")
    print("### Which rule closed each cycle\n")
    print(exit_table(metrics))
    print("\n### Costs\n")
    print(cost_table(metrics))
    print("\n### Wing widths actually used\n")
    print(wing_width_table(detail["cycles"]))
    print("\n### Entry sessions refused, by rule\n")
    print(decline_table(_decisions(args.results, args.arm)))
    print("\n### Execution\n")
    print(f"- feasibility verdicts: `{metrics['feasibility']}`")
    print(f"- sessions with stale marks: {metrics['stale_mark_sessions']}")
    print(
        f"- entries attempted: {metrics['entries']}, "
        f"cycles completed: {metrics['completed_cycles']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
