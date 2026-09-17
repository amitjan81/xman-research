"""Per-session statistics of the 10:00-15:00 window, for range rules that need history.

An ATR or a Bollinger band computed over *whole sessions* is the wrong measurement for a
strategy that trades 10:00 to 15:00: it includes the opening auction's gap and the closing
half hour, which are the two parts of the day this strategy deliberately avoids. What matters
is how far the index travels **inside the window it will be exposed in**, so that is what is
measured here — one row per session, high, low, first and last print between 10:00 and 15:00.

Cached beside the corpus and rebuilt when any session file is newer, exactly as
:mod:`xman_research.overlay.context` does. Every read is of sessions strictly before the one
asking, so a range built from it cannot see the day it is drawn for.
"""

from __future__ import annotations

import datetime as dt
import glob
import os
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from xman_research.corpus_hygiene import ist_stamps, underlying_spot

__all__ = ["DEFAULT_CACHE_ROOT", "WindowStats", "build_window_frame", "load_window_stats"]

DEFAULT_CACHE_ROOT = Path("/home/qa/runtime/data/research/overlay")

WINDOW_START = dt.time(10, 0)
WINDOW_END = dt.time(15, 0)

#: Bumped when the derivation changes, so a cache built by the old one is not silently
#: reused. v2: spot comes from the index's own bar, in session hours only.
DERIVATION = "v2"


def build_window_frame(
    *,
    corpus_root: Path,
    underlying: str,
    window: tuple[dt.time, dt.time] = (WINDOW_START, WINDOW_END),
) -> pd.DataFrame:
    """One row per session: the index's travel inside the trading window."""
    start, end = window
    rows: list[dict[str, object]] = []
    for path in sorted(glob.glob(str(corpus_root / underlying / "*.parquet"))):
        session_date = dt.date.fromisoformat(os.path.basename(path)[:10])
        frame = pq.read_table(path, columns=["minute_ts", "symbol", "spot"]).to_pandas()
        spots = underlying_spot(frame, underlying, session_date)
        if spots.empty:
            continue
        times = ist_stamps(spots).dt.time
        inside = spots[(times >= start) & (times <= end)]
        if len(inside) < 10:
            continue
        rows.append(
            {
                "session_date": session_date,
                "window_open": float(inside.spot.iloc[0]),
                "window_close": float(inside.spot.iloc[-1]),
                "window_high": float(inside.spot.max()),
                "window_low": float(inside.spot.min()),
            }
        )
    out = pd.DataFrame(rows).sort_values("session_date").reset_index(drop=True)
    if out.empty:
        return out
    # The window's own true range, as a fraction of where the window started. The classic
    # true range takes the previous *close* into account; here the previous window's close is
    # separated from this window's open by an overnight gap and an opening auction, neither
    # of which this strategy is exposed to, so the in-window high-low is the honest analogue.
    out["range_pct"] = (out.window_high - out.window_low) / out.window_open
    out["move_pct"] = (out.window_close - out.window_open) / out.window_open
    return out


def _cache_path(root: Path, underlying: str) -> Path:
    return root / f"window_stats_{underlying}_{DERIVATION}.parquet"


def load_window_stats(
    *, corpus_root: Path, underlying: str, cache_root: Path = DEFAULT_CACHE_ROOT
) -> WindowStats:
    cache = _cache_path(cache_root, underlying)
    sessions = sorted(glob.glob(str(corpus_root / underlying / "*.parquet")))
    newest = max((os.path.getmtime(path) for path in sessions), default=0.0)
    if cache.is_file() and os.path.getmtime(cache) >= newest:
        frame = pd.read_parquet(cache)
    else:
        frame = build_window_frame(corpus_root=corpus_root, underlying=underlying)
        cache.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(cache, index=False)
    return WindowStats(frame)


@dataclass(frozen=True, slots=True)
class WindowBands:
    """What a range rule needs, for one session, from the sessions before it."""

    atr_pct: float | None
    """Mean in-window range over the lookback, as a fraction of the window's open."""
    sigma_pct: float | None
    """Standard deviation of the in-window close-to-open move over the lookback."""
    observations: int


class WindowStats:
    """Lookback statistics, with the look-ahead rule enforced by construction."""

    def __init__(self, frame: pd.DataFrame) -> None:
        self._frame = (
            frame.sort_values("session_date").reset_index(drop=True) if not frame.empty else frame
        )
        self._index = (
            {row.session_date: i for i, row in enumerate(self._frame.itertuples())}
            if not frame.empty
            else {}
        )

    @property
    def frame(self) -> pd.DataFrame:
        return self._frame

    def bands_for(self, session_date: dt.date, *, lookback: int = 14) -> WindowBands:
        """The ATR and sigma from the ``lookback`` sessions **before** ``session_date``."""
        position = self._index.get(session_date)
        if position is None or position == 0:
            return WindowBands(None, None, 0)
        history = self._frame.iloc[max(0, position - lookback) : position]
        if history.empty:
            return WindowBands(None, None, 0)
        atr = float(history.range_pct.mean())
        sigma = float(history.move_pct.std(ddof=1)) if len(history) > 1 else None
        return WindowBands(atr, sigma, len(history))
