"""European cash settlement, against a rule that is stored and dated rather than coded.

Indian index options are **European and cash-settled against the last half hour of the
underlying** — not against the close. That is not a detail to be tidied up later; it is
the reason several US-derived hypotheses do not transfer. A pin-risk or
close-to-settlement effect documented on SPX, where settlement is an opening auction
print, describes a different random variable here. A backtester that settles at the
15:29 close is therefore not slightly imprecise: on expiry day it is measuring something
the exchange does not pay.

**Why the rule is a dated table rather than a constant.** The acceptance criterion is
that expiry settles against *the stored formula for that date*, and settlement
methodology is exactly the kind of thing a circular changes — the last three years alone
moved expiry weekday, contract size and the exchange each series lists on. A constant
buried in a function would make a future change indistinguishable from a bug, and would
make two results computed either side of it look comparable. The table costs four lines
and makes the change a row.

**What is computed, and what NSE's wording says.** NSE defines the closing value of the
index as the *weighted* average of the index over the last thirty minutes. This module
computes the **unweighted mean of the underlying's minute closes** in that window, and
the divergence is forced rather than chosen: the corpus carries no index-level volume —
the index's own rows have null ``volume`` and ``oi`` — so no weight exists to apply. The
method is therefore named for what it computes
(:data:`METHOD_MEAN_UNDERLYING_MINUTE_CLOSE`) and not for what the exchange calls it, so
that nobody reads the code and concludes the weighting was implemented. On a 30-minute
window of a large-cap index the two differ by small change; that is a reason to proceed,
not a reason to call them the same thing.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from xman_research.backtest.costs import Confidence
from xman_research.backtest.market import SessionView

__all__ = [
    "METHOD_MEAN_UNDERLYING_MINUTE_CLOSE",
    "SETTLEMENT_RULES",
    "SettlementRule",
    "SettlementValue",
    "SettlementWindowError",
    "settlement_rule_for",
    "settlement_value",
]

#: The one method implemented. Named for the computation, not for the exchange's term.
METHOD_MEAN_UNDERLYING_MINUTE_CLOSE = "mean_of_underlying_minute_close_over_window"


class SettlementWindowError(Exception):
    """The settlement window did not hold the bars the rule requires.

    Raised rather than averaging whatever is present. A window short of its bars produces
    a number that is silently a different statistic — an average over 11 minutes wearing
    the name of an average over 30 — and it would land in a result that reports itself
    clean. The caller decides what to do about a session that cannot settle; it must not
    be decided here by default.
    """


@dataclass(frozen=True, slots=True)
class SettlementRule:
    """How final settlement value is derived, in force from a date."""

    effective_from: dt.date
    method: str
    window_start: dt.time
    window_end: dt.time
    expected_bars: int
    source: str
    source_url: str
    confidence: Confidence
    implemented: bool = True
    note: str = ""


#: The one method that is implemented. Its sibling below deliberately is not.
METHOD_CLOSING_AUCTION_EQUILIBRIUM = "closing_auction_session_equilibrium_price"

#: Settlement methodology by effective date.
#:
#: **The second entry is the argument for the whole table.** NSE launched a Closing
#: Auction Session on 3 August 2026: for F&O-listed stocks the closing price became the
#: auction's equilibrium price rather than the last-30-minute VWAP, and since the index
#: close is built bottom-up from constituent closes, index-option final settlement
#: inherits it. That is a change of *statistic*, mid-corpus-lifetime, nine days before
#: this component was written. A constant in a function would have absorbed it silently
#: and every expiry after it would have been settled against a formula the exchange had
#: stopped using.
#:
#: The current corpus ends 2026-06-12, entirely inside the first regime, so nothing here
#: is presently affected. The CAS entry is carried with ``implemented=False`` so that the
#: moment a backfill or a resumed capture reaches past 3 August 2026, settlement
#: **refuses** rather than quietly applying the superseded rule.
SETTLEMENT_RULES: tuple[SettlementRule, ...] = (
    SettlementRule(
        effective_from=dt.date(2010, 1, 1),
        method=METHOD_MEAN_UNDERLYING_MINUTE_CLOSE,
        window_start=dt.time(15, 0),
        window_end=dt.time(15, 30),
        expected_bars=30,
        implemented=True,
        source="NSE — final settlement value for index options is the closing value of "
        "the index on expiry day, the closing value being the volume-weighted average "
        "of the index over the last 30 minutes of trading",
        source_url="https://www.nseindia.com/products-services/equity-derivatives-settlement",
        confidence=Confidence.CORROBORATED,
        note=(
            "Two caveats, neither cosmetic. (1) The exchange's average is VOLUME-WEIGHTED, "
            "built bottom-up from constituent VWAPs; this computes the UNWEIGHTED mean of "
            "the index's own minute closes, because the corpus carries no index-level "
            "volume and therefore no weights. The divergence is small on a large-cap index "
            "over 30 minutes and it is real. (2) The effective_from date asserts that this "
            "methodology covers every session the corpus can reach; it is not a claim that "
            "it began in 2010, and it is the weakest field in this table."
        ),
    ),
    SettlementRule(
        effective_from=dt.date(2026, 8, 3),
        method=METHOD_CLOSING_AUCTION_EQUILIBRIUM,
        window_start=dt.time(15, 15),
        window_end=dt.time(15, 35),
        expected_bars=0,
        implemented=False,
        source="SEBI circular HO/47/11/11(3)2025-MRD-POD2/I/2765/2026 (16 Jan 2026) and "
        "NSE's implementing circular; Closing Auction Session live from 3 Aug 2026",
        source_url="https://www.nseindia.com/static/products-services/closing-auction-session",
        confidence=Confidence.CORROBORATED,
        note=(
            "Not implemented, and not implementable from minute bars: the equilibrium "
            "price of a call auction is not recoverable from OHLC of continuous trading. "
            "Any session on or after this date must refuse to settle until the corpus "
            "carries the auction print. Fallback behaviour when CAS does not conclude for "
            "a constituent is UNVERIFIED — the circular text could not be retrieved."
        ),
    ),
)


@dataclass(frozen=True, slots=True)
class SettlementValue:
    """The settled value of the underlying, and what it was derived from."""

    session_date: dt.date
    underlying: str
    value: float
    bars_used: int
    window_start: dt.datetime
    window_end: dt.datetime
    rule: SettlementRule

    def provenance(self) -> dict[str, object]:
        return {
            "session_date": self.session_date.isoformat(),
            "underlying": self.underlying,
            "value": self.value,
            "bars_used": self.bars_used,
            "window": f"{self.window_start.isoformat()}..{self.window_end.isoformat()}",
            "method": self.rule.method,
            "rule_effective_from": self.rule.effective_from.isoformat(),
            "confidence": str(self.rule.confidence),
        }


def settlement_rule_for(
    on: dt.date, rules: tuple[SettlementRule, ...] = SETTLEMENT_RULES
) -> SettlementRule:
    """The settlement rule in force on ``on``, or a refusal."""
    found: SettlementRule | None = None
    for rule in sorted(rules, key=lambda item: item.effective_from):
        if rule.effective_from <= on:
            found = rule
        else:
            break
    if found is None:
        raise SettlementWindowError(
            f"no settlement rule recorded for {on.isoformat()} — the table starts on "
            f"{min(rule.effective_from for rule in rules).isoformat()}."
        )
    return found


def settlement_value(
    session: SessionView,
    *,
    rules: tuple[SettlementRule, ...] = SETTLEMENT_RULES,
    minimum_bars: int | None = None,
) -> SettlementValue:
    """Settle ``session``'s underlying against the rule in force that day.

    ``minimum_bars`` defaults to the rule's ``expected_bars`` — the full window. Accepting
    a short window is a decision with a name, so it is a parameter a caller passes
    deliberately rather than a tolerance that quietly absorbs a bad session.
    """
    rule = settlement_rule_for(session.session_date, rules)
    if not rule.implemented:
        raise SettlementWindowError(
            f"{session.underlying} {session.session_date}: the settlement rule in force "
            f"from {rule.effective_from.isoformat()} is '{rule.method}', which this "
            f"component does not implement — {rule.note} Settling this session under the "
            f"superseded rule would produce a number the exchange does not pay."
        )
    required = rule.expected_bars if minimum_bars is None else minimum_bars

    window = [
        bar
        for bar in session.underlying_bars()
        if rule.window_start <= bar.minute.replace(tzinfo=None).time() < rule.window_end
    ]
    if len(window) < required:
        raise SettlementWindowError(
            f"{session.underlying} {session.session_date}: the settlement window "
            f"{rule.window_start}..{rule.window_end} holds {len(window)} underlying bars, "
            f"fewer than the {required} the rule requires. Averaging what is present would "
            f"produce a different statistic under the same name."
        )
    total = 0.0
    for bar in window:
        total += bar.close
    return SettlementValue(
        session_date=session.session_date,
        underlying=session.underlying,
        value=total / len(window),
        bars_used=len(window),
        window_start=window[0].minute,
        window_end=window[-1].minute,
        rule=rule,
    )
