"""Unit tests for the expiry-day / closing-auction research metrics.

The relations under test are algebraic identities, so they can be checked against a
synthetic chain priced at exact intrinsic: every residual must be zero there, and a single
injected mispricing must show up at its own strike and nowhere else. That is what catches a
sign error, which is the failure mode these metrics are most prone to — a flipped sign in
the box relation produces a residual of exactly twice the strike spacing on every row, which
looks like a large uniform "arbitrage" rather than like a bug.
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pandas as pd
import pytest

RESEARCH_DIR = Path(__file__).resolve().parents[1] / "research" / "expiry_cas"
sys.path.insert(0, str(RESEARCH_DIR))

from analyze import (  # noqa: E402
    box_residuals,
    butterfly_violations,
    parity_residuals,
    vertical_violations,
)
from load import SessionData  # noqa: E402

SESSION_DATE = dt.date(2026, 8, 18)
STRIKES = [24_100.0, 24_150.0, 24_200.0, 24_250.0, 24_300.0]
SPOT = 24_205.0
ANCHOR = 24_200.0


def _fair_chain(
    spot: float = SPOT, bumps: dict[tuple[float, str], float] | None = None
) -> pd.DataFrame:
    """A two-minute chain priced at exact intrinsic, optionally with one leg bumped."""
    bumps = bumps or {}
    rows = []
    for minute in (dt.time(15, 31), dt.time(15, 32)):
        ts = pd.Timestamp.combine(SESSION_DATE, minute).tz_localize("Asia/Kolkata")
        for strike in STRIKES:
            for kind in ("CE", "PE"):
                intrinsic = max(spot - strike, 0.0) if kind == "CE" else max(strike - spot, 0.0)
                rows.append(
                    {
                        "ts": ts,
                        "symbol": f"NIFTY-18Aug2026-{int(strike)}-{kind}",
                        "strike": strike,
                        "opt_type": kind,
                        "close": intrinsic + bumps.get((strike, kind), 0.0),
                        "volume": 1_000.0,
                        "expiry": SESSION_DATE,
                        "spot": spot,
                    }
                )
    return pd.DataFrame(rows)


def _session(chain: pd.DataFrame) -> SessionData:
    spot = pd.DataFrame(
        {
            "feed": SPOT,
            "parity": SPOT,
            "parity_anchor": SPOT,
            "feed_fresh": True,
            "best": SPOT,
            "best_source": "parity",
        },
        index=pd.Index(sorted(chain["ts"].unique()), name="ts"),
    )
    return SessionData(
        underlying="NIFTY",
        session_date=SESSION_DATE,
        status="published",
        chain=chain,
        index=pd.Series(dtype=float),
        spot=spot,
        lot_size=65,
        front_expiry=SESSION_DATE,
        parity_anchor_strike=ANCHOR,
    )


@pytest.mark.parametrize(
    "builder",
    [box_residuals, parity_residuals, vertical_violations, butterfly_violations],
)
def test_fairly_priced_chain_has_no_residual(builder) -> None:
    """A chain at exact intrinsic violates no arbitrage relation.

    Guards the sign of every relation at once: an inverted box would report twice the
    strike spacing here rather than zero.
    """
    frame = builder(_session(_fair_chain()))
    assert not frame.empty
    assert frame["residual"].abs().max() == pytest.approx(0.0, abs=1e-9)


def test_box_residual_reports_the_injected_mispricing() -> None:
    """A call richened by 5 points shows a 5-point box residual against its neighbour."""
    frame = box_residuals(_session(_fair_chain(bumps={(24_150.0, "CE"): 5.0})))
    affected = frame[(frame["strike"] == 24_150.0) | (frame["strike2"] == 24_150.0)]
    assert affected["residual"].abs().max() == pytest.approx(5.0)
    untouched = frame.drop(affected.index)
    assert untouched["residual"].abs().max() == pytest.approx(0.0, abs=1e-9)


def test_parity_residuals_exclude_the_anchor_strike() -> None:
    """The strike the parity spot is built from must never appear in residual statistics.

    Its residual is zero by construction, so including it would dilute the distribution
    with a row that is an identity rather than an observation.
    """
    frame = parity_residuals(_session(_fair_chain()))
    assert not frame.empty
    assert ANCHOR not in set(frame["strike"])


def test_stale_bars_are_flagged_not_silently_dropped() -> None:
    """A zero-volume leg marks the strike-minute untraded so the gate can split on it."""
    chain = _fair_chain()
    chain.loc[(chain["strike"] == 24_100.0) & (chain["opt_type"] == "CE"), "volume"] = 0.0
    frame = box_residuals(_session(chain))
    stale = frame[frame["strike"] == 24_100.0]
    assert len(stale)
    assert not stale["all_legs_traded"].any()
    assert frame[frame["strike"] == 24_250.0]["all_legs_traded"].all()


def test_butterfly_flags_a_concavity() -> None:
    """One cheap strike violates convexity in the triples where it is a *wing*.

    Cheapening 24,200 by 8 leaves the triple centred on it more convex, not less
    (``C1 - 2C2 + C3`` gains twice the bump, so there is no violation there). The
    violation appears in the two neighbouring triples where the cheap strike sits on an
    end and the sum loses the bump once — which is why the largest residual is the bump
    itself rather than twice it.
    """
    frame = butterfly_violations(_session(_fair_chain(bumps={(24_200.0, "CE"): -8.0})))
    assert frame["residual"].max() == pytest.approx(8.0)
    centred = frame[(frame["strike"] == 24_150.0) & (frame["strike2"] == 24_250.0)]
    assert centred["residual"].max() == pytest.approx(0.0, abs=1e-9)
