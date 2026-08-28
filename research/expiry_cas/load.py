"""Session loader for expiry-day last-30-minute and closing-auction analysis.

Underlying-agnostic: every path is derived from ``underlying``, so a SENSEX pass runs
the same code once BSE sessions land in the corpus.

**The spot problem, which shapes this whole module.** The index feed in these sessions
is not a clean series in the window that matters:

* From 2026-08-03 the 15:00-15:30 index feed freezes for ten-plus minutes and catches up
  in one jump, so a repeated close is a repeat rather than an observation.
* In 15:30-15:39 — the post-close/auction window, where expiring options print in size —
  the feed carries exactly one distinct value for the whole ten minutes. The underlying
  is unobservable there from the feed alone.
* A session can lose the index symbol entirely part-way through the day, in which case
  there is no feed in the window at all.

So the underlying has to be recovered from the option chain by put-call parity,
:math:`S = C - P + K`, exact at :math:`T\\to 0` for European index options.

**The circularity this creates, and the guard against it.** A parity-derived spot fed
back into a parity *residual* :math:`r = C - P - (S - K)` yields :math:`r \\equiv 0` at
whichever strike produced :math:`S` — a manufactured finding. :class:`SessionData`
therefore carries ``parity_anchor_strike`` alongside the series so the analysis can drop
the anchor mechanically rather than by convention, and the robust cross-strike estimator
is reported for what it is: a median, against which residuals measure cross-sectional
*disagreement between strikes* and cannot see a mispricing common to all of them.

**Forward bias on non-expiring chains.** :math:`C - P = S - K e^{-rT}`, so parity spot
overstates the index by :math:`K(1 - e^{-rT}) \\approx K r T` when :math:`T > 0` — order
17 points on a 24,000 index four days out. Level comparisons against a non-expiring
chain are therefore invalid; *changes* over a ten-minute window are not, because the
bias is near-constant across it. :attr:`SessionData.parity_is_biased` says which case a
session is in.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

DATASETS_ROOT = Path("/home/qa/runtime/data/backtest/datasets/dhan")
QUARANTINE_ROOT = Path("/home/qa/runtime/data/backtest/dhan/quarantine")

#: Continuous session close. Bars at or after this are the post-close / closing-auction
#: window: expiring options keep printing in size while the index feed does not move.
AUCTION_START = dt.time(15, 30)
AUCTION_END = dt.time(15, 39)
#: Start of the settlement-relevant final half hour.
FINAL_WINDOW_START = dt.time(15, 0)

_SYMBOL_RE = re.compile(r"^(?P<root>.+?)-(?P<expiry>\d{2}[A-Za-z]{3}\d{4})-(?P<strike>\d+(?:\.\d+)?)-(?P<kind>CE|PE)$")


@dataclass(frozen=True, slots=True)
class SessionData:
    """One trading session's option chain plus every underlying series that can be built.

    ``spot`` is indexed by IST minute and carries, per minute: ``feed`` (the broadcast
    index level, forward-filled by the source and therefore possibly stale),
    ``feed_fresh`` (the feed changed from the previous minute — the only minutes where
    the feed is an observation), ``parity`` (cross-strike median of :math:`C-P+K` over
    strikes whose both legs traded that minute), ``parity_anchor`` (the same quantity at
    the single anchor strike), and ``best`` (``feed`` where fresh, ``parity`` otherwise).
    """

    underlying: str
    session_date: dt.date
    status: str
    chain: pd.DataFrame
    index: pd.Series
    spot: pd.DataFrame
    lot_size: int
    front_expiry: dt.date
    parity_anchor_strike: float

    @property
    def is_expiry_session(self) -> bool:
        """Whether the chain's front expiry settles today — the only case with exercise."""
        return self.front_expiry == self.session_date

    @property
    def parity_is_biased(self) -> bool:
        """Whether parity spot carries the forward bias :math:`K(1-e^{-rT})`.

        True whenever the chain does not expire today. Level comparisons against feed
        spot are then invalid; ten-minute changes remain usable.
        """
        return not self.is_expiry_session

    @property
    def has_auction_window(self) -> bool:
        """Whether any option bar prints at or after 15:30 in this session."""
        return bool(len(self.chain[self.chain["ts"].dt.time >= AUCTION_START]))


def session_path(underlying: str, session_date: dt.date) -> tuple[Path, str]:
    """Locate a session's parquet, preferring the published corpus over quarantine.

    Returns the path and the status label that every table carrying this session must
    print. A quarantined session is analysable but its coverage failed the publication
    gate, and a table that does not say so is misleading.
    """
    stem = f"{session_date.isoformat()}.parquet"
    published = DATASETS_ROOT / underlying / stem
    if published.exists():
        return published, "published"
    quarantined = QUARANTINE_ROOT / underlying / stem
    if quarantined.exists():
        return quarantined, "quarantined"
    raise FileNotFoundError(f"no session parquet for {underlying} {session_date} in either corpus")


def _lot_size(underlying: str, session_date: dt.date, default: int) -> int:
    """Declared lot size from the session's own refdata, which is per-expiry and revised."""
    for root in (DATASETS_ROOT, QUARANTINE_ROOT):
        ref = root / underlying / f"{session_date.isoformat()}.refdata" / "nfo_instruments.json"
        if not ref.exists():
            continue
        rows = json.loads(ref.read_text())
        sizes = {int(r["LotSize"]) for r in rows if r.get("LotSize")}
        if len(sizes) == 1:
            return sizes.pop()
        if sizes:
            # Mixed lot sizes across expiries; the front expiry's is the one that trades.
            front = min(dt.datetime.strptime(r["ExpiryDate"], "%d/%m/%Y").date() for r in rows)
            front_sizes = {
                int(r["LotSize"])
                for r in rows
                if dt.datetime.strptime(r["ExpiryDate"], "%d/%m/%Y").date() == front
            }
            if len(front_sizes) == 1:
                return front_sizes.pop()
    return default


def _parse_symbols(chain: pd.DataFrame, underlying: str) -> pd.DataFrame:
    parsed = chain["symbol"].str.extract(_SYMBOL_RE)
    chain = chain.assign(
        strike=pd.to_numeric(parsed["strike"]),
        opt_type=parsed["kind"],
        expiry=pd.to_datetime(parsed["expiry"], format="%d%b%Y").dt.date,
    )
    return chain[chain["opt_type"].notna()]


def _parity_spot(chain: pd.DataFrame, anchor_strike: float) -> pd.DataFrame:
    """Per-minute :math:`S = C - P + K`, as a cross-strike median and at the anchor.

    Only strike-minutes where **both** legs printed volume contribute. A zero-volume bar
    carries a stale close, and a stale close differenced against a live one manufactures
    a residual that is pure staleness rather than mispricing.
    """
    traded = chain[chain["volume"] > 0]
    wide = traded.pivot_table(index=["ts", "strike"], columns="opt_type", values="close", aggfunc="last")
    if "CE" not in wide.columns or "PE" not in wide.columns:
        return pd.DataFrame(columns=["parity", "parity_anchor", "parity_n"])
    wide = wide.dropna(subset=["CE", "PE"])
    implied = (wide["CE"] - wide["PE"] + wide.index.get_level_values("strike")).rename("implied")
    frame = implied.reset_index()
    agg = frame.groupby("ts")["implied"].agg(parity="median", parity_n="size")
    anchor = frame[frame["strike"] == anchor_strike].set_index("ts")["implied"].rename("parity_anchor")
    return agg.join(anchor)


def _anchor_strike(chain: pd.DataFrame, index: pd.Series, session_date: dt.date) -> float:
    """Strike nearest the underlying at the start of the final window.

    Chosen from the feed while the feed is still moving, so the anchor does not depend on
    the parity estimate it goes on to produce. The chain's broadcast ``spot`` column is
    preferred over the index symbol's own bars: a session can lose the index symbol
    part-way through the day while the broadcast survives to the close, and an anchor
    struck from a two-hour-stale level can sit several strikes away from the money.
    """
    ref_time = pd.Timestamp.combine(session_date, FINAL_WINDOW_START).tz_localize("Asia/Kolkata")
    broadcast = chain.dropna(subset=["spot"])
    broadcast = broadcast[broadcast["ts"] <= ref_time]
    if len(broadcast):
        level = float(broadcast["spot"].iloc[-1])
    elif len(index):
        earlier = index[index.index <= ref_time]
        level = float(earlier.iloc[-1]) if len(earlier) else float(index.iloc[-1])
    else:
        level = float(chain["strike"].median())
    strikes = np.sort(chain["strike"].unique())
    return float(strikes[np.argmin(np.abs(strikes - level))])


def load_session(underlying: str, session_date: dt.date, lot_size_default: int = 65) -> SessionData:
    """Load one session into a chain frame plus every derivable underlying series."""
    path, status = session_path(underlying, session_date)
    raw = pd.read_parquet(path)
    raw["ts"] = pd.to_datetime(raw["minute_ts"], unit="us", utc=True).dt.tz_convert("Asia/Kolkata")
    # An 18:00 stub bar appears in some sessions; it is not a trading minute.
    raw = raw[raw["ts"].dt.hour < 16]

    index = raw.loc[raw["symbol"] == underlying].set_index("ts")["close"].sort_index()
    chain = _parse_symbols(raw[raw["symbol"] != underlying].copy(), underlying).sort_values("ts")
    front_expiry = min(chain["expiry"])
    chain = chain[chain["expiry"] == front_expiry]

    anchor = _anchor_strike(chain, index, session_date)
    parity = _parity_spot(chain, anchor)

    # The feed is broadcast onto every option row; one value per minute.
    feed = chain.groupby("ts")["spot"].last().rename("feed")
    spot = pd.DataFrame(index=feed.index.union(parity.index)).join(feed).join(parity)
    spot["feed_fresh"] = spot["feed"].ne(spot["feed"].shift()) & spot["feed"].notna()

    # Which series to difference for per-minute movement.
    #
    # The feed is forward-filled through its freeze, so consecutive feed values are not
    # consecutive observations: a print that lands after twelve frozen minutes carries
    # twelve minutes of movement, and differencing it as a one-minute return reports a
    # jump that never happened in one minute. Parity has no such gap — it is recomputed
    # from options that traded in that minute.
    #
    # Parity is preferred outright once the chain expires today, because T -> 0 collapses
    # the forward term to under a tenth of a point on a 24,000 index and the estimate is
    # then exact rather than proxied. On a chain with days left the forward term is order
    # 17 points and parity also inherits vega noise from every leg, so the feed's fresh
    # prints are the better observation and parity only fills the gaps.
    exact_parity = front_expiry == session_date
    if exact_parity:
        spot["best"] = spot["parity"].where(spot["parity"].notna(), spot["feed"])
        spot["best_source"] = np.where(spot["parity"].notna(), "parity", "feed")
    else:
        spot["best"] = np.where(spot["feed_fresh"], spot["feed"], spot["parity"])
        spot["best_source"] = np.where(spot["feed_fresh"], "feed", "parity")
    spot.loc[spot["best"].isna(), "best_source"] = "none"

    return SessionData(
        underlying=underlying,
        session_date=session_date,
        status=status,
        chain=chain,
        index=index,
        spot=spot,
        lot_size=_lot_size(underlying, session_date, lot_size_default),
        front_expiry=front_expiry,
        parity_anchor_strike=anchor,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--underlying", default="NIFTY")
    parser.add_argument("--dates", nargs="+", required=True)
    args = parser.parse_args()
    for raw_date in args.dates:
        session = load_session(args.underlying, dt.date.fromisoformat(raw_date))
        window = session.spot[session.spot.index.time >= FINAL_WINDOW_START]
        print(
            f"{session.session_date} {session.status:11} expiry={session.front_expiry} "
            f"expiry_session={session.is_expiry_session} lot={session.lot_size} "
            f"anchor={session.parity_anchor_strike:.0f} "
            f"auction={session.has_auction_window} "
            f"final_window_minutes={len(window)} "
            f"feed_fresh={int(window['feed_fresh'].sum())} "
            f"parity_minutes={int(window['parity'].notna().sum())}"
        )


if __name__ == "__main__":
    main()
