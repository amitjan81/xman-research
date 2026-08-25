"""What the ranker proposed, what it actually made, and when a template stops earning it.

**The ledger closes the loop the library opens.** The library records what a template was
admitted on — an offline measurement over a window that has already happened. The ranker
copies that expectation onto every idea it proposes. Nothing in either loop ever asks
whether the expectation held. This module is that question: every presented idea is written
down at the moment it is presented, marked at the price the market actually printed once its
hold has elapsed, and compared against the number the admission card promised. A template
whose realised edge walks away from its admitted edge is demoted against a rule written
before the first number existed.

**Why JSON rather than sqlite.** The trial log is sqlite because it has concurrent writers
and its integrity is the thing under audit. This ledger has neither property: it is written
once a night by one process and read by a human asking why a template was demoted. JSON
gains a diffable artefact that lives in the repository beside ``templates.json`` — a demotion
and the settled rows that caused it land in the same commit, and a reviewer can read the
evidence without a client. It costs concurrency (two writers racing lose one's entries; the
save-time prefix check below catches the ordinary case and is not a lock) and it costs
query-ability (every statistic is computed by reading the whole file into memory, which is
fine at a few thousand rows and would not be at a few million). The realistic alternative is
sqlite with the trial log's integrity machinery; it is the right choice the day something
other than one nightly process writes here, and it is not worth its complexity before then.

**Append-only, like the library and the trial log.** A settlement never edits the row it
settles. Presented ideas and settlements are two kinds of entry in one ordered list, and the
current state of an idea is the last settlement entry naming it. This is not merely stylistic:
:meth:`IdeaLedger.save` refuses a file whose stored entries are not a prefix of what is about
to be written, so an in-place edit of an already-stored row would make the ledger
unappendable. The write itself is a temp file and a rename, so a reader sees one whole
version or the other.

**Re-recording a sheet.** Recording the same sheet twice is a no-op: an idea is keyed on its
as-of date, template, parameter point and underlying, and an identical row is skipped rather
than duplicated. Recording a *different* sheet for an as-of date already recorded is
**refused**, not superseded. The ledger's job is to say what the operator was actually shown
on a given evening; a re-scan after a code change that quietly overwrote that would let the
drift statistics be computed against a night that never happened. A genuine re-scan gets a
new as-of date or a new ledger.

**The base every return is expressed on.** A ledger row's realised return is one trade's
profit and loss over a **fixed capital base** — ``BacktestConfig.starting_cash``, the
denominator :func:`xman_research.validation.series.ReturnSeries.from_equity_curve` divides
every equity change by. The admission card's comparable figure is
:attr:`~xman_research.alpha.library.EvidenceCard.mean_return_per_round_trip`: the measured
run's net profit per position opened, over that same base.

``mean_return_at_hold`` is **not** that figure. It is ``mean_return_per_session x
hold_sessions``, and ``mean_return_per_session`` divides by every session in the window
including the ones the template sat flat through. A template in position on a fraction ``f``
of sessions therefore earns ``mean_return_at_hold / f`` per trade, and the shipped templates
are nowhere near ``f = 1``: a hold-3 template enters only on the session furthest from
expiry, and every conditioned template fires on a minority of sessions. Comparing one trade
against the hold-scaled figure would leave every drift biased by ``(1 - f)`` of a trade's
expectation — a permanent phantom shortfall on exactly the templates that trade selectively.

A sheet's ``expected_edge`` is the hold-scaled figure times that night's regime factor, so
each promised edge is carried onto the per-position base by the **ratio of the card's two
figures**, which leaves the regime factor untouched. Where the card reports no per-position
figure — a decision record whose runner does not report one — the promised edge stands
unscaled and the report says so in its reason rather than quietly comparing the two bases.

**Realised is normalised to the size the evidence was measured at.** A ledger row's profit
is earned at the lots the scan was *granted*, which the participation caps may have cut below
the lots it *requested* at its target notional, while the card's figure comes from a run
sized at that target. Left alone, a capped idea's realised return would be scaled down purely
by sizing, and for a positive expectation that bias points *toward* demotion — the one
direction the rest of this module's biases do not point. So realised is multiplied by
``requested_lots / granted_lots``, both of which the sheet already carries, and an idea
missing either is settled unscaled with that stated on the row. Lots and not notionals: a
structure's notional is the sum over its short legs, so a straddle's ratio would carry a
factor of two that has nothing to do with sizing.

**Marks are gross of costs, which biases against demotion.** The admission card's figure is
net of the statutory cost drag; a ledger row's is not. The realised number is therefore
overstated by roughly one round trip's charges, which makes realised-minus-expected too
generous and makes the demotion rule fire later than a like-for-like comparison would. The
bias has one direction and it is the conservative one — this module never demotes a template
because of a cost it failed to charge.

**Two exit-side ways a leg cannot be marked, and they are not the same fact.** The corpus
captures a strike ladder around the money, so a contract that has drifted outside it is simply
absent from that session's instrument master and ``universe.by_symbol`` returns ``None``: the
apparatus never saw the leg. A contract that *is* listed but printed no bar at the decision
minute is a leg the apparatus saw and found untraded. The first is a coverage limit of the
capture, the second is a liquidity fact about the option, and an operator reading a run of
unmarkable ideas needs to know which one they are looking at. A third cause sits on the entry
side: an idea presented with no ``price_at_decision_minute`` on some leg was never markable at
all. An idea that cannot be marked is recorded as unmarkable with its cause; it is never
recorded as a zero return, which would enter the drift statistics as a real observation of
"made nothing".

**The demotion rule, fixed before any number existed.** Over the last ``window`` settled ideas
at one ``(template_id, parameter_key)``, with ``d_i = realised_i - expected_i``:

1. a one-sided lower CUSUM, ``S_0 = 0`` and ``S_i = min(0, S_{i-1} + d_i)``, breaches when
   ``min(S) <= -k * sigma`` with ``k = 3``; or
2. the realised mean over the window is below zero while the admission card's expectation is
   above zero, and the one-sided t-statistic ``mean / (stdev / sqrt(n))`` is ``<= -2``.

``sigma`` is the **sample standard deviation of the ``d_i`` series itself**, not a dispersion
carried on the admission card — the card records a mean return at hold and no spread around
it, so there is no admitted dispersion to compare against. The consequence is that the
threshold is estimated from the same data it judges: a template whose realised returns are
wildly dispersed earns a wider tolerance and is demoted later than a steady one drifting by
the same amount. That is the price of not having an admitted dispersion, and it is stated
rather than hidden. Where ``sigma`` is zero the CUSUM cannot be judged at all and the verdict
says so, rather than treating any shortfall as an infinite breach.

The CUSUM has **no slack term**. A slack parameter is a second free knob, and the whole claim
this rule makes is that it cannot be retuned after seeing a bad month.

**The second rule is checked first, so that a losing template is named as one.** Where the
expectation is constant across the window and ``n >= 3``, rule 2 cannot fire alone: the whole
window is itself a contiguous run, so the CUSUM is at most the window's total shortfall
``n * (mean - expected)``, and a mean that reaches a t of ``-2`` has already carried that
total past ``3 * sigma``. That is the case the bound is proved for and it is narrower than
what the code allows — ``min_settled`` may be as low as one on a direct call, and a regime
factor scaled per idea makes the drift dispersion differ from the realised dispersion — so
rule 2 is a naming device in the ordinary case rather than a proven-redundant trigger in
every case. It is evaluated first so that a template which is simply **losing money** is
reported as that rather than as having drifted. Both are demotions; they are not the same
diagnosis, and a report that collapsed them would send a reader looking for a regime change
where there is a dead strategy.

Nothing is demoted on fewer than ``min_settled`` settled ideas, and a template below that line
is reported as unjudged with its count rather than passed over in silence — "no demotion" and
"not enough evidence to demote" are different states and a report that showed them the same
way would let a template with two settled ideas read as healthy.

**The trade-off of a fixed rule.** It gains auditability: the thresholds were written before
the first observation, so a demotion cannot be argued into or out of existence after the fact,
and the rule that fired is the rule a reader can check against this docstring. It costs
adaptivity: a genuine regime change — a volatility environment the admission window never
contained — is demoted on exactly the same evidence as a template that was never real. The
ledger cannot tell those apart, and it does not try; it demotes, records the numbers in the
reason, and leaves re-admission to the offline loop, where a human and a fresh gate can.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import os
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from xman_research.alpha.features import DEFAULT_DECISION_TIME
from xman_research.alpha.holdout import require_unsealed
from xman_research.alpha.library import TemplateLibrary
from xman_research.alpha.templates import parameter_key
from xman_research.backtest.engine import BacktestConfig
from xman_research.backtest.market import SessionView
from xman_research.backtest.settlement import (
    SETTLEMENT_RULES,
    SettlementRule,
    SettlementWindowError,
    settlement_value,
)
from xman_research.clock import Clock, SystemClock
from xman_research.session_store import SessionStore

__all__ = [
    "CUSUM_K",
    "DEFAULT_CAPITAL_BASE",
    "DEFAULT_LEDGER_PATH",
    "DEFAULT_MIN_SETTLED",
    "DEFAULT_WINDOW",
    "LEDGER_SCHEMA_VERSION",
    "STATUS_SETTLED",
    "STATUS_UNMARKABLE",
    "T_STATISTIC_THRESHOLD",
    "UNMARKABLE_CONTRACT_ABSENT",
    "UNMARKABLE_NO_ENTRY_PRICE",
    "UNMARKABLE_NO_EXIT_SESSION",
    "UNMARKABLE_NO_PRINT",
    "UNMARKABLE_NO_REFDATA",
    "UNMARKABLE_NO_SETTLEMENT_VALUE",
    "AppendOnlyLedgerError",
    "ConflictingSheetError",
    "DriftReport",
    "IdeaLedger",
    "LedgerError",
    "LedgerFileError",
    "LegMark",
    "PresentedIdea",
    "Settlement",
    "apply_demotions",
    "cusum_low",
    "one_sided_t_statistic",
]

DEFAULT_LEDGER_PATH = Path("research/library/ledger.json")

LEDGER_SCHEMA_VERSION = 1

#: The denominator every return in this module is expressed over, tied to the engine's own
#: default rather than restated, so the ledger and the evidence it is compared against cannot
#: come to disagree about what a return is a fraction of.
DEFAULT_CAPITAL_BASE = BacktestConfig().starting_cash

#: Settled ideas the drift statistics look back over at one parameter point.
DEFAULT_WINDOW = 20

#: Settled ideas below which no demotion may fire, however bad the numbers look.
DEFAULT_MIN_SETTLED = 10

#: Multiples of the drift series' own standard deviation the CUSUM may fall before breaching.
CUSUM_K = 3.0

#: One-sided t-statistic at or below which a negative realised mean is a breach.
T_STATISTIC_THRESHOLD = -2.0

ENTRY_PRESENTED = "presented"
ENTRY_SETTLEMENT = "settlement"

STATUS_SETTLED = "SETTLED"
STATUS_UNMARKABLE = "UNMARKABLE"

#: The idea carried no decision-minute price on some leg, so it was never markable.
UNMARKABLE_NO_ENTRY_PRICE = "no_entry_price"

#: The contract is absent from the exit session's instrument master — outside the strike
#: ladder the corpus captures, or dropped on its own expiry date.
UNMARKABLE_CONTRACT_ABSENT = "contract_absent_from_instrument_master"

#: The contract is listed on the exit session but printed no bar at the decision minute.
UNMARKABLE_NO_PRINT = "listed_but_no_print_at_decision_minute"

#: The corpus holds no session view for a date the hold window needs.
UNMARKABLE_NO_EXIT_SESSION = "no_session_view_for_exit_date"

#: The corpus holds the session but no instrument master for it, so nothing on it can be
#: identified. A capture limit like :data:`UNMARKABLE_NO_EXIT_SESSION`, and a different one:
#: the session was captured and its reference data was not.
UNMARKABLE_NO_REFDATA = "session_holds_no_refdata"

#: The expiry session's underlying could not be settled under the rule in force that day.
UNMARKABLE_NO_SETTLEMENT_VALUE = "expiry_session_has_no_settlement_value"

EXIT_BAR_CLOSE = "bar_close_at_decision_minute"
EXIT_INTRINSIC = "intrinsic_at_expiry"

VERDICT_NOT_ENOUGH_SETTLED = "NOT_ENOUGH_SETTLED"
VERDICT_WITHIN_TOLERANCE = "WITHIN_TOLERANCE"
VERDICT_CUSUM_BREACH = "CUSUM_BREACH"
VERDICT_NEGATIVE_MEAN_BREACH = "NEGATIVE_MEAN_BREACH"

_BUY = "buy"


class LedgerError(ValueError):
    """Raised when the ledger declines to record or read something."""


class LedgerFileError(LedgerError):
    """Raised when a ledger file on disk cannot mean what it claims to."""


class AppendOnlyLedgerError(LedgerError):
    """Raised when a save would drop entries another writer appended."""


class ConflictingSheetError(LedgerError):
    """Raised when an as-of date already recorded is offered a different idea."""


@dataclass(frozen=True, slots=True)
class PresentedIdea:
    """One idea exactly as an operator was shown it, before the market answered.

    Every field is copied off the sheet rather than recomputed. ``expected_edge`` is the
    number the ranker attached that night — the admission card's mean return at hold scaled
    by the regime factor — and it is what the realised return is scored against, because it
    is what was actually promised.
    """

    as_of: str
    template_id: str
    parameters: Mapping[str, float]
    underlying: str
    rank: int
    score: float
    expected_edge: float
    granted_lots: int
    hold_sessions: int
    legs: tuple[Mapping[str, Any], ...]
    generated_at: str
    code_version: str
    requested_lots: int | None = None
    """Lots the strategy asked for at its target notional, before the caps bound."""

    @property
    def size_scale(self) -> float:
        """What a realised return must be multiplied by to be comparable with the card's.

        The strategy asked for a number of lots at its target notional and the participation
        caps granted some of them; the profit below is earned at the granted lots and the
        evidence was measured at the requested ones, so the ratio of the two puts both on one
        size. Lots rather than notionals, because a structure's notional sums its short legs
        and a straddle's would divide the ratio by two.

        ``1.0`` where the sheet reports no request, or where the scan was granted nothing:
        an idea that could not be sized has no ratio, and inventing one would put a made-up
        number into the drift series.
        """
        if self.requested_lots is None or self.granted_lots <= 0:
            return 1.0
        return self.requested_lots / self.granted_lots

    @property
    def parameter_key(self) -> str:
        return parameter_key(self.parameters)

    @property
    def key(self) -> tuple[str, str, str, str]:
        """What makes this idea one idea: a night, a template, a point, an underlying."""
        return (self.as_of, self.template_id, self.parameter_key, self.underlying)

    @property
    def identity(self) -> tuple[str, str]:
        """The library identity this idea's evidence lives under."""
        return (self.template_id, self.parameter_key)

    @property
    def as_of_date(self) -> dt.date:
        return dt.date.fromisoformat(self.as_of)

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": ENTRY_PRESENTED,
            "as_of": self.as_of,
            "template_id": self.template_id,
            "parameters": {name: float(value) for name, value in sorted(self.parameters.items())},
            "parameter_key": self.parameter_key,
            "underlying": self.underlying,
            "rank": self.rank,
            "score": self.score,
            "expected_edge": self.expected_edge,
            "granted_lots": self.granted_lots,
            "hold_sessions": self.hold_sessions,
            "requested_lots": self.requested_lots,
            "legs": [dict(leg) for leg in self.legs],
            "generated_at": self.generated_at,
            "code_version": self.code_version,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> PresentedIdea:
        return cls(
            as_of=str(payload["as_of"]),
            template_id=str(payload["template_id"]),
            parameters={str(k): float(v) for k, v in (payload.get("parameters") or {}).items()},
            underlying=str(payload["underlying"]),
            rank=int(payload["rank"]),
            score=float(payload["score"]),
            expected_edge=float(payload["expected_edge"]),
            granted_lots=int(payload["granted_lots"]),
            hold_sessions=int(payload["hold_sessions"]),
            requested_lots=(
                None if payload.get("requested_lots") is None else int(payload["requested_lots"])
            ),
            legs=tuple(dict(leg) for leg in payload.get("legs") or ()),
            generated_at=str(payload["generated_at"]),
            code_version=str(payload["code_version"]),
        )


@dataclass(frozen=True, slots=True)
class LegMark:
    """One leg of a settled idea, priced at both ends or explicitly not priced at all."""

    trading_symbol: str
    side: str
    units: int
    entry_price: float | None
    exit_price: float | None
    exit_source: str | None
    exit_as_of: str | None
    unmarkable_cause: str | None = None
    unmarkable_reason: str | None = None

    @property
    def signed_units(self) -> int:
        """Units with the position's sign — a sold leg is short, so its units are negative."""
        return self.units if self.side == _BUY else -self.units

    @property
    def pnl(self) -> float | None:
        if self.entry_price is None or self.exit_price is None:
            return None
        return self.signed_units * (self.exit_price - self.entry_price)

    def as_dict(self) -> dict[str, Any]:
        return {
            "trading_symbol": self.trading_symbol,
            "side": self.side,
            "units": self.units,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "exit_source": self.exit_source,
            "exit_as_of": self.exit_as_of,
            "unmarkable_cause": self.unmarkable_cause,
            "unmarkable_reason": self.unmarkable_reason,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> LegMark:
        return cls(
            trading_symbol=str(payload["trading_symbol"]),
            side=str(payload["side"]),
            units=int(payload["units"]),
            entry_price=_optional_float(payload.get("entry_price")),
            exit_price=_optional_float(payload.get("exit_price")),
            exit_source=_optional_str(payload.get("exit_source")),
            exit_as_of=_optional_str(payload.get("exit_as_of")),
            unmarkable_cause=_optional_str(payload.get("unmarkable_cause")),
            unmarkable_reason=_optional_str(payload.get("unmarkable_reason")),
        )


@dataclass(frozen=True, slots=True)
class Settlement:
    """What one presented idea turned into once its hold had elapsed.

    ``realised_return`` is ``None`` exactly when ``status`` is ``UNMARKABLE``: there is no
    number here, and the difference between that and a return of zero is the whole reason
    this field is nullable.
    """

    as_of: str
    template_id: str
    parameter_key: str
    underlying: str
    status: str
    exit_as_of: str | None
    hold_sessions: int
    capital_base: float
    pnl: float | None
    realised_return: float | None
    expected_return: float
    legs: tuple[LegMark, ...]
    reason: str
    settled_at: str
    size_scale: float = 1.0

    @property
    def key(self) -> tuple[str, str, str, str]:
        return (self.as_of, self.template_id, self.parameter_key, self.underlying)

    @property
    def identity(self) -> tuple[str, str]:
        return (self.template_id, self.parameter_key)

    @property
    def drift(self) -> float | None:
        """Realised minus expected, or ``None`` when there is no realised number."""
        if self.realised_return is None:
            return None
        return self.realised_return - self.expected_return

    @property
    def unmarkable_causes(self) -> tuple[str, ...]:
        """Every distinct cause that stopped a leg being marked, in first-seen order."""
        seen: list[str] = []
        for leg in self.legs:
            if leg.unmarkable_cause is not None and leg.unmarkable_cause not in seen:
                seen.append(leg.unmarkable_cause)
        return tuple(seen)

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": ENTRY_SETTLEMENT,
            "as_of": self.as_of,
            "template_id": self.template_id,
            "parameter_key": self.parameter_key,
            "underlying": self.underlying,
            "status": self.status,
            "exit_as_of": self.exit_as_of,
            "hold_sessions": self.hold_sessions,
            "capital_base": self.capital_base,
            "size_scale": self.size_scale,
            "pnl": self.pnl,
            "realised_return": self.realised_return,
            "expected_return": self.expected_return,
            "drift": self.drift,
            "unmarkable_causes": list(self.unmarkable_causes),
            "legs": [leg.as_dict() for leg in self.legs],
            "reason": self.reason,
            "settled_at": self.settled_at,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> Settlement:
        return cls(
            as_of=str(payload["as_of"]),
            template_id=str(payload["template_id"]),
            parameter_key=str(payload["parameter_key"]),
            underlying=str(payload["underlying"]),
            status=str(payload["status"]),
            exit_as_of=_optional_str(payload.get("exit_as_of")),
            hold_sessions=int(payload["hold_sessions"]),
            capital_base=float(payload["capital_base"]),
            size_scale=float(payload.get("size_scale", 1.0)),
            pnl=_optional_float(payload.get("pnl")),
            realised_return=_optional_float(payload.get("realised_return")),
            expected_return=float(payload["expected_return"]),
            legs=tuple(LegMark.from_dict(leg) for leg in payload.get("legs") or ()),
            reason=str(payload["reason"]),
            settled_at=str(payload["settled_at"]),
        )


@dataclass(frozen=True, slots=True)
class DriftReport:
    """Whether one admitted point is still earning what it was admitted on.

    ``verdict`` is the whole answer. ``NOT_ENOUGH_SETTLED`` is not a pass — it says the
    question has not been asked yet, and ``n_settled`` says how far off asking it is.
    """

    template_id: str
    parameter_key: str
    n_settled: int
    n_unmarkable: int
    window: int
    min_settled: int
    realised_mean: float | None
    expected_mean: float | None
    card_mean_return_at_hold: float | None
    card_hit_rate: float | None
    realised_hit_rate: float | None
    hit_rate_deviation: float | None
    sigma: float | None
    cusum: float | None
    cusum_threshold: float | None
    t_statistic: float | None
    verdict: str
    reason: str
    card_mean_return_per_round_trip: float | None = None
    expected_scale: float = 1.0
    """What each idea's promised edge was multiplied by to reach a per-trade expectation.

    ``1.0`` means the card carried no per-position figure to rescale onto and the comparison
    is the promised per-session-scaled one; :attr:`reason` says so when that happens.

    :attr:`expected_mean` is therefore the *scaled* mean, while the ``expected_return`` on
    each settlement row is the number the operator was promised that night, unscaled. The
    row records what was said; the report records what it is being judged against, and this
    field is the whole difference between them.
    """

    @property
    def identity(self) -> tuple[str, str]:
        return (self.template_id, self.parameter_key)

    @property
    def breached(self) -> bool:
        return self.verdict in (VERDICT_CUSUM_BREACH, VERDICT_NEGATIVE_MEAN_BREACH)

    def as_dict(self) -> dict[str, Any]:
        return {
            "template_id": self.template_id,
            "parameter_key": self.parameter_key,
            "n_settled": self.n_settled,
            "n_unmarkable": self.n_unmarkable,
            "window": self.window,
            "min_settled": self.min_settled,
            "realised_mean": self.realised_mean,
            "expected_mean": self.expected_mean,
            "card_mean_return_at_hold": self.card_mean_return_at_hold,
            "card_mean_return_per_round_trip": self.card_mean_return_per_round_trip,
            "expected_scale": self.expected_scale,
            "card_hit_rate": self.card_hit_rate,
            "realised_hit_rate": self.realised_hit_rate,
            "hit_rate_deviation": self.hit_rate_deviation,
            "sigma": self.sigma,
            "cusum": self.cusum,
            "cusum_threshold": self.cusum_threshold,
            "t_statistic": self.t_statistic,
            "verdict": self.verdict,
            "reason": self.reason,
        }

    def summary(self) -> str:
        """One line an operator can read without opening the JSON.

        It names the rule's two per-invocation settings as well as its verdict. A demotion
        reason that said only "the CUSUM breached" could not be checked afterwards: over how
        many settled ideas, and above what floor, are what decide whether it should have.
        """
        point = self.parameter_key or "(no parameters)"
        head = f"{self.template_id} [{point}]: {self.verdict}"
        rule = f"window {self.window}, min_settled {self.min_settled}"
        if self.realised_mean is None:
            return f"{head} — {self.reason} [{rule}]"
        expected = "none" if self.expected_mean is None else f"{self.expected_mean:+.6g}"
        return (
            f"{head} — realised {self.realised_mean:+.6g} vs expected {expected} over "
            f"{self.n_settled} settled ({self.n_unmarkable} unmarkable) — {self.reason} "
            f"[{rule}]"
        )


def cusum_low(drifts: Sequence[float]) -> float:
    """The lowest point of the one-sided lower CUSUM of ``drifts``.

    ``S_0 = 0`` and ``S_i = min(0, S_{i-1} + d_i)``, and the value returned is ``min(S)``,
    which is zero or negative. There is no slack term: the rule this feeds must not carry a
    knob that could be tuned after the fact.
    """
    running = 0.0
    lowest = 0.0
    for value in drifts:
        running = min(0.0, running + value)
        lowest = min(lowest, running)
    return lowest


def one_sided_t_statistic(values: Sequence[float]) -> float | None:
    """``mean / (sample stdev / sqrt(n))``, or ``None`` where it is not a number.

    Undefined below two observations — a single point has no dispersion — and undefined at
    zero dispersion, where the ratio would be an infinity dressed up as evidence.
    """
    n = len(values)
    if n < 2:
        return None
    mean = math.fsum(values) / n
    variance = math.fsum((value - mean) ** 2 for value in values) / (n - 1)
    deviation = math.sqrt(variance)
    if deviation == 0.0:
        return None
    return mean / (deviation / math.sqrt(n))


def _sample_deviation(values: Sequence[float]) -> float | None:
    if len(values) < 2:
        return None
    mean = math.fsum(values) / len(values)
    return math.sqrt(math.fsum((value - mean) ** 2 for value in values) / (len(values) - 1))


def _optional_float(value: Any) -> float | None:
    return None if value is None else float(value)


def _optional_str(value: Any) -> str | None:
    return None if value is None else str(value)


class IdeaLedger:
    """Every idea the ranker presented, and what the market made of it.

    Entries are appended and never edited. A presented idea is one entry; the settlement
    that closes it is another, and the state of an idea is the last settlement naming it.
    """

    def __init__(self, path: Path = DEFAULT_LEDGER_PATH, *, clock: Clock | None = None) -> None:
        self._path = Path(path)
        self._clock = clock if clock is not None else SystemClock()
        self._presented: list[PresentedIdea] = []
        self._settlements: list[Settlement] = []
        self._order: list[tuple[str, int]] = []

    @classmethod
    def load(cls, path: Path = DEFAULT_LEDGER_PATH, *, clock: Clock | None = None) -> IdeaLedger:
        """Read a ledger, or start an empty one where no file exists yet."""
        ledger = cls(path, clock=clock)
        if not ledger._path.exists():
            return ledger
        try:
            document = json.loads(ledger._path.read_text())
        except json.JSONDecodeError as error:
            raise LedgerFileError(
                f"the ledger at {ledger._path} is not readable JSON: {error}"
            ) from error
        entries = document.get("entries")
        if not isinstance(entries, list):
            raise LedgerFileError(
                f"the ledger at {ledger._path} carries no 'entries' list, so it is not a ledger "
                "this reader understands"
            )
        for row in entries:
            ledger._append(_entry_from_dict(row, path=ledger._path))
        return ledger

    @property
    def path(self) -> Path:
        return self._path

    def _append(self, entry: PresentedIdea | Settlement) -> None:
        if isinstance(entry, PresentedIdea):
            self._order.append((ENTRY_PRESENTED, len(self._presented)))
            self._presented.append(entry)
        else:
            self._order.append((ENTRY_SETTLEMENT, len(self._settlements)))
            self._settlements.append(entry)

    def entries(self) -> Iterator[PresentedIdea | Settlement]:
        """Every entry in the order it was appended."""
        for kind, index in self._order:
            yield self._presented[index] if kind == ENTRY_PRESENTED else self._settlements[index]

    def presented(self) -> tuple[PresentedIdea, ...]:
        return tuple(self._presented)

    def settlements(self) -> tuple[Settlement, ...]:
        return tuple(self._settlements)

    def settlement_for(self, key: tuple[str, str, str, str]) -> Settlement | None:
        """The last settlement naming ``key``, or ``None`` while the idea is still open."""
        for settlement in reversed(self._settlements):
            if settlement.key == key:
                return settlement
        return None

    def open_ideas(self) -> tuple[PresentedIdea, ...]:
        """Presented ideas no settlement has closed, oldest first."""
        settled = {settlement.key for settlement in self._settlements}
        return tuple(idea for idea in self._presented if idea.key not in settled)

    def record_sheet(self, sheet: Any) -> tuple[PresentedIdea, ...]:
        """File every idea on one night's sheet, whether or not it was traded.

        ``sheet`` is either an :class:`~xman_research.alpha.ranker.IdeaSheet` or the parsed
        JSON the CLI's ``scan`` wrote from one. Accepting both is deliberate: the ledger keeps
        a flat row per presented idea and needs no reconstructed ``Idea`` object, so demanding
        one would mean a ``from_dict`` chain across the ranker and the explanation layer to
        rebuild objects this method would immediately flatten again. The JSON document is the
        artefact an operator actually has on disk, and reading it directly is the shorter path
        to the same rows.

        Recording is idempotent on an idea's key — its as-of date, template, parameter point
        and underlying. An identical row already filed is skipped; a *different* row for a key
        already filed is refused, because the ledger records what was shown on a night and not
        the latest opinion about it.

        Ideas the scan granted no lots are still recorded. What the ranker proposed is the
        thing under audit, and dropping the ones an operator could not size would leave the
        drift statistics measuring a subset selected on feasibility.
        """
        document = sheet.as_dict() if hasattr(sheet, "as_dict") else dict(sheet)
        as_of = str(document["as_of"])
        generated_at = str(document["generated_at"])
        code_version = str(document["code_version"])
        existing = {idea.key: idea for idea in self._presented}
        recorded: list[PresentedIdea] = []
        for row in document.get("ideas") or ():
            idea = _presented_from_sheet_row(
                row, as_of=as_of, generated_at=generated_at, code_version=code_version
            )
            already = existing.get(idea.key)
            if already is not None:
                if already.as_dict() != idea.as_dict():
                    raise ConflictingSheetError(
                        f"the ledger at {self._path} already holds a different idea for "
                        f"{idea.template_id} [{idea.parameter_key or 'no parameters'}] on "
                        f"{idea.underlying} at {as_of}. A recorded night is what the operator "
                        "was shown and is not rewritten; re-scan under a new as-of date, or "
                        "record into a different ledger."
                    )
                continue
            self._append(idea)
            existing[idea.key] = idea
            recorded.append(idea)
        return tuple(recorded)

    def settle(
        self,
        *,
        as_of_end: dt.date,
        store: SessionStore,
        decision_time: dt.time = DEFAULT_DECISION_TIME,
        settlement_rules: tuple[SettlementRule, ...] = SETTLEMENT_RULES,
        gaps_reason: str | None = None,
        seal_override: str | None = None,
    ) -> tuple[Settlement, ...]:
        """Mark every open idea whose hold window has elapsed by ``as_of_end``.

        The fill convention is the engine's: enter and exit at the bar close at the decision
        minute, no slippage, at the units the sheet already granted — the ranker capped those
        against the participation limits and re-capping here would apply the limit twice. A
        leg whose contract expires strictly before the exit session is cash-settled at
        intrinsic against the underlying's settlement value on its expiry date, which is what
        :func:`xman_research.backtest.engine._settle_expiring` does; a leg expiring *on* the
        exit session is marked at the close like any other, because the engine's exit runs at
        the decision minute and settlement runs after it.

        The exit session is the ``hold_sessions``-th session the corpus holds after the entry,
        so a gap in the capture lengthens the calendar hold rather than skipping the exit —
        the same walk the engine makes over resolved sessions. An idea whose exit session has
        not arrived by ``as_of_end`` is left open and returns no entry.

        Nothing outside ``[as_of, as_of_end]`` is ever resolved. A ledger settling through a
        date cannot read past it, which is what keeps a sealed holdout sealed.

        Sessions are read **whole**, unlike the truncated views the ranker is handed. The
        ranker's view stops at the decision minute because a feature computed from later bars
        would be look-ahead; a settlement is taken after the fact about a session that has
        entirely happened, and an expiring leg is paid out of the settlement window, which
        sits after the decision minute by construction. Reading a truncated view here would
        make every expiry unmarkable for want of the bars that decide it.

        The denominator realised returns are expressed over is
        :data:`DEFAULT_CAPITAL_BASE`, read off the engine's own default rather than accepted
        from the caller: it must equal the base the admission evidence was measured on, and a
        parameter through which it could differ is a parameter through which the whole
        comparison this module makes can be made meaningless without anything noticing.

        ``as_of_end`` at or past :data:`~xman_research.alpha.holdout.HOLDOUT_FIRST_DATE`
        needs a written ``seal_override``. Settling reads sessions, and a session read here
        is spent for ``research/h1`` too.
        """
        override = require_unsealed(
            as_of_end, what="the settlement window", override_reason=seal_override
        )
        capital_base = DEFAULT_CAPITAL_BASE
        due = [idea for idea in self.open_ideas() if idea.as_of_date <= as_of_end]
        if not due:
            return ()
        settled: list[Settlement] = []
        readers: dict[str, _SessionReader] = {}
        for idea in due:
            reader = readers.get(idea.underlying)
            if reader is None:
                reader = _SessionReader(
                    store,
                    idea.underlying,
                    _refs_between(
                        store,
                        idea.underlying,
                        min(
                            other.as_of_date for other in due if other.underlying == idea.underlying
                        ),
                        as_of_end,
                        gaps_reason=gaps_reason,
                    ),
                )
                readers[idea.underlying] = reader
            entry = self._settle_one(
                idea,
                reader=reader,
                decision_time=decision_time,
                capital_base=capital_base,
                settlement_rules=settlement_rules,
                seal_override=override,
            )
            if entry is None:
                continue
            self._append(entry)
            settled.append(entry)
        return tuple(settled)

    def _settle_one(
        self,
        idea: PresentedIdea,
        *,
        reader: _SessionReader,
        decision_time: dt.time,
        capital_base: float,
        settlement_rules: tuple[SettlementRule, ...],
        seal_override: str | None,
    ) -> Settlement | None:
        after = [day for day in reader.session_dates if day > idea.as_of_date]
        if len(after) < idea.hold_sessions:
            return None
        exit_date = after[idea.hold_sessions - 1]
        marks = self._mark_legs(
            idea,
            exit_date=exit_date,
            reader=reader,
            decision_time=decision_time,
            settlement_rules=settlement_rules,
        )
        unmarkable = [leg for leg in marks if leg.unmarkable_cause is not None]
        if unmarkable:
            causes = ", ".join(
                f"{leg.trading_symbol}: {leg.unmarkable_reason}" for leg in unmarkable
            )
            return Settlement(
                as_of=idea.as_of,
                template_id=idea.template_id,
                parameter_key=idea.parameter_key,
                underlying=idea.underlying,
                status=STATUS_UNMARKABLE,
                exit_as_of=exit_date.isoformat(),
                hold_sessions=idea.hold_sessions,
                capital_base=capital_base,
                size_scale=idea.size_scale,
                pnl=None,
                realised_return=None,
                expected_return=idea.expected_edge,
                legs=marks,
                reason=(
                    f"{len(unmarkable)} of {len(marks)} leg(s) could not be marked, so this "
                    f"idea has no realised return — {causes}"
                ),
                settled_at=self._now(),
            )
        pnl = math.fsum(leg.pnl or 0.0 for leg in marks)
        scale = idea.size_scale
        realised = (pnl / capital_base) * scale
        return Settlement(
            as_of=idea.as_of,
            template_id=idea.template_id,
            parameter_key=idea.parameter_key,
            underlying=idea.underlying,
            status=STATUS_SETTLED,
            exit_as_of=exit_date.isoformat(),
            hold_sessions=idea.hold_sessions,
            capital_base=capital_base,
            size_scale=scale,
            pnl=pnl,
            realised_return=realised,
            expected_return=idea.expected_edge,
            legs=marks,
            reason=(
                f"entered {idea.as_of}, exited {exit_date.isoformat()} after "
                f"{idea.hold_sessions} session(s); {pnl:+.2f} on a capital base of "
                f"{capital_base:.0f}"
                + (
                    ""
                    if scale == 1.0
                    else (
                        f", scaled by {scale:.4g} to the notional the evidence was measured "
                        "at rather than the one the caps granted"
                    )
                )
                + ("" if seal_override is None else f"; past the corpus seal: {seal_override}")
            ),
            settled_at=self._now(),
        )

    def _mark_legs(
        self,
        idea: PresentedIdea,
        *,
        exit_date: dt.date,
        reader: _SessionReader,
        decision_time: dt.time,
        settlement_rules: tuple[SettlementRule, ...],
    ) -> tuple[LegMark, ...]:
        marks: list[LegMark] = []
        for leg in idea.legs:
            symbol = str(leg["trading_symbol"])
            side = str(leg["side"])
            units = int(leg["units"])
            entry_price = _optional_float(leg.get("price_at_decision_minute"))
            expiry = dt.date.fromisoformat(str(leg["expiry"]))
            if entry_price is None:
                marks.append(
                    LegMark(
                        trading_symbol=symbol,
                        side=side,
                        units=units,
                        entry_price=None,
                        exit_price=None,
                        exit_source=None,
                        exit_as_of=None,
                        unmarkable_cause=UNMARKABLE_NO_ENTRY_PRICE,
                        unmarkable_reason=(
                            "the sheet presented this leg with no price at the decision "
                            "minute, so there is no entry to mark against"
                        ),
                    )
                )
                continue
            if expiry < exit_date:
                marks.append(
                    _intrinsic_mark(
                        symbol=symbol,
                        side=side,
                        units=units,
                        entry_price=entry_price,
                        strike=float(leg["strike"]),
                        option_type=str(leg["option_type"]),
                        expiry=expiry,
                        reader=reader,
                        settlement_rules=settlement_rules,
                    )
                )
                continue
            marks.append(
                _close_mark(
                    symbol=symbol,
                    side=side,
                    units=units,
                    entry_price=entry_price,
                    exit_date=exit_date,
                    reader=reader,
                    decision_time=decision_time,
                )
            )
        return tuple(marks)

    def drift(
        self,
        library: TemplateLibrary,
        *,
        window: int = DEFAULT_WINDOW,
        min_settled: int = DEFAULT_MIN_SETTLED,
        template_id: str | None = None,
    ) -> tuple[DriftReport, ...]:
        """One report per ``(template_id, parameter_key)`` the ledger has settled ideas for.

        The window is the last ``window`` **settled** ideas at that point in ledger order;
        unmarkable ones are counted and reported but never enter a statistic, because an idea
        the apparatus could not price is evidence about the corpus and not about the template.

        Every report is returned, including the ones the rule declines to judge. Filtering to
        the breached ones here would make "no report" mean both "healthy" and "never asked".
        """
        if window < 1:
            raise LedgerError(f"window must be at least 1 settled idea, got {window}")
        if min_settled < 1:
            raise LedgerError(f"min_settled must be at least 1 settled idea, got {min_settled}")
        grouped: dict[tuple[str, str], list[Settlement]] = {}
        for settlement in self._settlements:
            if template_id is not None and settlement.template_id != template_id:
                continue
            grouped.setdefault(settlement.identity, []).append(settlement)
        return tuple(
            _drift_report(
                identity,
                entries,
                library=library,
                window=window,
                min_settled=min_settled,
            )
            for identity, entries in sorted(grouped.items())
        )

    def save(self) -> Path:
        """Write the ledger, refusing to drop entries another writer appended.

        The stored entries must be a prefix of the in-memory ones. The comparison runs both
        sides through the readers, so an entry written before an optional field existed
        compares equal to a freshly serialised one and does not report a writer who was never
        there. It is a check and not a lock, on the same terms as the template library's.
        """
        if self._path.exists():
            stored_raw = json.loads(self._path.read_text()).get("entries") or []
            mine = [entry.as_dict() for entry in self.entries()]
            try:
                stored = [_entry_from_dict(row, path=self._path).as_dict() for row in stored_raw]
            except (KeyError, TypeError, ValueError) as error:
                raise LedgerFileError(
                    f"the ledger at {self._path} holds an entry this reader cannot "
                    f"deserialise, so it cannot be appended to: {error}"
                ) from error
            if len(stored) > len(mine) or stored != mine[: len(stored)]:
                raise AppendOnlyLedgerError(
                    f"the ledger at {self._path} holds {len(stored)} entries that are not a "
                    f"prefix of the {len(mine)} about to be written — another writer has "
                    "changed it since this one loaded. Reload and re-apply."
                )
        self._path.parent.mkdir(parents=True, exist_ok=True)
        document = (
            json.dumps(
                {
                    "schema_version": LEDGER_SCHEMA_VERSION,
                    "entries": [entry.as_dict() for entry in self.entries()],
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
        temporary = self._path.with_name(f"{self._path.name}.{os.getpid()}.tmp")
        temporary.write_text(document)
        os.replace(temporary, self._path)
        return self._path

    def _now(self) -> str:
        return self._clock.now().isoformat()


def apply_demotions(
    reports: Sequence[DriftReport],
    library: TemplateLibrary,
    *,
    by: str,
) -> tuple[DriftReport, ...]:
    """Demote every breached point in ``reports`` and return the ones demoted.

    The library's demotion carries a written reason and the name of whoever made the call, and
    that stays true here: this function is the rule's hand on the lever, and ``by`` is the
    operator who set the rule running. The reason string carries the actual numbers, so the
    library entry is readable without the ledger beside it.

    Points already demoted are left alone — the rule keeps breaching after it has fired, and
    a second demotion entry every night would bury the one that mattered.
    """
    live = {record.identity for record in library.admitted()}
    demoted: list[DriftReport] = []
    for report in reports:
        if not report.breached or report.identity not in live:
            continue
        library.demote(
            template_id=report.template_id,
            parameters=_parameters_from_key(report.parameter_key),
            by=by,
            reason=report.summary(),
        )
        demoted.append(report)
    return tuple(demoted)


def _drift_report(
    identity: tuple[str, str],
    entries: Sequence[Settlement],
    *,
    library: TemplateLibrary,
    window: int,
    min_settled: int,
) -> DriftReport:
    template_id, key = identity
    marked = [entry for entry in entries if entry.status == STATUS_SETTLED][-window:]
    n_unmarkable = sum(1 for entry in entries if entry.status == STATUS_UNMARKABLE)
    # An empty key is not a selector for "the template's only point" — it matches every
    # entry, so a library holding the template at two points would refuse the lookup and
    # fail the whole run over one hand-built row. It carries no point, so it finds no card.
    point = _parameters_from_key(key)
    record = library.current(template_id, parameters=point) if point else None
    card_mean = record.evidence.mean_return_at_hold if record is not None else None
    card_per_trip = record.evidence.mean_return_per_round_trip if record is not None else None
    card_hit = record.evidence.hit_rate if record is not None else None
    scale, scale_note = _expected_scale(card_mean, card_per_trip)
    base_note = f" — {scale_note}" if scale_note else ""
    common: dict[str, Any] = {
        "template_id": template_id,
        "parameter_key": key,
        "n_settled": len(marked),
        "n_unmarkable": n_unmarkable,
        "window": window,
        "min_settled": min_settled,
        "card_mean_return_at_hold": card_mean,
        "card_mean_return_per_round_trip": card_per_trip,
        "expected_scale": scale,
        "card_hit_rate": card_hit,
    }
    if not marked:
        return DriftReport(
            realised_mean=None,
            expected_mean=None,
            realised_hit_rate=None,
            hit_rate_deviation=None,
            sigma=None,
            cusum=None,
            cusum_threshold=None,
            t_statistic=None,
            verdict=VERDICT_NOT_ENOUGH_SETTLED,
            reason=(
                f"not enough settled ideas to judge: 0 of {min_settled}"
                + (f", and {n_unmarkable} that could not be marked" if n_unmarkable else "")
            ),
            **common,
        )
    realised = [entry.realised_return or 0.0 for entry in marked]
    expected = [entry.expected_return * scale for entry in marked]
    drifts = [r - e for r, e in zip(realised, expected, strict=True)]
    realised_mean = math.fsum(realised) / len(realised)
    expected_mean = math.fsum(expected) / len(expected)
    realised_hit = sum(1 for value in realised if value > 0.0) / len(realised)
    hit_deviation = None if card_hit is None else realised_hit - card_hit
    sigma = _sample_deviation(drifts)
    cusum = cusum_low(drifts)
    threshold = None if sigma is None else -CUSUM_K * sigma
    t_statistic = one_sided_t_statistic(realised)
    common.update(
        {
            "realised_mean": realised_mean,
            "expected_mean": expected_mean,
            "realised_hit_rate": realised_hit,
            "hit_rate_deviation": hit_deviation,
            "sigma": sigma,
            "cusum": cusum,
            "cusum_threshold": threshold,
            "t_statistic": t_statistic,
        }
    )
    if len(marked) < min_settled:
        return DriftReport(
            verdict=VERDICT_NOT_ENOUGH_SETTLED,
            reason=(
                f"not enough settled ideas to judge: {len(marked)} of {min_settled}. The "
                "statistics are reported so the trend is visible, and no demotion may fire "
                f"on them.{base_note}"
            ),
            **common,
        )
    # The negative-mean rule is checked first because it names the more specific fact. It is
    # never the only rule that fires: the whole window is itself a contiguous run, so the
    # CUSUM is at most the window's total shortfall, and a mean significant enough to reach
    # a t of -2 has already carried that total past three sigma. Checking the CUSUM first
    # would therefore report every losing template as "drifted" and leave "losing money"
    # unreachable, which is the one distinction an operator most needs from this report.
    reference = card_per_trip if card_per_trip is not None else card_mean
    if reference is None:
        reference = expected_mean
    if (
        realised_mean < 0.0
        and reference is not None
        and reference > 0.0
        and t_statistic is not None
        and t_statistic <= T_STATISTIC_THRESHOLD
    ):
        return DriftReport(
            verdict=VERDICT_NEGATIVE_MEAN_BREACH,
            reason=(
                f"realised mean {realised_mean:.6g} over {len(marked)} settled ideas is below "
                f"zero against an admitted {reference:.6g}, at a one-sided t of "
                f"{t_statistic:.4g} (threshold {T_STATISTIC_THRESHOLD:g}){base_note}"
            ),
            **common,
        )
    if threshold is not None and sigma is not None and sigma > 0.0 and cusum <= threshold:
        return DriftReport(
            verdict=VERDICT_CUSUM_BREACH,
            reason=(
                f"the drift CUSUM reached {cusum:.6g}, at or below {CUSUM_K:g} sigma "
                f"({threshold:.6g}, sigma={sigma:.6g}) over {len(marked)} settled ideas"
                f"{base_note}"
            ),
            **common,
        )
    if sigma is None or sigma == 0.0:
        return DriftReport(
            verdict=VERDICT_WITHIN_TOLERANCE,
            reason=(
                f"the drift series over {len(marked)} settled ideas has no dispersion, so the "
                "CUSUM has no sigma to breach. Where the expectation is constant across the "
                "window that also makes the realised series constant, its t-statistic "
                "undefined and the negative-mean rule unreachable — ten identical losses "
                f"land here{base_note}"
            ),
            **common,
        )
    return DriftReport(
        verdict=VERDICT_WITHIN_TOLERANCE,
        reason=(
            f"CUSUM {cusum:.6g} is above {threshold:.6g} and the realised mean "
            f"{realised_mean:+.6g} does not breach{base_note}"
        ),
        **common,
    )


def _expected_scale(
    mean_return_at_hold: float | None, mean_return_per_round_trip: float | None
) -> tuple[float, str]:
    """What to multiply a promised edge by to make it one trade's expectation.

    A sheet's ``expected_edge`` is the card's ``mean_return_at_hold`` times a regime factor,
    and both card figures describe the same measured run, so their ratio converts the first
    into ``mean_return_per_round_trip`` and carries the regime factor through untouched.

    The ratio is refused — and the promised edge left alone — when either figure is absent,
    when the hold-scaled figure is zero, or when the two disagree in sign. A negative ratio
    would flip every drift, which is a larger error than the one being corrected.
    """
    if mean_return_at_hold is None or mean_return_per_round_trip is None:
        return 1.0, (
            "the admission card reports no per-position return, so the comparison is against "
            "the per-session mean scaled by the hold, which overstates a template's per-trade "
            "shortfall by however often it sits flat"
        )
    if mean_return_at_hold == 0.0:
        return 1.0, (
            "the admission card's mean return at hold is zero, so there is no ratio to carry "
            "the per-position figure onto each idea's promised edge"
        )
    if (mean_return_at_hold > 0.0) != (mean_return_per_round_trip > 0.0):
        return 1.0, (
            f"the admission card's per-session mean scaled by the hold "
            f"({mean_return_at_hold:.6g}) and its per-position mean "
            f"({mean_return_per_round_trip:.6g}) disagree in sign, so no rescaling is applied"
        )
    return mean_return_per_round_trip / mean_return_at_hold, ""


def _intrinsic_mark(
    *,
    symbol: str,
    side: str,
    units: int,
    entry_price: float,
    strike: float,
    option_type: str,
    expiry: dt.date,
    reader: _SessionReader,
    settlement_rules: tuple[SettlementRule, ...],
) -> LegMark:
    """Cash-settle one expired leg at intrinsic, on the engine's own settlement value."""
    unmarkable = LegMark(
        trading_symbol=symbol,
        side=side,
        units=units,
        entry_price=entry_price,
        exit_price=None,
        exit_source=None,
        exit_as_of=expiry.isoformat(),
    )
    view = reader.view(expiry)
    if view is None:
        cause, detail = reader.absence(expiry)
        return _with_cause(
            unmarkable,
            cause,
            f"{detail}, and it is the leg's expiry date, so it cannot be settled at intrinsic",
        )
    try:
        settled = settlement_value(view, rules=settlement_rules)
    except SettlementWindowError as error:
        return _with_cause(unmarkable, UNMARKABLE_NO_SETTLEMENT_VALUE, str(error))
    contract = view.universe.by_symbol(symbol)
    if contract is not None:
        intrinsic = contract.intrinsic(settled.value)
    else:
        # A contract is dropped from the instrument master on its own expiry date, so the
        # leg being settled is routinely absent from the very session that settles it. The
        # strike and right travel on the ledger row for exactly this case. The formula is
        # `Contract.intrinsic`'s and must stay identical to it: a settlement this module
        # computed differently from the engine would put the ledger and the evidence it
        # audits on two different definitions of what an expiry pays.
        intrinsic = (
            max(0.0, settled.value - strike)
            if option_type == "CE"
            else max(0.0, strike - settled.value)
        )
    return LegMark(
        trading_symbol=symbol,
        side=side,
        units=units,
        entry_price=entry_price,
        exit_price=intrinsic,
        exit_source=EXIT_INTRINSIC,
        exit_as_of=expiry.isoformat(),
    )


def _close_mark(
    *,
    symbol: str,
    side: str,
    units: int,
    entry_price: float,
    exit_date: dt.date,
    reader: _SessionReader,
    decision_time: dt.time,
) -> LegMark:
    """Mark one leg at the bar close on the exit session's decision minute."""
    unmarkable = LegMark(
        trading_symbol=symbol,
        side=side,
        units=units,
        entry_price=entry_price,
        exit_price=None,
        exit_source=None,
        exit_as_of=exit_date.isoformat(),
    )
    view = reader.view(exit_date)
    if view is None:
        cause, detail = reader.absence(exit_date)
        return _with_cause(
            unmarkable, cause, f"{detail}, and it is where this leg's hold window ends"
        )
    if view.universe.by_symbol(symbol) is None:
        return _with_cause(
            unmarkable,
            UNMARKABLE_CONTRACT_ABSENT,
            f"{symbol} is absent from {exit_date.isoformat()}'s instrument master — the "
            "capture holds a strike ladder around the money and this contract is outside it, "
            "so the apparatus never saw the leg on its exit session",
        )
    minute = view.minute_at_or_after(decision_time)
    if minute is None:
        return _with_cause(
            unmarkable,
            UNMARKABLE_NO_PRINT,
            f"{exit_date.isoformat()} holds no minute at or after "
            f"{decision_time.isoformat(timespec='minutes')}, so there is no decision minute "
            "to mark at",
        )
    bar = view.bar(symbol, minute)
    price = bar.close if bar is not None else None
    if price is None:
        return _with_cause(
            unmarkable,
            UNMARKABLE_NO_PRINT,
            f"{symbol} is listed on {exit_date.isoformat()} but printed no bar at "
            f"{minute.isoformat()} — the contract traded nowhere at the decision minute",
        )
    return LegMark(
        trading_symbol=symbol,
        side=side,
        units=units,
        entry_price=entry_price,
        exit_price=float(price),
        exit_source=EXIT_BAR_CLOSE,
        exit_as_of=exit_date.isoformat(),
    )


def _with_cause(mark: LegMark, cause: str, reason: str) -> LegMark:
    return LegMark(
        trading_symbol=mark.trading_symbol,
        side=mark.side,
        units=mark.units,
        entry_price=mark.entry_price,
        exit_price=None,
        exit_source=None,
        exit_as_of=mark.exit_as_of,
        unmarkable_cause=cause,
        unmarkable_reason=reason,
    )


def _refs_between(
    store: SessionStore,
    underlying: str,
    start: dt.date,
    end: dt.date,
    *,
    gaps_reason: str | None,
) -> tuple[Any, ...]:
    resolution = store.resolve(underlying, start, end)
    if gaps_reason is not None and not resolution.is_complete:
        return resolution.accept_gaps(gaps_reason)
    return resolution.sessions()


class _SessionReader:
    """Whole sessions for one underlying, read once each and kept for the batch.

    A settlement run marks many ideas against the same handful of exit sessions, and a
    session is tens of thousands of rows; reading each one per idea would dominate the cost
    of the run. The cache is bounded by the settlement range the caller asked for, which is
    the set of sessions the run was always going to touch.
    """

    def __init__(self, store: SessionStore, underlying: str, refs: Sequence[Any]) -> None:
        self._store = store
        self._underlying = underlying
        self._refs = {ref.session_date: ref for ref in refs}
        self._views: dict[dt.date, SessionView | None] = {}

    @property
    def session_dates(self) -> tuple[dt.date, ...]:
        return tuple(sorted(self._refs))

    def absence(self, day: dt.date) -> tuple[str, str]:
        """Why :meth:`view` has nothing for ``day`` — two capture limits, not one.

        A date the store never resolved is a session the corpus does not hold. A date it
        resolved without reference data is a session the corpus *does* hold and cannot
        identify an instrument on, which is a different hole in the capture and sends an
        operator looking somewhere else.
        """
        ref = self._refs.get(day)
        if ref is None:
            return (
                UNMARKABLE_NO_EXIT_SESSION,
                f"the corpus holds no session for {day.isoformat()}",
            )
        return (
            UNMARKABLE_NO_REFDATA,
            f"the corpus holds {day.isoformat()} but no instrument master for it, so no "
            "contract on that session can be identified",
        )

    def view(self, day: dt.date) -> SessionView | None:
        if day in self._views:
            return self._views[day]
        ref = self._refs.get(day)
        view: SessionView | None = None
        if ref is not None and ref.has_refdata:
            view = SessionView.from_frame(
                ref.session_date,
                self._underlying,
                self._store.load_session(ref),
                self._store.load_refdata(ref),
            )
        self._views[day] = view
        return view


def _presented_from_sheet_row(
    row: Mapping[str, Any], *, as_of: str, generated_at: str, code_version: str
) -> PresentedIdea:
    trade = (row.get("rationale") or {}).get("trade") or {}
    if "hold_sessions" not in trade:
        raise LedgerFileError(
            f"the idea for {row.get('template_id')} on {as_of} carries no trade with a hold "
            "length, so there is no window to settle it over"
        )
    return PresentedIdea(
        as_of=as_of,
        template_id=str(row["template_id"]),
        parameters={str(k): float(v) for k, v in (row.get("parameters") or {}).items()},
        underlying=str(row["underlying"]),
        rank=int(row["rank"]),
        score=float(row["score"]),
        expected_edge=float(row["expected_edge"]),
        granted_lots=int(row["granted_lots"]),
        hold_sessions=int(trade["hold_sessions"]),
        requested_lots=(None if row.get("requested_lots") is None else int(row["requested_lots"])),
        legs=tuple(dict(leg) for leg in trade.get("legs") or ()),
        generated_at=generated_at,
        code_version=code_version,
    )


def _entry_from_dict(row: Mapping[str, Any], *, path: Path) -> PresentedIdea | Settlement:
    kind = row.get("kind")
    if kind == ENTRY_PRESENTED:
        return PresentedIdea.from_dict(row)
    if kind == ENTRY_SETTLEMENT:
        return Settlement.from_dict(row)
    raise LedgerFileError(
        f"the ledger at {path} holds an entry of kind {kind!r}, which is neither "
        f"{ENTRY_PRESENTED!r} nor {ENTRY_SETTLEMENT!r}"
    )


def _parameters_from_key(key: str) -> dict[str, float]:
    """Recover the parameter point a canonical key names.

    The key is the library's own identity for an admitted point, and the library's lookups
    take a mapping. Reading it back here keeps the ledger from having to carry a second copy
    of the point on every settlement row purely to demote against it.
    """
    if not key:
        return {}
    point: dict[str, float] = {}
    for pair in key.split(","):
        name, _, value = pair.partition("=")
        point[name] = float(value)
    return point
