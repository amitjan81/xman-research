"""Write a backtest out as an artifact a user interface can draw.

The numbers in a decision record answer "did it work". They cannot answer "show me the day
that trade happened on", which is the question an operator actually asks when deciding
whether to believe a rule. This module writes, for every trade a run produced, the session's
own spot path with both candidate bands drawn on it and the entry and exit marked — so the
day can be looked at rather than summarised.

**Both bands are always written, whichever one drove the trade.** The ATR band and the
Bollinger band disagree about what a normal day looks like — one measures how far the index
travels, the other where it ends up — and seeing them together on the same chart is how a
reader tells which one the market respected.

**The spot path is stored as a start time, an interval and a list of numbers**, not as a
list of objects. A session is 375 minutes and a run touches hundreds of sessions; the
object-per-minute form costs about four times the bytes for the same picture, and a browser
has to parse all of it before drawing anything.

The artifact contract is versioned. `xman-ui` validates against it and refuses a file it does
not understand rather than drawing a half-empty chart.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from xman_research.corpus_hygiene import ist_stamps, underlying_spot
from xman_research.intraday.window_stats import WindowStats

__all__ = ["DEFAULT_EXPORT_DIR", "SCHEMA_VERSION", "export_run"]

#: Bumped when the shape changes in a way a reader must notice. The UI pins it.
SCHEMA_VERSION = 1

#: Where the UI looks. Beside the other research artifacts it reads.
DEFAULT_EXPORT_DIR = Path("/home/qa/runtime/data/research/custom_backtests")

_IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


def export_run(
    *,
    run: Any,
    strategy_id: str,
    title: str,
    description: str,
    corpus_root: Path,
    underlying: str,
    window_stats: WindowStats,
    out_dir: Path = DEFAULT_EXPORT_DIR,
    lookback: int | None = None,
    atr_multiple: float | None = None,
    bollinger_sigma: float | None = None,
) -> Path:
    """Write one run's trades, with their sessions' spot paths and bands, as JSON.

    **The band widths come from the run's own parameters unless overridden.** Hardcoding
    0.75x drew the 0.75 band under an arm that traded the 1.0 band — a chart showing a rule
    the run did not follow, which is worse than no chart, because it looks like evidence.
    """
    lookback = _param(run, "lookback_sessions", lookback, 14)
    atr_multiple = _param(run, "atr_multiple", atr_multiple, 0.75)
    bollinger_sigma = _param(run, "bollinger_sigma", bollinger_sigma, 1.5)
    trades = [dict(cycle) for cycle in run.cycles]
    realised = _realised_by_key(run)
    sessions = sorted({trade["session_date"] for trade in trades})

    paths: dict[str, dict[str, Any]] = {}
    for session_date in sessions:
        path = _spot_path(corpus_root, underlying, session_date)
        if path is None:
            continue
        bands = window_stats.bands_for(dt.date.fromisoformat(session_date), lookback=lookback)
        anchor = _anchor_at(path, dt.time(10, 0))
        paths[session_date] = {
            "spot": path,
            "anchor_1000": anchor,
            "bands": _bands(anchor, bands, atr_multiple, bollinger_sigma),
            "atr_pct": bands.atr_pct,
            "sigma_pct": bands.sigma_pct,
            "lookback_observations": bands.observations,
        }

    for trade in trades:
        key = (trade["session_date"], trade.get("symbol"))
        trade["realised_pnl"] = realised.get(key, realised.get(trade["session_date"], 0.0))

    payload = {
        "schema_version": SCHEMA_VERSION,
        "strategy_id": strategy_id,
        "title": title,
        "description": description,
        "underlying": underlying,
        "generated_at": dt.datetime.now(_IST).isoformat(),
        "window": {
            "start": run.config.start.isoformat(),
            "end": run.config.end.isoformat(),
        },
        "parameters": _json_safe(run.config.params),
        "summary": _json_safe(run.metrics),
        "trades": _json_safe(trades),
        "sessions": paths,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    destination = out_dir / f"{strategy_id}.json"
    destination.write_text(json.dumps(payload, separators=(",", ":"), default=str))
    return destination


def _param(run: Any, name: str, override: Any, default: Any) -> Any:
    """An explicit override, else the run's own parameter, else the study's default."""
    if override is not None:
        return override
    value = getattr(run.config.params, name, None)
    return default if value is None else value


def _spot_path(corpus_root: Path, underlying: str, session_date: str) -> dict[str, Any] | None:
    """The session's index path, as a start time, an interval and a list of prices."""
    path = corpus_root / underlying / f"{session_date}.parquet"
    if not path.is_file():
        return None
    frame = pq.read_table(path, columns=["minute_ts", "symbol", "spot"]).to_pandas()
    # The index's own bar, in session hours — not the spot stamped on each option row, which
    # disagrees with itself inside a minute on a third of sessions.
    spots = underlying_spot(frame, underlying, dt.date.fromisoformat(session_date))
    if spots.empty:
        return None
    times = ist_stamps(spots)
    # The compact form is a start, an interval and a list — it has no way to say "this
    # minute did not print". A gap would shift every later value and mis-anchor 10:00, so a
    # non-contiguous session is refused rather than drawn wrong. No captured session has
    # one; this is the check that keeps that true.
    minutes = times.dt.hour * 60 + times.dt.minute
    if len(minutes) > 1 and not (minutes.diff().iloc[1:] == 1).all():
        return None
    return {
        "start": times.iloc[0].strftime("%H:%M"),
        "interval_seconds": 60,
        "values": [round(float(value), 2) for value in spots.spot],
    }


def _anchor_at(path: dict[str, Any], when: dt.time) -> float | None:
    """The price at a given clock time, from a compact path."""
    start = dt.datetime.strptime(path["start"], "%H:%M").time()
    offset = (
        ((when.hour * 60 + when.minute) - (start.hour * 60 + start.minute))
        * 60
        // path["interval_seconds"]
    )
    values = path["values"]
    if offset < 0 or offset >= len(values):
        return None
    return values[offset]


def _bands(
    anchor: float | None, bands: Any, atr_multiple: float, bollinger_sigma: float
) -> dict[str, Any]:
    """Both candidate bands, drawn from the 10:00 anchor, whichever one drove the trade."""
    if anchor is None:
        return {}
    out: dict[str, Any] = {}
    if bands.atr_pct:
        width = bands.atr_pct * atr_multiple
        out["atr"] = {
            "multiple": atr_multiple,
            "upper": round(anchor * (1 + width), 2),
            "lower": round(anchor * (1 - width), 2),
        }
    if bands.sigma_pct:
        width = bands.sigma_pct * bollinger_sigma
        out["bollinger"] = {
            "sigma": bollinger_sigma,
            "upper": round(anchor * (1 + width), 2),
            "lower": round(anchor * (1 - width), 2),
        }
    return out


def _realised_by_key(run: Any) -> dict[Any, float]:
    """Per-leg where the strategy trades legs, per session where it trades positions."""
    from xman_research.intraday.run import _pnl_by_leg, _pnl_by_session

    totals: dict[Any, float] = {}
    totals.update(_pnl_by_session(run.result))
    totals.update(_pnl_by_leg(run.result))
    return totals


def _json_safe(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return _json_safe(asdict(value))
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (dt.date, dt.time, dt.datetime)):
        return value.isoformat()
    if isinstance(value, float) and value != value:  # NaN
        return None
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
