"""The M1 record: H1's expression, amended for notional sizing and the backfilled window.

**An amendment, never a fresh record.** ``research/models/M1_short_atm_straddle.md`` files
M1 under H1's record ``h_817b33ff6b9f68e288161f5990739744``, and two id-bearing things have
moved since that record was minted: the sizing rule (M1 §5, owner-approved 2026-08-19 —
notional targeting replaced one lot, and the ``n_t >= 1`` floor was dropped), and the
window the model is graded over. Editing the H1 record is impossible by construction; the
sanctioned move is :meth:`HypothesisRecord.amend`, which costs a trial and keeps the
family's parent chain intact.

Minting a fresh record instead would reset the family trial count to zero and make M1
easier to pass. That is C4's one documented hole, and it is the single move this apparatus
exists to prevent.
"""

from __future__ import annotations

from xman_research.h1.hypothesis import h1_record
from xman_research.hypothesis import HypothesisRecord

__all__ = ["M1_THRESHOLDS", "m1_record"]

#: Recalibrated at the realised sample shape, not inherited. See research/m1/gate.toml for
#: the grid and the argument; the numbers are repeated here because the record is what
#: binds them, and ``DecisionGate.check_binding`` refuses a gate that disagrees.
M1_THRESHOLDS = {
    "deflated_sharpe": 0.90,
    "cost_breakeven_multiple": 2.0,
    "max_drawdown": 0.10,
    "risk_matched_increment": 0.0,
    "holdout.deflated_sharpe": 0.50,
    "holdout.cost_breakeven_multiple": 2.0,
    "holdout.max_drawdown": 0.10,
    "holdout.risk_matched_increment": 0.0,
}


def m1_record() -> HypothesisRecord:
    """M1, as an amendment of H1. Deterministic — same text in, same content-address out."""
    return h1_record().amend(
        name="M1 — near-week short ATM straddle, notional-sized (H1 expression, backfilled)",
        entry_rule={
            "decision_time_ist": "09:20",
            "expiry": "near week — the first listed expiry strictly after the session date",
            "strike": "the listed strike nearest spot at the decision minute",
            "legs": "short one CE and one PE at that strike, atomically (M1 §4)",
            "sizing": (
                "n_t = floor(N* / (S_t * L_t) + 1/2), N* = 1500000 rupees of index "
                "exposure. NO FLOOR AT ONE LOT: a target under half a contract sizes to "
                "zero and the session does not trade (M1 §5, owner-approved 2026-08-19). "
                "M1 §12.1's pre-registration check is what makes that safe, and it was "
                "run over the graded window before this record was registered."
            ),
            "suppressed_when": (
                "under one trading day to expiry, either leg unlisted, either leg "
                "infeasible, or n_t = 0"
            ),
        },
        exit_rule={
            "hold": "to expiry, no intermediate exit",
            "settlement": (
                "European cash settlement against the unweighted mean of the last 30 "
                "minutes of the expiry session (M1 §6). NSE's rule is volume-weighted; "
                "the corpus carries no index volume, so this is a known divergence."
            ),
            "ceiling": (
                "2026-08-03, the NSE Closing Auction Session change, which the cost and "
                "settlement tables carry with implemented=false and refuse to settle "
                "against."
            ),
        },
        thresholds=M1_THRESHOLDS,
        notes=(
            "WHAT MOVED SINCE H1, and why each move is id-bearing.\n\n"
            "SIZING. H1 ran one lot. M1 §5 sizes by notional so that the Sharpe, the "
            "drawdown and the cost-breakeven ratio are invariant to the contract "
            "multiplier — which matters far more on this window than on H1's, because "
            "the multiplier changes inside it. The n_t = 0 branch is the one place "
            "sizing could re-introduce a dependence on L_t, and M1 §12.1's check is what "
            "removes it: it was executed over 2024-10-01..2026-04-30 and passed, minimum "
            "ratio 0.7610 on 2025-12-01. Reported in research/m1/gate.toml with the "
            "declared-lot-size reading beside it.\n\n"
            "WINDOW. H1 was graded on 80 sessions beginning 2025-12-31. M1 is graded on "
            "385 sessions beginning 2024-10-01, the first date at which the securities "
            "transaction tax rates are in force at all. The holdout boundary is NOT "
            "moved: it stays where H1 sealed it, at 2026-05-01, and every session the "
            "backfill added is OLDER than that boundary, which is what makes this "
            "re-run clean rather than a second look at data already seen.\n\n"
            "WHAT DID NOT MOVE. The mechanism, the null, the predictors and the "
            "benchmark's structural identity with the candidate are H1's, unchanged. "
            "This is the same claim about the same premium, expressed on a longer "
            "window with a sizing rule that does not depend on the lot size."
        ),
    )
