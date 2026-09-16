"""The daily series the entry filters need, derived from the corpus itself.

ST-10 asks for India VIX and a 252-day implied-volatility percentile; ST-11 for five-day
realised volatility against the weekly at-the-money implied; ST-12 for a 20-day simple
moving average; ST-13 for the opening gap. **The corpus carries no India VIX series**, so
the VIX floor is unimplementable as written. What it does carry is the vendor's implied
volatility on every captured option of every session — the contracts the strategy actually
sells, on the underlying it sells them on.

So ST-10 is implemented as its second limb only — the IV-percentile test — with the VIX
limb recorded as inapplicable rather than silently passed. The substitution is stamped on
every run through :data:`VIX_SUBSTITUTION`. It is a substitution, not an improvement: VIX is
a constant-maturity 30-day index and this is a weekly at-the-money print, and the two would
not rank a given week identically.

**The percentile is same-tenor, and the first version of it was not.** Each captured session
carries whichever weekly expiry is nearest, so one session's at-the-money implied volatility
is a 6-day number and another's is a 0-day number. Ranking today's value against a trailing
year of *that* series measures the tenor, not the volatility: a weekly option on its expiry
afternoon prints a median at-the-money IV of 0.053 against 0.11-0.15 mid-week, and an entry
session is always preceded by an expiry session under both the Thursday and the Tuesday
regime — so the comparison read "today is unusually high" almost every week, and ST-10 halved
92 of the first five-year run's 142 positions. The percentile is now taken over prior sessions
**at the same days to expiry as the entry**, and what is ranked is the volatility the strategy
measures at the entry minute rather than the previous session's closing print.

Everything here is derived from captured bars by a pure function of the file set, cached
beside the corpus, and rebuilt whenever the cache is older than the newest session file.
No series in this module may be read for a date on or after the session that reads it,
except the two that are legitimately same-session observations: the opening print (ST-13's
gap) and the entry minute's own implied volatility.
"""

from __future__ import annotations

import datetime as dt
import glob
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

__all__ = [
    "MINIMUM_PERCENTILE_SAMPLE",
    "VIX_SUBSTITUTION",
    "DailyContext",
    "build_daily_frame",
    "load_context",
]

#: Stamped on every run so no reader has to reconstruct why no VIX number appears.
VIX_SUBSTITUTION = (
    "ST-10 volatility filter: the corpus carries no India VIX series, so the VIX-floor limb "
    "is inapplicable and only the IV-percentile limb is evaluated. The percentile ranks the "
    "at-the-money implied volatility measured at the entry minute against the trailing 252 "
    "sessions' observations AT THE SAME DAYS TO EXPIRY, because each captured session carries "
    "a different tenor and a mixed-tenor percentile measures the tenor rather than the "
    "volatility."
)

#: Where the derived series is cached. Beside the corpus, never inside the repository:
#: it is regenerable output, and a committed copy would go stale silently.
DEFAULT_CACHE_ROOT = Path("/home/qa/runtime/data/research/overlay")

_TRADING_DAYS = 252

#: Fewer comparable observations than this and the percentile is not computed. A year of
#: entry-window sessions is about 55 of them, so this is roughly one quarter's worth.
MINIMUM_PERCENTILE_SAMPLE = 12


def _ist(minute_ts: int) -> dt.datetime:
    return dt.datetime.fromtimestamp(minute_ts / 1e6, dt.UTC).astimezone(
        dt.timezone(dt.timedelta(hours=5, minutes=30))
    )


def build_daily_frame(*, corpus_root: Path, underlying: str) -> pd.DataFrame:
    """Scan every captured session and return one row per session.

    Columns: ``session_date``, ``open``, ``close`` (the underlying's first and last printed
    spot), ``atm_iv`` (the mean of the call and put implied volatility at the strike nearest
    spot, at the session's last minute) and ``expiry``/``dte`` for the contract captured
    that session.
    """
    rows: list[dict[str, object]] = []
    for path in sorted(glob.glob(str(corpus_root / underlying / "*.parquet"))):
        session_date = dt.date.fromisoformat(os.path.basename(path)[:10])
        frame = pq.read_table(
            path, columns=["minute_ts", "symbol", "iv", "close", "spot"]
        ).to_pandas()
        spots = frame.dropna(subset=["spot"])
        if spots.empty:
            continue
        spots = spots.sort_values("minute_ts")
        options = frame[frame.symbol.str.contains("-", regex=False)]
        row: dict[str, object] = {
            "session_date": session_date,
            "open": float(spots.spot.iloc[0]),
            "close": float(spots.spot.iloc[-1]),
            "atm_iv": np.nan,
            "expiry": None,
            "dte": np.nan,
        }
        if not options.empty:
            parts = options.symbol.str.split("-", expand=True)
            options = options.assign(strike=parts[2].astype(float), option_type=parts[3])
            expiry = dt.datetime.strptime(parts[1].iloc[0], "%d%b%Y").date()
            row["expiry"] = expiry
            row["dte"] = (expiry - session_date).days
            last_minute = options.minute_ts.max()
            snapshot = options[(options.minute_ts == last_minute) & options.iv.notna()]
            if not snapshot.empty:
                spot = float(spots.spot.iloc[-1])
                atm = snapshot.strike.iloc[(snapshot.strike - spot).abs().argsort()].iloc[0]
                at_strike = snapshot[snapshot.strike == atm]
                if not at_strike.empty:
                    row["atm_iv"] = float(at_strike.iv.mean())
        rows.append(row)
    return pd.DataFrame(rows).sort_values("session_date").reset_index(drop=True)


def _cache_path(root: Path, underlying: str) -> Path:
    return root / f"daily_context_{underlying}.parquet"


def load_context(
    *, corpus_root: Path, underlying: str, cache_root: Path = DEFAULT_CACHE_ROOT
) -> DailyContext:
    """The derived series, from cache when it is newer than every session file."""
    cache = _cache_path(cache_root, underlying)
    sessions = sorted(glob.glob(str(corpus_root / underlying / "*.parquet")))
    newest = max((os.path.getmtime(path) for path in sessions), default=0.0)
    if cache.is_file() and os.path.getmtime(cache) >= newest:
        frame = pd.read_parquet(cache)
    else:
        frame = build_daily_frame(corpus_root=corpus_root, underlying=underlying)
        cache.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(cache, index=False)
    return DailyContext(frame)


@dataclass(frozen=True, slots=True)
class FilterInputs:
    """Everything the entry filters read, measured once for one session."""

    previous_close: float | None
    sma_20: float | None
    realised_vol_5d: float | None
    session_open: float | None
    gap_pct: float | None


class DailyContext:
    """Indexed access to the derived series, with the look-ahead rule enforced by construction.

    Every series is computed from sessions **strictly before** the one being asked about.
    The only same-session values returned are the opening print and the gap it implies,
    which ST-13 evaluates on entry morning and which are therefore legitimately observable.
    """

    def __init__(self, frame: pd.DataFrame) -> None:
        self._frame = frame.sort_values("session_date").reset_index(drop=True)
        self._index = {row.session_date: i for i, row in enumerate(self._frame.itertuples())}

    @property
    def frame(self) -> pd.DataFrame:
        return self._frame

    def sessions(self) -> tuple[dt.date, ...]:
        return tuple(self._frame.session_date)

    def iv_percentile(
        self, session_date: dt.date, current_iv: float, *, dte_bucket: tuple[int, ...] = (5, 6)
    ) -> float | None:
        """Where ``current_iv`` sits in the trailing year of **same-tenor** observations.

        ``dte_bucket`` is the set of days-to-expiry the comparison is restricted to, and it
        defaults to the entry window's own 5-6. Only sessions strictly before
        ``session_date`` are considered. ``None`` when fewer than
        :data:`MINIMUM_PERCENTILE_SAMPLE` comparable observations exist, because a percentile
        over a handful of points is a number without a meaning — and an unevaluable filter
        is recorded as unevaluable rather than passed.
        """
        position = self._index.get(session_date)
        if position is None or current_iv <= 0:
            return None
        history = self._frame.iloc[max(0, position - _TRADING_DAYS) : position]
        comparable = history[history.dte.isin(dte_bucket)].atm_iv.dropna()
        if len(comparable) < MINIMUM_PERCENTILE_SAMPLE:
            return None
        return float((comparable < current_iv).mean() * 100.0)

    def inputs_for(self, session_date: dt.date) -> FilterInputs:
        position = self._index.get(session_date)
        if position is None:
            return FilterInputs(None, None, None, None, None)
        history = self._frame.iloc[:position]
        today = self._frame.iloc[position]
        previous_close = float(history.close.iloc[-1]) if len(history) else None
        sma_20 = float(history.close.iloc[-20:].mean()) if len(history) >= 20 else None
        realised = None
        if len(history) >= 6:
            closes = history.close.iloc[-6:].to_numpy(dtype=float)
            log_returns = np.diff(np.log(closes))
            realised = float(np.std(log_returns, ddof=1) * np.sqrt(_TRADING_DAYS))
        session_open = float(today.open) if pd.notna(today.open) else None
        gap = None
        if previous_close and session_open:
            gap = (session_open - previous_close) / previous_close
        return FilterInputs(
            previous_close=previous_close,
            sma_20=sma_20,
            realised_vol_5d=realised,
            session_open=session_open,
            gap_pct=gap,
        )
