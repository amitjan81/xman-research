"""What the corpus can and cannot say about this strategy, per underlying.

Everything the report claims about coverage is produced here, so the claims are
reproducible rather than remembered: how many sessions exist, how many of them are entry
windows at 5-6 days to expiry, how often the 0.12-delta short strike is inside the captured
band, and how much room is left beyond it for a wing.

    uv run python research/overlay/coverage.py --underlying NIFTY \
        --out research/overlay/results/coverage_NIFTY.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Any

from xman_research.backtest.market import OptionType, SessionView
from xman_research.overlay.greeks import bs_delta, year_fraction
from xman_research.session_store import DEFAULT_CORPUS_ROOT, SessionStore

PROBE_TIME = dt.time(10, 0)
DELTA_BAND = (0.10, 0.14)
TARGET = 0.12


def probe(*, underlying: str, corpus_root: Path) -> dict[str, Any]:
    store = SessionStore(root=corpus_root)
    directory = corpus_root / underlying
    dates = sorted(dt.date.fromisoformat(path.stem) for path in directory.glob("*.parquet"))
    if not dates:
        return {"underlying": underlying, "sessions": 0}

    resolution = store.resolve(underlying, dates[0], dates[-1])
    # A coverage probe is the one reader that must not refuse an incomplete range: what it
    # is measuring *is* the incompleteness. The holes travel out in the result instead.
    refs = (
        resolution.sessions()
        if resolution.is_complete
        else resolution.accept_gaps("coverage probe: the gaps are the measurement")
    )
    rows: list[dict[str, Any]] = []
    for ref in refs:
        view = SessionView.from_frame(
            ref.session_date, underlying, store.load_session(ref), store.load_refdata(ref)
        )
        expiry = view.universe.nearest_expiry(ref.session_date)
        if expiry is None:
            continue
        days_to_expiry = (expiry - ref.session_date).days
        row: dict[str, Any] = {
            "session_date": ref.session_date.isoformat(),
            "dte": days_to_expiry,
        }
        if days_to_expiry in (5, 6):
            row.update(_entry_window_facts(view, expiry, days_to_expiry))
        rows.append(row)

    windows = [row for row in rows if row["dte"] in (5, 6)]
    both_in_band = [row for row in windows if row.get("short_call") and row.get("short_put")]
    return {
        "underlying": underlying,
        "sessions": len(rows),
        "first_session": rows[0]["session_date"],
        "last_session": rows[-1]["session_date"],
        "missing_sessions": [value.isoformat() for value in resolution.missing],
        "entry_windows": len(windows),
        "both_shorts_in_delta_band": len(both_in_band),
        "wing_room": _room_summary(both_in_band),
        "min_abs_delta_available": {
            side: _quantiles(
                [
                    row[f"min_abs_delta_{side}"]
                    for row in windows
                    if row.get(f"min_abs_delta_{side}")
                ]
            )
            for side in ("call", "put")
        },
        "sessions_detail": rows,
    }


def _entry_window_facts(view: SessionView, expiry: dt.date, days_to_expiry: int) -> dict[str, Any]:
    minute = view.minute_at_or_after(PROBE_TIME)
    if minute is None:
        return {}
    spot = view.spot_at(minute)
    if not spot:
        return {}
    t_years = year_fraction(
        minute_hour=minute.hour + minute.minute / 60.0, days_to_expiry=days_to_expiry
    )
    facts: dict[str, Any] = {"spot": spot}
    for role, option_type, name in (
        ("short_call", OptionType.CALL, "call"),
        ("short_put", OptionType.PUT, "put"),
    ):
        printed: list[tuple[float, float]] = []
        for strike in view.universe.strikes(expiry):
            contract = view.universe.get(expiry, strike, option_type)
            if contract is None:
                continue
            bar = view.bar(contract.trading_symbol, minute)
            if bar is None or not bar.iv or bar.iv <= 0:
                continue
            delta = abs(
                bs_delta(
                    option_type=option_type, spot=spot, strike=strike, t_years=t_years, iv=bar.iv
                )
            )
            printed.append((strike, delta))
        if not printed:
            continue
        facts[f"min_abs_delta_{name}"] = min(delta for _strike, delta in printed)
        in_band = [
            (strike, delta) for strike, delta in printed if DELTA_BAND[0] <= delta <= DELTA_BAND[1]
        ]
        if not in_band:
            continue
        strike = min(in_band, key=lambda pair: abs(pair[1] - TARGET))[0]
        facts[role] = strike
        strikes = [value for value, _delta in printed]
        facts[f"{name}_room"] = (
            max(strikes) - strike if option_type == OptionType.CALL else strike - min(strikes)
        )
    return facts


def _room_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    call = [row.get("call_room", 0.0) for row in rows]
    put = [row.get("put_room", 0.0) for row in rows]
    return {
        "call": _quantiles(call),
        "put": _quantiles(put),
        "both_sides_at_least_100": sum(
            1 for c, p in zip(call, put, strict=True) if c >= 100 and p >= 100
        ),
        "both_sides_at_least_300": sum(
            1 for c, p in zip(call, put, strict=True) if c >= 300 and p >= 300
        ),
        "either_side_zero": sum(1 for c, p in zip(call, put, strict=True) if c == 0 or p == 0),
    }


def _quantiles(values: list[float]) -> dict[str, float] | None:
    if not values:
        return None
    ordered = sorted(values)

    def at(fraction: float) -> float:
        return ordered[min(int(fraction * len(ordered)), len(ordered) - 1)]

    return {
        "min": ordered[0],
        "p25": at(0.25),
        "median": at(0.5),
        "p75": at(0.75),
        "max": ordered[-1],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--underlying", default="NIFTY")
    parser.add_argument("--corpus-root", type=Path, default=DEFAULT_CORPUS_ROOT)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    facts = probe(underlying=args.underlying, corpus_root=args.corpus_root)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(facts, indent=2, default=str))
    summary = {key: value for key, value in facts.items() if key != "sessions_detail"}
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
