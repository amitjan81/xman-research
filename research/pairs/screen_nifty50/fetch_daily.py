"""Fetch daily cash-equity OHLCV for the screen universe from Dhan.

RUN ENVIRONMENT — this script runs *only* under the Dhan worktree's venv, which owns
the client and the dhanhq SDK; the research worktree's env has neither::

    cd /home/qa/xman/.claude/worktrees/feat-dhan-banknifty && uv run python \
        /home/qa/xman-research/.claude/worktrees/research-pairs/research/pairs/screen_nifty50/fetch_daily.py

The client is used read-only: nothing under the Dhan worktree is written or modified.

Endpoint: ``POST /v2/charts/historical`` via ``dhanhq.historical_daily_data``, segment
``NSE_EQ`` / instrument ``EQUITY``. It returns the real traded close (verified against a
CAS probe), one candle per session, timestamps at IST midnight, and accepts a multi-year
span in a single request — so the universe costs one call per name.

Two structural breaks live inside any window this fetches, and both are stamped into the
output's sidecar metadata rather than left to the reader:

- **2026-04-01** — the STT hike (0.02 % → 0.05 % futures sell-side) roughly doubled round
  -trip friction, so a cost model applied across this date is date-effective, not flat.
- **2026-08-03** — the closing-auction (CAS) change. Closes before and after are
  different statistical objects: a continuous-trade last price before, an auction
  discovery print after. A formation window spanning it mixes the two.

Rate limit is set to 2.5 req/s (below the documented 5 req/s) because Dhan returns
DH-904 on bursts.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, "/home/qa/xman/.claude/worktrees/feat-dhan-banknifty/backtest/src")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fno_universe import futures_underlyings, newest_scrip_master
from nifty50_members import NIFTY50
from xman_backtest.dhan.auth import DhanCredentials, TokenProvider
from xman_backtest.dhan.client import DhanClient, RateLimiter

OUT_DIR = Path("/home/qa/runtime/data/research/pairs")
# Each universe writes its own parquet: a bare re-run of one must not clobber the other.
DEFAULT_OUT = {
    "nifty50": OUT_DIR / "nifty50_daily.parquet",
    "fno": OUT_DIR / "fno_daily.parquet",
}
STT_BREAK = "2026-04-01"
CAS_BREAK = "2026-08-03"
REQUESTS_PER_S = 2.5


def resolve_security_ids(master_csv: Path, symbols: list[str]) -> tuple[dict[str, str], list[str]]:
    """Map trading symbol -> Dhan security id over NSE / segment E / series EQ rows.

    Returns the resolved mapping and the symbols with no such row. An unresolvable
    symbol is a data fact about the universe list and is reported, never dropped
    silently.
    """
    master = pd.read_csv(master_csv, low_memory=False)
    eq = master[
        (master["SEM_EXM_EXCH_ID"] == "NSE")
        & (master["SEM_SEGMENT"] == "E")
        & (master["SEM_SERIES"] == "EQ")
    ]
    by_symbol = dict(
        zip(
            eq["SEM_TRADING_SYMBOL"].astype(str),
            eq["SEM_SMST_SECURITY_ID"].astype(str),
            strict=True,
        )
    )
    resolved = {s: by_symbol[s] for s in symbols if s in by_symbol}
    missing = [s for s in symbols if s not in by_symbol]
    return resolved, missing


def fetch_symbol(
    client: DhanClient, security_id: str, from_date: str, to_date: str
) -> pd.DataFrame:
    """Daily OHLCV for one security id as a frame of date, o/h/l/c/v."""
    sdk = client._sdk_handle()
    payload = client._call(
        "historical_daily_data",
        lambda: sdk.historical_daily_data(
            security_id=security_id,
            exchange_segment="NSE_EQ",
            instrument_type="EQUITY",
            from_date=from_date,
            to_date=to_date,
        ),
    )
    frame = pd.DataFrame(payload)
    if frame.empty:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
    ist = pd.to_datetime(frame["timestamp"], unit="s", utc=True).dt.tz_convert("Asia/Kolkata")
    frame["date"] = ist.dt.date
    return frame[["date", "open", "high", "low", "close", "volume"]]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--universe", choices=sorted(DEFAULT_OUT), default="nifty50")
    parser.add_argument("--from-date", default="2023-09-01")
    parser.add_argument("--to-date", default=date.today().isoformat())
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument(
        "--probe",
        type=int,
        default=0,
        help="fetch only the first N symbols — a shape check before the paced batch",
    )
    parser.add_argument(
        "--min-rows",
        type=int,
        default=500,
        help="names with fewer sessions are dropped from the output",
    )
    args = parser.parse_args()

    args.out = args.out or DEFAULT_OUT[args.universe]
    master_csv = newest_scrip_master()
    excluded_test_scrips: list[str] = []
    if args.universe == "fno":
        lots, excluded_test_scrips = futures_underlyings(master_csv)
        symbols = sorted(lots)
    else:
        symbols = sorted(NIFTY50)
    resolved, missing = resolve_security_ids(master_csv, symbols)
    if args.probe:
        resolved = dict(list(resolved.items())[: args.probe])
    print(f"scrip master: {master_csv.name}")
    print(f"universe: {args.universe}, {len(symbols)} symbols")
    print(f"excluded exchange test scrips: {len(excluded_test_scrips)}")
    print(f"resolved {len(resolved)}/{len(symbols)} symbols; unresolved: {missing or 'none'}")

    client = DhanClient(
        TokenProvider(DhanCredentials.from_env_file()), RateLimiter(REQUESTS_PER_S)
    )
    frames: list[pd.DataFrame] = []
    counts: dict[str, int] = {}
    failed: dict[str, str] = {}
    for symbol, security_id in resolved.items():
        try:
            frame = fetch_symbol(client, security_id, args.from_date, args.to_date)
        except Exception as exc:  # a single name's failure must not lose the batch
            failed[symbol] = repr(exc)
            print(f"{symbol}: FAILED {exc!r}", flush=True)
            continue
        frame.insert(0, "symbol", symbol)
        counts[symbol] = len(frame)
        frames.append(frame)
        print(f"{symbol}: {len(frame)} rows", flush=True)

    if not frames:
        print("no data fetched", file=sys.stderr)
        return 1

    combined = pd.concat(frames, ignore_index=True)
    thin = sorted(s for s, n in counts.items() if n < args.min_rows)
    if thin:
        combined = combined[~combined["symbol"].isin(thin)]
    combined = combined.sort_values(["symbol", "date"]).reset_index(drop=True)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    combined.to_parquet(args.out, index=False)

    meta = {
        "fetched_on": date.today().isoformat(),
        "universe": args.universe,
        "universe_size": len(symbols),
        "excluded_test_scrips": excluded_test_scrips,
        "scrip_master": master_csv.name,
        "endpoint": "charts/historical (daily), NSE_EQ / EQUITY",
        "from_date": args.from_date,
        "to_date": args.to_date,
        "min_rows": args.min_rows,
        "row_counts": counts,
        "unresolved_symbols": missing,
        "failed_symbols": failed,
        "dropped_thin_symbols": thin,
        "symbols_written": sorted(combined["symbol"].unique().tolist()),
        "structural_breaks": {
            STT_BREAK: "STT hike 0.02%->0.05% futures sell-side; cost model is date-effective",
            CAS_BREAK: "closing auction (CAS): closes before/after are different objects",
        },
    }
    meta_path = args.out.with_suffix(".meta.json")
    meta_path.write_text(json.dumps(meta, indent=2))

    print(f"\nwrote {len(combined)} rows for {combined['symbol'].nunique()} symbols -> {args.out}")
    print(f"dropped (<{args.min_rows} rows): {thin or 'none'}")
    print(f"date range: {combined['date'].min()} .. {combined['date'].max()}")
    print(f"metadata -> {meta_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
