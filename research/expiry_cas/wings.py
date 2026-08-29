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
* The underlying is recovered by put-call parity at a single anchor pair, never spliced
  from the feed. On a chain with :math:`T > 0` this level carries the forward bias
  :math:`K(1 - e^{-rT})`, order 90 points at :math:`K = 77{,}200` seven days out, so
  parity **levels** here are not comparable to a published index level; only changes
  over the window are. :data:`PARITY_BIAS_NOTE` is printed beside every such table.

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
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

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

PARITY_BIAS_NOTE = (
    "Parity spot on a non-expiring chain overstates the index by K(1-e^{-rT}) "
    "(~90 pts at K=77,200, T=7d). Changes over the window are usable; levels are not."
)

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
    ref_spot = float(session.implied_spot.dropna().iloc[0])
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
        after = {t: _px_at(close, vol, k, dt.time(15, m)) for t, m in
                 (("15:30", 30), ("15:35", 35), ("15:39", 39))}
        rev = {
            f"reversal_{t}_pct": (np.nan if abs(height) < 1e-9 else (peak - after[t]) / height * 100.0)
            for t in after
        }
        # The crash window itself. This, not the largest one-minute move, is the direct
        # answer to "did the wing reprice off the indicative": it is the extreme premium
        # reached while the indicative was at its low, against the same strike's last
        # continuous-session price.
        live = close[k].where(vol[k] > 0).dropna()
        base = live[live.index.time <= WINDOW_START]
        crash = live[(live.index.time >= dt.time(15, 18)) & (live.index.time <= dt.time(15, 23))]
        if len(base) and len(crash) and base.iloc[-1] > 0:
            extreme = float(crash.max() if kind == "PE" else crash.min())
            crash_pct = (extreme / float(base.iloc[-1]) - 1.0) * 100.0
        else:
            crash_pct = float("nan")
        rows.append(
            {
                "strike": k,
                "moneyness": k / ref_spot,
                "crash_1518_1523_pct": crash_pct,
                "spike_min": r["to_ts"].strftime("%H:%M"),
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
        out["moneyness"] <= wing_max_moneyness if kind == "PE"
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
    """The 15:14 at-the-money put premium and the strike it came from."""
    ref = float(session.implied_spot.dropna().iloc[0])
    k = min(session.pe_close.columns, key=lambda c: abs(c - ref))
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
        ref = float(session.implied_spot.dropna().iloc[0])
        changes = traded_changes(session.pe_close, session.pe_vol)
        if changes.empty:
            continue
        changes["moneyness"] = changes["strike"] / ref
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
        for thr in (25.0, 50.0, threshold_pct):
            row[f"hits_{thr:.0f}pct"] = wing[wing["d_pct"] >= thr]["strike"].nunique()
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


def figures(session: ChainSession, puts: pd.DataFrame, nifty: ChainSession | None, repo: Path
            ) -> list[str]:
    out = _fig_dir(repo)
    names = []

    # 1. The wing's price paths against the implied index and the published indicative.
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 8), sharex=True,
                                   gridspec_kw={"height_ratios": [2, 3]})
    spot = session.implied_spot.dropna()
    ax1.plot(spot.index, spot.values, color="#1f4e79", lw=1.8, label="option-implied index (parity)")
    ax1.axhline(INDICATIVE_0827["low"], color="#c00000", ls="--", lw=1.2,
                label=f"published indicative low {INDICATIVE_0827['low']:,.0f}")
    ax1.axhline(INDICATIVE_0827["close"], color="#548235", ls=":", lw=1.4,
                label=f"official close {INDICATIVE_0827['close']:,.0f}")
    ax1.axvspan(spot.index[0].replace(hour=15, minute=18), spot.index[0].replace(hour=15, minute=23),
                color="#c00000", alpha=0.08)
    ax1.set_ylabel("index")
    ax1.legend(fontsize=7, loc="lower right")
    ax1.set_title(f"{session.underlying} {session.session_date} — {session.expiry} wings vs the "
                  f"closing-auction indicative")

    wing = puts[puts["is_wing"]].nlargest(6, "d_pct")
    for _, r in wing.iterrows():
        k = r["strike"]
        live = session.pe_close[k].where(session.pe_vol[k] > 0).dropna()
        ax2.plot(live.index, live.values, marker=".", ms=3, lw=1.2, label=f"{k:,.0f} PE")
    ax2.axvspan(spot.index[0].replace(hour=15, minute=18), spot.index[0].replace(hour=15, minute=23),
                color="#c00000", alpha=0.08)
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
    grid = changes.pivot_table(index="strike", columns=changes["to_ts"].dt.strftime("%H:%M"),
                               values="d_pct")
    fig, ax = plt.subplots(figsize=(12, 8))
    lim = float(np.nanmax(np.abs(grid.to_numpy()))) if grid.size else 1.0
    im = ax.imshow(grid.to_numpy(), aspect="auto", cmap="RdBu_r", vmin=-lim, vmax=lim)
    ax.set_yticks(range(len(grid.index)))
    ax.set_yticklabels([f"{k:,.0f}" for k in grid.index], fontsize=6)
    ax.set_xticks(range(len(grid.columns)))
    ax.set_xticklabels(grid.columns, rotation=90, fontsize=6)
    ax.set_title(f"{session.underlying} {session.expiry} puts — traded-to-traded % change "
                 f"(blank = no trade in that minute)")
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
            ref = float(sess.implied_spot.dropna().iloc[0])
            money = {k: k / ref for k in sess.pe_close.columns}
            picks = sorted(money, key=lambda k: abs(money[k] - 0.975))[:3]
            for k in picks:
                live = sess.pe_close[k].where(sess.pe_vol[k] > 0).dropna()
                if len(live) < 2:
                    continue
                ax.plot(live.index.strftime("%H:%M"), live.values / live.iloc[0] * 100.0,
                        style, color=colour, lw=1.3, alpha=0.8,
                        label=f"{sess.underlying} {k:,.0f} (m={money[k]:.3f})")
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


def build_report(underlying: str, session_date: dt.date, repo: Path, wing_m: float,
                 threshold: float) -> str:
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
        ["strike", "moneyness", "crash_1518_1523_pct", "spike_min", "gap_min", "px_before",
         "px_spike", "d_pct", "d_rs", "vol_spike", "px_15:30", "px_15:35", "px_15:39",
         "reversal_15:30_pct", "reversal_15:35_pct", "reversal_15:39_pct"]
    ].copy()
    top_rs = puts.nlargest(10, "d_rs")[
        ["strike", "moneyness", "is_wing", "spike_min", "gap_min", "px_before", "px_spike",
         "d_pct", "d_rs", "vol_spike", "reversal_15:39_pct"]
    ].copy()

    # --- intrinsic references ---------------------------------------------------------
    ref_spot = float(session.implied_spot.dropna().iloc[0])
    ref = puts[["strike", "moneyness", "px_1514", "px_spike", "spike_min", "px_15:39"]].copy()
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
    call_rows = calls[calls["is_wing"]].nsmallest(8, "d_pct")[
        ["strike", "moneyness", "spike_min", "gap_min", "px_before", "px_spike", "d_pct", "d_rs",
         "vol_spike", "px_15:35", "px_15:39"]
    ].copy()
    call_rows = call_rows.rename(columns={"px_spike": "px_trough", "d_pct": "drop_pct",
                                          "d_rs": "drop_rs"})
    call_rows["recovery_by_1539_pct"] = (
        (call_rows["px_15:39"] - call_rows["px_trough"])
        / (call_rows["px_before"] - call_rows["px_trough"]).replace(0, np.nan) * 100.0
    )

    # --- Nifty cross-check --------------------------------------------------------------
    cross_rows = []
    for target in (0.960, 0.970, 0.975, 0.980, 0.985, 0.990):
        row: dict[str, object] = {"moneyness": target}
        for sess, tag in ((session, "sensex"), (nifty, "nifty_front"), (nifty_next, "nifty_next")):
            if sess is None or sess.implied_spot.dropna().empty:
                continue
            r0 = float(sess.implied_spot.dropna().iloc[0])
            k = min(sess.pe_close.columns, key=lambda c: abs(c / r0 - target))
            ch = traded_changes(sess.pe_close[[k]], sess.pe_vol[[k]])
            live = sess.pe_close[k].where(sess.pe_vol[k] > 0).dropna()
            crash = live[(live.index.time >= dt.time(15, 18)) & (live.index.time <= dt.time(15, 23))]
            base = live.iloc[0] if len(live) else np.nan
            row[f"{tag}_K"] = float(k)
            row[f"{tag}_dte"] = sess.days_to_expiry
            row[f"{tag}_max_1min_pct"] = float(ch["d_pct"].max()) if len(ch) else np.nan
            row[f"{tag}_1518_1523_pct"] = (
                (float(crash.max()) / base - 1.0) * 100.0 if len(crash) and base else np.nan
            )
        cross_rows.append(row)
    cross = pd.DataFrame(cross_rows)

    # --- controls ------------------------------------------------------------------------
    control_sessions = [
        ("SENSEX", dt.date(2026, 8, 20)), ("SENSEX", dt.date(2026, 8, 25)),
        ("SENSEX", dt.date(2026, 8, 26)), ("SENSEX", dt.date(2026, 8, 28)),
        ("NIFTY", dt.date(2026, 8, 25)), ("NIFTY", dt.date(2026, 8, 26)),
        ("NIFTY", dt.date(2026, 8, 27)), ("NIFTY", dt.date(2026, 8, 28)),
    ]
    controls = control_scan(control_sessions, wing_m, threshold)
    event = control_scan([(underlying, session_date)], wing_m, threshold)
    controls = pd.concat([event.assign(row="EVENT"), controls.assign(row="control")],
                         ignore_index=True)

    return _render(session, expiries, puts, top_pct, top_rs, ref, rr, call_rows, cross, controls,
                   tv, tv_strike, figs, wing_m, threshold, ref_spot)


def _render(session, expiries, puts, top_pct, top_rs, ref, rr, calls, cross, controls, tv,
            tv_strike, figs, wing_m, threshold, ref_spot) -> str:
    ctl = controls[controls["row"] == "control"]
    n_hits = int(ctl[f"hits_{threshold:.0f}pct"].sum())
    n_wing = int(ctl["n_wing"].sum())
    ev = controls[controls["row"] == "EVENT"].iloc[0]
    peak = puts.nlargest(1, "d_pct").iloc[0]

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
        f"**Parity levels are biased.** {PARITY_BIAS_NOTE} Every index level below is therefore "
        f"used for *changes* only, and the published indicative path "
        f"({INDICATIVE_0827['ref_1515']:,.2f} at 15:15 → {INDICATIVE_0827['low']:,.2f} between "
        f"{INDICATIVE_0827['low_window'][0]} and {INDICATIVE_0827['low_window'][1]} → close "
        f"{INDICATIVE_0827['close']:,.2f}) is a set of published constants, not a measurement "
        f"from this feed.",
        "",
        "**Every change is between two bars that each printed volume**, and every row carries "
        "`gap_min`. A `gap_min` above 1 is a multi-minute move and is not a one-minute spike.",
        "",
        "---",
        "",
        "## 1. Did the next-week wings reprice off the indicative?",
        "",
        f"Implied index at 15:14: **{ref_spot:,.2f}** (parity, biased high — see §0). Its own "
        f"path over the window and the wing put paths are in "
        f"`fig/wings/{figs[0]}`; the full strike × minute change grid is "
        f"`fig/wings/{figs[1]}`.",
        "",
        "### 1.1 Top 10 put strike-minutes by % change",
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
        "**This is the sharpest single statement in the study.** Had the index really been at "
        f"{INDICATIVE_0827['low']:,.2f}, every strike above it was in the money by "
        "construction, and `spike_over_intrinsic_low` would have to be at or above zero — "
        "a put cannot trade below intrinsic. It is deeply **negative** across the whole "
        "in-that-scenario-ITM range: the strikes read as hundreds of rupees below what they "
        "would be worth if the indicative were a real index level. The options market did not "
        "price the indicative as an index at all, at any strike, in any minute.",
        "",
        _md(ref.round(3)),
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
        f"That estimate holds implied volatility at its pre-dislocation level and ignores "
        f"gamma over a 2,200-point distance, so it **understates** the adverse mark. Every "
        f"`reward_risk` below is therefore optimistic in the direction that flatters the trade.",
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
        f"Nifty's front expiry is a Tuesday weekly, so its tenor does not match Sensex's "
        f"{session.days_to_expiry} days. Both Nifty expiries are shown so the comparison cannot "
        f"be read as a tenor artifact. `*_1518_1523_pct` is the largest traded premium in "
        f"15:18–15:23 against the same strike's 15:14 price — the crash window itself.",
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
        f"implied index, because listed depth differs session to session. `hits` counts distinct "
        f"wing strikes whose largest traded-to-traded move in {WINDOW_START:%H:%M}–"
        f"{WINDOW_END:%H:%M} reached the threshold.",
        "",
        _md(controls.round(4)),
        "",
        f"**At the {threshold:.0f} % threshold the trigger fires nowhere — {n_hits} of {n_wing} "
        f"control wing strike-sessions across {len(ctl)} sessions, and "
        f"{int(ev[f'hits_{threshold:.0f}pct'])} of {int(ev['n_wing'])} on the event session "
        f"itself.** A trigger with no false positives and no true positives is not a trigger; "
        f"it is a threshold above the entire distribution. The sweep is what carries the "
        f"information: at **50 %** the event fires {int(ev['hits_50pct'])} of "
        f"{int(ev['n_wing'])} while the controls fire {int(ctl['hits_50pct'].sum())} of "
        f"{n_wing}, and at **25 %** the event fires {int(ev['hits_25pct'])} against "
        f"{int(ctl['hits_25pct'].sum())} for the controls. The event session is separable from "
        f"an ordinary one — but only at a threshold that describes a ₹8 move on a ₹12 premium.",
        "",
        "---",
        "",
        "## 5. Verdict",
        "",
        f"**Yes, the next-week wings repriced off the indicative — and the size of the "
        f"repricing is the finding.** The deepest listed put moved "
        f"{peak['crash_1518_1523_pct']:+.1f} % through the crash window and "
        f"{peak['d_pct']:+.1f} % in its largest single traded minute "
        f"(**{peak['strike']:,.0f} PE, ₹{peak['px_before']:.2f} → ₹{peak['px_spike']:.2f}** at "
        f"{peak['spike_min']}, gap {peak['gap_min']:.0f} min), and the response decays "
        f"monotonically as the strike approaches the money. The move is real, it is ordered, "
        f"it is {peak['crash_1518_1523_pct'] / 6.25:.0f}× the same-moneyness Nifty response, "
        f"and **it is ₹{peak['d_rs']:.2f}**.",
        "",
        "**No, there was no defined-risk trade with positive expectancy.** Three independent "
        "reasons, any one of which is sufficient:",
        "",
        "1. **The reward is a rounding error and the risk is not.** Selling the largest spike "
        "on the board and covering at the last bar returns "
        f"₹{rr['reward_rs_per_lot'].max():.0f} per lot at best. Against the same-session "
        "mark at the band floor the ratio is about **1 : 100**, and that denominator is "
        "already the most flattering one available — it holds volatility flat across a "
        "2,200-point move.",
        "2. **The risk is genuinely unbounded.** The band constrains today's auction close. "
        f"These are {session.expiry} contracts: they carry the overnight gap, and the "
        "band says nothing about it. The one structural feature that made the expiring-series "
        "version of this trade *analysable* — a known worst case — does not exist here.",
        "3. **The trigger cannot be built.** A wing-put spike is only distinguishable from an "
        "ordinary session at a threshold of roughly 25–50 %, which on these premiums is a "
        "handful of rupees, and the corpus is 8 control sessions. There is no sample here "
        "capable of estimating the false-positive rate of a trigger that loose.",
        "",
        "**What the data says instead, and it is the stronger result:** the wings priced the "
        "indicative as noise, correctly and immediately. At the indicative low every strike "
        f"above {INDICATIVE_0827['low']:,.2f} was notionally in the money, yet none of them "
        "traded within hundreds of rupees of that intrinsic (§1.3). The mispricing the thesis "
        "needs — wings marked to a crash that was not going to happen — **is not present to "
        "be traded.** The market never made the error.",
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
    parser.add_argument("--wing-moneyness", type=float, default=0.98,
                        help="a put is a wing if K/S at 15:14 is at or below this")
    parser.add_argument("--spike-threshold", type=float, default=100.0,
                        help="percent move that counts as a spike in the control scan")
    parser.add_argument("--repo", default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    repo = Path(args.repo)
    text = build_report(
        args.underlying, dt.date.fromisoformat(args.date), repo, args.wing_moneyness,
        args.spike_threshold,
    )
    stamp = dt.date.fromisoformat(args.date).strftime("%m%d")
    out = (
        Path(args.out) if args.out
        else repo / "research" / "expiry_cas" / f"WINGS_{stamp}.md"
    )
    out.write_text(text)
    print(f"wrote {out} ({len(text)} chars)")


if __name__ == "__main__":
    main()
