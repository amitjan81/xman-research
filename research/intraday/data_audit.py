"""Audit the captured corpus for defects that would change a backtest's answer.

Written after one defect was found by accident — 15% of sessions carry minute timestamps
outside the NSE exchange day — on the principle that a defect found by accident is evidence
of a class nobody has looked for. Each check below is something that, if true, silently moves
a result rather than raising an error.

**Its boundaries are the reader's boundaries**, imported from
:mod:`xman_research.corpus_hygiene` rather than restated here. An audit that draws the line
somewhere the reader does not measures a different thing than the one being fixed, which is
how the first version of this file reported 208 padded sessions where there are 185: the
other 23 were the Closing Auction Session, which is market and which the reader keeps.

Every check reports counts and examples, never a verdict. What to do about a finding is a
decision; what the data says is a measurement.

    uv run python research/intraday/data_audit.py --workers 12
"""

from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from itertools import pairwise
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq

from xman_research.corpus_hygiene import (
    CONTINUOUS_CLOSE,
    SESSION_CLOSE,
    SESSION_OPEN,
)

IST = "Asia/Kolkata"

#: A minute-to-minute index move larger than this is a print to look at, not a market move.
SPOT_JUMP_PCT = 2.0


def audit_session(path_str: str) -> dict[str, Any]:
    """Every check, for one session file."""
    path = Path(path_str)
    session_date = dt.date.fromisoformat(path.stem)
    frame = pq.read_table(path).to_pandas()
    out: dict[str, Any] = {"session": path.stem, "rows": len(frame)}
    if frame.empty:
        out["empty_file"] = True
        return out

    stamps = pd.to_datetime(frame.minute_ts, unit="us", utc=True).dt.tz_convert(IST)
    times = stamps.dt.time
    dates = stamps.dt.date

    # 1. Timestamps outside the exchange session.
    #
    # **The boundary is the auction's end, not the continuous close**, and the two are
    # reported separately because they are different facts. A row at 15:39 is the Closing
    # Auction Session — market, and what settlement settles against. A row at 07:06 or 18:40
    # is the feed talking to itself. An earlier version of this audit drew the line at 15:30
    # and so counted 23 sessions of pure CAS as padded, overstating the defect by 12%.
    in_session = (times >= SESSION_OPEN) & (times <= SESSION_CLOSE)
    out["rows_outside_session_hours"] = int((~in_session).sum())
    out["rows_in_closing_auction"] = int(
        ((times > CONTINUOUS_CLOSE) & (times <= SESSION_CLOSE)).sum()
    )
    out["first_minute"] = stamps.min().strftime("%H:%M")
    out["last_minute"] = stamps.max().strftime("%H:%M")
    out["distinct_minutes"] = int(frame.minute_ts.nunique())

    # 2. Rows whose timestamp belongs to another date entirely.
    out["rows_on_another_date"] = int((dates != session_date).sum())

    # 3. The same instrument printing twice in one minute.
    duplicates = frame.duplicated(subset=["minute_ts", "symbol"]).sum()
    out["duplicate_symbol_minutes"] = int(duplicates)

    # 4. The underlying disagreeing with itself inside one minute.
    #
    # Everything below this point measures the market, so it measures the rows the backtester
    # will actually see. Run on the unfiltered frame, the stalled-feed check simply
    # re-detected defect 1 — 163 of its 165 hits were the padded sessions — and a 07:06
    # print beside the 09:15 open registered as a 2% minute-to-minute jump.
    frame = frame[in_session]
    if frame.empty:
        out["no_in_session_rows"] = True
        return out
    times = times[in_session]
    spots = frame.dropna(subset=["spot"])
    if not spots.empty:
        spread = spots.groupby("minute_ts").spot.agg(lambda s: s.max() - s.min())
        out["minutes_with_inconsistent_spot"] = int((spread > 0.01).sum())
        out["max_spot_disagreement"] = round(float(spread.max()), 2)
        underlying = spots[spots.symbol == path.parent.name].sort_values("minute_ts")
        if len(underlying) > 2:
            moves = underlying.spot.pct_change().abs() * 100
            out["spot_jumps_over_2pct"] = int((moves > SPOT_JUMP_PCT).sum())
            out["max_minute_spot_move_pct"] = round(float(moves.max()), 3)
            # A spot that does not move for a long stretch is a stalled feed, not a quiet market.
            unchanged = (underlying.spot.diff() == 0).astype(int)
            longest = 0
            current = 0
            for value in unchanged:
                current = current + 1 if value else 0
                longest = max(longest, current)
            out["longest_unchanged_spot_run"] = int(longest)
    else:
        out["no_spot_rows"] = True

    options = frame[frame.symbol.str.contains("-", regex=False)]
    out["option_rows"] = len(options)
    if options.empty:
        out["no_option_rows"] = True
        return out

    # 5. Prices that cannot be prices.
    out["nonpositive_close"] = int((options.close <= 0).sum())
    out["high_below_low"] = int((options.high < options.low).sum())
    out["close_outside_high_low"] = int(
        ((options.close > options.high) | (options.close < options.low)).sum()
    )
    # 6. Implied volatility that cannot be one.
    ivs = options.iv.dropna()
    out["iv_missing"] = int(options.iv.isna().sum())
    out["iv_nonpositive"] = int((ivs <= 0).sum())
    out["iv_over_300pct"] = int((ivs > 3.0).sum())
    # 7. Volume and open interest.
    out["negative_volume"] = int((options.volume.dropna() < 0).sum())
    out["negative_oi"] = int((options.oi.dropna() < 0).sum())

    # 8. Chain shape: how many strikes, and whether the ladder has holes.
    parts = options.symbol.str.split("-", expand=True)
    strikes = parts[2].astype(float)
    out["distinct_expiries"] = int(parts[1].nunique())
    unique_strikes = sorted(strikes.unique())
    out["distinct_strikes"] = len(unique_strikes)
    if len(unique_strikes) > 2:
        steps = [round(b - a, 2) for a, b in pairwise(unique_strikes)]
        # The MODE, not the minimum. NIFTY lists a 50-point ladder near the money and a
        # 100-point one in the wings, so `min` made the ordinary wing spacing look like a
        # hole in every session that had both.
        base = Counter(steps).most_common(1)[0][0]
        out["strike_ladder_holes"] = int(sum(1 for step in steps if step > base + 0.01))
    # 9. A side missing its pair — a strike listed as a call but not a put.
    calls = set(strikes[parts[3] == "CE"])
    puts = set(strikes[parts[3] == "PE"])
    out["unpaired_strikes"] = len(calls ^ puts)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--underlying", default="NIFTY")
    parser.add_argument(
        "--corpus", type=Path, default=Path("/home/qa/runtime/data/backtest/datasets/dhan")
    )
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    paths = sorted(glob.glob(str(args.corpus / args.underlying / "*.parquet")))
    rows: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        rows.extend(pool.map(audit_session, paths))

    frame = pd.DataFrame(rows)
    total = len(frame)
    print(f"{args.underlying}: {total} sessions audited\n")

    def report(column: str, label: str, *, threshold: float = 0) -> None:
        if column not in frame:
            return
        values = frame[column].fillna(0)
        hits = frame[values > threshold]
        if hits.empty:
            print(f"  ok    {label}")
            return
        share = len(hits) / total * 100
        worst = hits.nlargest(3, column)[["session", column]].values.tolist()
        print(f"  FOUND {label}: {len(hits)} sessions ({share:.1f}%) — worst {worst}")

    print("TIMESTAMPS")
    report("rows_outside_session_hours", "rows outside 09:15-16:00 (feed padding)")
    report("rows_in_closing_auction", "rows in the closing auction, 15:30-16:00 (market, kept)")
    report("rows_on_another_date", "rows stamped with a different date")
    report("distinct_minutes", "more than 406 distinct minutes", threshold=406)
    print("\nINTEGRITY")
    report("duplicate_symbol_minutes", "same instrument twice in one minute")
    report("minutes_with_inconsistent_spot", "spot disagreeing with itself in a minute")
    report("spot_jumps_over_2pct", "minute-to-minute spot jump over 2%")
    report("longest_unchanged_spot_run", "spot unchanged for 30+ consecutive minutes", threshold=30)
    print("\nPRICES")
    report("nonpositive_close", "non-positive option close")
    report("high_below_low", "high below low")
    report("close_outside_high_low", "close outside the bar's own range")
    print("\nIMPLIED VOLATILITY")
    report("iv_nonpositive", "non-positive implied volatility")
    report("iv_over_300pct", "implied volatility above 300%")
    print("\nSIZE FIELDS")
    report("negative_volume", "negative volume")
    report("negative_oi", "negative open interest")
    print("\nCHAIN SHAPE")
    report("strike_ladder_holes", "gaps in the strike ladder")
    report("unpaired_strikes", "strikes listed on one side only")
    report("distinct_expiries", "more than one expiry captured", threshold=1)

    if "distinct_strikes" in frame:
        print(
            f"\n  strikes per session: median {frame.distinct_strikes.median():.0f}, "
            f"min {frame.distinct_strikes.min():.0f}, max {frame.distinct_strikes.max():.0f}"
        )
    if "first_minute" in frame:
        print(f"  session start times: {dict(Counter(frame.first_minute).most_common(5))}")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(rows, indent=1, default=str))
        print(f"\nper-session detail written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
