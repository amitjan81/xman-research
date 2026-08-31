"""Render a screen run's tables as markdown, from the run's own CSV and meta.

The screen document quotes counts, funnels and per-pair rows. Transcribing those by
hand at a few hundred candidates is where an arithmetic error enters a document that
reads as evidence, so every table in the document is emitted here from
``all_candidates.csv`` and ``meta.json`` and pasted unedited.

    uv run python research/pairs/screen_nifty50/report_tables.py \
        --run N10L=_output_fno_n10L --run N25L=_output_fno_n25L
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from screen import HALF_LIFE_MAX_SESSIONS, HURST_MAX, LOT_ERROR_MAX, SIGMA_BPS_MIN


def gate_margins(row: pd.Series) -> list[str]:
    """Every failed gate on one candidate, each with the distance from its bar."""
    misses = []
    if not row["bh_pass"]:
        ratio = row["coint_p"] / row["bh_bar"] if row["bh_bar"] > 0 else float("inf")
        misses.append(f"BH: p {row['coint_p']:.3f} vs bar {row['bh_bar']:.2}, {ratio:.0f}x over")
    if not row["gate_half_life"]:
        hl = row["half_life"]
        gap = "no reversion" if hl == float("inf") else f"+{hl - HALF_LIFE_MAX_SESSIONS:.1f} sessions"
        misses.append(f"half-life: {hl:.1f} vs {HALF_LIFE_MAX_SESSIONS:.0f} ({gap})")
    if not row["gate_hurst"]:
        misses.append(f"Hurst: {row['hurst']:.3f} vs {HURST_MAX} (+{row['hurst'] - HURST_MAX:.3f})")
    if not row["gate_sigma"]:
        misses.append(f"sigma: {row['sigma_bps']:.0f} vs {SIGMA_BPS_MIN:.0f} bps")
    if not row["gate_lot"]:
        need = row["min_notional_for_lot_gate"] / 1e5
        misses.append(
            f"lot: err {row['lot_error']:.1%} vs {LOT_ERROR_MAX:.0%} (needs N >= Rs {need:.0f}L)"
        )
    return misses


def markdown(frame: pd.DataFrame, columns: list[str]) -> str:
    """A markdown table, floats to three decimals. Written out rather than delegated to
    ``DataFrame.to_markdown`` so the report needs no dependency beyond the screen's own."""
    lines = ["| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)]
    for _, row in frame.iterrows():
        cells = [f"{row[c]:.3f}" if isinstance(row[c], float) else str(row[c]) for c in columns]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="append", required=True, help="LABEL=path-to-out-dir")
    parser.add_argument("--nearest", type=int, default=5)
    parser.add_argument("--divergent-cap", type=int, default=10)
    args = parser.parse_args()

    runs = {}
    for spec in args.run:
        label, path = spec.split("=", 1)
        directory = Path(path)
        runs[label] = (
            pd.read_csv(directory / "all_candidates.csv"),
            json.loads((directory / "meta.json").read_text()),
        )

    print("### Funnel, both sizings\n")
    labels = list(runs)
    rows = [
        ("Universe names in panel", lambda f, m: m["universe"]),
        ("Candidate pairs (m)", lambda f, m: m["candidates"]),
        ("... passing BH at q=0.10", lambda f, m: m["funnel"]["pass_bh"]),
        ("... and half-life <= 5", lambda f, m: m["funnel"]["pass_bh_and_half_life"]),
        ("... and Hurst < 0.5", lambda f, m: m["funnel"]["pass_bh_hl_hurst"]),
        ("... and sigma >= 50 bps", lambda f, m: m["funnel"]["pass_bh_hl_hurst_sigma"]),
        ("... and lot error <= 10 % (admitted)", lambda f, m: m["funnel"]["admitted"]),
        ("solo: BH", lambda f, m: m["funnel"]["solo_pass_bh"]),
        ("solo: half-life", lambda f, m: m["funnel"]["solo_pass_half_life"]),
        ("solo: Hurst", lambda f, m: m["funnel"]["solo_pass_hurst"]),
        ("solo: sigma", lambda f, m: m["funnel"]["solo_pass_sigma"]),
        ("solo: lot error", lambda f, m: m["funnel"]["solo_pass_lot"]),
        ("min half-life", lambda f, m: round(m["funnel"]["min_half_life"], 2)),
        ("min coint p", lambda f, m: round(m["funnel"]["min_coint_p"], 4)),
        ("BH bar at rank 1", lambda f, m: f"{m['funnel']['bh_bar_at_rank_1']:.2}"),
        ("n half-life <= 10", lambda f, m: m["funnel"]["n_half_life_le_10"]),
        ("n coint p <= 0.05 (unadjusted)", lambda f, m: m["funnel"]["n_coint_p_le_0p05_unadjusted"]),
        ("median min N for lot gate (Rs L)",
         lambda f, m: round(f["min_notional_for_lot_gate"].median() / 1e5, 1)),
    ]
    print("| Stage | " + " | ".join(labels) + " |")
    print("|---|" + "---|" * len(labels))
    for name, fn in rows:
        print(f"| {name} | " + " | ".join(str(fn(*runs[lbl])) for lbl in labels) + " |")

    for label, (frame, meta) in runs.items():
        admitted = frame[frame["admitted"]]
        print(f"\n### {label}: admitted = {len(admitted)}; "
              f"entry candidates |z|>=2 = {int((admitted['z_today'].abs() >= 2).sum())}; "
              f"watchlist = {int((admitted['z_today'].abs() < 2).sum())}")
        if not admitted.empty:
            cols = ["symbol_a", "symbol_b", "beta", "half_life", "sigma_bps", "coint_p",
                    "bh_bar", "hurst", "crossings", "lot_error", "lots_a", "lots_b", "z_today"]
            print(markdown(admitted.sort_values("z_today", key=abs, ascending=False), cols))

    frame, meta = runs[labels[0]]
    frame = frame.copy()
    gates = ["bh_pass", "gate_half_life", "gate_hurst", "gate_sigma", "gate_lot"]
    frame["gates_failed"] = (~frame[gates]).sum(axis=1)
    nearest = frame.sort_values(["gates_failed", "coint_p"]).head(args.nearest)
    print(f"\n### Nearest misses ({labels[0]} sizing) — NOT admitted\n")
    print("| pair | gates failed | which, and by how much |")
    print("|---|---|---|")
    for _, row in nearest.iterrows():
        print(f"| {row['symbol_a']}/{row['symbol_b']} | {int(row['gates_failed'])} | "
              + "; ".join(gate_margins(row)) + " |")

    divergent = frame[(frame["z_today"].abs() >= 2) & ~frame["admitted"]]
    print(f"\n### Divergent but NOT admitted: {len(divergent)} pairs "
          f"(top {min(args.divergent_cap, len(divergent))} by |z|)\n")
    top = divergent.sort_values("z_today", key=abs, ascending=False).head(args.divergent_cap)
    cols = ["symbol_a", "symbol_b", "z_today", "beta", "half_life", "sigma_bps", "coint_p",
            "hurst", "lot_error"]
    if not top.empty:
        print(markdown(top, cols))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
