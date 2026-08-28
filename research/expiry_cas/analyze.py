"""Metrics for the expiry-day final half hour and the closing-auction print window.

Run: ``uv run python research/expiry_cas/analyze.py --underlying NIFTY --dates ... --controls ...``

**What the windows are.** ``15:00-15:29`` is continuous trading and is the window the
pre-auction settlement rule averaged over. ``15:30-15:39`` is after the continuous close:
expiring options keep printing in size while the index feed holds one value, so it is the
only place a closing-auction effect can show up in this corpus.

**Three classes of arbitrage relation, and why the order matters.**

1. *Spot-free cross-strike relations* — vertical-spread bounds, butterfly convexity, and
   the box. These need only option prices, never an underlying level. On a session whose
   spot is unobservable they are the **only** trustworthy mispricing evidence, and they
   are what this module leads with.
2. *Put-call parity residuals* :math:`r = C - P - (S - K)`. These need a spot. Where the
   spot is itself parity-derived the residual is zero by construction at the anchor
   strike, and across all strikes it can only measure disagreement *between* strikes —
   never a mispricing common to the whole chain. The anchor is excluded mechanically and
   the limitation is printed with the table.
3. *Directional and premium-decay effects* — straddle time value, per-strike returns.
   These need a spot for intrinsic and inherit whatever the spot's provenance is.

**The staleness gate, applied everywhere.** A bar with zero volume carries a forward-fill
of the last trade, and differencing a stale close against a live one manufactures a
residual that is pure staleness. Every relation is computed twice: over all strike-minutes,
and over the subset where **every leg** printed volume in that same minute. The gap
between the two is the artefact measurement, and it is reported rather than hidden.

**What no OHLC corpus can support.** These bars carry no bid/ask. Every "capturable"
residual below is an upper bound on what a limit-order trader could have seen: it assumes
a fill at the bar close on every leg simultaneously, which is exactly the assumption a
real spread trade violates. Nothing here is a fill simulation.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from load import AUCTION_START, FINAL_WINDOW_START, SessionData, load_session  # noqa: E402

from xman_research.backtest.costs import (  # noqa: E402
    ChargeableTrade,
    Side,
    StatutoryCostStack,
    TradeKind,
)

#: NSE's Closing Auction Session goes live on this date; before it, expiring options
#: print no post-close bars at all and the settlement statistic is a different one.
CAS_LIVE_FROM = dt.date(2026, 8, 3)

CONTINUOUS_END = dt.time(15, 29)
AUCTION_END = dt.time(15, 39)
LOTTERY_ENTRY = dt.time(15, 25)

_STACK = StatutoryCostStack()


def regime(session_date: dt.date) -> str:
    return "post-CAS" if session_date >= CAS_LIVE_FROM else "pre-CAS"


def _cost(trade: ChargeableTrade) -> float:
    """Total rupee cost of one chargeable event.

    :attr:`CostBreakdown.total` already carries ``stt_on_exercise`` as one of its summed
    terms — the field is kept separate from ``stt`` so the two rates and payers stay
    distinguishable, not so callers add it back. Adding it again would double-charge the
    settlement leg of every held-to-expiry structure.
    """
    return _STACK.charge(trade).total


def _window(frame: pd.DataFrame | pd.Series, start: dt.time, end: dt.time):
    times = frame.index.time if isinstance(frame.index, pd.DatetimeIndex) else frame["ts"].dt.time
    return frame[(times >= start) & (times <= end)]


# --------------------------------------------------------------------------- swings


def swing_metrics(session: SessionData) -> dict[str, object]:
    """Underlying movement in the final half hour, split at the continuous close.

    Uses the ``best`` spot series — the feed on minutes it actually moved, parity
    elsewhere — because a forward-filled feed level differenced against itself reports a
    zero return that is an absence of data rather than an absence of movement.
    """
    spot = session.spot.dropna(subset=["best"]).copy()
    spot["ret"] = spot["best"].pct_change()

    cont = _window(spot, FINAL_WINDOW_START, CONTINUOUS_END)
    auction = _window(spot, AUCTION_START, AUCTION_END)
    rest = spot[spot.index.time < FINAL_WINDOW_START]

    def rng(frame: pd.DataFrame) -> float:
        return float(frame["best"].max() - frame["best"].min()) if len(frame) else float("nan")

    def largest_move(frame: pd.DataFrame, span: int) -> tuple[float, str]:
        if len(frame) <= span:
            return float("nan"), "--"
        moves = frame["best"].diff(span).dropna()
        if moves.empty:
            return float("nan"), "--"
        at = moves.abs().idxmax()
        return float(moves.loc[at]), at.strftime("%H:%M")

    # Realised vol is annualised only inside the report's own comparison; here it is the
    # per-minute standard deviation over the window, which is what the windows differ in.
    def rvol(frame: pd.DataFrame) -> float:
        r = frame["ret"].dropna()
        return float(r.std() * 100) if len(r) > 1 else float("nan")

    m1, t1 = largest_move(spot[spot.index.time >= FINAL_WINDOW_START], 1)
    m3, t3 = largest_move(spot[spot.index.time >= FINAL_WINDOW_START], 3)
    m5, t5 = largest_move(spot[spot.index.time >= FINAL_WINDOW_START], 5)
    am1, at1 = largest_move(auction, 1)

    return {
        "date": session.session_date,
        "status": session.status,
        "regime": regime(session.session_date),
        "expiry_session": session.is_expiry_session,
        "range_1500_1529": rng(cont),
        "range_1530_1539": rng(auction),
        "rvol_1500_1529_pct": rvol(cont),
        "rvol_1530_1539_pct": rvol(auction),
        "rvol_rest_of_day_pct": rvol(rest),
        "max_1min": m1,
        "max_1min_at": t1,
        "max_3min": m3,
        "max_3min_at": t3,
        "max_5min": m5,
        "max_5min_at": t5,
        "max_1min_auction": am1,
        "max_1min_auction_at": at1,
        "auction_spot_quality": "exact (T=0)" if session.is_expiry_session else "proxy (T>0, noisy)",
        "feed_stale_min_1500_1539": int((~_window(session.spot, FINAL_WINDOW_START, AUCTION_END)["feed_fresh"]).sum()),
        "spot_minutes_1500_1539": int(len(_window(spot, FINAL_WINDOW_START, AUCTION_END))),
    }


# ------------------------------------------------------------------- chain repricing


def _atm_straddle(session: SessionData) -> pd.DataFrame:
    """ATM straddle mark and time value per minute, at the anchor strike.

    Time value is straddle minus intrinsic, and intrinsic needs a spot; on minutes where
    the spot is parity-derived the time value inherits that provenance. At the anchor
    strike specifically, parity spot forces :math:`C - P = S - K` exactly, so intrinsic
    and therefore time value are pinned — the anchor's time value on a parity minute is
    ``straddle - |S-K|`` with ``S`` chosen to satisfy the very identity being measured.
    The column is kept because the *level* of the straddle is still an observation; the
    caveat travels with it in the report.
    """
    k = session.parity_anchor_strike
    at_k = session.chain[session.chain["strike"] == k]
    wide = at_k.pivot_table(index="ts", columns="opt_type", values="close", aggfunc="last")
    vol = at_k.pivot_table(index="ts", columns="opt_type", values="volume", aggfunc="last")
    if "CE" not in wide or "PE" not in wide:
        return pd.DataFrame()
    out = pd.DataFrame(index=wide.index)
    out["straddle"] = wide["CE"] + wide["PE"]
    out["legs_traded"] = (vol.get("CE", 0) > 0) & (vol.get("PE", 0) > 0)
    spot = session.spot["best"].reindex(out.index)
    out["intrinsic"] = (spot - k).abs()
    out["time_value"] = out["straddle"] - out["intrinsic"]
    out["spot_source"] = session.spot["best_source"].reindex(out.index)
    return out


def repricing_metrics(session: SessionData) -> dict[str, object]:
    straddle = _atm_straddle(session)
    if straddle.empty:
        return {"date": session.session_date, "atm_strike": session.parity_anchor_strike}

    def at(hhmm: str, col: str) -> float:
        target = dt.time(int(hhmm[:2]), int(hhmm[3:]))
        rows = straddle[straddle.index.time <= target]
        return float(rows[col].iloc[-1]) if len(rows) else float("nan")

    # Per-strike option return over the auction approach, the "lottery vs crush" split.
    chain = session.chain
    entry = _window(chain, LOTTERY_ENTRY, LOTTERY_ENTRY)
    exit_rows = _window(chain, AUCTION_END, AUCTION_END)
    if exit_rows.empty:
        exit_rows = _window(chain, CONTINUOUS_END, CONTINUOUS_END)
    e = entry.set_index("symbol")["close"]
    x = exit_rows.set_index("symbol")["close"]
    both = pd.concat([e.rename("entry"), x.rename("exit")], axis=1).dropna()
    both = both[both["entry"] > 0]
    rets = (both["exit"] / both["entry"] - 1.0) * 100 if len(both) else pd.Series(dtype=float)

    return {
        "date": session.session_date,
        "status": session.status,
        "regime": regime(session.session_date),
        "expiry_session": session.is_expiry_session,
        "atm_strike": session.parity_anchor_strike,
        "straddle_1500": at("15:00", "straddle"),
        "straddle_1529": at("15:29", "straddle"),
        "straddle_1539": at("15:39", "straddle"),
        "tv_1500": at("15:00", "time_value"),
        "tv_1529": at("15:29", "time_value"),
        "tv_1539": at("15:39", "time_value"),
        "n_strikes_ret": int(len(rets)),
        "ret_median_pct": float(rets.median()) if len(rets) else float("nan"),
        "ret_max_pct": float(rets.max()) if len(rets) else float("nan"),
        "ret_min_pct": float(rets.min()) if len(rets) else float("nan"),
        "frac_to_zero_pct": float((rets <= -95).mean() * 100) if len(rets) else float("nan"),
        "frac_multibag_pct": float((rets >= 100).mean() * 100) if len(rets) else float("nan"),
    }


# ------------------------------------------------------------------------- residuals


def _leg_matrix(session: SessionData) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Close and volume pivots indexed by (ts, strike) with CE/PE columns."""
    chain = session.chain
    close = chain.pivot_table(index=["ts", "strike"], columns="opt_type", values="close", aggfunc="last")
    volume = chain.pivot_table(index=["ts", "strike"], columns="opt_type", values="volume", aggfunc="last")
    return close, volume


def parity_residuals(session: SessionData) -> pd.DataFrame:
    """:math:`r = C - P - (S - K)` per strike-minute, anchor strike excluded.

    The anchor is dropped because the parity spot is built from it, which would report a
    residual of exactly zero and call it evidence. What survives measures cross-strike
    disagreement only.
    """
    close, volume = _leg_matrix(session)
    if "CE" not in close or "PE" not in close:
        return pd.DataFrame()
    frame = pd.DataFrame(
        {
            "call": close["CE"],
            "put": close["PE"],
            "call_vol": volume["CE"],
            "put_vol": volume["PE"],
        }
    ).reset_index()
    frame = frame[frame["strike"] != session.parity_anchor_strike]
    frame["spot"] = frame["ts"].map(session.spot["best"])
    frame["spot_source"] = frame["ts"].map(session.spot["best_source"])
    frame = frame.dropna(subset=["call", "put", "spot"])
    frame["residual"] = frame["call"] - frame["put"] - (frame["spot"] - frame["strike"])
    frame["all_legs_traded"] = (frame["call_vol"] > 0) & (frame["put_vol"] > 0)
    frame["min_leg_volume"] = frame[["call_vol", "put_vol"]].min(axis=1)
    frame["relation"] = "parity"
    return frame


def box_residuals(session: SessionData) -> pd.DataFrame:
    """Box value against :math:`K_2-K_1` for adjacent strike pairs — needs no spot.

    :math:`(C_1-P_1)-(C_2-P_2)` must equal :math:`K_2-K_1` for European options at any
    maturity, discounting aside, so a deviation is a mispricing between two strikes that
    no underlying-level uncertainty can explain. This is the strongest arbitrage evidence
    available from a session whose spot is unobservable.
    """
    close, volume = _leg_matrix(session)
    if "CE" not in close or "PE" not in close:
        return pd.DataFrame()
    synth = (close["CE"] - close["PE"]).rename("synth").reset_index()
    vmin = volume[["CE", "PE"]].min(axis=1).rename("vmin").reset_index()
    merged = synth.merge(vmin, on=["ts", "strike"]).dropna(subset=["synth"])
    merged = merged.sort_values(["ts", "strike"])
    nxt = merged.groupby("ts").shift(-1)
    out = pd.DataFrame(
        {
            "ts": merged["ts"],
            "strike": merged["strike"],
            "strike2": nxt["strike"],
            "spread": merged["synth"] - nxt["synth"],
            "width": nxt["strike"] - merged["strike"],
            "min_leg_volume": pd.concat([merged["vmin"], nxt["vmin"]], axis=1).min(axis=1),
        }
    ).dropna(subset=["strike2"])
    # synth(K) = C(K) - P(K) = S - K, so synth(K1) - synth(K2) = K2 - K1 exactly.
    out["residual"] = out["spread"] - out["width"]
    out["all_legs_traded"] = out["min_leg_volume"] > 0
    out["relation"] = "box"
    return out


def vertical_violations(session: SessionData) -> pd.DataFrame:
    """Call vertical bound :math:`C(K_1)-C(K_2)\\in[0,K_2-K_1]` for adjacent strikes.

    Reported as the signed distance outside the bound, zero when the bound holds.
    """
    close, volume = _leg_matrix(session)
    rows = []
    for kind, sign in (("CE", 1.0), ("PE", -1.0)):
        if kind not in close:
            continue
        series = close[kind].rename("px").reset_index()
        vol = volume[kind].rename("v").reset_index()
        merged = series.merge(vol, on=["ts", "strike"]).dropna(subset=["px"]).sort_values(["ts", "strike"])
        nxt = merged.groupby("ts").shift(-1)
        frame = pd.DataFrame(
            {
                "ts": merged["ts"],
                "strike": merged["strike"],
                "strike2": nxt["strike"],
                "width": nxt["strike"] - merged["strike"],
                "min_leg_volume": pd.concat([merged["v"], nxt["v"]], axis=1).min(axis=1),
            }
        )
        # A call spread is long the lower strike; a put spread is long the higher.
        diff = (merged["px"] - nxt["px"]) * sign
        frame["diff"] = diff
        frame = frame.dropna(subset=["strike2"])
        below = -frame["diff"].clip(upper=0.0)
        above = (frame["diff"] - frame["width"]).clip(lower=0.0)
        frame["residual"] = np.where(below > 0, below, above)
        frame["relation"] = f"vertical_{kind}"
        rows.append(frame)
    if not rows:
        return pd.DataFrame()
    out = pd.concat(rows, ignore_index=True)
    out["all_legs_traded"] = out["min_leg_volume"] > 0
    return out


def butterfly_violations(session: SessionData) -> pd.DataFrame:
    """Convexity :math:`C(K_1)-2C(K_2)+C(K_3)\\ge 0` on equally spaced adjacent strikes."""
    close, volume = _leg_matrix(session)
    rows = []
    for kind in ("CE", "PE"):
        if kind not in close:
            continue
        series = close[kind].rename("px").reset_index()
        vol = volume[kind].rename("v").reset_index()
        merged = series.merge(vol, on=["ts", "strike"]).dropna(subset=["px"]).sort_values(["ts", "strike"])
        g = merged.groupby("ts")
        mid, hi = g.shift(-1), g.shift(-2)
        spacing_even = (mid["strike"] - merged["strike"]) == (hi["strike"] - mid["strike"])
        fly = merged["px"] - 2 * mid["px"] + hi["px"]
        frame = pd.DataFrame(
            {
                "ts": merged["ts"],
                "strike": merged["strike"],
                "strike2": hi["strike"],
                "residual": (-fly).clip(lower=0.0),
                "min_leg_volume": pd.concat([merged["v"], mid["v"], hi["v"]], axis=1).min(axis=1),
                "relation": f"butterfly_{kind}",
            }
        )
        rows.append(frame[spacing_even.fillna(False) & hi["strike"].notna()])
    if not rows:
        return pd.DataFrame()
    out = pd.concat(rows, ignore_index=True)
    out["all_legs_traded"] = out["min_leg_volume"] > 0
    return out


def roundtrip_cost_points(
    session: SessionData,
    legs: int,
    notional: float,
    premium: float,
    *,
    exit_kind: str = "settlement",
) -> float:
    """Round-trip cost of a ``legs``-leg structure, expressed in index points per unit.

    ``exit_kind`` decides how the position leaves. ``"settlement"`` is a position carried
    into expiry: ``legs`` opening trades plus one settlement event, which is where
    exercise STT — charged on intrinsic at a different rate from premium STT, and only on
    the long side — enters. ``"trade"`` is a position closed in the market before expiry:
    ``2 * legs`` ordinary trades and no settlement charge at all. Charging settlement on a
    position that was sold back, or premium-only on one that expired in the money, are
    the two ways to get an expiry-day cost estimate wrong in opposite directions.
    """
    units = session.lot_size
    opening_legs = legs if exit_kind == "settlement" else 2 * legs
    total = 0.0
    for _ in range(opening_legs):
        total += _cost(
            ChargeableTrade(
                trade_date=session.session_date,
                kind=TradeKind.TRADE,
                side=Side.SELL,
                quantity_units=units,
                price=premium,
                orders=1,
            )
        )
    if exit_kind == "settlement":
        total += _cost(
            ChargeableTrade(
                trade_date=session.session_date,
                kind=TradeKind.SETTLEMENT,
                side=Side.SELL,
                quantity_units=units,
                price=premium,
                orders=0,
                notional_price=notional,
            )
        )
    return total / units


def residual_summary(session: SessionData, frame: pd.DataFrame, cost_points: float) -> list[dict[str, object]]:
    """Residual distribution per relation and window, with the staleness gate applied.

    ``persistent`` counts strike-minutes whose residual clears the cost threshold in two
    consecutive minutes at the same strike. A single-minute residual on bar closes is
    indistinguishable from two non-simultaneous prints; two in a row is weak evidence that
    something was actually standing there.
    """
    if frame.empty:
        return []
    out = []
    frame = frame.copy()
    frame["window"] = np.where(frame["ts"].dt.time >= AUCTION_START, "15:30-15:39", "15:00-15:29")
    frame = frame[frame["ts"].dt.time >= FINAL_WINDOW_START]
    for (relation, window), grp in frame.groupby(["relation", "window"]):
        for gate, sub in (("all bars", grp), ("traded bars", grp[grp["all_legs_traded"]])):
            if sub.empty:
                continue
            mag = sub["residual"].abs()
            over = sub[mag > cost_points]
            # Persistence: the same strike clearing cost on consecutive minutes.
            persistent = 0
            if len(over):
                marks = over[["ts", "strike"]].drop_duplicates().sort_values(["strike", "ts"])
                gaps = marks.groupby("strike")["ts"].diff()
                persistent = int((gaps == pd.Timedelta(minutes=1)).sum())
            out.append(
                {
                    "date": session.session_date,
                    "status": session.status,
                    "regime": regime(session.session_date),
                    "relation": relation,
                    "window": window,
                    "gate": gate,
                    "n": int(len(sub)),
                    "median_abs": float(mag.median()),
                    "p95_abs": float(mag.quantile(0.95)),
                    "max_abs": float(mag.max()),
                    "cost_points": cost_points,
                    "n_over_cost": int(len(over)),
                    "pct_over_cost": float(len(over) / len(sub) * 100),
                    "n_persistent": persistent,
                    "median_volume_over": float(over["min_leg_volume"].median()) if len(over) else float("nan"),
                }
            )
    return out


# ------------------------------------------------------------------------ strategies


def strategy_short_straddle(session: SessionData) -> dict[str, object]:
    """Sell the ATM straddle at 15:00 and hold to settlement.

    Harvests whatever time value remains in the last half hour. Settlement value uses the
    session's terminal underlying estimate; on an expiry session that estimate is the
    parity spot from the auction window, where every strike agrees on one number.
    """
    straddle = _atm_straddle(session)
    if straddle.empty or not session.is_expiry_session:
        # A chain with days left is not settled by this session's close. Marking one to
        # intrinsic at 15:39 would book the whole remaining time value as profit and
        # report a held-to-expiry edge that the session never delivered.
        return {}
    k = session.parity_anchor_strike
    entry_rows = straddle[straddle.index.time <= FINAL_WINDOW_START]
    if entry_rows.empty:
        return {}
    entry = float(entry_rows["straddle"].iloc[-1])
    terminal = session.spot["best"].dropna()
    if terminal.empty:
        return {}
    settle = float(terminal.iloc[-1])
    intrinsic = abs(settle - k)
    gross = entry - intrinsic
    cost = roundtrip_cost_points(session, legs=2, notional=settle, premium=entry / 2)
    return {
        "date": session.session_date,
        "status": session.status,
        "regime": regime(session.session_date),
        "expiry_session": session.is_expiry_session,
        "entry_premium": entry,
        "settle_intrinsic": intrinsic,
        "gross_points": gross,
        "cost_points": cost,
        "net_points": gross - cost,
        "net_rupees_per_lot": (gross - cost) * session.lot_size,
    }


def strategy_auction_strangle(session: SessionData) -> dict[str, object]:
    """Buy a 2-strike-wide OTM strangle at 15:25 and close at the last auction print.

    The lottery ticket the owner's "wild swings" thesis implies: cheap wings bought just
    before the auction window, exited on its final print.
    """
    chain = session.chain
    strikes = np.sort(chain["strike"].unique())
    k = session.parity_anchor_strike
    idx = int(np.argmin(np.abs(strikes - k)))
    if idx < 2 or idx + 2 >= len(strikes):
        return {}
    call_k, put_k = strikes[idx + 2], strikes[idx - 2]

    def px(strike: float, kind: str, at: dt.time) -> float:
        rows = chain[(chain["strike"] == strike) & (chain["opt_type"] == kind) & (chain["ts"].dt.time <= at)]
        return float(rows["close"].iloc[-1]) if len(rows) else float("nan")

    entry = px(call_k, "CE", LOTTERY_ENTRY) + px(put_k, "PE", LOTTERY_ENTRY)
    exit_px = px(call_k, "CE", AUCTION_END) + px(put_k, "PE", AUCTION_END)
    if not np.isfinite(entry) or not np.isfinite(exit_px) or entry <= 0:
        return {}
    gross = exit_px - entry
    terminal = session.spot["best"].dropna()
    settle = float(terminal.iloc[-1]) if len(terminal) else float("nan")
    # The wings are sold back on the last auction print, not carried into settlement.
    cost = roundtrip_cost_points(session, legs=2, notional=settle, premium=entry / 2, exit_kind="trade")
    return {
        "date": session.session_date,
        "status": session.status,
        "regime": regime(session.session_date),
        "expiry_session": session.is_expiry_session,
        "entry_premium": entry,
        "exit_premium": exit_px,
        "gross_points": gross,
        "cost_points": cost,
        "net_points": gross - cost,
        "net_rupees_per_lot": (gross - cost) * session.lot_size,
        "return_pct": gross / entry * 100,
    }


def strategy_fade_first_auction_print(session: SessionData) -> dict[str, object]:
    """Measure mean reversion of the underlying inside the auction window.

    The trade the owner's "wild fluctuation" framing suggests: if the first post-close
    print jumps away from the continuous close, does it come back by 15:39? Reported as
    the jump and the subsequent retracement, not as a fill — there is no tradeable
    instrument here beyond the options themselves.
    """
    spot = session.spot["best"].dropna()
    cont = spot[spot.index.time <= CONTINUOUS_END]
    auction = spot[spot.index.time >= AUCTION_START]
    if cont.empty or len(auction) < 2:
        return {}
    last_cont = float(cont.iloc[-1])
    first_auction = float(auction.iloc[0])
    final = float(auction.iloc[-1])
    jump = first_auction - last_cont
    retrace = first_auction - final
    return {
        "date": session.session_date,
        "status": session.status,
        "regime": regime(session.session_date),
        "expiry_session": session.is_expiry_session,
        "last_continuous": last_cont,
        "first_auction": first_auction,
        "final_auction": final,
        "jump_points": jump,
        "retrace_points": retrace,
        "retrace_frac_pct": (retrace / jump * 100) if jump else float("nan"),
    }


# ----------------------------------------------------------------------------- report


def _md(frame: pd.DataFrame, floatfmt: str = "{:.2f}") -> str:
    if frame.empty:
        return "_(no rows)_\n"
    disp = frame.copy()
    for col in disp.columns:
        if pd.api.types.is_float_dtype(disp[col]):
            disp[col] = disp[col].map(lambda v: "" if pd.isna(v) else floatfmt.format(v))
    header = "| " + " | ".join(str(c) for c in disp.columns) + " |"
    sep = "| " + " | ".join("---" for _ in disp.columns) + " |"
    body = "\n".join("| " + " | ".join(str(v) for v in row) + " |" for row in disp.itertuples(index=False))
    return f"{header}\n{sep}\n{body}\n"


def make_figures(sessions: list[SessionData], outdir: Path) -> list[str]:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return []
    outdir.mkdir(parents=True, exist_ok=True)
    written = []

    fig, ax = plt.subplots(figsize=(10, 5))
    for s in sessions:
        series = s.spot["best"].dropna()
        series = series[series.index.time >= FINAL_WINDOW_START]
        if series.empty:
            continue
        label = f"{s.session_date} {'expiry' if s.is_expiry_session else 'control'}"
        ax.plot([t.strftime("%H:%M") for t in series.index], series / series.iloc[0] * 100 - 100, label=label)
    ax.axvline("15:30", color="k", ls="--", lw=1)
    ax.set_title("Underlying path, 15:00-15:39 (rebased, dashed line = continuous close)")
    ax.set_ylabel("% from 15:00")
    ax.tick_params(axis="x", rotation=90, labelsize=6)
    ax.legend(fontsize=7)
    fig.tight_layout()
    p = outdir / "spot_final_window.png"
    fig.savefig(p, dpi=110)
    plt.close(fig)
    written.append(p.name)

    fig, ax = plt.subplots(figsize=(10, 5))
    for s in sessions:
        st = _atm_straddle(s)
        if st.empty:
            continue
        st = st[st.index.time >= FINAL_WINDOW_START]
        ax.plot([t.strftime("%H:%M") for t in st.index], st["time_value"], label=f"{s.session_date}")
    ax.axvline("15:30", color="k", ls="--", lw=1)
    ax.axhline(0, color="grey", lw=0.8)
    ax.set_title("ATM straddle time value into settlement")
    ax.set_ylabel("points")
    ax.tick_params(axis="x", rotation=90, labelsize=6)
    ax.legend(fontsize=7)
    fig.tight_layout()
    p = outdir / "atm_time_value.png"
    fig.savefig(p, dpi=110)
    plt.close(fig)
    written.append(p.name)

    fig, ax = plt.subplots(figsize=(9, 5))
    for s in sessions:
        bx = box_residuals(s)
        if bx.empty:
            continue
        bx = bx[bx["all_legs_traded"] & (bx["ts"].dt.time >= FINAL_WINDOW_START)]
        if bx.empty:
            continue
        ax.hist(bx["residual"].clip(-30, 30), bins=60, histtype="step", label=f"{s.session_date}")
    ax.set_title("Box-spread residual, traded bars only, 15:00-15:39 (spot-free relation)")
    ax.set_xlabel("points")
    ax.legend(fontsize=7)
    fig.tight_layout()
    p = outdir / "box_residuals.png"
    fig.savefig(p, dpi=110)
    plt.close(fig)
    written.append(p.name)
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--underlying", default="NIFTY")
    parser.add_argument("--dates", nargs="+", required=True, help="expiry sessions")
    parser.add_argument("--controls", nargs="*", default=[], help="non-expiry control sessions")
    parser.add_argument("--outdir", default=str(Path(__file__).resolve().parent / "fig"))
    args = parser.parse_args()

    all_dates = [(d, False) for d in args.dates] + [(d, True) for d in args.controls]
    sessions = [load_session(args.underlying, dt.date.fromisoformat(d)) for d, _ in all_dates]

    swings, repricing, residuals, straddles, strangles, fades = [], [], [], [], [], []
    for s in sessions:
        swings.append(swing_metrics(s))
        repricing.append(repricing_metrics(s))
        terminal = s.spot["best"].dropna()
        notional = float(terminal.iloc[-1]) if len(terminal) else float(s.parity_anchor_strike)
        st = _atm_straddle(s)
        premium = float(st["straddle"].median()) / 2 if not st.empty else 50.0
        cost_pts = roundtrip_cost_points(s, legs=4, notional=notional, premium=premium)
        for builder in (parity_residuals, box_residuals, vertical_violations, butterfly_violations):
            residuals.extend(residual_summary(s, builder(s), cost_pts))
        for coll, fn in ((straddles, strategy_short_straddle), (strangles, strategy_auction_strangle), (fades, strategy_fade_first_auction_print)):
            r = fn(s)
            if r:
                coll.append(r)

    outdir = Path(args.outdir)
    figs = make_figures(sessions, outdir)

    print(f"\n## Underlying swings ({args.underlying})\n")
    print(_md(pd.DataFrame(swings)))
    print(f"\n## Chain repricing ({args.underlying})\n")
    print(_md(pd.DataFrame(repricing)))
    print(f"\n## Arbitrage residuals ({args.underlying})\n")
    res = pd.DataFrame(residuals)
    if not res.empty:
        res = res.sort_values(["relation", "date", "window", "gate"])
    print(_md(res))
    print(f"\n## Strategy: short ATM straddle 15:00 -> settlement ({args.underlying})\n")
    print(_md(pd.DataFrame(straddles)))
    print(f"\n## Strategy: OTM strangle 15:25 -> 15:39 ({args.underlying})\n")
    print(_md(pd.DataFrame(strangles)))
    print(f"\n## Auction-window jump and retracement ({args.underlying})\n")
    print(_md(pd.DataFrame(fades)))
    print(f"\nfigures: {', '.join(figs) if figs else 'none (matplotlib unavailable)'}")


if __name__ == "__main__":
    main()
