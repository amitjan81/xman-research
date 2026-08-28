"""Guards on the four inference steps that decide what the expiry/CAS report may claim.

Each test pins a property that, if it broke, would not fail loudly — it would print a
plausible-looking number and change a conclusion:

* **Spot-series purity.** The movement series must come from one source. Mixing a
  forward-filled index feed with a parity level that sits tens of points away from it
  reports the offset between the two as market movement, on every minute that switches.
* **Anchor exclusion.** The strike whose put-call parity produced the spot has a residual
  of zero by construction. Excluding a *different* strike leaves the manufactured zero in
  the distribution and biases every residual statistic toward "no mispricing".
* **Persistence sign.** Persistence exists to screen out prints landing in a different
  order within each bar. A residual that flips sign between adjacent minutes is that
  artefact, so counting it as persistence certifies the artefact as evidence.
* **Cost threshold.** The threshold is a per-unit figure dominated by per-order brokerage,
  so it depends on lot size and is not size-invariant — the reason a Sensex threshold
  (lot 20) is several times a Nifty one (lot 65) with no market difference involved. It is
  also applied strictly, so a residual exactly at cost does not clear it.
* **Settlement side.** Exercise STT falls on the purchaser. A short flattens with a BUY
  and owes none; charging it inflates the cost floor of every short-premium structure.
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import numpy as np
import pandas as pd

RESEARCH_DIR = Path(__file__).resolve().parents[1] / "research" / "expiry_cas"
sys.path.insert(0, str(RESEARCH_DIR))

import load as load_mod  # noqa: E402
from analyze import residual_summary, roundtrip_cost_points  # noqa: E402
from load import SessionData, load_session  # noqa: E402

from xman_research.backtest.costs import Side  # noqa: E402

SESSION_DATE = dt.date(2026, 8, 27)
UNDERLYING = "SENSEX"
STRIKES = [76_900.0, 77_000.0, 77_100.0, 77_200.0, 77_300.0]
ANCHOR = 77_100.0
#: The index feed sits this far from the chain's implied level. Any splice between the two
#: series shows up as a step of this size in a one-minute difference.
FEED_OFFSET = 80.0


def _write_corpus(
    root: Path,
    *,
    implied_by_minute: dict[dt.time, float],
    per_strike_skew: dict[float, float] | None = None,
) -> None:
    """Write one synthetic session parquet whose implied spot is known exactly.

    Options are priced at intrinsic against ``implied_by_minute``, so ``C - P + K`` returns
    that level at every strike. ``per_strike_skew`` adds a per-strike bump to the call,
    which moves that strike's implied level and nothing else — the cross-strike
    disagreement the residual statistics are supposed to measure.

    The index feed is written ``FEED_OFFSET`` below the implied level and is fresh only on
    the first minute, which is the shape that makes a spliced series detectable.
    """
    skew = per_strike_skew or {}
    minutes = sorted(implied_by_minute)
    first_feed = implied_by_minute[minutes[0]] - FEED_OFFSET
    rows = []
    for minute, implied in sorted(implied_by_minute.items()):
        ts = pd.Timestamp.combine(SESSION_DATE, minute).tz_localize("Asia/Kolkata")
        stamp = int(ts.timestamp() * 1_000_000)
        feed = implied - FEED_OFFSET if minute == minutes[0] else first_feed
        # The index symbol stops before the auction window, as BSE's does in this corpus.
        if minute < load_mod.AUCTION_START:
            rows.append(
                {
                    "minute_ts": stamp,
                    "symbol": UNDERLYING,
                    "close": feed,
                    "volume": 0.0,
                    "spot": feed,
                }
            )
        for strike in STRIKES:
            bump = skew.get(strike, 0.0)
            for kind in ("CE", "PE"):
                intrinsic = (
                    max(implied - strike, 0.0) if kind == "CE" else max(strike - implied, 0.0)
                )
                rows.append(
                    {
                        "minute_ts": stamp,
                        "symbol": f"{UNDERLYING}-27Aug2026-{int(strike)}-{kind}",
                        "close": intrinsic + (bump if kind == "CE" else 0.0),
                        "volume": 1_000.0,
                        "spot": feed,
                    }
                )
    target = root / UNDERLYING
    target.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(target / f"{SESSION_DATE.isoformat()}.parquet")


def _load(tmp_path: Path, monkeypatch, **kwargs) -> SessionData:
    monkeypatch.setattr(load_mod, "DATASETS_ROOT", tmp_path)
    monkeypatch.setattr(load_mod, "QUARANTINE_ROOT", tmp_path / "_absent")
    _write_corpus(tmp_path, **kwargs)
    return load_session(UNDERLYING, SESSION_DATE, lot_size_default=20)


def _residual_frame(residuals: list[tuple[dt.time, float, float]]) -> pd.DataFrame:
    """A ready-made residual frame: one row per (minute, strike, residual)."""
    return pd.DataFrame(
        [
            {
                "ts": pd.Timestamp.combine(SESSION_DATE, minute).tz_localize("Asia/Kolkata"),
                "strike": strike,
                "residual": residual,
                "all_legs_traded": True,
                "min_leg_volume": 500.0,
                "relation": "box",
            }
            for minute, strike, residual in residuals
        ]
    )


def _session_for_summary() -> SessionData:
    return SessionData(
        underlying=UNDERLYING,
        session_date=SESSION_DATE,
        status="published",
        chain=pd.DataFrame(),
        index=pd.Series(dtype=float),
        spot=pd.DataFrame(),
        lot_size=20,
        front_expiry=SESSION_DATE,
        parity_anchor_strike=ANCHOR,
    )


# T1 -------------------------------------------------------------------- spot purity


def test_the_movement_series_never_splices_the_feed_into_the_parity_level(tmp_path, monkeypatch):
    """A stale feed sitting 80 points away must not enter the series on any minute.

    The feed is fresh on the first minute only and the true level is flat, so a series
    that preferred a fresh feed where one exists would step by ``FEED_OFFSET`` on the
    second minute. A single-source series differences to zero throughout.
    """
    level = 77_150.0
    minutes = [dt.time(15, 28), dt.time(15, 29), dt.time(15, 30), dt.time(15, 31)]
    session = _load(
        tmp_path, monkeypatch, implied_by_minute=dict.fromkeys(minutes, level)
    )

    best = session.spot["best"]
    assert session.spot["feed_fresh"].sum() == 1, "fixture must have exactly one fresh feed minute"
    assert (session.spot["best_source"] == "parity_anchor").all()
    np.testing.assert_allclose(best.dropna().to_numpy(), level)
    assert best.diff().abs().max() < 1e-6, "a spliced series would step by FEED_OFFSET"


# T2 --------------------------------------------------------------- anchor exclusion


def test_parity_residuals_drop_the_strike_the_spot_was_built_from(tmp_path, monkeypatch):
    """The excluded strike must be the circular one, and no survivor may be a manufactured zero.

    Every strike is bumped, so each disagrees with the anchor. If the level came from a
    cross-strike median while the anchor were excluded, the median strike's residual would
    survive at exactly zero.
    """
    from analyze import parity_residuals

    level = 77_150.0
    minutes = [dt.time(15, 20), dt.time(15, 21)]
    skew = {77_000.0: 3.0, 77_100.0: 1.0, 77_200.0: 5.0, 77_300.0: 9.0, 76_900.0: 7.0}
    session = _load(
        tmp_path,
        monkeypatch,
        implied_by_minute=dict.fromkeys(minutes, level),
        per_strike_skew=skew,
    )

    assert session.parity_anchor_strike == ANCHOR
    # The level is the anchor pair's own implied spot, bump included.
    np.testing.assert_allclose(session.spot["best"].dropna().to_numpy(), level + skew[ANCHOR])

    frame = parity_residuals(session)
    assert not frame.empty
    assert ANCHOR not in set(frame["strike"]), "the circular strike must be excluded"
    assert (frame["residual"].abs() > 1e-9).all(), "a surviving exact zero is manufactured"
    # What remains is implied(K) - implied(anchor), which the bumps determine exactly.
    for strike, bump in skew.items():
        if strike == ANCHOR:
            continue
        rows = frame[frame["strike"] == strike]
        np.testing.assert_allclose(rows["residual"].to_numpy(), bump - skew[ANCHOR])


# T3 ------------------------------------------------------------- persistence sign


def test_persistence_counts_consecutive_pairs_only_when_the_sign_holds():
    """A sign flip between adjacent minutes is the artefact, not evidence of a standing edge."""
    session = _session_for_summary()
    cost = 2.0

    whipsaw = _residual_frame(
        [
            (dt.time(15, 10), 77_000.0, +9.0),
            (dt.time(15, 11), 77_000.0, -9.0),
            (dt.time(15, 12), 77_000.0, +9.0),
        ]
    )
    (row,) = [r for r in residual_summary(session, whipsaw, cost) if r["gate"] == "traded bars"]
    assert row["n_over_cost"] == 3
    assert row["n_persistent"] == 0

    standing = _residual_frame(
        [
            (dt.time(15, 10), 77_000.0, +9.0),
            (dt.time(15, 11), 77_000.0, +9.0),
            (dt.time(15, 12), 77_000.0, +9.0),
        ]
    )
    (row,) = [r for r in residual_summary(session, standing, cost) if r["gate"] == "traded bars"]
    # A run of k minutes contributes k-1 pairs.
    assert row["n_persistent"] == 2

    gapped = _residual_frame(
        [
            (dt.time(15, 10), 77_000.0, +9.0),
            (dt.time(15, 12), 77_000.0, +9.0),
        ]
    )
    (row,) = [r for r in residual_summary(session, gapped, cost) if r["gate"] == "traded bars"]
    assert row["n_persistent"] == 0, "non-adjacent minutes are not a run"


# T4 ---------------------------------------------------------------- cost threshold


def test_the_cost_threshold_is_strict_and_scales_with_lot_size():
    """`> cost` is exclusive, and the per-unit threshold falls as the lot absorbs brokerage."""
    session = _session_for_summary()
    cost = 2.0
    frame = _residual_frame(
        [
            (dt.time(15, 10), 77_000.0, 2.0),  # exactly at cost — does not clear it
            (dt.time(15, 10), 77_100.0, 2.000001),
            (dt.time(15, 10), 77_200.0, -2.5),  # magnitude is what counts, not sign
        ]
    )
    (row,) = [r for r in residual_summary(session, frame, cost) if r["gate"] == "traded bars"]
    assert row["n"] == 3
    assert row["n_over_cost"] == 2

    # Per-order brokerage is a flat rupee charge, so spreading it over more units lowers the
    # per-unit threshold. A Sensex lot of 20 therefore carries a several-times-higher
    # threshold than a Nifty lot of 65 with no difference in market conditions.
    small_lot = roundtrip_cost_points(session, legs=4, notional=77_000.0, premium=50.0)
    big = SessionData(
        underlying="NIFTY",
        session_date=SESSION_DATE,
        status="published",
        chain=pd.DataFrame(),
        index=pd.Series(dtype=float),
        spot=pd.DataFrame(),
        lot_size=65,
        front_expiry=SESSION_DATE,
        parity_anchor_strike=ANCHOR,
    )
    big_lot = roundtrip_cost_points(big, legs=4, notional=77_000.0, premium=50.0)
    assert small_lot > big_lot

    # A position sold back in the market pays 2*legs trades and no settlement event, so its
    # cost is linear in the leg count.
    two = roundtrip_cost_points(session, legs=2, notional=77_000.0, premium=50.0, exit_kind="trade")
    four = roundtrip_cost_points(
        session, legs=4, notional=77_000.0, premium=50.0, exit_kind="trade"
    )
    np.testing.assert_allclose(four, 2 * two, rtol=1e-9)


# T5 ---------------------------------------------------------------- settlement side


def test_a_short_flattening_at_settlement_owes_no_exercise_stt():
    """Exercise STT falls on the purchaser, so only the BUY-side settlement escapes it."""
    session = _session_for_summary()
    kwargs = {"legs": 2, "notional": 77_000.0, "premium": 50.0}

    long_side = roundtrip_cost_points(
        session, settlement_side=Side.SELL, settlement_intrinsic=100.0, **kwargs
    )
    short_side = roundtrip_cost_points(
        session, settlement_side=Side.BUY, settlement_intrinsic=100.0, **kwargs
    )
    assert short_side < long_side

    # The charge the long carries is proportional to the intrinsic it is levied on.
    long_double = roundtrip_cost_points(
        session, settlement_side=Side.SELL, settlement_intrinsic=200.0, **kwargs
    )
    np.testing.assert_allclose(long_double - short_side, 2 * (long_side - short_side), rtol=1e-9)
