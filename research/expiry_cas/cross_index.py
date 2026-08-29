"""Cross-index divergence between Sensex and Nifty across the closing-auction window.

Run: ``uv run python research/expiry_cas/cross_index.py --outdir research/expiry_cas/fig/cross_index``

**The question.** Cash trading ends 15:15 and the closing auction clears at 15:30-15:35,
but equity derivatives trade continuously to 15:40. So for twenty-five minutes there are
option prices on two highly correlated indices and no traded index level on either. If one
index's options dislocate while the other's do not, the dislocation is index-specific and a
candidate for reversion, because the two indices share most of their risk factors.

**How the underlying is recovered.** Put-call parity, :math:`S = C - P + K`, at one strike
per session per underlying, over minutes where both legs printed volume. The strike is
fixed for the whole session — chosen as the strike with the most both-legs-traded minutes
in 15:00-15:39 — because different strikes sit at different parity levels, so a series that
switches strike between minutes reports the level step between strikes as a price move. A
minute the fixed strike misses is filled from the nearest strike that traded and flagged;
the headline divergence figures are recomputed without those minutes.

**Why the divergence is a ratio, not a difference.** :math:`S_{fair}(t) = S_{ref}
(N_{imp}(t)/N_{ref})^\\beta` with both references taken at 15:14, the last minute of
continuous cash trading. On a chain with days to run, parity spot carries the forward bias
:math:`K(1-e^{-rT})`; that bias enters :math:`S_{imp}` and :math:`S_{ref}` alike and cancels
to first order in the ratio, which is why levels are never compared across underlyings and
only the ratio to each index's own 15:14 reference is.

**The price band and what it bounds.** Each constituent's auction price is confined to
±3 % of its 15:00-15:15 VWAP, so an index of bounded constituents is itself bounded by
±3 % of the index computed on those VWAP references. That reference index is not in this
corpus, so the floor and ceiling here are computed from the 15:14 implied level, which is a
close proxy and not the same number. The bound is therefore approximate at the edges — it
is used only to establish that no strike in an ATM±10 ladder is anywhere near it, a
conclusion with more than an order of magnitude of slack.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from load import DATASETS_ROOT, QUARANTINE_ROOT, SessionData, load_session

from xman_research.backtest.costs import ChargeableTrade, Side, StatutoryCostStack, TradeKind

#: Sessions where both underlyings carry option bars under the CAS regime.
SESSIONS = [
    "2026-08-03", "2026-08-04", "2026-08-05", "2026-08-06", "2026-08-07",
    "2026-08-10", "2026-08-11", "2026-08-12", "2026-08-13", "2026-08-14",
    "2026-08-17", "2026-08-18", "2026-08-19", "2026-08-20", "2026-08-21",
    "2026-08-24", "2026-08-25", "2026-08-26", "2026-08-27",
]  # fmt: skip

#: The session whose BSE auction dislocated. Excluded from the beta regression so the
#: estimator is not fitted on the event it is built to detect.
DISLOCATED = dt.date(2026, 8, 27)

#: Last minute of continuous cash trading, and the reference for every ratio here.
REF_TIME = dt.time(15, 14)
#: Cash auction order entry opens; the first minute where derivatives price a frozen spot.
WINDOW_START = dt.time(15, 15)
#: Matching completes and the official close is published around here.
MATCH_END = dt.time(15, 35)
#: Last option bar of the derivatives session.
WINDOW_END = dt.time(15, 39)

#: Constituent auction price band, as a fraction of the constituent's reference VWAP.
BAND = 0.03

LOT_DEFAULT = {"SENSEX": 20, "NIFTY": 65}

_STACK = StatutoryCostStack()


# --------------------------------------------------------------- implied index series


@dataclass(frozen=True, slots=True)
class ImpliedIndex:
    """One underlying's option-implied index level through the auction window.

    ``series`` is indexed by minute and carries ``implied`` (the parity level),
    ``strike`` (which strike produced it) and ``fallback`` (the fixed strike did not
    trade that minute, so a neighbour was used and the level carries that strike's own
    parity offset).
    """

    session: SessionData
    strike: float
    series: pd.DataFrame
    reference: float
    reference_time: pd.Timestamp

    @property
    def underlying(self) -> str:
        return self.session.underlying


def _implied_by_strike(session: SessionData) -> pd.DataFrame:
    """Per-minute :math:`C-P+K` at every strike where both legs printed volume."""
    traded = session.chain[session.chain["volume"] > 0]
    wide = traded.pivot_table(
        index=["ts", "strike"], columns="opt_type", values="close", aggfunc="last"
    )
    if "CE" not in wide.columns or "PE" not in wide.columns:
        return pd.DataFrame(columns=["ts", "strike", "implied"])
    wide = wide.dropna(subset=["CE", "PE"])
    implied = (wide["CE"] - wide["PE"] + wide.index.get_level_values("strike")).rename("implied")
    return implied.reset_index()


def implied_index(session: SessionData) -> ImpliedIndex | None:
    """Build the fixed-strike implied index series for one session.

    The strike is the one with the most both-legs-traded minutes over 15:00-15:39, ties
    broken by proximity to the level at the reference minute. Fixing it for the session is
    what stops the cross-strike parity offset entering the series as movement.
    """
    frame = _implied_by_strike(session)
    if frame.empty:
        return None
    window = frame[
        (frame["ts"].dt.time >= dt.time(15, 0)) & (frame["ts"].dt.time <= WINDOW_END)
    ]
    if window.empty:
        return None
    counts = window.groupby("strike")["implied"].size()
    level_rows = window[window["ts"].dt.time <= REF_TIME]
    level = float(level_rows["implied"].iloc[-1]) if len(level_rows) else float(counts.index[0])
    best = max(counts.index, key=lambda k: (counts[k], -abs(k - level)))

    minutes = sorted(window["ts"].unique())
    rows = []
    for ts in minutes:
        at_ts = window[window["ts"] == ts]
        primary = at_ts[at_ts["strike"] == best]
        if len(primary):
            rows.append((ts, float(primary["implied"].iloc[0]), best, False))
            continue
        near = at_ts.iloc[(at_ts["strike"] - best).abs().argsort()]
        if len(near):
            rows.append((ts, float(near["implied"].iloc[0]), float(near["strike"].iloc[0]), True))
    series = pd.DataFrame(rows, columns=["ts", "implied", "strike", "fallback"]).set_index("ts")
    ref_rows = series[series.index.time <= REF_TIME]
    if ref_rows.empty:
        return None
    return ImpliedIndex(
        session=session,
        strike=best,
        series=series,
        reference=float(ref_rows["implied"].iloc[-1]),
        reference_time=ref_rows.index[-1],
    )


# ------------------------------------------------------------------------------- beta


def _daily_closes(underlying: str) -> pd.Series:
    """Official daily closes from the index symbol's own bars, one per session.

    The last index bar of a session carries the settled close (the vendor back-stamps it),
    which is the number a daily return should use. Sessions where the index symbol is
    absent are dropped rather than filled.
    """
    out: dict[dt.date, float] = {}
    for root in (DATASETS_ROOT, QUARANTINE_ROOT):
        folder = root / underlying
        if not folder.exists():
            continue
        for path in sorted(folder.glob("*.parquet")):
            day = dt.date.fromisoformat(path.stem)
            if day in out:
                continue
            frame = pd.read_parquet(
                path,
                columns=["minute_ts", "symbol", "close"],
                filters=[("symbol", "==", underlying)],
            )
            if frame.empty:
                continue
            frame = frame.sort_values("minute_ts")
            out[day] = float(frame["close"].iloc[-1])
    return pd.Series(out).sort_index()


@dataclass(frozen=True, slots=True)
class Beta:
    """Sensex-on-Nifty daily log-return regression over the corpus overlap."""

    beta: float
    stderr: float
    r_squared: float
    n: int
    first: dt.date
    last: dt.date


def estimate_beta(exclude: set[dt.date] | None = None) -> Beta:
    """OLS with intercept of Sensex daily log returns on Nifty's.

    The dislocated session is excluded by the caller: a regression fitted through the
    event would move the fair-value line toward the dislocation and shrink the very
    divergence it is used to measure.
    """
    exclude = exclude or set()
    sensex, nifty = _daily_closes("SENSEX"), _daily_closes("NIFTY")
    common = sensex.index.intersection(nifty.index)
    rs = np.log(sensex[common]).diff().dropna()
    rn = np.log(nifty[common]).diff().dropna()
    keep = [d for d in rs.index.intersection(rn.index) if d not in exclude]
    x, y = rn[keep].to_numpy(), rs[keep].to_numpy()
    design = np.column_stack([np.ones_like(x), x])
    coef, *_ = np.linalg.lstsq(design, y, rcond=None)
    resid = y - design @ coef
    dof = len(x) - 2
    sigma2 = float(resid @ resid) / dof
    cov = sigma2 * np.linalg.inv(design.T @ design)
    ss_tot = float(((y - y.mean()) ** 2).sum())
    return Beta(
        beta=float(coef[1]),
        stderr=float(np.sqrt(cov[1, 1])),
        r_squared=1.0 - float(resid @ resid) / ss_tot,
        n=len(x),
        first=min(keep),
        last=max(keep),
    )


# ------------------------------------------------------------------------- divergence


def divergence(sensex: ImpliedIndex, nifty: ImpliedIndex, beta: float) -> pd.DataFrame:
    """Minute-by-minute :math:`d = S_{imp} - S_{ref}(N_{imp}/N_{ref})^\\beta`.

    Computed only on minutes where **both** underlyings printed a live parity level. A
    minute present on one side and forward-filled on the other would charge the missing
    side's real movement to the divergence.
    """
    s = sensex.series[
        (sensex.series.index.time >= WINDOW_START) & (sensex.series.index.time <= WINDOW_END)
    ]
    n = nifty.series[
        (nifty.series.index.time >= WINDOW_START) & (nifty.series.index.time <= WINDOW_END)
    ]
    common = s.index.intersection(n.index)
    if len(common) == 0:
        return pd.DataFrame()
    s, n = s.loc[common], n.loc[common]
    fair = sensex.reference * (n["implied"] / nifty.reference) ** beta
    frame = pd.DataFrame(
        {
            "s_imp": s["implied"],
            "n_imp": n["implied"],
            "s_fair": fair,
            "d_points": s["implied"] - fair,
            "fallback": s["fallback"] | n["fallback"],
        }
    )
    frame["d_pct"] = 100.0 * frame["d_points"] / frame["s_fair"]
    return frame


def _at(frame: pd.DataFrame, column: str, when: dt.time) -> float:
    """Value at the last minute at or before ``when``; NaN if the window starts later."""
    rows = frame[frame.index.time <= when]
    return float(rows[column].iloc[-1]) if len(rows) else float("nan")


def divergence_row(
    date: dt.date, sensex: ImpliedIndex, nifty: ImpliedIndex, frame: pd.DataFrame
) -> dict[str, object]:
    clean = frame[~frame["fallback"]]
    peak_idx = frame["d_points"].abs().idxmax()
    peak_clean = clean["d_points"].abs().idxmax() if len(clean) else None
    d35 = _at(frame, "d_points", MATCH_END)
    peak = float(frame.loc[peak_idx, "d_points"])
    return {
        "date": date,
        "s_expiry": sensex.session.is_expiry_session,
        "n_expiry": nifty.session.is_expiry_session,
        "status": "Q" if "quarantined" in (sensex.session.status, nifty.session.status) else "",
        "minutes": len(frame),
        "fallback_minutes": int(frame["fallback"].sum()),
        "s_ref": sensex.reference,
        "n_ref": nifty.reference,
        "d_peak": peak,
        "d_peak_pct": float(frame.loc[peak_idx, "d_pct"]),
        "t_peak": peak_idx.strftime("%H:%M"),
        "d_peak_clean": float(clean.loc[peak_clean, "d_points"]) if peak_clean is not None else np.nan,
        # The owner's thesis is a statement about the two indices separately — one moved,
        # the other did not — so both raw moves are carried beside the divergence.
        "s_chg_pct": 100.0 * (float(frame["s_imp"].iloc[-1]) / sensex.reference - 1.0),
        "n_chg_pct": 100.0 * (float(frame["n_imp"].iloc[-1]) / nifty.reference - 1.0),
        "d_1530": _at(frame, "d_points", dt.time(15, 30)),
        "d_1535": d35,
        "d_1539": _at(frame, "d_points", WINDOW_END),
        "reverted_pct": 100.0 * (1.0 - abs(d35) / abs(peak)) if peak else np.nan,
    }


# ------------------------------------------------------------------- band vs. ladder


def band_row(sensex: ImpliedIndex) -> dict[str, object]:
    """Where the ±3 % auction band sits relative to the strikes the corpus carries."""
    strikes = np.sort(sensex.session.chain["strike"].unique())
    ref = sensex.reference
    floor, ceiling = ref * (1 - BAND), ref * (1 + BAND)
    return {
        "date": sensex.session.session_date,
        "s_ref": ref,
        "band_floor": floor,
        "band_ceiling": ceiling,
        "ladder_low": float(strikes[0]),
        "ladder_high": float(strikes[-1]),
        "ladder_low_pct": 100.0 * (strikes[0] / ref - 1.0),
        "ladder_high_pct": 100.0 * (strikes[-1] / ref - 1.0),
        "strikes_below_floor": int((strikes < floor).sum()),
        "strikes_above_ceiling": int((strikes > ceiling).sum()),
    }


def structural_overpricing(sensex: ImpliedIndex) -> pd.DataFrame:
    """Strike-minutes whose price exceeds the most the band could ever settle them for.

    Only meaningful on an expiry session. A put struck below the band floor cannot settle
    in the money, so any positive price on it is a claim the band will break; a put struck
    above the floor is capped at :math:`K - floor`. On a chain with days to run the band
    bounds today's close and says nothing about tomorrow's gap, so no price on it can be
    called structurally too high.
    """
    session = sensex.session
    if not session.is_expiry_session:
        return pd.DataFrame()
    floor, ceiling = sensex.reference * (1 - BAND), sensex.reference * (1 + BAND)
    chain = session.chain
    chain = chain[
        (chain["volume"] > 0)
        & (chain["ts"].dt.time >= WINDOW_START)
        & (chain["ts"].dt.time <= WINDOW_END)
    ].copy()
    chain["max_settle"] = np.where(
        chain["opt_type"] == "PE",
        np.maximum(0.0, chain["strike"] - floor),
        np.maximum(0.0, ceiling - chain["strike"]),
    )
    over = chain[chain["close"] > chain["max_settle"]]
    return over[["ts", "strike", "opt_type", "close", "max_settle", "volume"]]


# ------------------------------------------------------------------------ strategies


def _trade_cost_points(session: SessionData, legs: int, premium: float) -> float:
    """Round-trip market cost of a ``legs``-leg structure, in index points per unit."""
    units = session.lot_size
    total = 0.0
    for _ in range(2 * legs):
        total += _STACK.charge(
            ChargeableTrade(
                trade_date=session.session_date,
                kind=TradeKind.TRADE,
                side=Side.SELL,
                quantity_units=units,
                price=max(premium, 0.05),
                orders=1,
            )
        ).total
    return total / units


def _settlement_cost_points(
    session: SessionData, legs: int, premium: float, notional: float, intrinsic: float
) -> float:
    """Cost of opening ``legs`` legs and carrying them into cash settlement, in points.

    The structure here is short, so it is assigned and flattens with a BUY, which is why
    no exercise STT enters: that charge falls on the purchaser.
    """
    units = session.lot_size
    total = 0.0
    for _ in range(legs):
        total += _STACK.charge(
            ChargeableTrade(
                trade_date=session.session_date,
                kind=TradeKind.TRADE,
                side=Side.SELL,
                quantity_units=units,
                price=max(premium, 0.05),
                orders=1,
            )
        ).total
    total += _STACK.charge(
        ChargeableTrade(
            trade_date=session.session_date,
            kind=TradeKind.SETTLEMENT,
            side=Side.BUY,
            quantity_units=units,
            price=intrinsic,
            orders=0,
            notional_price=notional,
        )
    ).total
    return total / units


def _leg_price(session: SessionData, ts: pd.Timestamp, strike: float, kind: str) -> float | None:
    """Traded close of one contract at one minute; ``None`` if that bar carried no trade."""
    chain = session.chain
    row = chain[
        (chain["ts"] == ts)
        & (chain["strike"] == strike)
        & (chain["opt_type"] == kind)
        & (chain["volume"] > 0)
    ]
    return float(row["close"].iloc[0]) if len(row) else None


def _leg_volume(session: SessionData, ts: pd.Timestamp, strike: float, kind: str) -> float:
    chain = session.chain
    row = chain[(chain["ts"] == ts) & (chain["strike"] == strike) & (chain["opt_type"] == kind)]
    return float(row["volume"].iloc[0]) if len(row) else 0.0


def _first_trigger(frame: pd.DataFrame, threshold_pct: float, sign: int) -> pd.Timestamp | None:
    """First minute where the divergence exceeds the threshold in the given direction.

    ``sign`` is -1 for Sensex cheap against fair (:math:`d \\le -X`) and +1 for rich.
    """
    limit = abs(threshold_pct)
    hits = frame[frame["d_pct"] <= -limit] if sign < 0 else frame[frame["d_pct"] >= limit]
    return hits.index[0] if len(hits) else None


def strategy_band_bounded_put(
    sensex: ImpliedIndex, frame: pd.DataFrame, threshold_pct: float
) -> dict[str, object] | None:
    """S1 — sell the lowest ladder put when Sensex is cheap against Nifty-implied fair.

    The band is the risk control: the settlement index cannot print below
    :math:`S_{ref}(1-0.03)`, so the short put's worst case is :math:`K - floor` per unit
    and is known at entry. Held to settlement, which is only defined on an expiry session.
    """
    session = sensex.session
    if not session.is_expiry_session:
        return None
    entry_ts = _first_trigger(frame, threshold_pct, -1)
    if entry_ts is None:
        return None
    # The lowest strike that actually printed a put trade in the trigger minute, not the
    # lowest strike on the ladder: the deepest listed put is often untraded for whole
    # minutes, and a fill assumed on a bar with no volume is a fill nobody could get.
    strike, premium = None, None
    for candidate in np.sort(session.chain["strike"].unique()):
        price = _leg_price(session, entry_ts, float(candidate), "PE")
        if price is not None:
            strike, premium = float(candidate), price
            break
    if strike is None:
        return None
    floor = sensex.reference * (1 - BAND)
    settle = float(frame["s_imp"].iloc[-1])
    intrinsic = max(0.0, strike - settle)
    cost = _settlement_cost_points(session, 1, premium, settle, intrinsic)
    worst = strike - floor
    return {
        "date": session.session_date,
        "threshold_pct": threshold_pct,
        "entry": entry_ts.strftime("%H:%M"),
        "strike": strike,
        "premium": premium,
        "settle": settle,
        "intrinsic": intrinsic,
        "worst_case_points": worst,
        "reward_risk": premium / worst if worst else np.nan,
        "net_points": premium - intrinsic - cost,
        "net_rupees_per_lot": (premium - intrinsic - cost) * session.lot_size,
        "worst_rupees_per_lot": (premium - worst - cost) * session.lot_size,
        "entry_volume": _leg_volume(session, entry_ts, strike, "PE"),
    }


def _call_spread(
    session: SessionData, ts: pd.Timestamp, atm: float, width_steps: int
) -> tuple[float, float, float, float] | None:
    """Price of a two-strike-wide call spread at one minute, and its leg volumes."""
    strikes = np.sort(session.chain["strike"].unique())
    step = float(np.median(np.diff(strikes))) if len(strikes) > 1 else 0.0
    k1 = float(strikes[np.argmin(np.abs(strikes - atm))])
    k2 = k1 + width_steps * step
    if k2 not in set(strikes):
        return None
    long_leg = _leg_price(session, ts, k1, "CE")
    short_leg = _leg_price(session, ts, k2, "CE")
    if long_leg is None or short_leg is None:
        return None
    vol = min(_leg_volume(session, ts, k1, "CE"), _leg_volume(session, ts, k2, "CE"))
    return long_leg - short_leg, k1, k2, vol


def strategy_paired_spread(
    sensex: ImpliedIndex,
    nifty: ImpliedIndex,
    frame: pd.DataFrame,
    threshold_pct: float,
    direction: int,
    beta: float,
    exit_time: dt.time,
    width_steps: int = 2,
) -> dict[str, object] | None:
    """S2/S3 — a Sensex call spread against the opposite Nifty call spread.

    ``direction`` is -1 for the S2 case (Sensex below Nifty-implied fair: long the Sensex
    spread, short Nifty's) and +1 for its mirror, S3. Both legs are call spreads, so each
    side's loss is capped at its width and the position is defined-risk in both indices.

    The Nifty size is the notional-matched, beta-scaled one: :math:`\\beta S_{ref} q_S /
    (N_{ref} q_N)` rounded to whole lots, because a lot is the smallest tradeable unit and
    a fractional hedge is not a position anyone can take.
    """
    s_sess, n_sess = sensex.session, nifty.session
    entry_ts = _first_trigger(frame, threshold_pct, direction)
    if entry_ts is None:
        return None
    exits = frame[frame.index.time <= exit_time]
    if not len(exits) or exits.index[-1] <= entry_ts:
        return None
    exit_ts = exits.index[-1]

    s_entry = _call_spread(s_sess, entry_ts, float(frame.loc[entry_ts, "s_imp"]), width_steps)
    n_entry = _call_spread(n_sess, entry_ts, float(frame.loc[entry_ts, "n_imp"]), width_steps)
    if s_entry is None or n_entry is None:
        return None
    s_exit = _call_spread(s_sess, exit_ts, float(frame.loc[entry_ts, "s_imp"]), width_steps)
    n_exit = _call_spread(n_sess, exit_ts, float(frame.loc[entry_ts, "n_imp"]), width_steps)
    if s_exit is None or n_exit is None:
        return None

    hedge_lots = max(
        1,
        int(round(beta * sensex.reference * s_sess.lot_size / (nifty.reference * n_sess.lot_size))),
    )
    s_move = (s_exit[0] - s_entry[0]) * (-direction)
    n_move = (n_exit[0] - n_entry[0]) * direction
    s_cost = _trade_cost_points(s_sess, 2, max(s_entry[0], 0.05))
    n_cost = _trade_cost_points(n_sess, 2, max(n_entry[0], 0.05))
    gross = s_move * s_sess.lot_size + n_move * n_sess.lot_size * hedge_lots
    cost = s_cost * s_sess.lot_size + n_cost * n_sess.lot_size * hedge_lots
    return {
        "date": s_sess.session_date,
        "threshold_pct": threshold_pct,
        "leg": "S2" if direction < 0 else "S3",
        "exit": exit_time.strftime("%H:%M"),
        "entry": entry_ts.strftime("%H:%M"),
        "d_entry_pct": float(frame.loc[entry_ts, "d_pct"]),
        "s_strikes": f"{s_entry[1]:.0f}/{s_entry[2]:.0f}",
        "n_strikes": f"{n_entry[1]:.0f}/{n_entry[2]:.0f}",
        "hedge_lots": hedge_lots,
        "s_move": s_move,
        "n_move": n_move,
        "gross_rupees": gross,
        "cost_rupees": cost,
        "net_rupees": gross - cost,
        "min_leg_volume": min(s_entry[3], n_entry[3], s_exit[3], n_exit[3]),
    }


# ----------------------------------------------------------------------- trigger stats


def trigger_stats(frames: dict[dt.date, pd.DataFrame], threshold_pct: float) -> dict[str, object]:
    """How often the trigger fires, how long it lasts, and whether it reverts by 15:35."""
    fired_sessions, minutes, runs, closed = [], 0, [], []
    for date, frame in frames.items():
        hit = frame["d_pct"].abs() >= threshold_pct
        if not hit.any():
            continue
        fired_sessions.append(date)
        minutes += int(hit.sum())
        run, longest = 0, 0
        for value in hit:
            run = run + 1 if value else 0
            longest = max(longest, run)
        runs.append(longest)
        peak_idx = frame["d_points"].abs().idxmax()
        peak = float(frame.loc[peak_idx, "d_points"])
        d35 = _at(frame, "d_points", MATCH_END)
        if peak:
            closed.append(1.0 - abs(d35) / abs(peak))
    return {
        "threshold_pct": threshold_pct,
        "sessions_fired": len(fired_sessions),
        "sessions_total": len(frames),
        "trigger_minutes": minutes,
        "median_run_minutes": float(np.median(runs)) if runs else np.nan,
        "median_closed_by_1535_pct": 100.0 * float(np.median(closed)) if closed else np.nan,
        "dates": ", ".join(d.isoformat()[5:] for d in fired_sessions) or "—",
    }


# --------------------------------------------------------------------------- reporting


def _md(frame: pd.DataFrame, floatfmt: str = "{:.2f}") -> str:
    if frame.empty:
        return "_(no rows)_\n"
    shown = frame.copy()
    for col in shown.columns:
        if pd.api.types.is_float_dtype(shown[col]):
            shown[col] = shown[col].map(lambda v: "—" if pd.isna(v) else floatfmt.format(v))
    header = "| " + " | ".join(str(c) for c in shown.columns) + " |"
    rule = "|" + "|".join("---" for _ in shown.columns) + "|"
    body = "\n".join("| " + " | ".join(str(v) for v in row) + " |" for row in shown.to_numpy())
    return f"{header}\n{rule}\n{body}\n"


def make_figures(
    frames: dict[dt.date, pd.DataFrame], bands: pd.DataFrame, outdir: Path
) -> list[str]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    outdir.mkdir(parents=True, exist_ok=True)
    written = []

    fig, ax = plt.subplots(figsize=(9, 5))
    for date, frame in frames.items():
        minutes = [(t.hour * 60 + t.minute) for t in frame.index.time]
        highlight = date == DISLOCATED
        ax.plot(
            minutes,
            frame["d_pct"],
            color="crimson" if highlight else "0.7",
            lw=2.0 if highlight else 0.9,
            zorder=3 if highlight else 1,
            label=date.isoformat() if highlight else None,
        )
    ax.axhline(0, color="k", lw=0.8)
    for level in (0.5, -0.5):
        ax.axhline(level, color="steelblue", ls=":", lw=0.9)
    ax.set_xticks([915, 920, 925, 930, 935, 939])
    ax.set_xticklabels(["15:15", "15:20", "15:25", "15:30", "15:35", "15:39"])
    ax.set_ylabel("d = S_imp − S_fair  (% of fair)")
    ax.set_title("Sensex vs Nifty-implied fair value through the auction window (19 sessions)")
    ax.legend(loc="lower left", fontsize=8)
    fig.tight_layout()
    path = outdir / "divergence_paths.png"
    fig.savefig(path, dpi=130)
    plt.close(fig)
    written.append(str(path))

    frame = frames.get(DISLOCATED)
    if frame is not None:
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(9, 6), sharex=True)
        minutes = [(t.hour * 60 + t.minute) for t in frame.index.time]
        ax1.plot(minutes, frame["s_imp"], color="crimson", label="Sensex implied")
        ax1.plot(minutes, frame["s_fair"], color="steelblue", ls="--", label="fair from Nifty")
        ax1.axhline(74983.19, color="0.4", ls=":", label="published indicative low 74,983")
        ax1.set_ylabel("index points")
        ax1.legend(fontsize=8)
        ax1.set_title("2026-08-27 — implied Sensex against Nifty-implied fair value")
        ax2.plot(minutes, frame["d_points"], color="k")
        ax2.axhline(0, color="0.6", lw=0.8)
        ax2.set_ylabel("d (points)")
        ax2.set_xticks([915, 920, 925, 930, 935, 939])
        ax2.set_xticklabels(["15:15", "15:20", "15:25", "15:30", "15:35", "15:39"])
        fig.tight_layout()
        path = outdir / "divergence_2026-08-27.png"
        fig.savefig(path, dpi=130)
        plt.close(fig)
        written.append(str(path))

    fig, ax = plt.subplots(figsize=(9, 4))
    idx = np.arange(len(bands))
    ax.bar(idx, bands["ladder_high_pct"] - bands["ladder_low_pct"],
           bottom=bands["ladder_low_pct"], color="steelblue", label="strike ladder (ATM±10)")
    ax.axhline(3.0, color="crimson", ls="--", label="auction band ±3 %")
    ax.axhline(-3.0, color="crimson", ls="--")
    ax.set_xticks(idx)
    ax.set_xticklabels([d.isoformat()[5:] for d in bands["date"]], rotation=90, fontsize=7)
    ax.set_ylabel("% from 15:14 implied level")
    ax.set_title("Where the Sensex ladder reaches versus where the auction band binds")
    ax.legend(fontsize=8)
    fig.tight_layout()
    path = outdir / "band_vs_ladder.png"
    fig.savefig(path, dpi=130)
    plt.close(fig)
    written.append(str(path))
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outdir", default="research/expiry_cas/fig/cross_index")
    parser.add_argument("--out", default="research/expiry_cas/cross_index_output.md")
    args = parser.parse_args()

    beta_fit = estimate_beta(exclude={DISLOCATED})
    implied: dict[dt.date, tuple[ImpliedIndex, ImpliedIndex]] = {}
    coverage = []
    for raw in SESSIONS:
        date = dt.date.fromisoformat(raw)
        s_sess = load_session("SENSEX", date, LOT_DEFAULT["SENSEX"])
        n_sess = load_session("NIFTY", date, LOT_DEFAULT["NIFTY"])
        s_imp, n_imp = implied_index(s_sess), implied_index(n_sess)
        if s_imp is None or n_imp is None:
            coverage.append({"date": date, "note": "no implied series"})
            continue
        implied[date] = (s_imp, n_imp)
        coverage.append(
            {
                "date": date,
                "s_strike": s_imp.strike,
                "n_strike": n_imp.strike,
                "s_lot": s_sess.lot_size,
                "n_lot": n_sess.lot_size,
                "s_expiry": s_sess.is_expiry_session,
                "n_expiry": n_sess.is_expiry_session,
                "status": "Q" if "quarantined" in (s_sess.status, n_sess.status) else "published",
            }
        )

    frames = {
        date: divergence(s_imp, n_imp, beta_fit.beta) for date, (s_imp, n_imp) in implied.items()
    }
    frames = {d: f for d, f in frames.items() if not f.empty}
    frames_unit = {
        date: divergence(s_imp, n_imp, 1.0) for date, (s_imp, n_imp) in implied.items()
    }

    div = pd.DataFrame(
        [divergence_row(d, *implied[d], frames[d]) for d in frames]
    )
    div_unit = pd.DataFrame(
        [divergence_row(d, *implied[d], frames_unit[d]) for d in frames]
    )
    bands = pd.DataFrame([band_row(implied[d][0]) for d in frames])
    over = pd.concat(
        [structural_overpricing(implied[d][0]).assign(date=d) for d in frames], ignore_index=True
    )
    triggers = pd.DataFrame([trigger_stats(frames, x) for x in (0.25, 0.5, 1.0, 1.5)])

    s1 = pd.DataFrame(
        [
            row
            for d in frames
            for x in (0.25, 0.5, 1.0, 1.5)
            if (row := strategy_band_bounded_put(implied[d][0], frames[d], x)) is not None
        ]
    )
    paired = pd.DataFrame(
        [
            row
            for d in frames
            for x in (0.25, 0.5, 1.0, 1.5)
            for direction in (-1, 1)
            for exit_time in (MATCH_END, WINDOW_END)
            if (
                row := strategy_paired_spread(
                    *implied[d], frames[d], x, direction, beta_fit.beta, exit_time
                )
            )
            is not None
        ]
    )

    dist = pd.DataFrame(
        {
            "quantile": ["p50", "p75", "p90", "p95", "max"],
            "abs_d_pct": [
                float(np.percentile(pd.concat(frames.values())["d_pct"].abs(), q))
                for q in (50, 75, 90, 95)
            ]
            + [float(pd.concat(frames.values())["d_pct"].abs().max())],
        }
    )

    figures = make_figures(frames, bands, Path(args.outdir))

    lines = [
        "# Cross-index divergence — generated output",
        "",
        f"Sessions with a divergence series: **{len(frames)}** of {len(SESSIONS)}.",
        "",
        "## Beta (Sensex on Nifty, daily log returns, 08-27 excluded)",
        "",
        f"beta = **{beta_fit.beta:.4f}** (SE {beta_fit.stderr:.4f}), R² = **{beta_fit.r_squared:.4f}**, "
        f"n = {beta_fit.n}, {beta_fit.first} … {beta_fit.last}",
        "",
        "## Coverage",
        "",
        _md(pd.DataFrame(coverage)),
        "## Divergence per session (beta-scaled)",
        "",
        _md(div),
        "## Divergence per session (beta = 1)",
        "",
        _md(div_unit[["date", "d_peak", "t_peak", "d_1535", "reverted_pct"]]),
        "## |d| distribution over all session-minutes",
        "",
        _md(dist, "{:.4f}"),
        "## Trigger statistics",
        "",
        _md(triggers),
        "## Band versus ladder",
        "",
        _md(bands),
        f"Structurally overpriced strike-minutes (expiry sessions): **{len(over)}**",
        "",
        _md(over.head(20)) if len(over) else "",
        "## S1 — band-bounded short put",
        "",
        _md(s1),
        "## S2 / S3 — paired call spreads",
        "",
        _md(paired),
        "## Figures",
        "",
        *[f"- `{p}`" for p in figures],
        "",
    ]
    Path(args.out).write_text("\n".join(lines))
    print(f"wrote {args.out} ({len(frames)} sessions, beta={beta_fit.beta:.4f})")


if __name__ == "__main__":
    main()
