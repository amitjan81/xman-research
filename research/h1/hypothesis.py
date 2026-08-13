"""H1 — the index variance risk premium, written down before it is tested.

This module holds exactly one thing: the :class:`~xman_research.hypothesis.HypothesisRecord`
for H1, as a function so that the runner and the gate file cannot drift apart. The record is
content-addressed, so its ``id`` changes if a single character of this text changes — which
is what binds the threshold file to the idea it was written against.

**Do not reword this record to reset the trial count.** Re-registering a reworded
hypothesis mints a fresh family whose logged trial count is zero, and the deflated Sharpe
computed against that count is then wrong by an unknowable amount in the flattering
direction. C4 documents the hole; it is not a feature. If the idea genuinely changes, use
:meth:`HypothesisRecord.amend`, which keeps the family and therefore the count.
"""

from __future__ import annotations

from xman_research import HypothesisRecord

__all__ = ["THRESHOLDS", "h1_record"]

#: The pre-registered decision criteria, mirrored in ``research/h1/gate.toml``.
#:
#: They live here as well as in the gate file on purpose: the record is immutable and
#: content-addressed, the file is editable, and
#: :meth:`~xman_research.validation.gate.DecisionGate.check_binding` refuses to grade if
#: the two disagree. That is what stops the editable half being the loophole around the
#: immutable half. The rationale for every number is in the gate file, next to the number.
THRESHOLDS = {
    "deflated_sharpe": 0.90,
    "cost_breakeven_multiple": 2.0,
    "max_drawdown": 0.10,
    "risk_matched_increment": 0.0,
    "holdout.deflated_sharpe": 0.50,
    "holdout.cost_breakeven_multiple": 2.0,
    "holdout.max_drawdown": 0.10,
    "holdout.risk_matched_increment": 0.0,
}


def h1_record() -> HypothesisRecord:
    """The H1 record. Deterministic — same text in, same content-address out."""
    return HypothesisRecord(
        name="H1 — NIFTY index variance risk premium (MVP anchor)",
        mechanism=(
            "Intermediation rent. One side of the Indian index-option market persistently "
            "demands convexity — index hedgers and retail buyers of protection — and the "
            "capacity-constrained intermediaries who absorb that flow cannot lay it off. "
            "They are paid for three frictions they carry rather than for a preference "
            "they hold: inventory risk in a book they cannot fully hedge, jump exposure "
            "that no dynamic hedge replicates because the underlying gaps, and margin "
            "that binds hardest at precisely the moment the payout is owed. The premium "
            "is therefore the rent on scarce risk-bearing capacity, and it should be "
            "observable as implied variance sitting systematically above the variance "
            "subsequently realised. Selling variance collects that rent."
        ),
        null_hypothesis=(
            "The short-variance position's mean excess return is not positive after the "
            "full statutory cost stack, and it does not beat the naive always-on "
            "short-variance benchmark on a risk-matched basis over the same window, the "
            "same data and the identical cost model."
        ),
        predictors=[
            "atm_implied_variance_at_entry",
            "continuous_realised_variance_trailing",
        ],
        entry_rule={
            "instrument": "NIFTY at-the-money straddle, nearest listed expiry",
            "side": "sell",
            "size": "1 lot, unconditional, opened only when the book is flat",
            "min_days_to_expiry": 1,
        },
        exit_rule={
            "exit": "European cash settlement at expiry, per the stored dated formula",
            "stop": "none — a stop is a separate research decision and a separate trial",
        },
        thresholds=THRESHOLDS,
        notes=(
            "REJECTED MECHANISM, recorded because a hypothesis must not silently carry a "
            "story its own evidence contradicts: the deep preference-based account, in "
            "which buyers purchase insurance against a wealth-destroying state and so pay "
            "above actuarial value. If frictionless synthetic options never showed "
            "negative alpha across a century of data, that channel is approximately zero "
            "and the premium is not a risk price but a rent. This record claims the rent, "
            "not the preference.\n\n"
            "INDIA REFINEMENT (Sankar et al. 2020): in Indian index options only past "
            "CONTINUOUS variance forecasts variance-swap returns; realised JUMPS carry no "
            "predictive power. A jump-loaded realised-variance estimator therefore "
            "degrades the signal, which is why the trailing predictor above is named as "
            "the continuous component. The MVP expression is unconditional and does not "
            "yet use either predictor — that is a limitation of the expression, not of "
            "the hypothesis, and the first conditional variant is where the refinement "
            "earns its place.\n\n"
            "EXPRESSION AND ITS OWN BENCHMARK: the MVP expresses H1 as an unconditional "
            "short ATM straddle, which is also the naive always-on benchmark spec §3 C6 "
            "requires. The risk-matched increment over that benchmark is therefore "
            "structurally zero this round and has no discriminating power. It is gated "
            "anyway, at zero, so that the criterion is on the record before the first "
            "conditional variant exists to be judged against it."
        ),
    )
