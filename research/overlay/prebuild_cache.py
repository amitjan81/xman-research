"""Build the extended-session cache once, in parallel, before the sweep reads it.

The extension is a pure function of the session, so the work parallelises perfectly by date
range and is then shared by every arm. Without it the first arm pays the whole bill and the
sweep's wall-clock is dominated by re-pricing bars nothing has changed.

    uv run python research/overlay/prebuild_cache.py --workers 4
"""

from __future__ import annotations

import argparse
import datetime as dt
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from xman_research.overlay.run import decision_times
from xman_research.overlay.synthetic import DEFAULT_CACHE_ROOT, SyntheticWingStore
from xman_research.session_store import DEFAULT_CORPUS_ROOT


def _build(args: tuple[str, dt.date, dt.date, Path, Path]) -> tuple[int, int]:
    underlying, start, end, corpus_root, cache_root = args
    store = SyntheticWingStore(root=corpus_root, minutes=decision_times(), cache_root=cache_root)
    resolution = store.resolve(underlying, start, end)
    refs = (
        resolution.sessions()
        if resolution.is_complete
        else resolution.accept_gaps("cache prebuild: gaps are irrelevant to a per-session build")
    )
    for ref in refs:
        store.load_session(ref)
    return len(refs), store.sessions_from_cache


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--underlying", default="NIFTY")
    parser.add_argument("--start", type=dt.date.fromisoformat, default=dt.date(2021, 6, 1))
    parser.add_argument("--end", type=dt.date.fromisoformat, default=dt.date(2026, 9, 15))
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--corpus-root", type=Path, default=DEFAULT_CORPUS_ROOT)
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE_ROOT)
    args = parser.parse_args(argv)

    span = (args.end - args.start).days // args.workers
    chunks = []
    cursor = args.start
    for index in range(args.workers):
        stop = args.end if index == args.workers - 1 else cursor + dt.timedelta(days=span)
        chunks.append((args.underlying, cursor, stop, args.corpus_root, args.cache_root))
        cursor = stop + dt.timedelta(days=1)

    built = cached = 0
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for sessions, from_cache in pool.map(_build, chunks):
            built += sessions
            cached += from_cache
    print(f"sessions touched: {built} ({cached} already cached) -> {args.cache_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
