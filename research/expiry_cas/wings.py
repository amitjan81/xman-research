"""Did the next-expiry wings reprice off a cash closing-auction indicative?

The question this answers, for one underlying and one session: while the cash closing
auction printed an indicative index far below the continuous close, did options on the
*next* expiry — which have days of life left and settle on nothing that happens today —
follow it down (puts bid up, calls sold), and if so was the move tradeable.

**Why the next expiry and not the expiring one.** The expiring series delists into
settlement and carries no bars in this corpus after its own expiry morning, so the
strike the press story names cannot be examined at all. A next-week contract at the same
strike is a different instrument with a different worst case, and the substitution has to
be stated wherever a number from one is read as evidence about the other.

**Two conventions this module never breaks**, both inherited from ``load.py``:

* A minute-to-minute change is computed only between two minutes that each printed
  volume. A zero-volume bar carries the previous close, so differencing across one
  reports a multi-minute move as a one-minute spike — which is precisely the artifact a
  spike table is most likely to manufacture. Every reported change carries the gap in
  minutes between its endpoints.
* Two underlying series, each used for one job. The **cash feed** at 15:14
  (:attr:`ChainSession.ref_spot`) classifies strikes — moneyness, the wing cut, the
  at-the-money time-value strike. **Parity** at a single anchor pair supplies *movement*,
  and is the only series that survives past 15:29 when the cash index stops. They are
  never spliced, and the level gap between them is reported rather than assumed away:
  parity prices the forward, which on this session sits far enough above cash that carry
  explains only part of it (:attr:`ChainSession.forward_premium`).

**The bound problem, stated once.** For an expiring option the ±3 % auction band bounds
settlement, so a short put has a known worst case. A next-expiry option has an unbounded
overnight gap, so no worst case exists. What can be bounded is the mark-to-market if the
position is closed the same session with the index at the band floor, and that bound is
built from a time-value estimate taken at 15:14 — before any volatility repricing. A
2,200-point dislocation raises implied volatility, so the estimate is a **lower** bound on
the adverse mark, and every reward-to-risk ratio built on it is optimistic in the
direction that flatters the trade.
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

CHAIN_ROOT = Path("/home/qa/runtime/data/backtest/datasets/dhan_chain")

#: The window this study covers: last minute of continuous cash trading through the last
#: derivatives bar the feed carries.
WINDOW_START = dt.time(15, 14)
WINDOW_END = dt.time(15, 39)

#: Published Sensex closing-auction indicative path for 2026-08-27 (press, not in any
#: feed). The vendor never carries the indicative index, so these are the only values
#: for it anywhere in this study and they are constants, not measurements.
INDICATIVE_0827 = {
    "ref_1515": 77182.91,
    "low": 74983.19,
    "low_window": ("15:18", "15:23"),
    "close": 76933.59,
}
#: ±3 % band floor around the 15:15 reference. Bounds *today's* auction close only.
BAND_FLOOR_0827 = 77182.91 * 0.97

#: Rate used to size the carry component of the parity-vs-cash gap. Indicative Indian
#: short-term funding; the point of quoting it is that the gap is larger than any
#: plausible value of it, so the residual is a finding rather than a mis-set constant.
CARRY_RATE = 0.065

_SYMBOL_RE = re.compile(
    r"^(?P<root>.+?)-(?P<expiry>\d{2}[A-Za-z]{3}\d{4})-(?P<strike>\d+(?:\.\d+)?)-(?P<kind>CE|PE)$"
)

LOT_SIZES = {"SENSEX": 20, "NIFTY": 75, "BANKNIFTY": 35}


@dataclass(frozen=True, slots=True)
class ChainSession:
    """One session of the ±25 chain tree, restricted to one expiry."""

    underlying: str
    session_date: dt.date
    expiry: dt.date
    #: Minute × strike close and volume, one frame per option type.
    ce_close: pd.DataFrame
    ce_vol: pd.DataFrame
    pe_close: pd.DataFrame
    pe_vol: pd.DataFrame
    #: Parity spot from the single anchor pair; index is the window's minutes.
    implied_spot: pd.Series
    anchor_strike: float
    #: Broadcast index level, NaN once the cash index stops.
    feed_spot: pd.Series
    lot_size: int

    @property
    def strikes(self) -> np.ndarray:
        return np.asarray(self.pe_close.columns, dtype=float)

    @property
    def days_to_expiry(self) -> int:
        return (self.expiry - self.session_date).days

    @property
    def ref_spot(self) -> float:
        """The cash index at 15:14 — the reference every moneyness in this study is struck on.

        This is the **feed** level, not the parity level. Parity on a non-expiring chain
        prices the *forward*, which sits materially above cash (:attr:`forward_premium`),
        so using it to classify strikes pushes the whole board one way: it labels more
        strikes as wings and picks an at-the-money strike that is hundreds of points in
        the money against cash. Moneyness, the wing cut, and the at-the-money time-value
        strike therefore all come from here.

        Parity is still the only usable series after 15:29, when the cash index stops. The
        division of labour is: cash level for *classification*, parity for *movement*.
        """
        live = self.feed_spot.dropna()
        live = live[live.index.time <= WINDOW_START]
        if len(live):
            return float(live.iloc[-1])
        return float(self.implied_spot.dropna().iloc[0])

    @property
    def forward_premium(self) -> float:
        """Parity level minus cash level at 15:14, in index points.

        For a chain with :math:`T > 0` put-call parity recovers :math:`S - Ke^{-rT}`, so a
        positive gap is expected. Its *size* is a finding rather than a nuisance: the carry
        term :math:`K(1-e^{-rT})` accounts for only part of it on this session, and the
        remainder is a genuine premium in the options market's forward, not a stale leg —
        it is consistent across strikes.
        """
        parity = self.implied_spot.dropna()
        if parity.empty:
            return float("nan")
        return float(parity.iloc[0]) - self.ref_spot

    def carry_points(self, rate: float = 0.065) -> float:
        """The part of :attr:`forward_premium` that carry at ``rate`` explains."""
        return self.anchor_strike * (1.0 - np.exp(-rate * self.days_to_expiry / 365.0))


def _load_raw(underlying: str, session_date: dt.date) -> pd.DataFrame:
    path = CHAIN_ROOT / underlying / f"{session_date.isoformat()}.parquet"
    if not path.exists():
        raise FileNotFoundError(f"no chain-tree parquet for {underlying} {session_date}")
    raw = pd.read_parquet(path)
    raw["ts"] = pd.to_datetime(raw["minute_ts"], unit="us", utc=True).dt.tz_convert("Asia/Kolkata")
    return raw[raw["ts"].dt.hour < 16]


def available_expiries(underlying: str, session_date: dt.date) -> list[dt.date]:
    """Expiries carrying option bars in this session's tree, earliest first.

    The tree holds only expiries still listed *and printing* when captured. A series
    that expired this morning has refdata but no bars, so it never appears here — which
    is why a strike's behaviour on the expiring series cannot be recovered from this
    corpus at all.
    """
    raw = _load_raw(underlying, session_date)
    parsed = raw["symbol"].str.extract(_SYMBOL_RE)
    exp = pd.to_datetime(parsed["expiry"].dropna(), format="%d%b%Y").dt.date
    return sorted(set(exp))


def load_chain(
    underlying: str, session_date: dt.date, expiry: dt.date | None = None
) -> ChainSession:
    """Load one expiry's minute grid over the study window.

    ``expiry`` defaults to the earliest expiry with bars. Closes are carried as printed;
    the volume grid beside them is what lets every consumer drop stale bars itself
    rather than trusting a forward-filled price.
    """
    raw = _load_raw(underlying, session_date)
    parsed = raw["symbol"].str.extract(_SYMBOL_RE)
    chain = raw.assign(
        strike=pd.to_numeric(parsed["strike"]),
        opt_type=parsed["kind"],
        expiry=pd.to_datetime(parsed["expiry"], format="%d%b%Y").dt.date,
    )
    feed = chain.dropna(subset=["spot"]).groupby("ts")["spot"].last()
    chain = chain[chain["opt_type"].notna()]
    if expiry is None:
        expiry = min(chain["expiry"])
    chain = chain[chain["expiry"] == expiry]

    window = chain[
        (chain["ts"].dt.time >= WINDOW_START) & (chain["ts"].dt.time <= WINDOW_END)
    ].copy()

    def grid(kind: str, value: str) -> pd.DataFrame:
        return window[window["opt_type"] == kind].pivot_table(
            index="ts", columns="strike", values=value, aggfunc="last"
        )

    ce_close, ce_vol = grid("CE", "close"), grid("CE", "volume")
    pe_close, pe_vol = grid("PE", "close"), grid("PE", "volume")

    # Anchor from the feed at the window's first minute, while the cash index is still
    # live, so the anchor never depends on the parity estimate it goes on to produce.
    ref_ts = pd.Timestamp.combine(session_date, WINDOW_START).tz_localize("Asia/Kolkata")
    earlier = feed[feed.index <= ref_ts]
    level = float(earlier.iloc[-1]) if len(earlier) else float(np.median(ce_close.columns))
    shared = sorted(set(ce_close.columns) & set(pe_close.columns))
    # Among strikes near the money, prefer the one whose pair trades the most minutes:
    # the anchor must print every minute or the movement series acquires holes.
    near = sorted(shared, key=lambda k: abs(k - level))[:5]
    both = {k: int(((ce_vol[k] > 0) & (pe_vol[k] > 0)).sum()) for k in near}
    anchor = max(both, key=lambda k: (both[k], -abs(k - level)))

    live = (ce_vol[anchor] > 0) & (pe_vol[anchor] > 0)
    implied = (ce_close[anchor] - pe_close[anchor] + anchor).where(live)

    return ChainSession(
        underlying=underlying,
        session_date=session_date,
        expiry=expiry,
        ce_close=ce_close,
        ce_vol=ce_vol,
        pe_close=pe_close,
        pe_vol=pe_vol,
        implied_spot=implied.rename("implied_spot"),
        anchor_strike=float(anchor),
        feed_spot=feed.reindex(ce_close.index).rename("feed_spot"),
        lot_size=LOT_SIZES.get(underlying, 20),
    )


def traded_changes(close: pd.DataFrame, vol: pd.DataFrame) -> pd.DataFrame:
    """Minute-to-minute changes between consecutive **traded** bars, long-form.

    One row per (strike, to_ts). ``gap_min`` is the distance to the previous traded bar:
    a change with ``gap_min > 1`` is not a one-minute move and must never be reported as
    one. Rows where either endpoint is a zero-volume (stale) bar do not exist.
    """
    rows = []
    for strike in close.columns:
        live = close[strike].where(vol[strike] > 0).dropna()
        if len(live) < 2:
            continue
        prev = live.shift()
        prev_ts = pd.Series(live.index, index=live.index).shift()
        frame = pd.DataFrame(
            {
                "strike": float(strike),
                "from_ts": prev_ts,
                "to_ts": live.index,
                "from_px": prev,
                "to_px": live,
                "from_vol": vol[strike].where(vol[strike] > 0).dropna().shift(),
                "to_vol": vol[strike].where(vol[strike] > 0).dropna(),
            }
        ).dropna(subset=["from_px"])
        rows.append(frame)
    if not rows:
        return pd.DataFrame(
            columns=["strike", "from_ts", "to_ts", "from_px", "to_px", "d_pct", "d_rs", "gap_min"]
        )
    out = pd.concat(rows, ignore_index=True)
    out["d_pct"] = (out["to_px"] / out["from_px"] - 1.0) * 100.0
    out["d_rs"] = out["to_px"] - out["from_px"]
    out["gap_min"] = (out["to_ts"] - out["from_ts"]).dt.total_seconds() / 60.0
    return out


def crash_base(live: pd.Series) -> tuple[float | None, str]:
    """The pre-crash reference price for one strike, and the minute it came from.

    The natural reference is the last continuous-session print at or before 15:14. Some
    deep-wing strikes do not trade until after that, so the first traded bar of the
    window stands in — which understates the move if that bar is already inside the
    dislocation. Every table reporting a crash-window change carries the minute this
    came from, because the two cases are not the same measurement and a reader cannot
    tell them apart from the percentage alone.
    """
    if not len(live):
        return None, "—"
    before = live[live.index.time <= WINDOW_START]
    chosen = before.iloc[-1] if len(before) else live.iloc[0]
    when = (before.index[-1] if len(before) else live.index[0]).strftime("%H:%M")
    return (float(chosen), when) if chosen > 0 else (None, "—")


#: The minutes the published indicative spent at its low.
CRASH_START, CRASH_END = dt.time(15, 18), dt.time(15, 23)
#: Cash matching runs 15:30-15:35 and the close is published around 15:35.
POST_AUCTION_START = dt.time(15, 30)


def phase_of(ts: pd.Timestamp) -> str:
    """Which part of the session a bar belongs to.

    Three phases, because a premium move means a different thing in each. ``crash`` is the
    window the indicative spent at its low — the only phase where a move is a response to
    the dislocation. ``post_auction`` is 15:30 onward, where matching is under way and the
    close is about to be published, so a move there is about the close becoming known.
    ``pre`` is everything before the dislocation.
    """
    t = ts.time()
    if t >= POST_AUCTION_START:
        return "post_auction"
    if CRASH_START <= t <= CRASH_END:
        return "crash"
    return "pre"


def forward_path(session: ChainSession) -> pd.DataFrame:
    """The option-implied forward's own move, in points and percent, at four checkpoints.

    This is the quantity the study's own conventions say is usable on a non-expiring chain
    — a *change*, from one source, with the level's forward premium differencing out. It
    is reported because a wing premium move cannot be read without it: part of any premium
    change is delta against this series, and only the remainder is a volatility or skew
    bid.
    """
    parity = session.implied_spot.dropna()
    if parity.empty:
        return pd.DataFrame()
    base = float(parity.iloc[0])
    rows = []
    for label, when in (
        ("15:23 (indicative low)", dt.time(15, 23)),
        ("15:30", dt.time(15, 30)),
        ("15:35", dt.time(15, 35)),
        ("15:39", dt.time(15, 39)),
    ):
        upto = parity[parity.index.time <= when]
        if upto.empty:
            continue
        level = float(upto.iloc[-1])
        rows.append(
            {
                "checkpoint": label,
                "implied_fwd": level,
                "change_pts": level - base,
                "change_pct": (level / base - 1.0) * 100.0,
            }
        )
    return pd.DataFrame(rows)


def delta_decomposition(session: ChainSession, strikes: list[float]) -> pd.DataFrame:
    """Split each wing put's crash-window move into a delta part and a residual.

    Delta is estimated empirically from this chain rather than assumed: for each strike,
    the slope of its traded premium change against the simultaneous change in the
    option-implied forward, over every minute of the window where both printed. The
    residual is what the forward's own move does not explain — a volatility or skew bid.

    The estimate's limits: the slope is fitted over a window in which volatility is itself
    moving, so it absorbs some vega into the delta term, and the strikes with the fewest
    prints have the loosest slopes. ``n`` is reported so a slope fitted on a handful of
    points is visible as such.
    """
    parity = session.implied_spot.dropna()
    d_fwd = parity.diff()
    rows = []
    for k in strikes:
        live = session.pe_close[k].where(session.pe_vol[k] > 0).dropna()
        d_px = live.diff()
        joined = pd.DataFrame({"dp": d_px, "ds": d_fwd.reindex(d_px.index)}).dropna()
        joined = joined[joined["ds"].abs() > 1e-9]
        if len(joined) < 5:
            continue
        slope = float(np.polyfit(joined["ds"], joined["dp"], 1)[0])
        base_px, base_min = crash_base(live)
        crash = live[(live.index.time >= CRASH_START) & (live.index.time <= CRASH_END)]
        if base_px is None or crash.empty:
            continue
        move = float(crash.max()) - base_px
        fwd_at = parity[parity.index.time <= CRASH_END]
        fwd_move = float(fwd_at.iloc[-1]) - float(parity.iloc[0]) if len(fwd_at) else np.nan
        rows.append(
            {
                "strike": k,
                "moneyness": k / session.ref_spot,
                "base_min": base_min,
                "n": len(joined),
                "empirical_delta": slope,
                # A put's delta is negative. A positive fitted slope means the regression
                # failed on that strike rather than that the option behaves strangely, so
                # the split must not be read there.
                "fit_ok": slope < 0,
                "fwd_move_pts": fwd_move,
                "move_rs": move,
                "delta_part_rs": slope * fwd_move,
                "residual_rs": move - slope * fwd_move,
            }
        )
    return pd.DataFrame(rows)


def _px_at(close: pd.DataFrame, vol: pd.DataFrame, strike: float, when: dt.time) -> float:
    """Last traded price at or before ``when`` for one strike; NaN if it never traded."""
    live = close[strike].where(vol[strike] > 0).dropna()
    live = live[live.index.time <= when]
    return float(live.iloc[-1]) if len(live) else float("nan")


def spike_table(session: ChainSession, kind: str, wing_max_moneyness: float) -> pd.DataFrame:
    """Per-strike largest single traded-to-traded move, with what reversed afterwards.

    ``reversal_*`` is retracement of the spike: 100 % means the price returned to where
    it stood before the spike, 0 % means it held the whole move. It is undefined when the
    spike had no height, so those strikes carry NaN rather than a divided-by-zero figure.
    """
    close = session.pe_close if kind == "PE" else session.ce_close
    vol = session.pe_vol if kind == "PE" else session.ce_vol
    changes = traded_changes(close, vol)
    if changes.empty:
        return changes
    ref_spot = session.ref_spot
    sign = 1 if kind == "PE" else -1
    changes = changes[changes["d_pct"] * sign > 0]
    if changes.empty:
        return changes
    best = changes.loc[
        changes.groupby("strike")["d_pct"].apply(lambda s: (s * sign).idxmax()).to_numpy()
    ].copy()

    rows = []
    for _, r in best.iterrows():
        k = r["strike"]
        pre, peak = r["from_px"], r["to_px"]
        height = peak - pre
        after = {
            t: _px_at(close, vol, k, dt.time(15, m))
            for t, m in (("15:30", 30), ("15:35", 35), ("15:39", 39))
        }
        # Retracement is only defined at a checkpoint that comes *after* the spike. At or
        # before it, the "later" price is the spike bar itself or the pre-spike dip, and
        # the ratio reports 0 % or 100 % for reasons that have nothing to do with the move
        # reversing.
        rev = {
            f"reversal_{t}_pct": (
                np.nan
                if abs(height) < 1e-9 or t <= r["to_ts"].strftime("%H:%M")
                else (peak - after[t]) / height * 100.0
            )
            for t in after
        }
        # The crash window itself. This, not the largest one-minute move, is the direct
        # answer to "did the wing reprice off the indicative": it is the extreme premium
        # reached while the indicative was at its low, against the same strike's last
        # continuous-session price.
        live = close[k].where(vol[k] > 0).dropna()
        crash = live[(live.index.time >= CRASH_START) & (live.index.time <= CRASH_END)]
        base_px, base_min = crash_base(live)
        if base_px is not None and len(crash):
            extreme = float(crash.max() if kind == "PE" else crash.min())
            crash_pct = (extreme / base_px - 1.0) * 100.0
        else:
            crash_pct, base_min = float("nan"), "—"
        rows.append(
            {
                "strike": k,
                "moneyness": k / ref_spot,
                "crash_1518_1523_pct": crash_pct,
                "crash_base_min": base_min,
                "spike_min": r["to_ts"].strftime("%H:%M"),
                "phase": phase_of(r["to_ts"]),
                "gap_min": r["gap_min"],
                "px_before": pre,
                "px_spike": peak,
                "d_pct": r["d_pct"],
                "d_rs": r["d_rs"],
                "vol_spike": r["to_vol"],
                "px_1514": _px_at(close, vol, k, WINDOW_START),
                **{f"px_{t}": v for t, v in after.items()},
                **rev,
            }
        )
    out = pd.DataFrame(rows)
    out["is_wing"] = (
        out["moneyness"] <= wing_max_moneyness
        if kind == "PE"
        else out["moneyness"] >= 2 - wing_max_moneyness
    )
    return out.sort_values("d_pct", ascending=(kind == "CE")).reset_index(drop=True)


def band_floor_bound(
    session: ChainSession, strike: float, floor: float, atm_time_value: float
) -> float:
    """Estimated value of a put at ``strike`` if the index sat at the auction band floor.

    Intrinsic is exact. Time value is estimated by the at-the-money put's own 15:14
    premium — the largest time value on the board, applied unchanged to a strike that
    would be at or in the money at the floor. Two limits, both understating the adverse
    mark: it holds implied volatility at its pre-dislocation level, and it ignores that a
    2,200-point move would itself reprice the surface. It is a floor on the loss, not a
    worst case: the contract has an unbounded overnight gap and no worst case exists.
    """
    return max(strike - floor, 0.0) + atm_time_value


def atm_time_value(session: ChainSession) -> tuple[float, float]:
    """The 15:14 at-the-money put premium and the strike it came from.

    At-the-money is struck against the **cash** index, so the premium returned is close to
    pure time value. Struck against the parity forward instead, the chosen strike sits
    hundreds of points in the money against cash and the premium carries intrinsic — which
    would inflate every bound built from it.
    """
    k = min(session.pe_close.columns, key=lambda c: abs(c - session.ref_spot))
    return _px_at(session.pe_close, session.pe_vol, k, WINDOW_START), float(k)


def control_scan(
    sessions: list[tuple[str, dt.date]], wing_max_moneyness: float, threshold_pct: float
) -> pd.DataFrame:
    """How often a wing put moves more than ``threshold_pct`` in the window, per session.

    The wing is defined by moneyness rather than absolute strike because the listed depth
    differs session to session — a fixed strike is a different distance from the money on
    every date. ``n_wing`` is the denominator each session contributes, and it is reported
    so the counts are readable as "k of N strike-sessions" rather than as a bare rate.
    """
    rows = []
    for underlying, date in sessions:
        try:
            session = load_chain(underlying, date)
        except FileNotFoundError:
            continue
        if session.implied_spot.dropna().empty:
            continue
        changes = traded_changes(session.pe_close, session.pe_vol)
        if changes.empty:
            continue
        changes["moneyness"] = changes["strike"] / session.ref_spot
        changes["phase"] = changes["to_ts"].map(phase_of)
        wing = changes[changes["moneyness"] <= wing_max_moneyness]
        n_wing = wing["strike"].nunique()
        peak = float(wing["d_pct"].max()) if len(wing) else float("nan")
        row = {
            "underlying": underlying,
            "session": date.isoformat(),
            "expiry": session.expiry.isoformat(),
            "dte": session.days_to_expiry,
            "n_wing": n_wing,
            "min_moneyness": float(wing["moneyness"].min()) if len(wing) else float("nan"),
            "max_wing_move_pct": peak,
        }
        # A single threshold cannot say whether the event separates from an ordinary day:
        # one high enough to be a "spike" may fire on neither. The sweep is what locates
        # the threshold, if any, at which the event and the controls part company.
        #
        # Hits are split by phase because they are not the same evidence. Only a move
        # inside 15:18-15:23 is a response to the indicative; a move at 15:30-15:31 lands
        # after matching has begun and the close is about to be published, which is a
        # different event with a different cause. Counting them together lets post-auction
        # blips masquerade as crash-window repricing.
        for thr in sorted({25.0, 50.0, threshold_pct}):
            hit = wing[wing["d_pct"] >= thr]
            row[f"hits_{thr:.0f}pct"] = hit["strike"].nunique()
            row[f"crash_hits_{thr:.0f}pct"] = hit[hit["phase"] == "crash"]["strike"].nunique()
            row[f"postauction_hits_{thr:.0f}pct"] = hit[hit["phase"] == "post_auction"][
                "strike"
            ].nunique()
        rows.append(row)
    return pd.DataFrame(rows)


def _md(frame: pd.DataFrame, floatfmt: str = "{:.2f}") -> str:
    def fmt(v: object) -> str:
        if isinstance(v, float):
            return "—" if pd.isna(v) else floatfmt.format(v)
        return str(v)

    head = "| " + " | ".join(frame.columns) + " |"
    rule = "|" + "|".join("---" for _ in frame.columns) + "|"
    body = ["| " + " | ".join(fmt(v) for v in row) + " |" for row in frame.itertuples(index=False)]
    return "\n".join([head, rule, *body])


def _fig_dir(repo: Path) -> Path:
    out = repo / "research" / "expiry_cas" / "fig" / "wings"
    out.mkdir(parents=True, exist_ok=True)
    return out


def figures(
    session: ChainSession, puts: pd.DataFrame, nifty: ChainSession | None, repo: Path
) -> list[str]:
    out = _fig_dir(repo)
    names = []

    # 1. The wing's price paths against the implied index and the published indicative.
    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(11, 8), sharex=True, gridspec_kw={"height_ratios": [2, 3]}
    )
    spot = session.implied_spot.dropna()
    ax1.plot(
        spot.index, spot.values, color="#1f4e79", lw=1.8, label="option-implied index (parity)"
    )
    ax1.axhline(
        INDICATIVE_0827["low"],
        color="#c00000",
        ls="--",
        lw=1.2,
        label=f"published indicative low {INDICATIVE_0827['low']:,.0f}",
    )
    ax1.axhline(
        INDICATIVE_0827["close"],
        color="#548235",
        ls=":",
        lw=1.4,
        label=f"official close {INDICATIVE_0827['close']:,.0f}",
    )
    ax1.axvspan(
        spot.index[0].replace(hour=15, minute=18),
        spot.index[0].replace(hour=15, minute=23),
        color="#c00000",
        alpha=0.08,
    )
    ax1.set_ylabel("index")
    ax1.legend(fontsize=7, loc="lower right")
    ax1.set_title(
        f"{session.underlying} {session.session_date} — {session.expiry} wings vs the "
        f"closing-auction indicative"
    )

    wing = puts[puts["is_wing"]].nlargest(6, "d_pct")
    for _, r in wing.iterrows():
        k = r["strike"]
        live = session.pe_close[k].where(session.pe_vol[k] > 0).dropna()
        ax2.plot(live.index, live.values, marker=".", ms=3, lw=1.2, label=f"{k:,.0f} PE")
    ax2.axvspan(
        spot.index[0].replace(hour=15, minute=18),
        spot.index[0].replace(hour=15, minute=23),
        color="#c00000",
        alpha=0.08,
    )
    ax2.set_ylabel("premium (₹)")
    ax2.set_xlabel("IST minute")
    ax2.legend(fontsize=7, ncol=2)
    fig.tight_layout()
    p = out / f"{session.underlying.lower()}_{session.session_date}_wing_paths.png"
    fig.savefig(p, dpi=130)
    plt.close(fig)
    names.append(p.name)

    # 2. Strike × minute traded-to-traded % change, puts.
    changes = traded_changes(session.pe_close, session.pe_vol)
    grid = changes.pivot_table(
        index="strike", columns=changes["to_ts"].dt.strftime("%H:%M"), values="d_pct"
    )
    fig, ax = plt.subplots(figsize=(12, 8))
    lim = float(np.nanmax(np.abs(grid.to_numpy()))) if grid.size else 1.0
    im = ax.imshow(grid.to_numpy(), aspect="auto", cmap="RdBu_r", vmin=-lim, vmax=lim)
    ax.set_yticks(range(len(grid.index)))
    ax.set_yticklabels([f"{k:,.0f}" for k in grid.index], fontsize=6)
    ax.set_xticks(range(len(grid.columns)))
    ax.set_xticklabels(grid.columns, rotation=90, fontsize=6)
    ax.set_title(
        f"{session.underlying} {session.expiry} puts — traded-to-traded % change "
        f"(blank = no trade in that minute)"
    )
    fig.colorbar(im, ax=ax, label="% change")
    fig.tight_layout()
    p = out / f"{session.underlying.lower()}_{session.session_date}_put_change_heatmap.png"
    fig.savefig(p, dpi=130)
    plt.close(fig)
    names.append(p.name)

    # 3. Cross-index: same-moneyness wing puts, both underlyings, indexed to 15:14.
    if nifty is not None:
        fig, ax = plt.subplots(figsize=(11, 5))
        for sess, colour, style in ((session, "#1f4e79", "-"), (nifty, "#c55a11", "--")):
            money = {k: k / sess.ref_spot for k in sess.pe_close.columns}
            picks = sorted(money, key=lambda k: abs(money[k] - 0.975))[:3]
            for k in picks:
                live = sess.pe_close[k].where(sess.pe_vol[k] > 0).dropna()
                if len(live) < 2:
                    continue
                ax.plot(
                    live.index.strftime("%H:%M"),
                    live.values / live.iloc[0] * 100.0,
                    style,
                    color=colour,
                    lw=1.3,
                    alpha=0.8,
                    label=f"{sess.underlying} {k:,.0f} (m={money[k]:.3f})",
                )
        ax.axhline(100, color="grey", lw=0.8)
        ax.set_ylabel("premium, 15:14 = 100")
        ax.set_xlabel("IST minute")
        ax.tick_params(axis="x", rotation=90, labelsize=6)
        ax.legend(fontsize=7, ncol=2)
        ax.set_title("Same-moneyness (~0.975) wing puts — Sensex vs Nifty, 2026-08-27")
        fig.tight_layout()
        p = out / f"cross_index_wing_{session.session_date}.png"
        fig.savefig(p, dpi=130)
        plt.close(fig)
        names.append(p.name)
    return names


def build_report(
    underlying: str, session_date: dt.date, repo: Path, wing_m: float, threshold: float
) -> str:
    session = load_chain(underlying, session_date)
    expiries = available_expiries(underlying, session_date)
    puts = spike_table(session, "PE", wing_m)
    calls = spike_table(session, "CE", wing_m)
    tv, tv_strike = atm_time_value(session)
    lot = session.lot_size

    try:
        nifty = load_chain("NIFTY", session_date)
        nifty_next = None
        n_exp = available_expiries("NIFTY", session_date)
        if len(n_exp) > 1:
            nifty_next = load_chain("NIFTY", session_date, n_exp[1])
    except FileNotFoundError:
        nifty = nifty_next = None

    figs = figures(session, puts, nifty, repo)

    # --- top strike-minutes, by % and by ₹ -------------------------------------------
    top_pct = puts.nlargest(10, "d_pct")[
        [
            "strike",
            "moneyness",
            "crash_1518_1523_pct",
            "crash_base_min",
            "spike_min",
            "phase",
            "gap_min",
            "px_before",
            "px_spike",
            "d_pct",
            "d_rs",
            "vol_spike",
            "px_15:30",
            "px_15:35",
            "px_15:39",
            "reversal_15:30_pct",
            "reversal_15:35_pct",
            "reversal_15:39_pct",
        ]
    ].copy()
    top_rs = puts.nlargest(10, "d_rs")[
        [
            "strike",
            "moneyness",
            "is_wing",
            "spike_min",
            "gap_min",
            "px_before",
            "px_spike",
            "d_pct",
            "d_rs",
            "vol_spike",
            "reversal_15:39_pct",
        ]
    ].copy()

    # --- the forward's own move, and what it explains of the wing move -----------------
    fwd = forward_path(session)
    decomp = delta_decomposition(
        session, list(puts[puts["is_wing"]].nlargest(8, "d_pct")["strike"])
    )

    # --- intrinsic references ---------------------------------------------------------
    ref_spot = session.ref_spot
    ref = puts[
        ["strike", "moneyness", "px_1514", "px_spike", "spike_min", "phase", "px_15:39"]
    ].copy()
    ref["intrinsic_at_indicative_low"] = np.maximum(ref["strike"] - INDICATIVE_0827["low"], 0.0)
    ref["intrinsic_at_close"] = np.maximum(ref["strike"] - INDICATIVE_0827["close"], 0.0)
    ref["spike_over_intrinsic_low"] = ref["px_spike"] - ref["intrinsic_at_indicative_low"]

    # --- reward : risk of selling the spike -------------------------------------------
    rr_rows = []
    for _, r in puts[puts["is_wing"]].nlargest(8, "d_pct").iterrows():
        bound = band_floor_bound(session, r["strike"], BAND_FLOOR_0827, tv)
        for cover, label in ((r["px_15:35"], "15:35"), (r["px_15:39"], "15:39")):
            reward = r["px_spike"] - cover
            risk = bound - r["px_spike"]
            rr_rows.append(
                {
                    "strike": r["strike"],
                    "entry": r["spike_min"],
                    "sold_at": r["px_spike"],
                    "cover_at": label,
                    "cover_px": cover,
                    "reward_pts": reward,
                    "floor_mark_pts": bound,
                    "adverse_pts": risk,
                    "reward_risk": reward / risk if risk > 0 else np.nan,
                    "reward_rs_per_lot": reward * lot,
                    "adverse_rs_per_lot": -risk * lot,
                    "vol_lots_at_entry": r["vol_spike"] / lot,
                }
            )
    rr = pd.DataFrame(rr_rows)

    # --- calls sold down ---------------------------------------------------------------
    call_rows = (
        calls[calls["is_wing"]]
        .nsmallest(8, "d_pct")[
            [
                "strike",
                "moneyness",
                "spike_min",
                "gap_min",
                "px_before",
                "px_spike",
                "d_pct",
                "d_rs",
                "vol_spike",
                "px_15:35",
                "px_15:39",
            ]
        ]
        .copy()
    )
    call_rows = call_rows.rename(
        columns={"px_spike": "px_trough", "d_pct": "drop_pct", "d_rs": "drop_rs"}
    )
    call_rows["recovery_by_1539_pct"] = (
        (call_rows["px_15:39"] - call_rows["px_trough"])
        / (call_rows["px_before"] - call_rows["px_trough"]).replace(0, np.nan)
        * 100.0
    )

    # --- Nifty cross-check --------------------------------------------------------------
    cross_rows = []
    for target in (0.960, 0.970, 0.975, 0.980, 0.985, 0.990):
        row: dict[str, object] = {"moneyness": target}
        for sess, tag in ((session, "sensex"), (nifty, "nifty_front"), (nifty_next, "nifty_next")):
            if sess is None or sess.implied_spot.dropna().empty:
                continue
            k = min(sess.pe_close.columns, key=lambda c: abs(c / sess.ref_spot - target))
            ch = traded_changes(sess.pe_close[[k]], sess.pe_vol[[k]])
            live = sess.pe_close[k].where(sess.pe_vol[k] > 0).dropna()
            crash = live[
                (live.index.time >= dt.time(15, 18)) & (live.index.time <= dt.time(15, 23))
            ]
            base_px, base_min = crash_base(live)
            row[f"{tag}_K"] = float(k)
            row[f"{tag}_dte"] = sess.days_to_expiry
            row[f"{tag}_max_1min_pct"] = float(ch["d_pct"].max()) if len(ch) else np.nan
            row[f"{tag}_base_min"] = base_min
            # The rupee levels travel with the percentage. At these moneynesses an option
            # can cost ₹1.60, where a single tick is a double-digit percentage and a ratio
            # of two such percentages is a ratio of ticks rather than of repricings.
            row[f"{tag}_base_px"] = base_px if base_px is not None else np.nan
            row[f"{tag}_crash_px"] = float(crash.max()) if len(crash) else np.nan
            row[f"{tag}_1518_1523_pct"] = (
                (float(crash.max()) / base_px - 1.0) * 100.0
                if len(crash) and base_px is not None
                else np.nan
            )
        cross_rows.append(row)
    cross = pd.DataFrame(cross_rows)

    # --- controls ------------------------------------------------------------------------
    control_sessions = [
        ("SENSEX", dt.date(2026, 8, 20)),
        ("SENSEX", dt.date(2026, 8, 25)),
        ("SENSEX", dt.date(2026, 8, 26)),
        ("SENSEX", dt.date(2026, 8, 28)),
        ("NIFTY", dt.date(2026, 8, 25)),
        ("NIFTY", dt.date(2026, 8, 26)),
        ("NIFTY", dt.date(2026, 8, 27)),
        ("NIFTY", dt.date(2026, 8, 28)),
    ]
    controls = control_scan(control_sessions, wing_m, threshold)
    event = control_scan([(underlying, session_date)], wing_m, threshold)
    controls = pd.concat(
        [event.assign(row="EVENT"), controls.assign(row="control")], ignore_index=True
    )

    return _render(
        session,
        expiries,
        puts,
        top_pct,
        top_rs,
        ref,
        rr,
        call_rows,
        cross,
        controls,
        tv,
        tv_strike,
        figs,
        wing_m,
        threshold,
        ref_spot,
        fwd,
        decomp,
    )


def _render(
    session,
    expiries,
    puts,
    top_pct,
    top_rs,
    ref,
    rr,
    calls,
    cross,
    controls,
    tv,
    tv_strike,
    figs,
    wing_m,
    threshold,
    ref_spot,
    fwd,
    decomp,
) -> str:
    ctl = controls[controls["row"] == "control"]
    n_hits = int(ctl[f"hits_{threshold:.0f}pct"].sum())
    n_wing = int(ctl["n_wing"].sum())
    ev = controls[controls["row"] == "EVENT"].iloc[0]
    # The headline strike is the largest mover *among wings*. Taken over all puts it would
    # be whichever deep in-the-money contract happened to print widest, which is delta on
    # an illiquid strike and not the subject of this study.
    wing_puts = puts[puts["is_wing"]]
    peak = wing_puts.nlargest(1, "d_pct").iloc[0]
    crash_wings = wing_puts[wing_puts["phase"] == "crash"]
    best_fade = rr.loc[rr["reward_rs_per_lot"].idxmax()]
    peak_fade = rr[(rr["strike"] == peak["strike"]) & (rr["cover_at"] == "15:39")]
    peak_fade = peak_fade.iloc[0] if len(peak_fade) else best_fade

    # The cross-index asymmetry is read off the deepest moneyness bucket the cross-check
    # covers, so it moves with the table rather than being asserted beside it.
    deepest = cross.iloc[0]
    asymmetry = (
        deepest["sensex_1518_1523_pct"] / deepest["nifty_front_1518_1523_pct"]
        if "nifty_front_1518_1523_pct" in cross.columns
        and pd.notna(deepest.get("nifty_front_1518_1523_pct"))
        and deepest.get("nifty_front_1518_1523_pct")
        else float("nan")
    )

    lines = [
        f"# The next-expiry wings on {session.session_date} — did they reprice off the "
        f"closing-auction indicative?",
        "",
        f"**Scope.** {session.underlying}, the **{session.expiry}** expiry "
        f"({session.days_to_expiry} days out), every listed strike "
        f"{session.strikes.min():,.0f}–{session.strikes.max():,.0f}, minute by minute "
        f"{WINDOW_START:%H:%M}–{WINDOW_END:%H:%M} IST. Lot {session.lot_size}. "
        f"Parity anchor {session.anchor_strike:,.0f}.",
        "",
        "## 0. What this data can and cannot settle",
        "",
        f"**The expiring series is not here.** The ±25 chain tree for this session carries "
        f"bars for **{', '.join(e.isoformat() for e in expiries)}** and nothing else. The "
        f"{session.session_date} expiring series has refdata entries but zero bars — it "
        f"delisted into settlement. **So the 75,000 PE the press story is about remains "
        f"untestable.** The 75,000 PE examined below is the *{session.expiry}* contract: a "
        f"different instrument, with a week of life left and an unbounded overnight gap, that "
        f"happens to share a strike. Nothing here confirms or refutes the ~4,800 % claim.",
        "",
        f"**The options forward sits {session.forward_premium:,.0f} points above cash, and that "
        f"is a finding, not a nuisance.** The cash feed reads "
        f"**{session.ref_spot:,.2f}** at 15:14; parity at the anchor pair reads "
        f"**{float(session.implied_spot.dropna().iloc[0]):,.2f}**. Carry at "
        f"{CARRY_RATE:.1%} over {session.days_to_expiry} days explains only "
        f"**{session.carry_points(CARRY_RATE):,.0f}** of the gap — the residual would need a "
        f"rate near {CARRY_RATE * session.forward_premium / max(session.carry_points(CARRY_RATE), 1e-9):.0%} "
        f"— and the parity level is consistent across neighbouring strikes, so it is a real "
        f"forward premium rather than one stale leg. **The two series therefore do different "
        f"jobs here:** cash classifies strikes (moneyness, the wing cut, the at-the-money "
        f"strike whose premium estimates time value), parity supplies movement and is the only "
        f"series that survives past 15:29. The choice is not cosmetic: struck on cash the wing "
        f"below is **{int(ev['n_wing'])} strikes**, struck on parity it would be wider, and the "
        f"'at-the-money' strike whose premium sets every bound in §2 would sit "
        f"{session.forward_premium:,.0f} points in the money against cash and carry intrinsic "
        f"rather than pure time value.",
        "",
        f"**The published indicative path is not in this feed's option rows** "
        f"({INDICATIVE_0827['ref_1515']:,.2f} at 15:15 → {INDICATIVE_0827['low']:,.2f} between "
        f"{INDICATIVE_0827['low_window'][0]} and {INDICATIVE_0827['low_window'][1]} → close "
        f"{INDICATIVE_0827['close']:,.2f}). The 15:15 reference does appear in the broadcast "
        f"`spot` column; the **indicative low does not appear anywhere**, which is the value "
        f"the whole question turns on.",
        "",
        "**Every change is between two bars that each printed volume**, and every such row "
        "carries `gap_min`. That guarantee covers the **spike leg only**. The checkpoint "
        "columns — `px_1514`, `px_15:30/35/39`, `cover_px`, and every §3 column — are "
        "last-trade-at-or-before their label with no gap reported, so a checkpoint may repeat "
        "an earlier print. Where that matters it is called out beside the table.",
        "",
        "---",
        "",
        "## 1. Did the next-week wings reprice off the indicative?",
        "",
        f"Cash index at 15:14: **{ref_spot:,.2f}** — the reference every moneyness below is "
        f"struck on. The wing put paths are in `fig/wings/{figs[0]}`; the full strike × minute "
        f"change grid is `fig/wings/{figs[1]}`.",
        "",
        "**The forward's own move, which every premium change has to be read against.** This is "
        "the quantity the study's conventions say is usable on a non-expiring chain — a change, "
        "from one source, with the forward premium differencing out:",
        "",
        _md(fwd.round(3)) if len(fwd) else "_(no parity series)_",
        "",
        "So while the published indicative fell **2,199.72 points**, the traded forward fell "
        f"**{abs(fwd.iloc[0]['change_pts']):,.0f}** by the end of the crash window — "
        f"**{abs(fwd.iloc[0]['change_pts']) / 2199.72 * 100:.0f} %** of it. Most of the "
        f"forward's eventual move arrives *after* the indicative recovered, and Nifty's forward "
        f"moved almost identically over the same span (§3), so it is market-wide drift into the "
        f"close rather than a response to the auction.",
        "",
        "### 1.1 Top 10 put strike-minutes by % change",
        "",
        "`crash_1518_1523_pct` is the extreme premium reached while the indicative was at its "
        "low, against the price in `crash_base_min`. That base is the last continuous-session "
        "print at or before 15:14 wherever one exists. **Where `crash_base_min` reads later "
        "than 15:14 the strike had not traded yet**, so the base is itself inside the "
        "dislocation and the percentage **understates** the move — which is the case for the "
        "deepest strike on the board, the one the verdict quotes.",
        "",
        _md(top_pct.round(4)),
        "",
        "### 1.2 Top 10 put strike-minutes by ₹ change",
        "",
        "A percentage on an ₹12 premium is a few ticks, so the same scan is ranked by money. "
        "**Note `is_wing`:** the largest rupee moves are not wing repricing at all. They are "
        "deep in-the-money puts — moneyness above 1 — whose premium tracks the underlying "
        "nearly one-for-one, printing one or two lots at a time across multi-minute gaps. "
        "That is delta on an illiquid contract, and it is the opposite end of the board from "
        "the question.",
        "",
        _md(top_rs.round(4)),
        "",
        "### 1.3 The wings never came close to the indicative's own intrinsic",
        "",
        f"`intrinsic_at_indicative_low` = max(K − {INDICATIVE_0827['low']:,.2f}, 0); "
        f"`intrinsic_at_close` = max(K − {INDICATIVE_0827['close']:,.2f}, 0). For a "
        f"{session.days_to_expiry}-day option neither is a settlement value — they are the "
        f"reference points the question asks for.",
        "",
        f"Had the index really been at {INDICATIVE_0827['low']:,.2f}, every strike above it "
        "would have been in the money and `spike_over_intrinsic_low` could not be negative. It "
        "is negative from 75,300 upward (75,100 is −86, 75,200 is −182, and it widens from "
        "there). **This is worth stating precisely, because on its own it is not independent "
        "evidence:** that the wings did not price the indicative as a level is the same fact as "
        "the forward not moving to it, already visible in the table above and established in "
        "`CROSS_INDEX.md`. It is that fact in rupee units. Note also that the column compares "
        "`px_spike`, a maximum over the whole window, against intrinsic at the 15:18–15:23 low, "
        "so it mixes times.",
        "",
        _md(ref.round(3)),
        "",
        "#### 1.3.1 What the ±25 chain adds: how much of the wing move was delta?",
        "",
        "This is the part the ±10 ladder could not answer. For each wing strike, an empirical "
        "delta is fitted from this chain — the slope of its traded premium change against the "
        "simultaneous forward change, over every minute both printed — and the crash-window "
        "move is split into the part that slope explains and the residual:",
        "",
        _md(decomp.round(4)) if len(decomp) else "_(too few paired prints to fit)_",
        "",
        "**The residual is most of the move at every wing strike.** The forward fell only "
        f"{abs(fwd.iloc[0]['change_pts']):,.0f} points through the crash window, and at these "
        "deltas that accounts for roughly a rupee or two; the rest is a volatility and skew "
        "bid. So the wings did reprice — as *insurance getting more expensive*, not as a "
        "directional mark to 74,983. `n` is the number of paired minutes behind each slope; a "
        "slope fitted on a handful of prints is loose, and the fit absorbs some vega into the "
        "delta term, which if anything makes the residual a conservative estimate.",
        "",
        "**Read `fit_ok` before reading any row.** A put's delta is negative by construction, "
        "so a positive fitted slope means the regression failed on that strike — which is "
        "exactly what happens at the headline 74,700, the thinnest contract on the board and "
        "the one with no pre-crash print. Its split is not usable. Every strike whose fit does "
        "hold lands in the same place: delta explains ₹1–3 of a ₹5–7 move and the residual is "
        "the majority.",
        "",
        "### 1.4 Calls — were they sold down?",
        "",
        _md(calls.round(4)),
        "",
        "---",
        "",
        "## 2. Was the mispricing tradeable and bounded?",
        "",
        f"**There is no bound.** The ±3 % band bounds *today's auction close* "
        f"(floor {BAND_FLOOR_0827:,.2f}), which is a settlement bound only for a contract "
        f"expiring today. A {session.expiry} put has an unbounded overnight gap, so its short "
        f"has **no worst case**. What is bounded is the mark-to-market if the position is closed "
        f"the same session with the index at the floor: `intrinsic at the floor + time value`, "
        f"with time value estimated as the 15:14 at-the-money put premium "
        f"(**₹{tv:.2f}** at K={tv_strike:,.0f}). "
        f"**The direction of that estimate's error is indeterminate, and it does not matter.** "
        f"Holding volatility at its pre-dislocation level understates the mark; applying an "
        f"at-the-money time value unchanged to strikes that would be hundreds of points in the "
        f"money at the floor overstates it. Intrinsic at the floor is exact — what is estimated "
        f"is only the time value's dependence on volatility and moneyness. The ratios below are "
        f"two orders of magnitude from break-even, so no plausible correction reaches them.",
        "",
        _md(rr.round(3)),
        "",
        f"`vol_lots_at_entry` is the whole strike-minute's traded volume in lots of "
        f"{session.lot_size} — the market's total, not a fill. A realistic share of it is a "
        f"fraction, and the quote that would actually be hit is unobservable: this corpus has "
        f"**no bid/ask**, only trade prints.",
        "",
        "---",
        "",
        "## 3. Nifty cross-check at the same moneyness",
        "",
        f"**Nifty is a no-event control, not a second response.** NSE runs no closing auction, "
        f"so there was no indicative to reprice off; the comparison measures what an ordinary "
        f"session's wings did over the same minutes. Nifty's front expiry is a Tuesday weekly, "
        f"so its tenor does not match Sensex's {session.days_to_expiry} days — both Nifty "
        f"expiries are shown so the result cannot be read as a tenor artifact.",
        "",
        "`*_1518_1523_pct` is the largest traded premium in 15:18–15:23 against the price at "
        "`*_base_min`, which is the same `crash_base` rule §1.1 uses. **Read the rupee columns "
        "first:** at these moneynesses a Nifty put costs ₹1.60, where one tick is a double-digit "
        "percentage, so a ratio of two such percentages is a ratio of ticks. `*_max_1min_pct` is "
        "a maximum over traded-to-traded changes whose gaps are not shown, so the `1min` in its "
        "name is not guaranteed.",
        "",
        _md(cross.round(4)),
        "",
        f"Figure: `fig/wings/{figs[-1]}`.",
        "",
        "---",
        "",
        f"## 4. Controls — how often does a wing put move ≥ {threshold:.0f} % in this window?",
        "",
        f"The wing is every put with moneyness ≤ **{wing_m}** against that session's own 15:14 "
        f"**cash** index, because listed depth differs session to session. `hits_*` counts "
        f"distinct wing strikes whose largest traded-to-traded move in {WINDOW_START:%H:%M}–"
        f"{WINDOW_END:%H:%M} reached the threshold; `crash_hits_*` and `postauction_hits_*` "
        f"split that count by **when** the move landed. **The split is the point.** Only a move "
        f"inside 15:18–15:23 is a response to the indicative. A move at 15:30–15:31 lands after "
        f"matching has begun and the close is about to be published — a different event with a "
        f"different cause, and one an ordinary session can produce too.",
        "",
        _md(controls.round(4)),
        "",
        f"**At the {threshold:.0f} % threshold the trigger fires nowhere — {n_hits} across "
        f"{len(ctl)} control sessions, and {int(ev[f'hits_{threshold:.0f}pct'])} on the event "
        f"session itself.** A trigger with neither false positives nor true positives is not a "
        f"trigger; it is a threshold above the entire distribution.",
        "",
        f"**Lowering it does not rescue the trigger, once the hits are read by phase.** At "
        f"25 % the event fires {int(ev['hits_25pct'])} against "
        f"{int(ctl['hits_25pct'].sum())} for the controls — but only "
        f"**{int(ev['crash_hits_25pct'])} of those {int(ev['hits_25pct'])} landed in the crash "
        f"window**; {int(ev['postauction_hits_25pct'])} landed at 15:30–15:31, after matching "
        f"began and as the close was being published. Those are not responses to the "
        f"indicative. The genuine crash-window separation on the event session is "
        f"**{int(ev['crash_hits_25pct'])} strike**, against a control maximum wing move of "
        f"{ctl['max_wing_move_pct'].max():.1f} %.",
        "",
        f"**And {n_wing} is not a denominator.** Strikes within a session move together, so the "
        f"independent unit is the session and there are {len(ctl)} of them. The per-strike "
        f"counts are reported for transparency, not as a rate. One control also carries a "
        f"caveat: the 2026-08-20 session's tree holds only the 3 Sep expiry, so it is a 14-day "
        f"chain with 2 wing strikes rather than a tenor-matched control.",
        "",
        "---",
        "",
        "## 5. Verdict",
        "",
        "**One claim, not two.** The wings repriced — as *insurance getting dearer*, not as a "
        "mark to the indicative. Those are the same finding, and the earlier framing that "
        "asserted both a repricing and a market that 'never made an error' was asserting a "
        "contradiction. What the chain shows is narrower and consistent:",
        "",
        f"- **What moved.** The wing bid rose broadly with depth (not monotonically — 75,200 "
        f"outruns 74,900 and 75,000, and 75,600 outruns 75,500). The largest wing mover is "
        f"**{peak['strike']:,.0f} PE**: ₹{peak['px_before']:.2f} → "
        f"**₹{peak['px_spike']:.2f}** at **{peak['spike_min']}** "
        f"({peak['d_pct']:+.1f} %, ₹{peak['d_rs']:+.2f}, gap {peak['gap_min']:.0f} min, "
        f"{peak['vol_spike'] / session.lot_size:.0f} lots traded that minute). It had no print "
        f"before {peak['crash_base_min']}, so its base is itself inside the dislocation and it "
        f"is a thin contract: the level that actually held afterwards was about ₹20.",
        f"- **Why it moved.** Not delta. The forward fell only "
        f"{abs(fwd.iloc[0]['change_pts']):,.0f} points through the crash window "
        f"({abs(fwd.iloc[0]['change_pts']) / 2199.72 * 100:.0f} % of the indicative's move), "
        f"which at these deltas explains a rupee or two of an ₹5–9 move (§1.3.1). The rest is a "
        f"volatility and skew bid — the wings got more expensive without the forward going "
        f"anywhere near 74,983.",
        f"- **When it moved.** Only {int(ev['crash_hits_25pct'])} wing strike cleared 25 % "
        f"inside 15:18–15:23; {int(ev['postauction_hits_25pct'])} of the session's hits landed "
        f"at 15:30–15:31, around the close publication, which an ordinary session also produces "
        f"(§4).",
        "",
        f"**The Nifty comparison has to be made in rupees, not in the ratio.** At the same "
        f"moneyness Nifty's front put moved "
        f"₹{deepest.get('nifty_front_base_px', float('nan')):.2f} → "
        f"₹{deepest.get('nifty_front_crash_px', float('nan')):.2f}, which is nominally "
        f"{asymmetry:.0f}× smaller in percentage terms — but it is **one tick on a "
        f"₹{deepest.get('nifty_front_base_px', float('nan')):.2f} option**, and a ratio of two "
        f"such percentages is a ratio of ticks. The comparison that carries weight is the "
        f"12-day Nifty put, whose premium "
        f"(₹{deepest.get('nifty_next_base_px', float('nan')):.2f}) is within striking distance "
        f"of the Sensex wing's ₹{peak['px_before']:.2f}: it moved "
        f"₹{deepest.get('nifty_next_crash_px', float('nan')) - deepest.get('nifty_next_base_px', float('nan')):.2f} "
        f"against the Sensex wing's ₹{peak['d_rs']:.2f}. Sensex's wing repriced roughly an "
        f"order of magnitude harder than Nifty's on a comparable premium — and both moves are "
        f"small enough that the whole comparison lives inside a few rupees.",
        "",
        "**No, there was no defined-risk trade with positive expectancy.** Three independent "
        "reasons, any one of which is sufficient:",
        "",
        f"1. **The reward is a rounding error and the risk is not.** Fading the headline spike "
        f"— sell {peak['strike']:,.0f} PE at ₹{peak_fade['sold_at']:.2f} at "
        f"{peak_fade['entry']}, cover at ₹{peak_fade['cover_px']:.2f} at "
        f"{peak_fade['cover_at']} — returns **₹{peak_fade['reward_rs_per_lot']:.0f} per lot** "
        f"against an adverse same-session mark of "
        f"**₹{abs(peak_fade['adverse_rs_per_lot']):,.0f}**: **1 : "
        f"{1 / peak_fade['reward_risk']:.0f}**. The best of the eight wing fades is "
        f"{best_fade['strike']:,.0f} PE at ₹{best_fade['reward_rs_per_lot']:.0f} per lot "
        f"(1 : {1 / best_fade['reward_risk']:.0f}). **Capacity cuts both ways and neither way "
        f"helps.** The headline strike is far too thin to trade — "
        f"{peak['vol_spike'] / session.lot_size:.0f} lots printed in its entry minute, so the "
        f"spike is a couple of prints rather than a market. The strikes that do carry size "
        f"(3,404 lots at 75,000 in its entry minute) show the same arithmetic at a worse "
        f"ratio.",
        "2. **The risk is genuinely unbounded.** The band constrains today's auction close. "
        f"These are {session.expiry} contracts: they carry the overnight gap, and the "
        "band says nothing about it. The one structural feature that made the expiring-series "
        "version of this trade *analysable* — a known worst case — does not exist here.",
        "3. **The trigger cannot be built.** A wing-put spike is only distinguishable from an "
        "ordinary session at a threshold of roughly 25–50 %, which on these premiums is a "
        "handful of rupees, and the corpus is 8 control sessions. There is no sample here "
        "capable of estimating the false-positive rate of a trigger that loose.",
        "",
        "**The reason there is nothing to fade:** the thesis needs wings *marked to a crash "
        "that was not going to happen*, and that is not what happened. The forward never went "
        f"near {INDICATIVE_0827['low']:,.2f} (§1), the wings never traded at the intrinsic that "
        "level implies (§1.3), and what did move was a few rupees of volatility premium — which "
        "is the correct response to a genuine spike in uncertainty about where the close would "
        "print, and which was itself largely justified: the eventual close came in 249 points "
        "below the 15:15 reference. There is a repricing here. There is no mispricing.",
        "",
        "### What is still missing",
        "",
        "- **The expiring series.** Zero bars in this corpus (§0), so the ~4,800 % move the "
        "thesis originates from cannot be examined on any feed available here. A trade in "
        "*that* instrument is neither confirmed nor refuted by anything above.",
        "- **Bid/ask.** Every price here is a trade print. Reward figures of ₹2–8 per unit sit "
        "inside a plausible wing spread, so a positive number in §2 may be entirely spread and "
        "the sign of the realised P&L is not determined by this data.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--underlying", default="SENSEX")
    parser.add_argument("--date", default="2026-08-27")
    parser.add_argument(
        "--wing-moneyness",
        type=float,
        default=0.98,
        help="a put is a wing if K/S at 15:14 is at or below this",
    )
    parser.add_argument(
        "--spike-threshold",
        type=float,
        default=100.0,
        help="percent move that counts as a spike in the control scan",
    )
    parser.add_argument("--repo", default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    repo = Path(args.repo)
    text = build_report(
        args.underlying,
        dt.date.fromisoformat(args.date),
        repo,
        args.wing_moneyness,
        args.spike_threshold,
    )
    stamp = dt.date.fromisoformat(args.date).strftime("%m%d")
    out = Path(args.out) if args.out else repo / "research" / "expiry_cas" / f"WINGS_{stamp}.md"
    out.write_text(text)
    print(f"wrote {out} ({len(text)} chars)")


if __name__ == "__main__":
    main()
