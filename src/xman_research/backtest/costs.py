"""The Indian statutory cost stack, as dated reference data.

**This is not a model and it is not pluggable.** The HLD review settled that
distinction and it is worth restating where the code lives: ``ICostModel`` in FR-BT-03
is the *slippage* abstraction — what a fill costs you beyond the printed price, which
nobody can know from OHLC bars and which a better data source will one day improve.
The statutory stack is the opposite kind of thing: it is the law, it is knowable
exactly, and the only legitimate variation across two runs of the same backtest is the
*date*. So slippage sits behind a Protocol in :mod:`xman_research.backtest.execution`
and this module has no Protocol at all — only a table with validity intervals.

Consequently every number here carries three things: an **effective date**, a
**source**, and a **confidence**. The confidence field exists because the alternative
to admitting an unverified rate is inventing one, and a wrong rate does not announce
itself — it scales every result by a constant that looks like alpha. Anything not
:attr:`Confidence.CONFIRMED` is propagated out of :meth:`StatutoryCostStack.charge` in
:attr:`CostBreakdown.unverified_components` and travels all the way to the backtest
result, so a headline number computed on a guessed rate says so.

**A schedule never refuses a date.** A trade before a schedule's earliest entry is charged
that schedule's *latest* rate and stamped ``costs.rate_extrapolated:<schedule>`` through
the same channel — owner decision of 2026-08-20, generalising the declared-lot-size
decision of 2026-08-13. The rule it replaced refused, and was thereby discarding 772 of
1,233 captured sessions. Extrapolation fills the unknown ends **only**; every dated change
that is actually recorded still applies on its own date. The direction of the resulting
error is **per schedule, not uniform**: STT has only been revised upward, so extrapolating
it overcharges — conservative, and therefore capable of hiding a real effect rather than
inventing one — while the NSE transaction charge was revised *downward* in 2024, so
extrapolating that one would undercharge and flatter a result.
:func:`extrapolation_message` derives the direction from the schedule it is given and
states both halves; it is what the stamp points a reader to.

**Two traps this module exists to avoid.**

*The expiry-settlement trap.* An index option that expires in the money is exercised,
and exercise attracts STT at a different rate on a different base — the **intrinsic**
value, not the premium. A backtest that charges only the premium-side rates is wrong by
the entire settlement charge on every held-to-expiry position, which for a strategy that
holds to expiry by design is most of them. See :data:`STT_ON_EXERCISE`.

*The attribution trap, which points the other way.* Exercise STT is levied on the
**purchaser** — the holder of the long. A short position that is assigned pays it not at
all. That is the direction of error that **flatters** a short-variance result, which is
H1, which is the hypothesis this platform was built to judge. It therefore gets the
loudest treatment available: its own line item in :class:`CostBreakdown` that is never
folded into a subtotal, its own confidence marker, and an explicit
:attr:`ExerciseSttRule.payer` field rather than a sign convention buried in an ``if``.

**What is deliberately absent:** rounding. Brokers round GST to paise and some round
brokerage per order; this charges exact floats. Rounding is a per-broker behaviour worth
a rupee a trade and worth nothing to the question being asked, and floating-point
determinism is worth more (see :mod:`xman_research.backtest.engine`).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum

__all__ = [
    "BROKERAGE_ZERODHA_FNO",
    "EXCHANGE_TRANSACTION_CHARGE",
    "GST",
    "SEBI_TURNOVER_FEE",
    "STAMP_DUTY",
    "STT_ON_EXERCISE",
    "STT_ON_SELL_PREMIUM",
    "BrokerageModel",
    "ChargeableTrade",
    "Confidence",
    "CostBreakdown",
    "FlatPerOrderBrokerage",
    "RateLookup",
    "RateSchedule",
    "Side",
    "StatutoryCostStack",
    "StatutoryRate",
    "TradeKind",
    "extrapolation_message",
]


class Confidence(StrEnum):
    """How well a rate in this file is sourced.

    ``CONFIRMED`` — a primary source says this: a Finance Act, an NSE or SEBI circular,
    a gazette notification. ``CORROBORATED`` — no primary text was reachable, but a
    published broker charge-list or comparable secondary source states it. ``UNVERIFIED``
    — believed correct and **not** checked; any result computed with it is provisional.
    """

    CONFIRMED = "confirmed"
    CORROBORATED = "corroborated"
    UNVERIFIED = "unverified"


class Side(StrEnum):
    """The side of a transaction. Settlement of a long is a ``SELL``; see :class:`TradeKind`."""

    BUY = "buy"
    SELL = "sell"


class TradeKind(StrEnum):
    """What kind of chargeable event this is.

    ``TRADE`` — an ordinary buy or sell of an option in the market, charged on premium
    turnover. ``SETTLEMENT`` — the exchange cash-settling an in-the-money option at
    expiry, charged (if at all) on intrinsic value.

    **The side convention for settlement is the one place this module is easy to get
    backwards.** A settlement that closes a *long* position carries ``Side.SELL``, and a
    settlement that closes a *short* position carries ``Side.BUY`` — the side is what the
    holder does to flatten, exactly as for a trade. Exercise STT is then charged on
    ``SETTLEMENT`` + ``SELL``, which is the purchaser, which is the law. Both directions
    are covered by tests precisely because the convention is not self-evident.
    """

    TRADE = "trade"
    SETTLEMENT = "settlement"


#: Stamp prefix for a rate that was extrapolated rather than looked up. Deliberately
#: low-cardinality — the schedule name only, never the date — because ``unverified_inputs``
#: is set-deduplicated at three layers and a per-session stamp would blow it up to
#: hundreds of entries that say the same thing.
RATE_EXTRAPOLATION_STAMP_PREFIX = "costs.rate_extrapolated"


def extrapolation_message(schedule: RateSchedule) -> str:
    """What an extrapolated-rate stamp means, including the direction of the error.

    Mirrors :meth:`~xman_research.backtest.lot_size.LotSizeAudit.contradiction_message`:
    a stamp that only said "something is approximate here" would be read as either fatal
    or ignorable, and it is neither. Both halves of the argument belong in the text.

    **The direction is derived from the schedule, never asserted globally.** An earlier
    draft of this function claimed these charges "have only ever been revised upward",
    which is false: ``nse.transaction_charge.options`` fell from 0.05% to 0.03503% on
    1 Oct 2024. Extrapolating that schedule would *understate* the charge, and a stamp
    that told the reader they were overcharged would be worse than no stamp at all.
    """
    latest, earliest = schedule.entries[-1], schedule.entries[0]
    head = (
        f"{schedule.name}: the trade date precedes the earliest entry in this schedule "
        f"({earliest.effective_from.isoformat()}), so the LATEST entry's rate "
        f"({latest.rate!r}, effective {latest.effective_from.isoformat()}) was charged "
        "instead of refusing the session — owner decision of 2026-08-20, generalising the "
        "declared-lot-size decision of 2026-08-13. "
    )
    if latest.rate > earliest.rate:
        return head + (
            "DIRECTION OF ERROR: this schedule has been revised UPWARD, so the rate "
            f"charged ({latest.rate!r}) is higher than the earliest recorded rate "
            f"({earliest.rate!r}) and almost certainly higher than the true historical "
            "one — the session is charged MORE than it truly bore. For "
            "stt.sell_option_premium the 2021-2024 rate was most likely 0.05% against the "
            "0.15% charged, which OVERSTATES that component by roughly 3x. That direction "
            "is conservative: it makes a hypothesis harder to pass and cannot manufacture "
            "a positive result out of a negative one. THE COST OF THAT SAFETY: an "
            "overstated cost floor can SUPPRESS a real effect — a strategy whose true edge "
            "cleared its true costs may be recorded here as failing to clear inflated "
            "ones. A negative result on an extrapolated window is therefore not evidence "
            "of no edge, and this stamp is what tells a reader which way to distrust it."
        )
    if latest.rate < earliest.rate:
        return head + (
            "DIRECTION OF ERROR: this schedule has been revised DOWNWARD, so the rate "
            f"charged ({latest.rate!r}) is LOWER than the earliest recorded rate "
            f"({earliest.rate!r}). The session is therefore charged LESS than it likely "
            "bore, and this extrapolation is NOT conservative: it flatters the result and "
            "could help a hypothesis pass on costs it would not really have survived. "
            "Treat a positive result on a window carrying this stamp as unproven until "
            "the historical entry is sourced and added."
        )
    return head + (
        "DIRECTION OF ERROR: this schedule records no rate change, so there is no "
        "observed trend to extrapolate along and the single known rate is simply carried "
        "back. The error is whatever undocumented change preceded the earliest entry; its "
        "size and its sign are both unknown, which is weaker than the upward-revision "
        "case and should not be read as 'probably fine'."
    )


@dataclass(frozen=True, slots=True)
class RateLookup:
    """The entry a schedule charges on a date, and whether reaching it needed extrapolation.

    ``extrapolated`` is True only when the date falls **before** the schedule's earliest
    entry. A date after the last entry is *not* extrapolation: a statutory rate stays in
    force until it is amended, so the final entry is open-ended forward by construction.
    """

    entry: StatutoryRate
    extrapolated: bool
    schedule_name: str

    @property
    def rate(self) -> float:
        return self.entry.rate

    @property
    def stamp(self) -> str | None:
        """The ``unverified_inputs`` stamp this lookup earns, if any."""
        if not self.extrapolated:
            return None
        return f"{RATE_EXTRAPOLATION_STAMP_PREFIX}:{self.schedule_name}"


@dataclass(frozen=True, slots=True)
class StatutoryRate:
    """One rate, in force from a date, with the provenance that makes it checkable."""

    effective_from: dt.date
    rate: float
    base: str
    side: str
    source: str
    source_url: str
    confidence: Confidence
    note: str = ""


@dataclass(frozen=True, slots=True)
class RateSchedule:
    """A named sequence of :class:`StatutoryRate` entries with validity intervals.

    Entries are held sorted by ``effective_from`` and looked up by the **trade date**,
    never by the wall clock — a 2024 backtest run today charges 2024's rates.
    """

    name: str
    entries: tuple[StatutoryRate, ...]

    def __post_init__(self) -> None:
        if not self.entries:
            raise ValueError(f"{self.name}: a schedule with no entries cannot charge anything")
        dates = [entry.effective_from for entry in self.entries]
        if dates != sorted(dates):
            raise ValueError(f"{self.name}: entries must be ordered by effective_from")
        if len(set(dates)) != len(dates):
            raise ValueError(f"{self.name}: two entries share an effective_from")

    def lookup(self, on: dt.date) -> RateLookup:
        """The entry to charge on ``on``. **This never refuses.**

        For any date at or after the earliest entry this is an exact in-force lookup, and
        the dated history is honoured precisely — the 1 Oct 2024 exchange-charge change and
        the 1 Apr 2026 STT rise still apply on their own dates. Extrapolation fills the
        unknown end only; it does not flatten known history.

        For a date *before* the earliest entry the **latest** entry is charged and the
        lookup is flagged. Latest, not nearest: the owner's instruction is to use the
        latest value for data of this kind.

        **It is NOT uniformly the conservative choice, and an earlier draft of this
        docstring said it was.** The direction depends on the individual schedule:
        ``stt.sell_option_premium`` has only been revised upward, so extrapolating it
        overcharges — conservative, and therefore able to hide a real effect rather than
        invent one. ``nse.transaction_charge.options`` was revised *downward* (0.05% ->
        0.03503% on 2024-10-01), so extrapolating that one **undercharges and flatters**
        the result. :func:`extrapolation_message` derives the direction from each
        schedule's own entries; consult it rather than assuming.

        A nearest-entry clamp would charge 0.1% rather than 0.15% on a 2021 session and
        roughly halve the overstatement, at the price of no longer being the latest
        value; that is an owner call, not a code call.
        """
        found: StatutoryRate | None = None
        for entry in self.entries:
            if entry.effective_from <= on:
                found = entry
            else:
                break
        if found is None:
            return RateLookup(entry=self.entries[-1], extrapolated=True, schedule_name=self.name)
        return RateLookup(entry=found, extrapolated=False, schedule_name=self.name)

    def at(self, on: dt.date) -> StatutoryRate:
        """The entry charged on ``on``. Never refuses; see :meth:`lookup`."""
        return self.lookup(on).entry

    def rate_at(self, on: dt.date) -> float:
        return self.lookup(on).rate


# --------------------------------------------------------------------------- the table
#
# Every entry below states where it came from. An entry whose confidence is not CONFIRMED
# is a known hole, is surfaced on every CostBreakdown that touches it, and should be
# closed before any result is acted upon.

#: **The pre-2024 premium-side history has been deleted, on purpose.**
#:
#: Two entries used to sit here: 0.05% from 1 June 2016 (Finance Act 2016) and 0.0625%
#: from 1 September 2019 (Finance (No. 2) Act 2019). Both were UNVERIFIED, and the second
#: is very likely wrong on both counts — the premium-side rise to 0.0625% appears to be
#: **Finance Act 2023, effective 1 April 2023**, with 0.05% holding from 2016 to 2023.
#: What Finance (No. 2) Act 2019 actually changed was the *exercise* side: the base moved
#: from settlement price to intrinsic value. See :data:`STT_ON_EXERCISE`.
#:
#: They were once carried so that a backfill would "not hit an error with no warning",
#: then deleted in favour of a hard refusal, and the refusal is now gone too — **by owner
#: decision of 2026-08-20**. The refusal was dropping 772 of 1,233 captured sessions,
#: which is the entire corpus before 1 Oct 2024, and losing five years of data to protect
#: a rate's precision is the wrong trade. What replaced it is not the old silent
#: backfill: a pre-2024-10-01 date is charged the LATEST rate and the result is STAMPED
#: all the way out to the verdict, so the number is used and the uncertainty is visible.
#: See :func:`extrapolation_message` for the direction of the error. The entries below are
#: still the only *sourced* history; anyone who reads the Finance Act texts should add the
#: real pre-2024 entries with citations and shrink the extrapolated window to nothing.
#:
#: One attempt was made to reach the primary text at incometaxindia.gov.in; it returned
#: HTTP 403, as it had for the reviewer. **No replacement dates were invented from
#: recollection** — the corrected dates above are themselves unverified, which is exactly
#: why they are in a comment and not in the table. Anyone needing a pre-October-2024
#: window reads the Finance Act texts and adds the entries with citations.
STT_ON_SELL_PREMIUM = RateSchedule(
    name="stt.sell_option_premium",
    entries=(
        StatutoryRate(
            effective_from=dt.date(2024, 10, 1),
            rate=0.001,
            base="option premium turnover",
            side="sell",
            source="Finance (No. 2) Act 2024, s. 98 STT schedule amendment",
            source_url="https://www.business-standard.com/markets/news/higher-stt-and-"
            "transaction-charges-on-nse-bse-mcx-effective-today-124100100146_1.html",
            confidence=Confidence.CORROBORATED,
            note="0.1%. The change the acceptance-criteria fixture is built around.",
        ),
        StatutoryRate(
            effective_from=dt.date(2026, 4, 1),
            rate=0.0015,
            base="option premium turnover",
            side="sell",
            source="Finance Bill 2026, clause 143, amending s. 98 of the Finance (No. 2) Act 2004",
            source_url="https://taxguru.in/income-tax/stt-rates-futures-options-hiked-"
            "1st-april-2026.html",
            confidence=Confidence.CORROBORATED,
            note=(
                "0.15%. **The current corpus straddles this date** — it runs 2025-12-16 "
                "to 2026-06-12 — so a backtest over the full corpus charges two STT "
                "regimes and any run that applied one flat rate throughout is wrong by "
                "50% of its largest single cost component over the later third of the "
                "window. This entry is the reason the schedule is dated rather than a "
                "constant, restated in the only way that matters: it caught a live one."
            ),
        ),
    ),
)

STT_ON_EXERCISE = RateSchedule(
    name="stt.exercised_option_intrinsic",
    entries=(
        StatutoryRate(
            effective_from=dt.date(2019, 9, 1),
            rate=0.00125,
            base="intrinsic value (settlement price minus strike, per unit)",
            side="purchaser",
            source="Income Tax Act STT schedule — sale of an option in securities, "
            "where option is exercised; base changed to intrinsic by Finance (No. 2) "
            "Act 2019",
            source_url="https://zerodha.com/z-connect/trending/stt-options-nse-bse-mcx-sx",
            confidence=Confidence.CORROBORATED,
            note=(
                "0.125% of INTRINSIC value (settlement price minus strike), not premium, "
                "and payable by the PURCHASER. Unchanged by the 1 Oct 2024 amendment, "
                "which moved only the premium-side rate. A stale secondary source "
                "describes the base as the entire contract value; every current source "
                "says intrinsic, and intrinsic is used here. See ExerciseSttRule for why "
                "the payer is a field rather than a sign convention. "
                "**This entry used to start on 2016-06-01 and no longer does.** Before "
                "Finance (No. 2) Act 2019 the exercise base was the SETTLEMENT PRICE, not "
                "intrinsic, so extending an intrinsic-based entry back to 2016 charged the "
                "right rate on the wrong base for three years of any backfill — and the "
                "difference is not small, since a deep-in-the-money option's settlement "
                "price is a multiple of its intrinsic value. The 2019-09-01 boundary is "
                "itself UNVERIFIED (the primary text returned HTTP 403); it is the date "
                "from which this entry's own stated base is defensible, not a sourced "
                "commencement. A window reaching earlier must read the Act and add the "
                "settlement-price entry. Until then a pre-2019-09-01 date is charged this "
                "entry's rate under the extrapolation rule and stamped — note that for "
                "THIS schedule the extrapolation is on the wrong BASE, not merely the "
                "wrong rate, which is a larger error than the premium-side case; the "
                "corpus starts 2021-06-01 and so does not currently reach it."
            ),
        ),
        StatutoryRate(
            effective_from=dt.date(2026, 4, 1),
            rate=0.0015,
            base="intrinsic value (settlement price minus strike, per unit)",
            side="purchaser",
            source="Finance Bill 2026, clause 143",
            source_url="https://taxguru.in/income-tax/stt-rates-futures-options-hiked-"
            "1st-april-2026.html",
            confidence=Confidence.CORROBORATED,
            note="0.15%. Raised alongside the premium-side rate; the corpus straddles it.",
        ),
    ),
)

EXCHANGE_TRANSACTION_CHARGE = RateSchedule(
    name="nse.transaction_charge.options",
    entries=(
        StatutoryRate(
            effective_from=dt.date(2021, 1, 1),
            rate=0.0005,
            base="option premium turnover",
            side="both",
            source="NSE transaction charge circular (pre-uniform-rate slab)",
            source_url="https://www.nseindia.com/regulations/exchange-communication-circulars",
            confidence=Confidence.UNVERIFIED,
            note=(
                "0.05% of premium. NSE's pre-October-2024 charge was slab-based on monthly "
                "turnover; this is the top-of-book retail slab and is an approximation for "
                "any operator whose volume earns a lower slab."
            ),
        ),
        StatutoryRate(
            effective_from=dt.date(2024, 10, 1),
            rate=0.0003503,
            base="option premium turnover",
            side="both",
            source="NSE circular FA73061 implementing SEBI/HO/MRD/TPD-1/P/CIR/2024/92 "
            "(uniform fee structure), effective 1 Oct 2024",
            source_url="https://www.bajajbroking.in/blog/nse-and-bse-revise-transaction-"
            "charges-from-october-2024",
            confidence=Confidence.CORROBORATED,
            note=(
                "Rs 3,503 per crore of premium turnover = 0.03503%. **A known open "
                "question sits on top of this entry:** brokers' current rate cards show "
                "NSE at 0.03553%, and no circular or effective date could be found for "
                "the move from 0.03503%. No entry was invented for it — a guessed date "
                "would put a wrong rate on one side of it and a right rate on the other, "
                "which is worse than a uniformly slightly-low charge. The understatement "
                "is 1.4% of this component, which is itself a few percent of the stack, "
                "so it is worth roughly a basis point of a basis point; it is recorded "
                "here rather than fixed because the honest fix is the circular."
            ),
        ),
    ),
)

SEBI_TURNOVER_FEE = RateSchedule(
    name="sebi.turnover_fee",
    entries=(
        StatutoryRate(
            effective_from=dt.date(2021, 1, 1),
            rate=0.000001,
            base="option premium turnover",
            side="both",
            source="SEBI (Regulatory Fee on Stock Exchanges) Regulations, as summarised "
            "on NSE's SEBI-turnover-fees page",
            source_url="https://www.nseindia.com/regulations/member-compliance-sebi-turnover-fees",
            confidence=Confidence.CORROBORATED,
            note=(
                "Rs 10 per crore of premium turnover = 0.0001%. The rate is well "
                "corroborated; its effective date is not, which is why this entry's "
                "effective_from is a floor chosen to cover the corpus rather than a "
                "sourced date. NSE's own wording adds that option turnover for this fee "
                "'shall be additionally computed on the basis of notional value of option "
                "contracts exercised or assigned' — which is why settlement attracts this "
                "one fee and no other. See SETTLEMENT_ATTRACTS_SEBI_FEE_ON_NOTIONAL."
            ),
        ),
    ),
)

STAMP_DUTY = RateSchedule(
    name="stamp_duty.options",
    entries=(
        StatutoryRate(
            effective_from=dt.date(2020, 7, 1),
            rate=0.00003,
            base="option premium turnover",
            side="buy",
            source="Indian Stamp Act 1899 as amended by the Finance Act 2019, uniform "
            "rates notified from 1 July 2020 (PIB release 1635399)",
            source_url="https://www.pib.gov.in/PressReleasePage.aspx?PRID=1635399",
            confidence=Confidence.CONFIRMED,
            note=(
                "0.003% on the buy side. The 2020 amendment made the rate uniform across "
                "states and collected at the exchange, which is why this is a single "
                "national entry rather than a per-state table. Backtests reaching before "
                "1 July 2020 would need the state dimension back."
            ),
        ),
    ),
)

GST = RateSchedule(
    name="gst.broking_services",
    entries=(
        StatutoryRate(
            effective_from=dt.date(2017, 7, 1),
            rate=0.18,
            base="brokerage + exchange transaction charge + SEBI turnover fee",
            side="both",
            source="CGST/SGST on broking services; unchanged by the September 2025 "
            "GST 2.0 slab reform, which left financial services at 18%",
            source_url="https://www.motilaloswal.com/learning-centre/2025/8/everything-"
            "you-need-to-know-about-gst-in-stock-broking",
            confidence=Confidence.CORROBORATED,
            note=(
                "18%. Applies to the service components only — NOT to STT and NOT to "
                "stamp duty, which are taxes rather than consideration for a service. "
                "The 2025 reform was checked specifically because a slab change that "
                "missed broking would have been invisible and would have moved every "
                "post-September-2025 result."
            ),
        ),
    ),
)

#: A discount broker's published F&O rate, as a **default, not a constant**. Brokerage is
#: the one component that is a commercial term rather than a statute, so it is injected
#: (see :class:`BrokerageModel`) and this value only names a plausible starting point.
BROKERAGE_ZERODHA_FNO = 20.0


@dataclass(frozen=True, slots=True)
class ExerciseSttRule:
    """Who pays exercise STT, held as data rather than as a sign convention.

    Encoded separately from the rate because the *payer* is the fact most likely to be
    wrong in a way that improves a short-variance result. Reading
    ``EXERCISE_STT_RULE.payer`` at the point of charge, and asserting on it in a test,
    makes the assumption visible rather than implicit in the direction of an inequality.
    """

    payer: Side
    payer_description: str
    confidence: Confidence


#: The long holder — the "purchaser" in the STT schedule's language — pays exercise STT.
#: A short position that is assigned pays nothing at settlement.
EXERCISE_STT_RULE = ExerciseSttRule(
    payer=Side.SELL,
    payer_description=(
        "the purchaser, i.e. the holder of the long position, whose settlement is "
        "booked as a SELL under this module's side convention"
    ),
    confidence=Confidence.CORROBORATED,
)

#: Which non-STT charges an expiry settlement attracts. Settlement is not a trade, and the
#: three flags below are three separately-sourced answers rather than one assumption.
#:
#: **Exchange transaction charge — unverified, assumed not levied.** No source, primary or
#: secondary, was found that says whether NSE's premium-turnover charge applies to the
#: settlement event as distinct from a trade. Assuming it away *understates* cost, which is
#: the direction that flatters a result, so it is flagged on every settlement it touches.
#:
#: **SEBI turnover fee — corroborated, levied, on notional.** NSE's own turnover-fee
#: wording says option turnover is "additionally computed on the basis of notional value of
#: option contracts exercised or assigned". This is the one charge that is definitely on
#: the settlement leg, and its base is notional, not intrinsic — a different base from
#: exercise STT on the same event, which is exactly the sort of thing a single "settlement
#: cost" number would flatten.
#:
#: **Stamp duty — unverified, assumed not levied.** Stamp duty attaches to the instrument
#: of transfer, so re-levying it on settlement would be surprising; no source says either
#: way, and "surprising" is not evidence.
SETTLEMENT_ATTRACTS_EXCHANGE_CHARGE = False
SETTLEMENT_ATTRACTS_SEBI_FEE_ON_NOTIONAL = True
SETTLEMENT_ATTRACTS_STAMP_DUTY = False


@dataclass(frozen=True, slots=True)
class ChargeableTrade:
    """One event the stack can charge: a market trade, or an expiry settlement.

    ``quantity_units`` is in **units** (contracts times lot size), matching the corpus's
    ``volume``/``oi`` columns, because every statutory base is a rupee turnover and
    turnover is price times units. ``price`` is the premium per unit for a ``TRADE`` and
    the per-unit intrinsic value for a ``SETTLEMENT``.

    ``notional_price`` is the settlement value of the underlying per unit, and is required
    on a ``SETTLEMENT`` because the SEBI fee's base there is **notional**, not intrinsic —
    two charges on one event with two different bases. Ignored for a ``TRADE``.
    """

    trade_date: dt.date
    kind: TradeKind
    side: Side
    quantity_units: int
    price: float
    orders: int = 1
    notional_price: float | None = None

    def __post_init__(self) -> None:
        if self.kind is TradeKind.SETTLEMENT and self.notional_price is None:
            raise ValueError(
                "a SETTLEMENT needs notional_price — the settlement value of the "
                "underlying — because the SEBI turnover fee on an exercised contract is "
                "charged on notional while STT on the same event is charged on intrinsic. "
                "Defaulting it to the intrinsic price would silently charge the fee on the "
                "wrong base."
            )
        if self.quantity_units < 0:
            raise ValueError(f"quantity_units must be non-negative, got {self.quantity_units}")
        if self.price < 0:
            raise ValueError(f"price must be non-negative, got {self.price}")
        if self.orders < 0:
            raise ValueError(f"orders must be non-negative, got {self.orders}")

    @property
    def turnover(self) -> float:
        return self.price * self.quantity_units


@dataclass(frozen=True, slots=True)
class CostBreakdown:
    """What one event cost, component by component.

    ``stt_on_exercise`` is its own field and is **never** folded into ``stt``. The two
    are different rates on different bases paid by different parties, and a single
    "STT" number would hide the one component whose misattribution flatters a
    short-variance backtest.
    """

    brokerage: float
    exchange_transaction_charge: float
    sebi_turnover_fee: float
    stt: float
    stt_on_exercise: float
    stamp_duty: float
    gst: float
    unverified_components: tuple[str, ...] = ()

    @property
    def total(self) -> float:
        """Summed in a fixed, declared order — not over a dict, and not over ``fields()``.

        Floating-point addition is not associative, so summation order is part of the
        answer. Reordering the fields of this dataclass must not silently change a total
        in the last bits and turn the determinism test into a mystery.
        """
        return (
            self.brokerage
            + self.exchange_transaction_charge
            + self.sebi_turnover_fee
            + self.stt
            + self.stt_on_exercise
            + self.stamp_duty
            + self.gst
        )

    @property
    def is_fully_verified(self) -> bool:
        return not self.unverified_components

    def as_dict(self) -> dict[str, float | list[str]]:
        return {
            "brokerage": self.brokerage,
            "exchange_transaction_charge": self.exchange_transaction_charge,
            "sebi_turnover_fee": self.sebi_turnover_fee,
            "stt": self.stt,
            "stt_on_exercise": self.stt_on_exercise,
            "stamp_duty": self.stamp_duty,
            "gst": self.gst,
            "total": self.total,
            "unverified_components": list(self.unverified_components),
        }

    def __add__(self, other: CostBreakdown) -> CostBreakdown:
        if not isinstance(other, CostBreakdown):  # pragma: no cover - defensive
            return NotImplemented
        return CostBreakdown(
            brokerage=self.brokerage + other.brokerage,
            exchange_transaction_charge=(
                self.exchange_transaction_charge + other.exchange_transaction_charge
            ),
            sebi_turnover_fee=self.sebi_turnover_fee + other.sebi_turnover_fee,
            stt=self.stt + other.stt,
            stt_on_exercise=self.stt_on_exercise + other.stt_on_exercise,
            stamp_duty=self.stamp_duty + other.stamp_duty,
            gst=self.gst + other.gst,
            unverified_components=tuple(
                sorted(set(self.unverified_components) | set(other.unverified_components))
            ),
        )


ZERO_COST = CostBreakdown(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)


class BrokerageModel:
    """Brokerage is a commercial term, so it is injected rather than tabulated.

    **An "order" is one (symbol, side, decision)** — a resize by a participation cap
    changes the quantity, never the order count, and a two-legged straddle is two orders.
    That definition propagates: GST rides on brokerage, so an order-count convention is
    also a GST convention.
    """

    def charge(self, trade: ChargeableTrade) -> float:  # pragma: no cover - interface
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class FlatPerOrderBrokerage(BrokerageModel):
    """Flat rupees per executed order.

    Zerodha's published F&O rate is a **flat** Rs 20 per executed order with no percentage
    alternative — the familiar "Rs 20 or 0.03%, whichever is lower" is their *equity
    intraday* pricing and does not apply here. Settlement is charged nothing by default —
    brokers differ on whether expiry settlement attracts brokerage, and charging zero is
    the assumption that does *not* flatter a held-to-expiry short-variance strategy, since
    zero brokerage there would understate cost. It is a parameter for that reason.

    **``pct_of_turnover`` was removed rather than repaired** (spec 1.1 scope). It capped a
    *per-order* charge against the *total* turnover of the trade and then multiplied the
    result by the order count, so with two orders the cap was applied twice to one
    turnover figure and the "cap" exceeded itself. Nothing in any default path set it, no
    test covered it, and the pricing it modelled does not exist for F&O — so there was no
    correct behaviour to restore, only a wrong formula to delete. A future broker that
    genuinely prices this way needs per-order turnover, which this signature does not
    carry.
    """

    rupees_per_order: float = BROKERAGE_ZERODHA_FNO
    charge_on_settlement: bool = False

    def charge(self, trade: ChargeableTrade) -> float:
        if trade.kind is TradeKind.SETTLEMENT and not self.charge_on_settlement:
            return 0.0
        if trade.orders == 0 or trade.quantity_units == 0:
            return 0.0
        return self.rupees_per_order * trade.orders


class StatutoryCostStack:
    """Charges the statutory components for one chargeable event.

    Schedules are constructor arguments so a test can drive a two-entry fixture across
    the 1 Oct 2024 boundary without touching the module table, and so an operator whose
    exchange or state differs can substitute one. They are **not** a strategy hook: a
    backtest that quietly lowers its own STT is not answering the question.
    """

    def __init__(
        self,
        *,
        brokerage: BrokerageModel | None = None,
        stt_sell_premium: RateSchedule = STT_ON_SELL_PREMIUM,
        stt_exercise: RateSchedule = STT_ON_EXERCISE,
        exchange_charge: RateSchedule = EXCHANGE_TRANSACTION_CHARGE,
        sebi_fee: RateSchedule = SEBI_TURNOVER_FEE,
        stamp_duty: RateSchedule = STAMP_DUTY,
        gst: RateSchedule = GST,
        exercise_stt_rule: ExerciseSttRule = EXERCISE_STT_RULE,
    ) -> None:
        self._brokerage = brokerage if brokerage is not None else FlatPerOrderBrokerage()
        self._stt_sell_premium = stt_sell_premium
        self._stt_exercise = stt_exercise
        self._exchange_charge = exchange_charge
        self._sebi_fee = sebi_fee
        self._stamp_duty = stamp_duty
        self._gst = gst
        self._exercise_stt_rule = exercise_stt_rule

    @property
    def exercise_stt_rule(self) -> ExerciseSttRule:
        return self._exercise_stt_rule

    def charge(self, trade: ChargeableTrade) -> CostBreakdown:
        """Every statutory component due on one event, plus brokerage and GST."""
        on = trade.trade_date
        is_settlement = trade.kind is TradeKind.SETTLEMENT
        unverified: list[str] = []

        def rate(schedule: RateSchedule) -> float:
            found = schedule.lookup(on)
            entry = found.entry
            # An extrapolated rate is a separate defect from an unverified one and gets its
            # own stamp: the confidence tier says "nobody checked this number", while this
            # says "this number is from the wrong date, and knowably too high". A run can
            # carry either, both, or neither, and a reader needs to tell them apart.
            if (stamp := found.stamp) is not None:
                unverified.append(stamp)
            if entry.confidence is not Confidence.CONFIRMED:
                # The TIER travels, not just the name. A bare schedule name makes a
                # CORROBORATED rate and a wholly UNVERIFIED one indistinguishable in
                # `unverified_inputs`, which is the field C6 reads — so the rule "any
                # UNVERIFIED input means the result is not evaluable" could not be
                # expressed, let alone enforced, against the old format.
                unverified.append(f"{schedule.name}:{entry.confidence}")
            return entry.rate

        turnover = trade.turnover
        brokerage = self._brokerage.charge(trade)

        if is_settlement:
            # Three separately-sourced answers, not one blanket rule. See the flags.
            exchange_base = turnover if SETTLEMENT_ATTRACTS_EXCHANGE_CHARGE else 0.0
            # **Only an exercised or assigned contract attracts the fee.** NSE's wording,
            # quoted on SETTLEMENT_ATTRACTS_SEBI_FEE_ON_NOTIONAL itself, says turnover is
            # "additionally computed on the basis of notional value of option contracts
            # exercised or assigned" — and an option expiring out of the money is neither.
            # It lapses. Charging on its notional put roughly -1.97 rupees on every
            # worthless leg, which for a short straddle held to expiry is one leg of every
            # pair, every week. `trade.price` is the per-unit intrinsic on a SETTLEMENT, so
            # it is exactly the in-the-money test.
            exercised = trade.price > 0.0
            sebi_base = (
                (trade.notional_price or 0.0) * trade.quantity_units
                if SETTLEMENT_ATTRACTS_SEBI_FEE_ON_NOTIONAL and exercised
                else 0.0
            )
            if not SETTLEMENT_ATTRACTS_EXCHANGE_CHARGE:
                unverified.append(
                    f"settlement.exchange_charge_assumed_not_levied:{Confidence.UNVERIFIED}"
                )
        else:
            exchange_base = turnover
            sebi_base = turnover
        exchange_charge = rate(self._exchange_charge) * exchange_base if exchange_base else 0.0
        sebi_fee = rate(self._sebi_fee) * sebi_base if sebi_base else 0.0

        stt = 0.0
        stt_on_exercise = 0.0
        if is_settlement:
            if trade.side is self._exercise_stt_rule.payer:
                stt_on_exercise = rate(self._stt_exercise) * turnover
                if self._exercise_stt_rule.confidence is not Confidence.CONFIRMED:
                    unverified.append(
                        f"stt.exercise_payer_attribution:{self._exercise_stt_rule.confidence}"
                    )
        elif trade.side is Side.SELL:
            stt = rate(self._stt_sell_premium) * turnover

        stamp_duty = 0.0
        charge_stamp = (not is_settlement) or SETTLEMENT_ATTRACTS_STAMP_DUTY
        if charge_stamp and trade.side is Side.BUY:
            stamp_duty = rate(self._stamp_duty) * turnover

        gst = rate(self._gst) * (brokerage + exchange_charge + sebi_fee)

        return CostBreakdown(
            brokerage=brokerage,
            exchange_transaction_charge=exchange_charge,
            sebi_turnover_fee=sebi_fee,
            stt=stt,
            stt_on_exercise=stt_on_exercise,
            stamp_duty=stamp_duty,
            gst=gst,
            unverified_components=tuple(sorted(set(unverified))),
        )

    def charge_all(self, trades: Iterable[ChargeableTrade]) -> CostBreakdown:
        """Total for a sequence of events, summed in the order given."""
        total = ZERO_COST
        for trade in trades:
            total = total + self.charge(trade)
        return total

    def schedule_provenance(self) -> tuple[dict[str, str], ...]:
        """Every rate this stack would use, for the run's provenance record."""
        schedules: Sequence[RateSchedule] = (
            self._stt_sell_premium,
            self._stt_exercise,
            self._exchange_charge,
            self._sebi_fee,
            self._stamp_duty,
            self._gst,
        )
        return tuple(
            {
                "schedule": schedule.name,
                "effective_from": entry.effective_from.isoformat(),
                "rate": repr(entry.rate),
                "base": entry.base,
                "side": entry.side,
                "source": entry.source,
                "source_url": entry.source_url,
                "confidence": str(entry.confidence),
            }
            for schedule in schedules
            for entry in schedule.entries
        )
