"""European cash settlement, against a rule that is stored and dated rather than coded.

Indian index options are **European and cash-settled against a value the exchange fixes
at the close** — not against the last traded price of the option, and not against a
number this package is free to choose. That is not a detail to be tidied up later; it is
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
and makes the change a row. It has now earned itself once: the statistic changed under
the corpus on 3 August 2026 and the table is what turned that into a row rather than a
silent bias on every expiry after it.

**What is computed, and what NSE's wording says.** Until 3 August 2026 NSE defined the
closing value of the index as the *weighted* average of the index over the last thirty
minutes. This module computes the **unweighted mean of the underlying's minute closes**
in that window, and the divergence is forced rather than chosen: the corpus carries no
index-level volume — the index's own rows have null ``volume`` and ``oi`` — so no weight
exists to apply. The method is therefore named for what it computes
(:data:`METHOD_MEAN_UNDERLYING_MINUTE_CLOSE`) and not for what the exchange calls it, so
that nobody reads the code and concludes the weighting was implemented. On a 30-minute
window of a large-cap index the two differ by small change; that is a reason to proceed,
not a reason to call them the same thing.

**The second regime, and why it is a proxy with its own name.** From 3 August 2026 the
exchange settles against a Closing Auction Session equilibrium price. No primary text for
that rule could be retrieved from this host — NSE's settlement page times out and the
SEBI circular URL 404s, as they have for weeks — so nothing here claims to implement it.
What *is* implemented is a different, measurable thing: the last print the index makes
inside a stated closing window (:data:`METHOD_LAST_UNDERLYING_PRINT`), which the corpus
does carry, and which is checked on every use against an independent witness before it is
returned. See :func:`option_implied_settlement` for the witness and
:data:`SETTLEMENT_RULES` for what the measurement showed. The rule is stamped
``UNVERIFIED`` for the honest reason: the proxy tracks whatever the exchange used, and
that is not the same as knowing what the exchange's rule says.
"""

from __future__ import annotations

import datetime as dt
import statistics
from dataclasses import dataclass

from xman_research.backtest.costs import Confidence
from xman_research.backtest.market import Bar, OptionType, SessionView

__all__ = [
    "METHOD_CLOSING_AUCTION_EQUILIBRIUM",
    "METHOD_LAST_UNDERLYING_PRINT",
    "METHOD_MEAN_UNDERLYING_MINUTE_CLOSE",
    "MINIMUM_CORROBORATING_PAIRS",
    "SETTLEMENT_RULES",
    "OptionImpliedSettlement",
    "SettlementRule",
    "SettlementValue",
    "SettlementWindowError",
    "option_implied_settlement",
    "settlement_rule_for",
    "settlement_value",
]

#: The window-mean method. Named for the computation, not for the exchange's term.
METHOD_MEAN_UNDERLYING_MINUTE_CLOSE = "mean_of_underlying_minute_close_over_window"

#: What the exchange computes from 3 August 2026. **Not implemented, and not a method
#: name any result carries** — the equilibrium price of a call auction is not recoverable
#: from minute bars of continuous trading. It is named so that the thing being proxied has
#: a name distinct from the proxy, and so a future corpus that carries the auction print
#: can add a row without renaming this one.
METHOD_CLOSING_AUCTION_EQUILIBRIUM = "closing_auction_session_equilibrium_price"

#: The proxy method: the last print the index makes inside the rule's closing window.
#: Named for the computation. It is not the auction price and does not claim to be.
METHOD_LAST_UNDERLYING_PRINT = "last_underlying_print_in_closing_window"

#: How many strikes must quote both a call and a put before put-call parity is treated as
#: a witness at all. Three is enough that one stale quote cannot carry the median, and low
#: enough that a thin chain still corroborates. The real corpus offers 21.
MINIMUM_CORROBORATING_PAIRS = 3


class SettlementWindowError(Exception):
    """The settlement window did not hold the bars the rule requires.

    Raised rather than averaging whatever is present. A window short of its bars produces
    a number that is silently a different statistic — an average over 11 minutes wearing
    the name of an average over 30 — and it would land in a result that reports itself
    clean. The caller decides what to do about a session that cannot settle; it must not
    be decided here by default.

    It is also raised when a settled value fails corroboration, which is the same failure
    wearing different clothes: a number that would be returned under a name it has not
    earned.
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
    corroboration_tolerance: float | None = None
    """How far the settled value may sit from the option chain's own view of it.

    ``None`` means no corroboration is attempted, which is the right setting for a rule
    whose statistic the option chain does not price — the pre-auction rule settles on a
    30-minute average, and an option one minute before expiry prices that average, not the
    spot, so the two agree by construction and the check would prove nothing.

    A number means every settled value is checked against
    :func:`option_implied_settlement` and refused if it misses by more than this.
    """


#: Settlement methodology by effective date.
#:
#: **The second entry is the argument for the whole table.** NSE launched a Closing
#: Auction Session on 3 August 2026: for F&O-listed stocks the closing price became the
#: auction's equilibrium price rather than the last-30-minute VWAP, and since the index
#: close is built bottom-up from constituent closes, index-option final settlement
#: inherits it. That is a change of *statistic*, mid-corpus-lifetime. A constant in a
#: function would have absorbed it silently and every expiry after it would have been
#: settled against a formula the exchange had stopped using.
#:
#: **What the corpus was measured to hold, before the second row was implemented.** Three
#: facts, all from the captured NIFTY sessions and all reproduced by
#: ``tests/test_settlement_real_corpus.py``:
#:
#: 1. The 15:00-15:30 index feed degrades at exactly this boundary. Before 3 August a
#:    session's 30 window bars carry 28-30 *distinct* closes; from 3 August they carry
#:    15-17, the feed freezing for ten-plus minutes and then catching up in one jump. The
#:    old statistic is therefore not merely superseded — it is no longer computable from
#:    this feed, because most of its inputs are repeats rather than observations.
#: 2. Expiring options gain a post-close print window at the same boundary — bars to
#:    15:39, with real volume and falling open interest, at pure intrinsic — where every
#:    strike agrees on one underlying value. That value is the witness.
#: 3. On all three post-auction expiries the corpus reaches (2026-08-04, -08-11, -08-18)
#:    the witness sits **0.15, 0.15 and 0.25 points** from the index's last print, and
#:    **146.3, 17.1 and 28.8 points** from the superseded 30-minute mean. Before the
#:    boundary the same witness sits within 0.03-8.0 points of the 30-minute mean while
#:    missing the last print by up to 51.9 — which is what makes the pre-auction row's
#:    statistic the right one for its own regime, and the post-auction row's a different
#:    measurement rather than a worse version of the same one.
#:
#: ``corroboration_tolerance`` is set from the **gap** those numbers leave, not from a
#: calibration three expiries cannot support: agreement was never worse than 0.25 and the
#: wrong statistic was never closer than 17.1, so any threshold in that empty band
#: separates them. Five points is one.
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
        method=METHOD_LAST_UNDERLYING_PRINT,
        window_start=dt.time(15, 28),
        window_end=dt.time(15, 45),
        expected_bars=1,
        implemented=True,
        source="SEBI circular HO/47/11/11(3)2025-MRD-POD2/I/2765/2026 (16 Jan 2026) and "
        "NSE's implementing circular; Closing Auction Session live from 3 Aug 2026. "
        "NEITHER TEXT WAS RETRIEVABLE from this host — the NSE page times out and the "
        "SEBI URL returns 404 — so the rule is recorded from secondary recollection and "
        "the implementation below deliberately does not attempt it.",
        source_url="https://www.nseindia.com/static/products-services/closing-auction-session",
        confidence=Confidence.UNVERIFIED,
        corroboration_tolerance=5.0,
        note=(
            "A PROXY, stamped as one. The exchange settles on the auction's equilibrium "
            "price; that print is not in the corpus and cannot be reconstructed from "
            "minute bars of continuous trading. What is computed is the last index print "
            "inside 15:28-15:45, taken because the expiring option chain — which settles "
            "against the real thing and trades at pure intrinsic in the post-close window "
            "this regime opened — agrees with it to a quarter of a point on every expiry "
            "the corpus reaches, while disagreeing with the superseded 30-minute mean by "
            "17 to 146. Every settled value under this rule is checked against that "
            "witness before it is returned, and every result computed through it carries "
            "settlement.last_underlying_print_in_closing_window:unverified. The tier is "
            "UNVERIFIED because no source states the rule: the measurement shows the proxy "
            "tracks whatever the exchange used, which is not the same as knowing what it "
            "used. It becomes CONFIRMED when the corpus carries the auction print itself, "
            "at which point this row is superseded rather than upgraded."
        ),
    ),
)


@dataclass(frozen=True, slots=True)
class OptionImpliedSettlement:
    """What the expiring option chain says the underlying settled at.

    Put-call parity on a European option at expiry has no discounting and no time value
    left to argue about: ``C - P = S - K`` exactly, so every strike that quotes both sides
    is an independent estimate of ``S``. The median across strikes is taken rather than
    the mean because the far wings quote the 0.05 tick floor, and a floor is a censored
    observation rather than a wrong one — it biases a mean and cannot move a median.

    This is a **witness, not a source**. It says what the market that settles against the
    exchange's number believed that number to be, minutes before it was published. That is
    enough to catch a settled value that is wrong by points; it is not enough to define the
    exchange's rule, and nothing here treats it as if it were.
    """

    minute: dt.datetime
    value: float
    pairs: int
    dispersion: float

    def provenance(self) -> dict[str, object]:
        return {
            "minute": self.minute.isoformat(),
            "value": self.value,
            "pairs": self.pairs,
            "dispersion": self.dispersion,
        }


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
    corroboration: OptionImpliedSettlement | None = None

    def provenance(self) -> dict[str, object]:
        record: dict[str, object] = {
            "session_date": self.session_date.isoformat(),
            "underlying": self.underlying,
            "value": self.value,
            "bars_used": self.bars_used,
            "window": f"{self.window_start.isoformat()}..{self.window_end.isoformat()}",
            "method": self.rule.method,
            "rule_effective_from": self.rule.effective_from.isoformat(),
            "confidence": str(self.rule.confidence),
        }
        if self.corroboration is not None:
            record["corroborated_by_option_parity"] = self.corroboration.provenance()
            record["corroboration_residual"] = abs(self.value - self.corroboration.value)
        return record


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


def option_implied_settlement(
    session: SessionView, *, minimum_pairs: int = MINIMUM_CORROBORATING_PAIRS
) -> OptionImpliedSettlement | None:
    """The chain's own view of the settled underlying, or ``None`` if it has no view.

    Read from the **last** minute of the session at which ``minimum_pairs`` strikes quote
    both a call and a put expiring today — the latest moment at which the market's estimate
    of the settlement value is expressed, and under the post-auction regime a moment after
    the cash close, when the expiring options carry no time value at all.

    Contracts come from :class:`~xman_research.backtest.market.ContractUniverse`, never
    from the trading symbol's spelling. The symbol plainly encodes its expiry and strike
    and reading them out of it is the mistake the sibling repo deleted a whole module for.
    """
    expiry = session.session_date
    strikes = session.universe.strikes(expiry)
    if len(strikes) < minimum_pairs:
        return None
    pairs: list[tuple[float, str, str]] = []
    for strike in strikes:
        call = session.universe.get(expiry, strike, OptionType.CALL)
        put = session.universe.get(expiry, strike, OptionType.PUT)
        if call is None or put is None:
            continue
        pairs.append((strike, call.trading_symbol, put.trading_symbol))
    if len(pairs) < minimum_pairs:
        return None

    for minute in reversed(session.minutes()):
        implied: list[float] = []
        for strike, call_symbol, put_symbol in pairs:
            call_bar = session.bar(call_symbol, minute)
            put_bar = session.bar(put_symbol, minute)
            if call_bar is None or put_bar is None:
                continue
            implied.append(strike + call_bar.close - put_bar.close)
        if len(implied) < minimum_pairs:
            continue
        return OptionImpliedSettlement(
            minute=minute,
            value=statistics.median(implied),
            pairs=len(implied),
            dispersion=max(implied) - min(implied),
        )
    return None


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
    window = _window_bars(session, rule)
    if rule.method == METHOD_LAST_UNDERLYING_PRINT:
        return _settle_on_last_print(session, rule, window, minimum_bars)
    return _settle_on_window_mean(session, rule, window, minimum_bars)


def _window_bars(session: SessionView, rule: SettlementRule) -> list[Bar]:
    return [
        bar
        for bar in session.underlying_bars()
        if rule.window_start <= bar.minute.replace(tzinfo=None).time() < rule.window_end
    ]


def _settle_on_window_mean(
    session: SessionView, rule: SettlementRule, window: list[Bar], minimum_bars: int | None
) -> SettlementValue:
    """The pre-auction statistic: the unweighted mean of the window's minute closes."""
    required = rule.expected_bars if minimum_bars is None else minimum_bars
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


def _settle_on_last_print(
    session: SessionView, rule: SettlementRule, window: list[Bar], minimum_bars: int | None
) -> SettlementValue:
    """The post-auction proxy: the last index print inside the closing window, corroborated.

    **The window is a filter, not a formality.** The corpus contains index rows stamped
    hours after the close — 2026-08-19 carries one at 18:40 — and "the last print of the
    session" would take them. What is wanted is the last print of *the close*, so a bar
    outside 15:28-15:45 is not a late close, it is not a close at all, and a session whose
    feed stopped before the window cannot settle rather than settling on whatever it
    stopped at.
    """
    required = rule.expected_bars if minimum_bars is None else minimum_bars
    if len(window) < required:
        total_bars = len(session.underlying_bars())
        raise SettlementWindowError(
            f"{session.underlying} {session.session_date}: the closing window "
            f"{rule.window_start}..{rule.window_end} holds {len(window)} underlying bars, "
            f"fewer than the {required} the rule requires (the session printed "
            f"{total_bars} underlying bars in total). Under "
            f"'{METHOD_CLOSING_AUCTION_EQUILIBRIUM}' the settled value is a closing print; "
            f"a print from outside the closing window is not a late one, it is a different "
            f"observation, and settling on it would put an arbitrary minute's price into "
            f"every payoff of the day."
        )
    settled = window[-1]
    corroboration = option_implied_settlement(session)
    if rule.corroboration_tolerance is not None and corroboration is not None:
        residual = abs(settled.close - corroboration.value)
        if residual > rule.corroboration_tolerance:
            raise SettlementWindowError(
                f"{session.underlying} {session.session_date}: the closing print "
                f"{settled.close} at {settled.minute.time()} misses the expiring chain's "
                f"own view of the settled value ({corroboration.value}, from "
                f"{corroboration.pairs} put-call pairs at "
                f"{corroboration.minute.time()}) by {residual:.2f} points, more than the "
                f"{rule.corroboration_tolerance} this rule allows. The proxy is only "
                f"defensible while the two agree — that agreement, not a source, is what "
                f"licenses it — so a session where they diverge does not settle."
            )
    return SettlementValue(
        session_date=session.session_date,
        underlying=session.underlying,
        value=settled.close,
        bars_used=1,
        window_start=settled.minute,
        window_end=settled.minute,
        rule=rule,
        corroboration=corroboration,
    )
