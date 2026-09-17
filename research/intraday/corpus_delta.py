"""What the corpus fix moved, measured rather than asserted.

Every before/after number quoted in ``research/intraday/FINDINGS.md`` and
``research/overlay/REPORT.md`` comes from here. A claim in a report with no script behind it
is a claim the next reader has to take on trust, and this study has already had one round of
numbers that did not survive checking.

Two comparisons:

* the derived daily series the overlay's entry filters read, old cache against new;
* the per-arm result files, baseline against rerun, for both intraday searches and the
  overlay's stage five.

    uv run python research/intraday/corpus_delta.py
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

CACHE = Path("/home/qa/runtime/data/research/overlay")


def _series_delta() -> dict[str, Any]:
    """The overlay's daily context, before the fix and after."""
    out: dict[str, Any] = {}
    pairs = [
        (
            "daily_context",
            CACHE / "daily_context_NIFTY.parquet",
            CACHE / "daily_context_NIFTY_v3.parquet",
        ),
        (
            "window_stats",
            CACHE / "window_stats_NIFTY.parquet",
            CACHE / "window_stats_NIFTY_v2.parquet",
        ),
    ]
    for name, before, after in pairs:
        if not (before.is_file() and after.is_file()):
            out[name] = "one side of the comparison is not on disk"
            continue
        merged = pd.read_parquet(before).merge(
            pd.read_parquet(after), on="session_date", suffixes=("_old", "_new")
        )
        # Numeric columns only: `expiry` is a date and differencing it yields a timedelta.
        columns = [
            c[:-4]
            for c in merged.columns
            if c.endswith("_old") and pd.api.types.is_numeric_dtype(merged[c])
        ]
        out[name] = {"sessions": len(merged)}
        for column in columns:
            changed = (merged[f"{column}_old"] - merged[f"{column}_new"]).abs()
            moved = changed > 1e-9
            out[name][column] = {
                "sessions_changed": int(moved.sum()),
                "share": round(float(moved.mean()), 4),
                "median_abs_change": (
                    round(float(changed[moved].median()), 4) if moved.any() else 0.0
                ),
                "max_abs_change": round(float(changed.max()), 4),
            }
    return out


def _rows(path: Path) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text())
    rows = payload if isinstance(payload, list) else payload.get("results", [])
    return {row["label"]: row for row in rows if isinstance(row, dict) and "label" in row}


def _arm_delta(before: Path, after: Path, fields: tuple[str, ...]) -> list[dict[str, Any]]:
    old, new = _rows(before), _rows(after)
    out: list[dict[str, Any]] = []
    for label, row in new.items():
        if label not in old or "error" in row or "error" in old[label]:
            continue
        entry: dict[str, Any] = {"label": label}
        for field in fields:
            a, b = old[label].get(field), row.get(field)
            if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                entry[field] = {"before": a, "after": b, "delta": round(b - a, 6)}
        out.append(entry)
    return out


def _nested(rows: dict[str, dict[str, Any]], slice_: str, field: str) -> dict[str, float]:
    return {
        label: row[slice_][field]
        for label, row in rows.items()
        if isinstance(row.get(slice_), dict) and isinstance(row[slice_].get(field), (int, float))
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out", type=Path, default=Path("research/intraday/results/corpus_delta.json")
    )
    args = parser.parse_args(argv)

    report: dict[str, Any] = {"derived_series": _series_delta()}

    report["intraday_dynamic"] = _arm_delta(
        Path("research/intraday/results/dynamic.json"),
        Path("research/intraday/results/rerun/dynamic.json"),
        ("trades", "net"),
    )
    report["intraday_atr"] = _arm_delta(
        Path("research/intraday/results/atr_bands.json"),
        Path("research/intraday/results/rerun/atr_bands.json"),
        ("trades", "net"),
    )

    old = _rows(Path("research/overlay/results/tuning_stage5/tuning.json"))
    new = _rows(Path("research/overlay/results/rerun_stage5/tuning.json"))
    overlay: list[dict[str, Any]] = []
    for label in new:
        if label not in old:
            continue
        entry: dict[str, Any] = {"label": label}
        for slice_ in ("in_sample", "out_of_sample"):
            for field in ("return_on_pc_annualised", "completed_cycles", "net_pnl_rupees"):
                a = _nested({label: old[label]}, slice_, field).get(label)
                b = _nested({label: new[label]}, slice_, field).get(label)
                if a is None or b is None:
                    continue
                entry[f"{slice_}.{field}"] = {"before": a, "after": b, "delta": round(b - a, 6)}
        overlay.append(entry)
    report["overlay_stage5"] = overlay

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=1, default=str))

    series = report["derived_series"].get("daily_context", {})
    print("daily_context, the series the overlay's entry filters read:")
    for column in ("open", "close", "atm_iv"):
        stat = series.get(column)
        if isinstance(stat, dict):
            print(
                f"  {column:8s} changed on {stat['sessions_changed']:4d} sessions "
                f"({stat['share']:.1%}), median |change| {stat['median_abs_change']}, "
                f"max {stat['max_abs_change']}"
            )

    def is_delta(entry: dict[str, Any]) -> float:
        return (entry.get("in_sample.return_on_pc_annualised") or {}).get("delta", 0.0)

    up = [e for e in overlay if is_delta(e) > 0]
    down = [e for e in overlay if is_delta(e) < 0]
    print(
        f"\noverlay stage five: {len(overlay)} configurations; "
        f"{len(down)} in-sample returns fall, {len(up)} rise"
    )
    oos_moved = [
        e
        for e in overlay
        if abs((e.get("out_of_sample.net_pnl_rupees") or {}).get("delta", 0)) > 0.005
    ]
    worst = max((abs(e["out_of_sample.net_pnl_rupees"]["delta"]) for e in oos_moved), default=0.0)
    print(
        f"  out-of-sample net P&L moves in {len(oos_moved)} of {len(overlay)}, "
        f"by at most Rs {worst:.0f}"
    )
    print(f"\nwritten to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
