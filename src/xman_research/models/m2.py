"""The M2 record: H26's expression, amended for notional sizing and the backfilled window.

An amendment of ``h_cacfc556d38a2bda25efef59eb5544cf``, which is itself an amendment of
H1 through the v1 record. The chain is H1 -> H26 v1 -> H26 v2 -> M2, so the family trial
count spans every trial any of them ever burned. ``research/models/M2_overnight_vs_intraday.md``
§2 states the reason directly: an amendment inflates N and can only make M2 harder to
pass, while a fresh family resets the count and makes it easier.
"""

from __future__ import annotations

from xman_research.h26.hypothesis import h26_record
from xman_research.hypothesis import HypothesisRecord

__all__ = ["M2_THRESHOLDS", "m2_record"]

#: Recalibrated at the realised sample shape. The deflated-Sharpe bar RISES from H26's
#: 0.80 to 0.90, because the condition that forced 0.80 — that 0.90 was auto-failing at
#: 79 observations — no longer holds at 384. research/m2/gate.toml carries the grid.
M2_THRESHOLDS = {
    "deflated_sharpe": 0.90,
    "cost_breakeven_multiple": 3.0,
    "max_drawdown": 0.10,
    "risk_matched_increment": 0.0,
    "holdout.deflated_sharpe": 0.50,
    "holdout.cost_breakeven_multiple": 3.0,
    "holdout.max_drawdown": 0.10,
    "holdout.risk_matched_increment": 0.0,
}


def m2_record() -> HypothesisRecord:
    """M2, as an amendment of H26 v2. Deterministic — same text in, same address out."""
    base = h26_record()
    return base.amend(
        name="M2 — near-week overnight vs intraday variance split, notional-sized (backfilled)",
        entry_rule={
            **dict(base.entry_rule),
            "sizing": (
                "M1 §5 via M2 §3: n_t = floor(N* / (S_t * L_t) + 1/2), N* = 1500000 "
                "rupees of index exposure, no floor at one lot. Both arms sized alike."
            ),
        },
        exit_rule={
            **dict(base.exit_rule),
            "settlement": (
                "Neither arm settles: both exit by trading, and the eligibility guard "
                "bars expiry-session entries. The 2026-08-03 Closing Auction Session "
                "refusal is therefore not reached — a claim the run checks by reporting "
                "its settlement count rather than assuming it is zero."
            ),
        },
        thresholds=M2_THRESHOLDS,
        notes=(
            "WHAT MOVED SINCE H26 v2.\n\n"
            "SIZING. H26 ran one lot per arm; M2 sizes by notional, so the two arms stay "
            "comparable across a window in which the contract multiplier changes. M1 "
            "§12.1's check was executed over the graded window and passed.\n\n"
            "WINDOW. H26 was graded on 80 sessions from 2025-12-31; M2 is graded on 385 "
            "from 2024-10-01. The holdout boundary is inherited UNCHANGED at 2026-05-01, "
            "for exactly the reason H26's own gate gave when it refused to move it: "
            "holdout_first_date is per-config, editable, and bound to no "
            "content-addressed record, so it is precisely the channel through which a "
            "disappointing result could be rescued. Every session added by the backfill "
            "is older than the boundary, so the seal is untouched and the holdout is "
            "enlarged rather than eroded.\n\n"
            "THE BAR ROSE. H26 registered 0.80 because 0.90 was unreachable at 79 "
            "observations against three or four trials — H1's own reasoning rejects an "
            "auto-failing bar. At 384 observations that condition is gone: 0.90 is "
            "cleared by a true annualised Sharpe of 2.0 in 57.5% of synthetic draws and "
            "by noise in none of them. Keeping 0.80 after the condition that justified "
            "it disappeared would be inheriting a number, which H26's own gate refused."
        ),
    )
