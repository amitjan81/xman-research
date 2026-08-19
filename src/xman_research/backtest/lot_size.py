"""Whether a session's declared lot size survives contact with its own bars.

**This module exists because it caught one.** ``market.py`` claimed — and a test
asserted — that every non-null volume and open-interest value in the corpus divides
exactly by the contract's lot size. The test checked a single session, 2026-06-09, and
the claim is false for the first ten sessions of the corpus. A tripwire that fires on a
cherry-picked day is not a weaker tripwire; it is an assurance that the property holds
when nobody has looked.

**What the corpus actually says.** Every ``.refdata`` bundle in the corpus — all **1,233**
sessions of it — declares NIFTY's lot size as **65**. On the ten sessions from 2025-12-16
to 2025-12-30 the bars disagree: 100% of positive volume divides by **75** and around 7%
divides by 65 — 7% being the rate you get by chance, since a multiple of 75 is a multiple
of 65 exactly when it is a multiple of 13, and 1/13 ≈ 7.7%. From 2025-12-31 onward the
relationship inverts exactly: 100% by 65, around 6% by 75.

**What a full-corpus scan found, and why almost none of it is encoded below.** The corpus
now carries a historical backfill reaching to 2021-06-01. Scanning all 1,233 sessions, the
multiplier the bars support moves through seven runs::

    75   2021-06-01 .. 2021-07-22   (36 sessions)
    50   2021-07-23 .. 2024-04-25   (637)
    25   2024-04-29 .. 2024-12-26   (157)
    75   2024-12-27 .. 2025-01-23   (20)
    25   2025-01-24 .. 2025-01-30   (5)
    75   2025-01-31 .. 2025-12-30   (222)
    65   2025-12-31 .. 2026-08-19   (156)

**1,077 of the 1,233 sessions contradict their own declared lot size**, so the
publish-time-dependence defect is corpus-wide rather than a December curiosity.

**Where the boundaries fall — measured, after an earlier version of this docstring got it
wrong.** That version argued the runs could not be encoded because :class:`LotSizeEpoch`
is keyed on contract **expiry** while "these boundaries are not expiry boundaries", citing
a front expiry of 2021-08-05 on both 2021-07-22 and 2021-07-23, and of 2025-02-06 across
the whole 2025-01-24..30 excursion. **Both citations are false and the opposite is true.**
Re-measuring every session against the contract its bars actually belong to:

* **Capture is front-expiry-only, so one session is one contract.** On all 1,233 sessions
  the positive-volume bars carry **exactly one** expiry — zero exceptions — the same data
  fact :func:`~xman_research.backtest.strategies._next_expiry_after` records. The sessions
  named above carry 2021-07-22, 2021-07-29, 2025-01-30 and 2025-02-06 respectively, not
  the expiries claimed, and each bundle's own front expiry agrees with its bars. The old
  claim was not a refdata-contamination artefact; it was simply wrong.
* **No contract is ever observed under two multipliers.** Over the 269 distinct expiries
  in the corpus, the number whose bars support more than one lot size is **zero**.
* **Every one of the six boundaries is an expiry handover**, not a mid-contract flip:
  2021-07-22(75)->2021-07-29(50), 2024-04-25(50)->2024-05-02(25),
  2024-12-26(25)->2025-01-02(75), 2025-01-23(75)->2025-01-30(25),
  2025-01-30(25)->2025-02-06(75), 2025-12-30(75)->2026-01-06(65).

An expiry-keyed table therefore represents this corpus exactly — the 25 excursion is the
one-expiry range ``[2025-01-30, 2025-01-30]`` among 75 neighbours. And it is not "one
unchanged contract" reading two ways: 2025-01-30 is a distinct contract, a month-end
expiry sitting between two weeklies. **So the live hypothesis is grandfathering, not a
vendor scaling artefact** — precisely the model :class:`LotSizeEpoch`'s own class
docstring already states, in which a revision binds newly-introduced contracts while
existing ones run to expiry at the old size. Two details support it: the 25->75 boundary
lands on the first session whose front contract is the 2025-01-02 weekly rather than on
any calendar date, and the *next* month-end expiry, 2025-02-27, already reads 75.

**Why the refusal stands anyway.** Grandfathering is a hypothesis this corpus cannot
close, because it turns on contract *listing* dates and each bundle's chain carries only
the three nearest expiries — on 2024-11-19 neither 2025-01-30 nor 2025-02-27 is listed
yet, so nothing here dates either contract's introduction. The revision the pattern is
consistent with is un-cited: no NSE or SEBI circular has been read for this module.
Divisibility only ever establishes a *lower* bound on a lot size, and the refdata is
contaminated on every session. So no entry is added for these runs. Writing seven epochs
from a hypothesis that merely fits would encode a guess in the shape of a finding, which
is precisely what the confidence field exists to prevent; writing nothing is the
reversible choice, and the runs are recorded here as evidence for whoever does read the
circulars.

**A related defect, reported and not fixed here.** :func:`epoch_for` takes a parameter
named ``expiry``, but its only production caller — :meth:`LotSizeAudit.contradiction_message`
— passes ``self.session_date``. The two coincide for the December window (its sessions and
its expiries share the 2025-12-16..12-30 range), which is why nothing has noticed. Deciding
whether the epoch is session-keyed or expiry-keyed is a semantic change to a frozen
dataclass and belongs in its own change, with the owner's call.

The cause is publish-time dependence, the same class already fixed for symbols on the
producer side: the sessions were published against the *then-current* scrip master rather
than the one in force on each date, so older bundles carry a lot size that did not apply.
**Nothing in the corpus ever declares 75.** The evidence for the December regime is
entirely in the bars, which is why it is recorded here as an epoch rather than read from a
file.

**The stamp.** A backtest whose window touches such a session runs, on the **declared**
lot size, and says so: the result carries ``corpus.declared_lot_size_contradicted`` in its
``unverified_inputs`` and the contradicted dates in
``data_provenance["lot_size_audit"]``. This was an unoverridable refusal until 2026-08-13;
the owner's decision reversed it, and :func:`~xman_research.backtest.engine.run_backtest`
carries the argument on both sides at the point where the stamp is applied.

What makes the stamp defensible rather than a shrug is that the damage is **bounded and
uneven, not diffuse**. Since sizing became an exposure target rather than a contract count
(:class:`~xman_research.backtest.strategies.ShortAtmStraddle`), the lot size no longer
scales the position: the strategy buys the same rupees of index either way and the
multiplier only decides the rounding. So the scale-free statistics a verdict rests on —
Sharpe, deflated Sharpe, return on peak margin, drawdown, the cost-breakeven ratio — are
invariant to it up to that rounding. What genuinely does move is the *feasibility* verdict,
because participation caps floor to whole lots against a lot size that never applied, and
the flat per-order brokerage, which scales with nothing. Those are exactly the questions
the stamp tells a reader to distrust.

**Volume is the inference series, open interest is only reported.** Every trade at the
exchange is struck in lots, so traded volume in units is a multiple of the lot size by
construction; that makes volume the clean signal, and it is 100% clean on every session
in the corpus under one lot size or the other. Open interest is not clean, and the
sessions where it is not are reported separately as
:attr:`LotSizeAudit.non_conforming_symbols` rather than folded into the lot verdict —
see that attribute for what was found and what was deliberately not concluded.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from xman_research.backtest.costs import Confidence

if TYPE_CHECKING:  # pragma: no cover - import cost is paid only by type checkers
    import pandas as pd

    from xman_research.session_store import RefData

__all__ = [
    "CANDIDATE_LOT_SIZES",
    "NIFTY_LOT_SIZE_EPOCHS",
    "LotSizeAudit",
    "LotSizeEpoch",
    "audit_lot_size",
    "epoch_for",
]

#: Lot sizes to test the bars against. NIFTY's own history (75, then 65) plus the two
#: smaller values that appear in NSE index-option history, so that a future regime the
#: corpus has not seen is still *detected* — reporting "no candidate explains this" is a
#: better failure than silently accepting the declared value.
CANDIDATE_LOT_SIZES: tuple[int, ...] = (15, 20, 25, 40, 50, 65, 75)

#: Below this share of positive volume rows, the declared lot size is not describing the
#: data. Chosen from the measured separation, which is not marginal: on the December
#: sessions the declared value explains ~7% of rows and the alternative explains 100%.
#: Anything between roughly 0.2 and 0.98 would classify this corpus identically.
_DECLARED_FLOOR = 0.90

#: An alternative has to explain essentially everything before it is allowed to convict
#: the declared value. This is what keeps a localised data-quality problem — a handful of
#: symbols with malformed open interest — from being misread as a lot-size regime.
_ALTERNATIVE_CEILING = 0.99

#: A symbol is called non-conforming when fewer than half its positive rows in some
#: series divide by the reference lot size. Deliberately far from both 0 and 1: the
#: symbols this finds sit at 88-100% non-conforming, and the ones it correctly ignores
#: sit at ~0%.
_SYMBOL_FLOOR = 0.5


@dataclass(frozen=True, slots=True)
class LotSizeEpoch:
    """A period during which one lot size was in force, and the evidence for saying so.

    **Keyed on contract expiry, not on session date.** NSE applies a lot-size revision to
    newly-introduced contracts and lets existing ones run to expiry at the old size, so
    the boundary is a property of the contract, not of the day it traded. The corpus makes
    this look like a session-date flip only because capture carried the front expiry
    alone: the last session whose front contract was a pre-revision one is 2025-12-30, and
    the next session's front contract is the 06/01/2026 expiry. A future backfill carrying
    the full ladder would see both regimes on the same day, and would need this field to
    resolve them.
    """

    underlying: str
    lot_size: int
    expiries_from: dt.date | None
    expiries_through: dt.date | None
    confidence: Confidence
    evidence: str

    def covers_expiry(self, expiry: dt.date) -> bool:
        if self.expiries_from is not None and expiry < self.expiries_from:
            return False
        return not (self.expiries_through is not None and expiry > self.expiries_through)


#: NIFTY's lot-size regimes as this corpus evidences them.
#:
#: The 75 entry is **CORROBORATED by the bars and contradicted by the refdata**, which is
#: an unusual combination and the reason it is written down here rather than trusted from
#: the bundle. It is not CONFIRMED because no NSE circular was read: the finding is a
#: measurement over 10 sessions and ~150,000 rows, not a citation. The producer repo
#: (``xman``) owns the refdata and is where the fix belongs; this package must not, and
#: does not, rewrite the corpus.
#: **The table is deliberately incomplete** — see "What a full-corpus scan found" in the
#: module docstring. It covers only the window its evidence covers; outside that,
#: :func:`epoch_for` returns ``None``, meaning "not established". That is the honest
#: answer, and :meth:`LotSizeAudit.contradiction_message` already handles it.
NIFTY_LOT_SIZE_EPOCHS: tuple[LotSizeEpoch, ...] = (
    LotSizeEpoch(
        underlying="NIFTY",
        lot_size=75,
        # **Closed, where this used to be open-started.** ``None`` claimed 75 for every
        # expiry in history, on evidence covering ten sessions in December 2025. A
        # full-corpus scan has since measured 50 and 25 regimes across 2021-2025, so the
        # open start was not merely unsupported — it was wrong.
        expiries_from=dt.date(2025, 12, 16),
        expiries_through=dt.date(2025, 12, 30),
        confidence=Confidence.CORROBORATED,
        evidence=(
            "Measured over the 10 corpus sessions 2025-12-16..2025-12-30, whose bars carry "
            "the 16/12/2025, 23/12/2025 and 30/12/2025 expiries: 100% of positive volume "
            "rows divide by 75 on every one of them, against ~7% by 65 (the chance rate, "
            "1/13). Every one of those sessions' .refdata declares 65, which is the "
            "publish-time-dependence defect: the corpus was published in one batch on "
            "2026-06-17 against the then-current scrip master. No refdata bundle anywhere "
            "in the corpus declares 75."
        ),
    ),
    LotSizeEpoch(
        underlying="NIFTY",
        lot_size=65,
        expiries_from=dt.date(2026, 1, 6),
        expiries_through=None,
        confidence=Confidence.CORROBORATED,
        evidence=(
            "Measured over the 156 corpus sessions from 2025-12-31 onward, whose front "
            "expiry is 06/01/2026 or later: 100% of positive volume rows divide by 65, "
            "against ~6% by 75. Here the refdata's declared 65 and the bars agree, which "
            "is why the whole corpus looks consistent to a check that samples one late "
            "session."
        ),
    ),
)


def epoch_for(expiry: dt.date, *, underlying: str = "NIFTY") -> LotSizeEpoch | None:
    """The recorded lot-size epoch covering ``expiry``, or ``None`` if none does."""
    for epoch in NIFTY_LOT_SIZE_EPOCHS:
        if epoch.underlying == underlying and epoch.covers_expiry(expiry):
            return epoch
    return None


@dataclass(frozen=True, slots=True)
class LotSizeAudit:
    """What one session's bars say about the lot size its refdata declares."""

    session_date: dt.date
    underlying: str
    declared_lot_sizes: tuple[int, ...]
    volume_rows: int
    declared_volume_share: float
    best_alternative: int | None
    best_alternative_share: float
    open_interest_rows: int
    declared_open_interest_share: float
    non_conforming_symbols: tuple[str, ...]
    """Symbols whose own rows do not divide by the reference lot size, in symbol order.

    **Reported, not diagnosed.** On this corpus the finding is confined to whole symbols
    at round-thousand strikes — the 30Mar2026 22000 and 23000 CE/PE on 2026-03-25, 03-27
    and 03-30, and the 30Dec2025 26000 CE/PE on 2025-12-24 through 12-30 — and it is
    open interest only, never volume. **On the same symbol in the same session, volume is
    100% divisible by the lot size while open interest is 0-12%** — measured on all four
    March symbols. That is the sharpest fact here and the one most useful to the producer:
    whatever went wrong did not corrupt whole rows, it reached the ``oi`` field alone.
    Between 88% and 100% of each affected symbol's open-interest rows fail, and the
    handful that pass are consistent with chance at 1/13, so the passing rows are noise
    rather than a partially-correct series. The values are
    multiples of 5 (December's additionally of 25) and their residues mod 13 are spread
    uniformly over 1..12, so no lot size in :data:`CANDIDATE_LOT_SIZES` explains them and
    none is proposed: what produced them is a question for the producer repo, and a
    guess recorded here would be indistinguishable from a finding.

    A non-empty tuple does **not** refuse the run. These symbols' open interest feeds a
    participation cap, so a strategy that traded one would size against a number that
    cannot be a unit count; the honest treatment is that the run says so, which it does
    via ``corpus.open_interest_not_divisible_by_lot_size`` in the result's
    ``unverified_inputs``.
    """

    @property
    def reference_lot_size(self) -> int:
        """The lot size the bars actually support — the alternative when one convicts."""
        if self.contradicts_declared and self.best_alternative is not None:
            return self.best_alternative
        return self.declared_lot_sizes[0] if self.declared_lot_sizes else 0

    @property
    def contradicts_declared(self) -> bool:
        """Whether an alternative lot size explains the bars and the declared one does not.

        Both halves are required. "The declared value does not explain everything" alone
        would convict on a session where a few symbols carry malformed open interest,
        which is a different defect with a different remedy; demanding that some *other*
        lot size explain essentially every row is what makes this specific.
        """
        return (
            self.declared_volume_share < _DECLARED_FLOOR
            and self.best_alternative is not None
            and self.best_alternative_share >= _ALTERNATIVE_CEILING
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "session_date": self.session_date.isoformat(),
            "underlying": self.underlying,
            "declared_lot_sizes": list(self.declared_lot_sizes),
            "volume_rows": self.volume_rows,
            "declared_volume_share": self.declared_volume_share,
            "best_alternative": self.best_alternative,
            "best_alternative_share": self.best_alternative_share,
            "open_interest_rows": self.open_interest_rows,
            "declared_open_interest_share": self.declared_open_interest_share,
            "non_conforming_symbols": list(self.non_conforming_symbols),
            "reference_lot_size": self.reference_lot_size,
            "contradicts_declared": self.contradicts_declared,
        }

    def contradiction_message(self) -> str:
        """What the stamp on this session means, in terms of what was measured.

        Renamed from ``failure_message``: nothing fails any more. The text is the
        explanation a reader of ``corpus.declared_lot_size_contradicted`` needs, and it
        must state what is and is not damaged — a stamp that only said "something is wrong
        here" would be read as either fatal or ignorable, and it is neither.
        """
        declared = ", ".join(str(lot) for lot in self.declared_lot_sizes) or "nothing"
        epoch = epoch_for(self.session_date, underlying=self.underlying)
        known = ""
        if self.best_alternative is not None and epoch is not None:
            known = (
                f" This is a recorded regime, not a surprise: {self.evidence_line(epoch)}"
                if epoch.lot_size == self.best_alternative
                else ""
            )
        return (
            f"{self.underlying} on {self.session_date.isoformat()}: refdata declares lot "
            f"size {declared}, but only {self.declared_volume_share:.1%} of "
            f"{self.volume_rows} positive volume rows divide by it, while "
            f"{self.best_alternative_share:.1%} divide by {self.best_alternative}. The "
            "declared lot size did not apply on this date. The run is computed on the "
            "declared value anyway and stamped, per the owner's decision of 2026-08-13: "
            "position sizing targets a notional rather than a contract count, so the "
            "scale-free statistics survive the wrong multiplier, while the participation "
            "caps and the flat per-order brokerage on this session do not and should not "
            "be relied on." + known + " The refdata belongs to the producer repository "
            "(xman) and must be regenerated there; nothing in this package may rewrite "
            "the corpus."
        )

    @staticmethod
    def evidence_line(epoch: LotSizeEpoch) -> str:
        return f"lot size {epoch.lot_size} was in force ({epoch.confidence}). {epoch.evidence}"


def audit_lot_size(
    *,
    session_date: dt.date,
    underlying: str,
    frame: pd.DataFrame,
    refdata: RefData,
) -> LotSizeAudit:
    """Test one session's bars against the lot size its refdata declares.

    Reads the frame only; nothing is written, and the frame is not modified.
    """
    declared = tuple(
        sorted(
            {
                int(row["LotSize"])
                for row in refdata.nfo_instruments
                if row.get("LookupName") == underlying and "LotSize" in row
            }
        )
    )
    options = frame[frame["symbol"] != underlying]
    volume = _positive(options, "volume")
    open_interest = _positive(options, "oi")

    declared_volume_share = max((_share(volume, lot) for lot in declared), default=0.0)
    declared_oi_share = max((_share(open_interest, lot) for lot in declared), default=0.0)

    # **Ties break to the largest candidate, and that is not a detail.** Divisibility can
    # only ever establish a *lower bound* on the lot size: every multiple of 75 is also a
    # multiple of 15, 25 and 5, so a naive "first candidate that explains the data" picks
    # 15 and reports the December regime as a lot size that never existed. The coarsest
    # value consistent with every row is the estimate the evidence actually supports.
    # :data:`CANDIDATE_LOT_SIZES` is ascending, so ``>=`` selects it.
    best_alternative: int | None = None
    best_alternative_share = 0.0
    for lot in CANDIDATE_LOT_SIZES:
        if lot in declared:
            continue
        share = _share(volume, lot)
        if share > 0.0 and share >= best_alternative_share:
            best_alternative, best_alternative_share = lot, share

    audit = LotSizeAudit(
        session_date=session_date,
        underlying=underlying,
        declared_lot_sizes=declared,
        volume_rows=len(volume),
        declared_volume_share=declared_volume_share,
        best_alternative=best_alternative,
        best_alternative_share=best_alternative_share,
        open_interest_rows=len(open_interest),
        declared_open_interest_share=declared_oi_share,
        non_conforming_symbols=(),
    )
    reference = audit.reference_lot_size
    return _with_non_conforming(audit, options, reference)


def _with_non_conforming(
    audit: LotSizeAudit, options: pd.DataFrame, reference: int
) -> LotSizeAudit:
    """Attach the per-symbol outliers, measured against the lot size the bars support."""
    if reference <= 0 or options.empty:
        return audit
    offenders: set[str] = set()
    for column in ("volume", "oi"):
        if column not in options.columns:
            continue
        series = options[["symbol", column]].dropna(subset=[column])
        series = series[series[column] > 0]
        if series.empty:
            continue
        conforming = (series[column] % reference == 0).groupby(series["symbol"]).mean()
        offenders.update(str(symbol) for symbol in conforming[conforming < _SYMBOL_FLOOR].index)
    return LotSizeAudit(
        session_date=audit.session_date,
        underlying=audit.underlying,
        declared_lot_sizes=audit.declared_lot_sizes,
        volume_rows=audit.volume_rows,
        declared_volume_share=audit.declared_volume_share,
        best_alternative=audit.best_alternative,
        best_alternative_share=audit.best_alternative_share,
        open_interest_rows=audit.open_interest_rows,
        declared_open_interest_share=audit.declared_open_interest_share,
        non_conforming_symbols=tuple(sorted(offenders)),
    )


def _positive(options: pd.DataFrame, column: str) -> pd.Series:
    """Positive, non-null values of ``column``. Zero and NaN carry no divisibility signal."""
    if column not in options.columns:
        return options.index.to_series().iloc[:0]
    series = options[column].dropna()
    return series[series > 0]


def _share(series: pd.Series, lot: int) -> float:
    """Fraction of ``series`` divisible by ``lot``; 0.0 for an empty series."""
    if lot <= 0 or len(series) == 0:
        return 0.0
    return float((series % lot == 0).mean())


def audit_sessions(
    audits: Sequence[LotSizeAudit],
) -> Mapping[str, Any]:
    """Summarise a run's per-session audits for the result's provenance record."""
    contradicted = [audit for audit in audits if audit.contradicts_declared]
    non_conforming = sorted({symbol for audit in audits for symbol in audit.non_conforming_symbols})
    return {
        "sessions_audited": len(audits),
        "sessions_contradicting_declared_lot_size": [
            audit.session_date.isoformat() for audit in contradicted
        ],
        "symbols_with_non_conforming_open_interest": non_conforming,
    }
