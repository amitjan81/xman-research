"""H26 — the overnight/intraday variance premium, written down before it is tested.

**H26 is an AMENDMENT of H1, not a new family.** :func:`h26_record` is built by calling
:meth:`HypothesisRecord.amend` on :func:`xman_research.h1.hypothesis.h1_record`, so the
amendment keeps ``parent_id`` and
:meth:`~xman_research.trial_log.TrialLog.count_family_trials` spans both records. The
deflated Sharpe is therefore computed against a trial count that includes H1's, which
makes H26 *harder* to pass than it would be as a fresh record. The reasoning is in
``research/h26/gate.toml`` under ``amendment_justification`` and is summarised here only
so nobody has to leave this file to learn that the choice was made deliberately.

**The rejected argument, recorded because a bad reason for a right answer is still a bad
reason.** An earlier draft justified the amendment by claiming H26's return stream is an
exact *partition* of H1's — that close-to-open plus open-to-close is the whole session, so
H26 merely slices a stream H1 already tested. That claim is false and was withdrawn before
pre-registration. H1 entered once per expiry cycle at 09:20 and held to cash settlement:
eighteen straddles over eighty sessions, never re-striking, never paying an exit spread,
its largest modelled cost the STT on exercise. H26 re-strikes twice a day at strikes chosen
at two different minutes, pays entry and exit costs H1 never paid, and never settles at
all. What the two clocks partition is the *day*, not H1's traded P&L. The amendment stands
on the argument in the gate file instead — direction of error — which does not depend on
the partition being exact.
"""

from __future__ import annotations

import datetime as dt

from xman_research import HypothesisRecord
from xman_research.h1.hypothesis import h1_record

__all__ = ["CLOSE_DECISION", "OPEN_DECISION", "THRESHOLDS", "h26_record"]

#: The decision minutes, fixed HERE, inside the content-addressed record.
#:
#: They are not merely configuration: which minute counts as "the open" and which as "the
#: close" moves real premium between the two arms, so they are exactly the kind of free
#: parameter a disappointing result invites someone to nudge. Pinning them in the record
#: means moving one mints a different hypothesis id and breaks the gate binding, which is
#: the only enforcement that does not rely on anybody's restraint.
#:
#: 09:20 rather than the true first bar at 09:15, and the choice is deliberately the
#: conservative one. Fills are at the bar close with no spread modelled anywhere in this
#: system, and the opening minute is the most spread-hostile, least-settled bar of the
#: session — so a bar-close fill at 09:15 flatters whichever arm trades there, which is
#: the *candidate*, the arm being graded. Buying back five minutes later transfers some
#: genuine overnight premium out of the candidate and into the intraday arm, biasing the
#: comparison against the hypothesis. It also matches H1's decision time, which is the
#: minute this corpus has already been shown to fill at.
OPEN_DECISION = dt.time(9, 20)

#: 15:29 is the last minute that prints on every session in the corpus (79 sessions end
#: there, 29 at 15:30, one at 15:39), so the close decision resolves on all of them.
#: A later time would silently resolve to ``None`` on most sessions and the engine would
#: skip the decision without erroring — the arm would simply stop trading.
CLOSE_DECISION = dt.time(15, 29)

#: The pre-registered decision criteria, mirrored in ``research/h26/gate.toml``, where
#: every number carries its derivation. ``DecisionGate.check_binding`` refuses to grade if
#: the two disagree, which is what stops the editable half being a loophole around the
#: immutable half.
THRESHOLDS = {
    "deflated_sharpe": 0.80,
    "cost_breakeven_multiple": 3.0,
    "max_drawdown": 0.10,
    "risk_matched_increment": 0.0,
    "holdout.deflated_sharpe": 0.50,
    "holdout.cost_breakeven_multiple": 3.0,
    "holdout.max_drawdown": 0.10,
    "holdout.risk_matched_increment": 0.0,
}


def h26_record() -> HypothesisRecord:
    """The H26 record, as an amendment of H1. Deterministic: same text, same id."""
    return h1_record().amend(
        name="H26 — overnight vs intraday variance premium (amendment of H1)",
        mechanism=(
            "Two clocks, and options are priced on both. Time decay is charged over "
            "CALENDAR time, while realised variance accrues only over TRADING time. A "
            "weekend charges a short-option holder three days of decay and delivers one "
            "day of variance; an NSE holiday cluster charges more still. The seller of "
            "that wedge is not being paid for a mistake anyone is making — they are paid "
            "for bearing GAP RISK, the possibility that the market reopens somewhere "
            "else, and they are compensated in decay for hours during which the "
            "underlying provably cannot move. This is a structural mismatch between two "
            "measures of time, not a behavioural bias and not a preference, so it "
            "requires nobody to be wrong. India sharpens it: NSE carries an unusually "
            "heavy holiday calendar, so the trading-day/calendar-day wedge is wider than "
            "in the US studies the idea comes from, and the 2025-09-01 move of index "
            "expiry from Thursday to Tuesday changed which weekend a weekly seller "
            "straddles. The claim is therefore about WHEN the variance premium accrues, "
            "not whether it exists — which is why this is an amendment of H1 and not a "
            "new hypothesis."
        ),
        null_hypothesis=(
            "The return to holding short variance across non-trading time is not "
            "positive after the full statutory cost stack, and it is not "
            "distinguishable, on a risk-matched basis over the same window and the "
            "identical cost model, from the return to holding the same exposure across "
            "trading time. That is: there is no premium specific to the "
            "overnight/holiday gap, only the general variance premium H1 already tests."
        ),
        predictors=[
            "calendar_days_spanned_by_gap",
            "trading_days_spanned_by_gap",
            "atm_implied_variance_at_entry",
        ],
        entry_rule={
            "instrument": "NIFTY at-the-money straddle, nearest listed expiry",
            "side": "sell",
            "size": "1 lot, unconditional, opened only when the book is flat",
            "candidate_arm": "sell at the close decision, buy back at the next open decision",
            "benchmark_arm": "sell at the open decision, buy back at the same session's close",
            "eligibility": (
                "both arms trade only sessions whose front expiry is strictly after the "
                "session date, so the two arms face an identical population"
            ),
            "open_decision_ist": OPEN_DECISION.isoformat(),
            "close_decision_ist": CLOSE_DECISION.isoformat(),
            "strike_rule": (
                "at-the-money against the spot printed at each arm's OWN entry minute, so "
                "the two arms may hold different strikes on a day the index moves "
                "intraday. This is the economically natural rule and it is recorded "
                "because it means the arms are not the identical contract."
            ),
        },
        exit_rule={
            "exit": "bought back at the paired decision minute; never held to settlement",
            "atomicity": (
                "both legs exit as one leg group: closing one alone would leave a naked "
                "short. The cost is the opposite failure — neither leg closes and the "
                "straddle is carried further, which the run reports as GROUP_INCOMPLETE"
            ),
            "stop": "none — a stop is a separate research decision and a separate trial",
        },
        thresholds=THRESHOLDS,
        notes=(
            "GRADED FORMULATION, and the one deliberately NOT graded. Two readings were "
            "available. (a) The general overnight-versus-intraday split, which has 62 "
            "observable gap events in-sample. (b) The calendar/trading-time wedge "
            "specifically, which isolates to the 19 in-sample multi-day gaps and, in its "
            "strongest holiday-extended form, to 2. This record grades (a), because every "
            "overnight IS non-trading time — the mechanism applies to all 62 gaps and the "
            "weekend is the amplified case, not a different case. (b) is reported in "
            "DECISION.md as a DESCRIPTIVE, UNGRADED dose-response and cannot change the "
            "outcome; its predicted sign is committed in gate.toml before the run.\n\n"
            "WHAT THIS EXPRESSION CANNOT SEE. The corpus carries only the front weekly "
            "expiry, so a straddle cannot be held across the night that its own contract "
            "expires, and the next contract has no bars to roll into. Every "
            "expiry-Tuesday-close to Wednesday-open gap is therefore absent from the "
            "sample — a distinctive population, being the first night of a new front week "
            "after an IV reset. The exclusion is a CAPTURE-SCOPE limitation (spec 3 C1), "
            "not a market fact, and no result here may be read as evidence about "
            "post-expiry overnights.\n\n"
            "THE MISSING TAIL. The premium claimed here is compensation for gap risk. In "
            "a sample this short the insured event has most likely simply not happened, "
            "and the skew/kurtosis correction inside the probabilistic Sharpe can only "
            "adjust for a tail it can SEE. A pass would therefore be evidence that the "
            "seller was paid in a window where the gap mostly did not occur, which is not "
            "the same thing as evidence the premium is free. This sentence is written "
            "before the run precisely so a favourable number cannot be read as more than "
            "it is."
        ),
    )
