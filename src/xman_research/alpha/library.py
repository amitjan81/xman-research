"""Which templates the scan may rank, and the evidence that says so.

**The library is the seam between the two loops.** The offline discovery loop runs on a
research clock — a hypothesis, a pre-registered gate, a sealed holdout, a decision record.
The nightly ranker runs on a market clock and has no opinions of its own: it may only
instantiate templates this library has admitted, and every expectation it attaches to an
idea is copied out of the admission record rather than measured at scan time. Re-measuring
nightly would be a fresh selection over the same corpus every evening, with the trial
count nowhere recorded.

**Filing evidence and admitting a template are two different acts, and only the second is
gated.** :meth:`TemplateLibrary.admit` refuses a decision record that is missing or
unparseable, because those mean there is no evidence to carry. Filing unpassed evidence as
a CANDIDATE is always allowed: the ranker never proposes a candidate, so recording what was
measured costs nothing. Admitting on unpassed evidence — a failed threshold, a failed
holdout, a run that could not be evaluated — requires a written ``override_reason``, which
is recorded on the entry. The ranker's ideas are real trade proposals, so that decision is
somebody's to make in writing rather than a default. The verdict itself is copied onto the
card verbatim either way, :attr:`EvidenceCard.passed_gate` is false, and any idea sheet
resting on such an admission says so on its face.

**Append-only, like the trial log.** Status changes are entries, not edits: the current
status of a template is the last entry naming it, and nothing rewrites an entry once
written.

**What the save-time check does and does not hold.** A file whose stored entries are not a
prefix of what is about to be written is refused rather than overwritten, which catches the
case this tool actually produces: a process that loaded the library, sat while somebody
else admitted a template, and then saved. It is **not** a lock. Two processes that check at
the same instant both pass, and the second write wins. The write itself is atomic — a temp
file and a rename — so a concurrent reader sees one whole version or the other and never a
half-written file, but a genuine race still loses one process's entries. The library is
maintained by a human at a command line, so the exposure is a person running two terminals;
anything stronger would need a lock file and is not worth its complexity until something
other than a person writes here.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from xman_research.alpha.templates import StrategyTemplate, parameter_key, parameter_value_key
from xman_research.clock import Clock, SystemClock
from xman_research.validation.decision import GateStatus, Outcome

__all__ = [
    "DEFAULT_LIBRARY_PATH",
    "LIBRARY_SCHEMA_VERSION",
    "PASSING_GATE_STATUS",
    "PASSING_OUTCOME",
    "SCREENED_NOT_GATED",
    "AdmissionRecord",
    "AdmissionStatus",
    "AdmittedParametersMismatchError",
    "AmbiguousParameterPointError",
    "AppendOnlyLibraryError",
    "DecisionRecordError",
    "EvidenceCard",
    "LibraryFileError",
    "TemplateLibrary",
    "CrossProductEvidenceError",
    "UnpassedEvidenceError",
]

#: Where the library lives, **relative to the working directory**, which in practice means
#: the repository root. The path is a research artefact and is expected to be committed: an
#: idea sheet is only reproducible if the admissions it rested on are recoverable.
#:
#: Relative rather than anchored because the repository root is not discoverable from an
#: installed package, and guessing it would be worse than this. The cost is real and is the
#: caller's to avoid: run from somewhere else and a missing file reads as an empty library,
#: so a scan reports that nothing is admitted rather than that it looked in the wrong place.
#: Pass ``--library`` with an absolute path from anywhere that is not the repository root.
DEFAULT_LIBRARY_PATH = Path("research/library/templates.json")

LIBRARY_SCHEMA_VERSION = 1


class DecisionRecordError(ValueError):
    """A decision record that is missing, unreadable, or not a decision record."""


class LibraryFileError(ValueError):
    """A library file that is missing a schema this reader understands, or is not one.

    Distinct from :class:`DecisionRecordError` because the two name different artefacts:
    one is the research output being read *into* the library, the other is the library
    itself. A nightly wrapper reading "decision record does not parse" when the library is
    what is corrupt would look in the wrong place.
    """


class AppendOnlyLibraryError(RuntimeError):
    """The stored library is not a prefix of what is about to be written."""


class AdmittedParametersMismatchError(ValueError):
    """The point being admitted is not the point the evidence measured.

    Distinct from :class:`UnpassedEvidenceError`: the evidence may have passed everything
    it was graded against and still describe a different trade from the one about to carry
    it. Admitting anyway would put a hold-3 record's numbers behind hold-1 proposals, or a
    half-ATR strangle's numbers behind a full-ATR one.
    """


class AmbiguousParameterPointError(ValueError):
    """A template named without a point, in a library that holds it at more than one.

    Every entry is filed against ``(template_id, parameters)``, so a template can be live at
    two points at once and a bare id then names two different trades. Refused rather than
    resolved to the most recent entry: demoting the wrong point would leave the ranker
    proposing exactly the idea somebody meant to stop.
    """


class CrossProductEvidenceError(ValueError):
    """An admission for one product built on evidence measured on another.

    A template is a shape any product can be screened on, so nothing upstream of the
    admission ties a card to a product. This is where the two are compared, and the mismatch
    is refused rather than noted: the ranker reads the admitted card's mean return, drawdown
    and regime table as a description of the trade it is about to propose on this product.
    """


class UnpassedEvidenceError(ValueError):
    """An admission whose evidence did not clear its gate, with no written override.

    Distinct from :class:`DecisionRecordError`: the record is present and readable, and what
    it says is that the strategy failed. That is a refusal about the *decision* being made,
    not about the artefact being read, and a caller that conflated the two would report a
    corrupt file when the truth is a failed gate.
    """


#: What the sole passing outcome of a decision record is called. A record reporting anything
#: else — a failed threshold, a failed holdout, a run that could not be evaluated — is not a
#: pass, and there is no fifth value that quietly counts as one. Read off the enum the
#: validation layer writes, so a rename there cannot leave this reading a value nothing emits.
PASSING_OUTCOME = str(Outcome.PASSES_SURVIVES_HOLDOUT)

#: What the sole passing gate status is called, on the in-sample metrics of a decision record.
PASSING_GATE_STATUS = str(GateStatus.PASSED)

#: The ``decision_outcome`` a screening-sheet entry carries. Spelled unlike any of the four
#: outcomes a decision record can report, so a reader scanning statuses cannot mistake a
#: stage-one point estimate for a graded verdict.
SCREENED_NOT_GATED = "screened_stage_1_not_gated"


class AdmissionStatus(StrEnum):
    """What the library currently says about a template.

    ``CANDIDATE`` — evidence exists and has been filed, and the ranker will not propose it.
    ``ADMITTED`` — the ranker may instantiate it nightly. ``DEMOTED`` — it was admitted and
    is not any longer; the entry naming the demotion carries the reason.
    """

    CANDIDATE = "candidate"
    ADMITTED = "admitted"
    DEMOTED = "demoted"


@dataclass(frozen=True, slots=True)
class EvidenceCard:
    """What the offline loop measured, copied out of one decision record.

    Every field is either read verbatim from the record or derived from named fields by a
    stated formula, and :attr:`provenance` says which for each — that is the property that
    makes the card auditable rather than merely detailed. A quantity the record does not
    report is ``None`` and stays ``None``; there is no default that would let a missing
    measurement read as a measured zero.
    """

    n_observations: int | None
    annualised_sharpe: float | None
    deflated_sharpe: float | None
    max_drawdown: float | None
    hit_rate: float | None
    mean_return_per_session: float | None
    mean_return_at_hold: float | None
    hold_sessions: int
    gate_status: str | None
    outcome: str | None
    window: str | None
    measured_strategy: str | None
    measured_strategy_parameters: Mapping[str, Any] | None
    cost_stamps: tuple[str, ...]
    regime_table: Mapping[str, float] | None
    provenance: Mapping[str, str]
    parameters: Mapping[str, float] | None = None
    mean_return_per_round_trip: float | None = None
    """Net profit per position the measured run opened, over its capital base.

    The figure a *single* live trade's profit over the same base is comparable to.
    :attr:`mean_return_at_hold` is not that figure unless the run held a position on
    every session of its window, and :mod:`xman_research.alpha.tracking` is where the
    difference decides whether a template looks like it is drifting.

    ``None`` where the source reports no round-trip count — a record written by a runner
    that does not report one, or a run that never entered.
    """
    round_trips: int | None = None
    """How many positions the measured run opened. ``None`` where the source is silent."""
    underlying: str | None = None
    """The product this evidence was measured on, where the source names one.

    ``None`` where it does not, and it stays ``None``: a source that is silent about its
    product cannot corroborate the product an admission is for, and
    :meth:`TemplateLibrary.admit` records that silence rather than reading the admission's
    own product back as if the evidence had confirmed it.
    """
    """The resolved template parameter point this evidence was measured at, if it names one.

    ``None`` means the source could not state a point — a decision record written by a
    runner that does not build from a template, for instance. The hold is then all that is
    recoverable, and :attr:`hold_sessions` carries it; :meth:`TemplateLibrary.admit` falls
    back to comparing holds and says so.
    """

    @property
    def passed_gate(self) -> bool:
        """Whether the record this card came from cleared its pre-registered gate."""
        return self.gate_status == "passed"

    def regime_factor(self, regime: str | None) -> float:
        """The multiplier this card's regime table gives ``regime``, or ``1.0``.

        ``1.0`` is returned whenever there is no table, or the table does not name the
        regime. Scaling by a factor invented for an unlisted regime would be a claim the
        record does not support, and scaling by nothing is the claim that the card's
        headline number applies as measured — which is exactly what it is.
        """
        if not self.regime_table or regime is None:
            return 1.0
        return float(self.regime_table.get(regime, 1.0))

    def as_dict(self) -> dict[str, Any]:
        return {
            "n_observations": self.n_observations,
            "annualised_sharpe": self.annualised_sharpe,
            "deflated_sharpe": self.deflated_sharpe,
            "max_drawdown": self.max_drawdown,
            "hit_rate": self.hit_rate,
            "mean_return_per_session": self.mean_return_per_session,
            "mean_return_at_hold": self.mean_return_at_hold,
            "mean_return_per_round_trip": self.mean_return_per_round_trip,
            "round_trips": self.round_trips,
            "underlying": self.underlying,
            "hold_sessions": self.hold_sessions,
            "gate_status": self.gate_status,
            "outcome": self.outcome,
            "window": self.window,
            "measured_strategy": self.measured_strategy,
            "measured_strategy_parameters": (
                dict(self.measured_strategy_parameters)
                if self.measured_strategy_parameters
                else None
            ),
            "cost_stamps": list(self.cost_stamps),
            "regime_table": dict(self.regime_table) if self.regime_table else None,
            "provenance": dict(self.provenance),
            "parameters": dict(self.parameters) if self.parameters is not None else None,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> EvidenceCard:
        table = payload.get("regime_table")
        return cls(
            # Through the same reader `from_decision_record` uses, so one document field has
            # one behaviour: a point carrying a non-numeric value is not a point, and reads
            # back as absent rather than raising here and returning None there.
            parameters=_parameter_point(payload.get("parameters")),
            n_observations=payload.get("n_observations"),
            annualised_sharpe=payload.get("annualised_sharpe"),
            deflated_sharpe=payload.get("deflated_sharpe"),
            max_drawdown=payload.get("max_drawdown"),
            hit_rate=payload.get("hit_rate"),
            mean_return_per_session=payload.get("mean_return_per_session"),
            mean_return_at_hold=payload.get("mean_return_at_hold"),
            mean_return_per_round_trip=_as_float(payload.get("mean_return_per_round_trip")),
            round_trips=_as_int(payload.get("round_trips")),
            underlying=_as_str(payload.get("underlying")),
            hold_sessions=int(payload["hold_sessions"]),
            gate_status=payload.get("gate_status"),
            outcome=payload.get("outcome"),
            window=payload.get("window"),
            measured_strategy=payload.get("measured_strategy"),
            measured_strategy_parameters=payload.get("measured_strategy_parameters"),
            cost_stamps=tuple(payload.get("cost_stamps") or ()),
            regime_table={str(k): float(v) for k, v in table.items()} if table else None,
            provenance=dict(payload.get("provenance") or {}),
        )

    @classmethod
    def from_decision_record(
        cls, payload: Mapping[str, Any], *, hold_sessions: int, source: str
    ) -> EvidenceCard:
        """Build a card from a decision record's in-sample verdict.

        **Three honesty decisions live here, and each one is written into
        :attr:`provenance` rather than argued for in a comment nobody reads with the
        number.**

        *The mean return is taken net of costs.* The record reports ``mean_gross_return``
        and ``mean_cost_drag`` separately; ranking on the gross figure would overstate every
        edge by the cost share, in the flattering direction, for every template equally —
        which is worse than a random error because it survives comparison.

        *The hit rate is ``None``.* No decision record field reports it. ``sessions_under_
        water`` counts sessions below the running peak, which is a drawdown statistic about
        a path, not a fraction of winning trades, and reading it as one would put a number
        in front of an operator that means something else.

        *The hold-length mean is a linear scaling of the per-session mean*, and the record
        it comes from measured a different holding structure. The formula and its inputs are
        named in the provenance so that a reader can discount it; leaving the field empty
        instead would leave the ranker with nothing to order ideas by, and inventing an
        unnamed number would be worse than either.

        **The card names the strategy the record measured, and does not check it.** A
        decision record is evidence about one strategy at one parameter point; whether that
        strategy is the template being admitted is a judgement, and the library's design is
        that a human makes it against their own name. What the card guarantees is that the
        judgement is *inspectable*: ``measured_strategy`` and its parameters travel onto
        every rationale, so a reader can see that, say, evidence from a straddle held to
        cash settlement is being attached to one bought back after N sessions.

        **The cost-epoch list is not a regime table.** A decision record's ``epochs.regimes``
        holds statutory-cost epoch boundaries — the dates a tax rate changed — and the
        ranker's regime tag is a volatility tercile. They are different partitions that
        share a word, so nothing here maps one onto the other and the table is ``None``
        until a per-regime measurement exists to fill it.
        """
        run = payload.get("runs")
        in_sample_run = run.get("in_sample") if isinstance(run, Mapping) else None
        measured = in_sample_run if isinstance(in_sample_run, Mapping) else {}
        in_sample = payload.get("in_sample")
        if not isinstance(in_sample, Mapping):
            raise DecisionRecordError(
                f"{source} has no `in_sample` verdict — it is not a decision record this "
                "library can read evidence from"
            )
        metrics = in_sample.get("metrics")
        if not isinstance(metrics, Mapping):
            raise DecisionRecordError(f"{source} has no `in_sample.metrics` to read")

        run_metrics = measured.get("metrics")
        run_metrics = run_metrics if isinstance(run_metrics, Mapping) else {}
        gross = _as_float(metrics.get("mean_gross_return"))
        drag = _as_float(metrics.get("mean_cost_drag"))
        # Both inputs are required. Treating an absent drag as zero would produce a "net"
        # figure that is the gross one, under a provenance string promising a subtraction
        # that never happened — the silent default this class exists to refuse.
        net = None if gross is None or drag is None else gross - drag
        at_hold = None if net is None else net * hold_sessions

        provenance = {
            "n_observations": f"{source}:in_sample.metrics.sample_length",
            "annualised_sharpe": f"{source}:in_sample.metrics.annualised_sharpe",
            "deflated_sharpe": f"{source}:in_sample.metrics.deflated_sharpe",
            "max_drawdown": f"{source}:in_sample.metrics.max_drawdown",
            "hit_rate": "not reported by the source decision record",
            "mean_return_per_session": (
                f"derived: {source}:in_sample.metrics.mean_gross_return "
                f"- {source}:in_sample.metrics.mean_cost_drag"
            ),
            "mean_return_at_hold": (
                f"derived: mean_return_per_session x hold_sessions ({hold_sessions}); the "
                "source record measured a hold to cash settlement, so this assumes the "
                "per-session mean is flat across the hold"
            ),
            "mean_return_per_round_trip": (
                f"{source}:runs.in_sample.metrics.mean_return_per_round_trip"
                if _as_float(run_metrics.get("mean_return_per_round_trip")) is not None
                else (
                    "absent: the source record reports no per-position figure, so the only "
                    "expectation recoverable here is the per-session one scaled by the hold"
                )
            ),
            "round_trips": (
                f"{source}:runs.in_sample.metrics.round_trips"
                if _as_int(run_metrics.get("round_trips")) is not None
                else "absent: the source record does not say how many positions it opened"
            ),
            "underlying": (
                f"{source}:runs.in_sample.underlying"
                if _as_str(measured.get("underlying")) is not None
                else (
                    "absent: the record names no product, so nothing here corroborates the "
                    "product an admission built on it is for"
                )
            ),
            "gate_status": f"{source}:in_sample.metrics.gate_status",
            "outcome": f"{source}:outcome",
            "window": f"{source}:in_sample.window",
            "measured_strategy": f"{source}:runs.in_sample.strategy",
            "measured_strategy_parameters": f"{source}:runs.in_sample.strategy_parameters",
            "parameters": (
                f"{source}:runs.in_sample.template_parameters"
                if isinstance(measured.get("template_parameters"), Mapping)
                else (
                    "absent: the record names no template parameter point, so the hold above "
                    "is the whole of what is recoverable about the trade it measured"
                )
            ),
            "cost_stamps": f"{source}:in_sample.metrics.unverified_inputs",
            "regime_table": (
                "absent: the source record's epoch list partitions the window by statutory "
                "cost changes, which is not the volatility regime the ranker tags"
            ),
        }
        return cls(
            n_observations=_as_int(metrics.get("sample_length")),
            annualised_sharpe=_as_float(metrics.get("annualised_sharpe")),
            deflated_sharpe=_as_float(metrics.get("deflated_sharpe")),
            max_drawdown=_as_float(metrics.get("max_drawdown")),
            hit_rate=None,
            mean_return_per_session=net,
            mean_return_at_hold=at_hold,
            mean_return_per_round_trip=_as_float(run_metrics.get("mean_return_per_round_trip")),
            round_trips=_as_int(run_metrics.get("round_trips")),
            underlying=_as_str(measured.get("underlying")),
            hold_sessions=hold_sessions,
            gate_status=_as_str(metrics.get("gate_status")),
            outcome=_as_str(payload.get("outcome")),
            window=_as_str(in_sample.get("window")),
            measured_strategy=_as_str(measured.get("strategy")),
            measured_strategy_parameters=(
                dict(measured["strategy_parameters"])
                if isinstance(measured.get("strategy_parameters"), Mapping)
                else None
            ),
            cost_stamps=tuple(str(stamp) for stamp in metrics.get("unverified_inputs") or ()),
            regime_table=None,
            provenance=provenance,
            parameters=_parameter_point(measured.get("template_parameters")),
        )


@dataclass(frozen=True, slots=True)
class AdmissionRecord:
    """One status change for one template, with the evidence that justified it.

    Entries are never edited. A template admitted and later demoted has two entries, and
    the demotion carries the reason the admission is no longer believed.
    """

    template_id: str
    underlying: str
    """The product this admission is for.

    Evidence scope lives here rather than on the template: a template is a trade shape any
    product can be screened on, and what one admission's evidence covers is one product.
    The ranker builds this template only when scanning this product.
    """
    hypothesis_id: str | None
    decision_path: str
    decision_outcome: str | None
    trial_ids: tuple[str, ...]
    evidence: EvidenceCard
    status: AdmissionStatus
    admitted_at: str
    admitted_by: str
    reason: str
    parameters: Mapping[str, float] = field(default_factory=dict)
    """The resolved parameter point the ranker must build this template at.

    **The point is part of the entry's identity, not a detail on it.** One template admitted
    at a three-session hold and at a one-session hold is two admissions carrying two
    different sets of numbers, and the ranker instantiates each at its own point. Grouping
    by :attr:`template_id` alone would silently keep whichever was filed last.
    """
    notes: str | None = None
    override_reason: str | None = None
    """Why this admission was made over evidence that did not pass its gate.

    A field rather than a sentence inside :attr:`notes`, because a reader scanning statuses
    must be able to see it without reading prose: an entry reading ADMITTED with nothing
    beside it is exactly the state the override policy exists to prevent.
    """

    @property
    def parameter_key(self) -> str:
        """The canonical name of this entry's point — half of the entry's identity."""
        return parameter_key(self.parameters)

    @property
    def identity(self) -> tuple[str, str, str]:
        """``(template_id, underlying, parameter_key)``: what makes two entries the same.

        The product is part of the identity because the evidence is: one shape admitted on
        NIFTY and on BANKNIFTY is two admissions carrying two different sets of numbers.
        """
        return (self.template_id, self.underlying, self.parameter_key)

    def as_dict(self) -> dict[str, Any]:
        return {
            "template_id": self.template_id,
            "underlying": self.underlying,
            "parameters": {name: float(value) for name, value in sorted(self.parameters.items())},
            "parameter_key": self.parameter_key,
            "hypothesis_id": self.hypothesis_id,
            "decision_path": self.decision_path,
            "decision_outcome": self.decision_outcome,
            "trial_ids": list(self.trial_ids),
            "evidence": self.evidence.as_dict(),
            "status": str(self.status),
            "admitted_at": self.admitted_at,
            "admitted_by": self.admitted_by,
            "reason": self.reason,
            "notes": self.notes,
            "override_reason": self.override_reason,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> AdmissionRecord:
        """Read one entry back.

        ``parameter_key`` in the document is **not** read into a field: it is derived from
        ``parameters``, and a second stored copy could disagree with the point it names.
        """
        return cls(
            template_id=str(payload["template_id"]),
            underlying=str(payload["underlying"]),
            parameters=_parameter_point(payload.get("parameters")) or {},
            hypothesis_id=_as_str(payload.get("hypothesis_id")),
            decision_path=str(payload["decision_path"]),
            decision_outcome=_as_str(payload.get("decision_outcome")),
            trial_ids=tuple(str(t) for t in payload.get("trial_ids") or ()),
            evidence=EvidenceCard.from_dict(payload["evidence"]),
            status=AdmissionStatus(str(payload["status"])),
            admitted_at=str(payload["admitted_at"]),
            admitted_by=str(payload["admitted_by"]),
            reason=str(payload.get("reason") or ""),
            notes=_as_str(payload.get("notes")),
            override_reason=_as_str(payload.get("override_reason")),
        )


class TemplateLibrary:
    """The append-only history of template status changes, persisted as JSON."""

    def __init__(
        self,
        path: Path | str = DEFAULT_LIBRARY_PATH,
        *,
        clock: Clock | None = None,
        entries: Sequence[AdmissionRecord] = (),
    ) -> None:
        self._path = Path(path)
        self._clock = clock if clock is not None else SystemClock()
        self._entries: list[AdmissionRecord] = list(entries)

    @classmethod
    def load(
        cls, path: Path | str = DEFAULT_LIBRARY_PATH, *, clock: Clock | None = None
    ) -> TemplateLibrary:
        """Read the library at ``path``. A file that does not exist is an empty library.

        An empty library is a legitimate state — no template has been admitted yet — and is
        distinguishable from a corrupt one, which raises.
        """
        target = Path(path)
        if not target.exists():
            return cls(target, clock=clock)
        try:
            payload = json.loads(target.read_text())
        except (OSError, json.JSONDecodeError) as error:
            raise LibraryFileError(f"library at {target} is not readable JSON: {error}") from error
        if not isinstance(payload, Mapping):
            raise LibraryFileError(
                f"library at {target} is not a JSON object; a list or scalar is not a "
                "library this reader can append to"
            )
        version = payload.get("schema_version")
        if version != LIBRARY_SCHEMA_VERSION:
            raise LibraryFileError(
                f"library at {target} declares schema_version {version!r}; this reader "
                f"understands {LIBRARY_SCHEMA_VERSION}"
            )
        entries = [AdmissionRecord.from_dict(row) for row in payload.get("entries") or ()]
        return cls(target, clock=clock, entries=entries)

    @property
    def path(self) -> Path:
        return self._path

    def entries(self) -> tuple[AdmissionRecord, ...]:
        """Every status change, oldest first."""
        return tuple(self._entries)

    def history(
        self,
        template_id: str,
        *,
        underlying: str | None = None,
        parameters: Mapping[str, float] | None = None,
    ) -> tuple[AdmissionRecord, ...]:
        """Every entry naming ``template_id``, narrowed by ``underlying`` and ``parameters``.

        **``parameters`` is a selector, not necessarily a whole point.** An entry matches
        when it carries every name and value supplied, so ``{"hold_sessions": 3}`` selects
        the hold-3 admission without the caller having to restate the defaults
        :meth:`StrategyTemplate.resolve` filled in. A selector that matches two points is a
        selector that names two different trades, and :meth:`current` refuses it rather than
        picking the later one.

        Values are compared through :func:`~xman_research.alpha.templates.parameter_value_key`,
        the same normalisation :attr:`AdmissionRecord.parameter_key` is built from. A hold
        read back from JSON as ``3.0`` therefore selects the entry stored from an integer
        ``3``, and — the property that matters — a point recovered by reading a
        ``parameter_key`` apart selects the entry that key was made from, for every value
        the range allows rather than only for the short ones.
        """
        rows = tuple(
            entry
            for entry in self._entries
            if entry.template_id == template_id
            and (underlying is None or entry.underlying == underlying)
        )
        if parameters is None:
            return rows
        wanted = {str(name): parameter_value_key(value) for name, value in parameters.items()}
        return tuple(
            entry
            for entry in rows
            if all(
                name in entry.parameters and parameter_value_key(entry.parameters[name]) == value
                for name, value in wanted.items()
            )
        )

    def points(self, template_id: str) -> tuple[str, ...]:
        """Every parameter point ``template_id`` has an entry at, oldest first, deduplicated."""
        seen: dict[str, None] = {}
        for entry in self.history(template_id):
            seen.setdefault(entry.parameter_key, None)
        return tuple(seen)

    def current(
        self,
        template_id: str,
        *,
        underlying: str | None = None,
        parameters: Mapping[str, float] | None = None,
    ) -> AdmissionRecord | None:
        """The latest entry for one admission, or ``None`` if there is none.

        The selector must land on at most one point, whether it is omitted entirely or is
        too partial to separate two. A template live at two points is two admissions, and
        answering with the more recent would name a trade the caller did not ask about.
        """
        history = self.history(template_id, underlying=underlying, parameters=parameters)
        matched = {(entry.underlying, entry.parameter_key) for entry in history}
        if len(matched) > 1:
            raise AmbiguousParameterPointError(
                f"template {template_id!r} has entries at {len(matched)} (product, parameter "
                f"point) pairs ({sorted(matched)})"
                + (f" matching [{parameter_key(parameters)}]" if parameters is not None else "")
                + ". Name the point: this would otherwise answer about whichever was filed "
                "last."
            )
        return history[-1] if history else None

    def status(
        self,
        template_id: str,
        *,
        underlying: str | None = None,
        parameters: Mapping[str, float] | None = None,
    ) -> AdmissionStatus | None:
        entry = self.current(template_id, underlying=underlying, parameters=parameters)
        return entry.status if entry else None

    def admitted(self) -> tuple[AdmissionRecord, ...]:
        """The current entry of every admission whose latest status is ``ADMITTED``.

        Keyed by ``(template_id, parameter_key)``, so one template admitted at two points
        appears twice and the ranker instantiates it at each. Ordered by that pair so a scan
        over the library is deterministic.
        """
        latest = {entry.identity: entry for entry in self._entries}
        return tuple(
            latest[identity]
            for identity in sorted(latest)
            if latest[identity].status is AdmissionStatus.ADMITTED
        )

    def admit(
        self,
        *,
        template: StrategyTemplate,
        underlying: str,
        decision_path: Path | str,
        by: str,
        reason: str,
        parameters: Mapping[str, float] | None = None,
        status: AdmissionStatus = AdmissionStatus.ADMITTED,
        notes: str | None = None,
        override_reason: str | None = None,
    ) -> AdmissionRecord:
        """File evidence for ``template`` from the decision record at ``decision_path``.

        Refuses when the record does not exist or does not parse — those mean there is no
        evidence, and a template admitted without evidence would hand the ranker an
        expected edge it invented.

        ``underlying`` is the product this admission covers. Where the record names its own
        product and the two disagree the admission is refused; where the record is silent
        the entry's card says so in its provenance, so a reader can see that the product was
        asserted here rather than corroborated by the measurement.

        **An ADMITTED status on evidence that did not pass its gate needs
        ``override_reason``.** The ranker's ideas are real trade proposals, so admitting a
        template whose pre-registered gate failed is a decision somebody must make in
        writing; the reason is recorded on the entry and travels onto every idea sheet that
        rests on it. Filing the same evidence as a CANDIDATE needs no override — the ranker
        never proposes a candidate, so recording what was measured costs nothing and hiding
        it costs the next reader.
        """
        if status is AdmissionStatus.DEMOTED:
            raise ValueError("use demote() to record a demotion, so it carries its own reason")
        if not by.strip():
            raise ValueError("admit requires `by`: an admission is somebody's decision")
        if not reason.strip():
            raise ValueError("admit requires a written `reason`")
        if not underlying.strip():
            raise ValueError(
                "admit requires `underlying`: an admission's evidence covers one product, "
                "and the ranker builds this template only when scanning that product"
            )

        source = Path(decision_path)
        payload = _read_decision_record(source)
        measured_point = _parameter_point(_measured_run(payload).get("template_parameters"))
        measured_hold = _measured_hold(payload)
        # The point the ranker will build at. Defaulting to the record's own point is what
        # lets `admit` be typed without a parameter flag and still admit the trade the
        # evidence describes; a supplied point is then an assertion the guard below checks.
        admitted_point = template.resolve(
            parameters if parameters is not None else measured_point,
        )
        admitted_hold = template.hold_for(admitted_point)
        if measured_point is not None:
            measured_key = parameter_key(template.resolve(measured_point))
            if measured_key != parameter_key(admitted_point):
                raise AdmittedParametersMismatchError(
                    f"{source} measured {template.template_id} at [{measured_key}] and this "
                    f"admission names [{parameter_key(admitted_point)}]. An admission attaches "
                    "this record's numbers to the trades the ranker will propose, and those "
                    "are two different trades: the mean return at hold, the expiry "
                    "invalidator and the drawdown all describe the measured one."
                )
        elif measured_hold is not None and measured_hold != admitted_hold:
            # The record names no point, so the hold is the whole of what can be compared.
            # Weaker than the check above and stated as such: two structures at one hold
            # pass it, and only `measured_strategy` on the card distinguishes them.
            raise AdmittedParametersMismatchError(
                f"{source} measured a {measured_hold}-session hold and this admission builds "
                f"{template.template_id} at {admitted_hold}. The record names no template "
                "parameter point, so the hold is all there is to compare — and these are two "
                "different trades: the mean return at hold, the expiry invalidator and the "
                "drawdown all describe the measured one."
            )
        evidence = EvidenceCard.from_decision_record(
            payload,
            hold_sessions=measured_hold if measured_hold is not None else admitted_hold,
            source=str(source),
        )
        if evidence.underlying is not None and evidence.underlying != underlying:
            raise CrossProductEvidenceError(
                f"{source} measured {template.template_id} on {evidence.underlying} and this "
                f"admission is for {underlying}. The mean return at hold, the drawdown and "
                "the regime table all describe the former market, and the ranker would read "
                "them as a description of a trade on the latter."
            )
        outcome = _as_str(payload.get("outcome"))
        recorded_override: str | None = None
        if status is AdmissionStatus.ADMITTED and not _passes(outcome, evidence):
            if override_reason is None or not override_reason.strip():
                raise UnpassedEvidenceError(
                    f"{source} reports outcome {outcome!r} and gate status "
                    f"{evidence.gate_status!r}, which is not a pass. The ranker proposes "
                    f"real trades, so admitting {template.template_id} on this evidence "
                    "requires a written `override_reason`. File it as a CANDIDATE instead "
                    "if the intent is to record what was measured."
                )
            recorded_override = override_reason.strip()

        entry = AdmissionRecord(
            template_id=template.template_id,
            underlying=underlying,
            parameters=admitted_point,
            hypothesis_id=_as_str(payload.get("hypothesis_id")),
            decision_path=str(source),
            decision_outcome=outcome,
            trial_ids=_trial_ids(payload),
            evidence=evidence,
            status=status,
            admitted_at=self._now(),
            admitted_by=by,
            reason=reason,
            notes=notes,
            override_reason=recorded_override,
        )
        self._entries.append(entry)
        return entry

    def seed_from_screen(
        self,
        *,
        template: StrategyTemplate,
        underlying: str,
        evidence: EvidenceCard,
        sheet_path: Path | str,
        by: str,
        reason: str,
        parameters: Mapping[str, float] | None = None,
        trial_ids: Sequence[str] = (),
        notes: str | None = None,
    ) -> AdmissionRecord:
        """File a screened instance as a CANDIDATE, pointing at the sheet it came from.

        **The status is not a parameter.** A screening sheet applies no threshold and
        pre-registers none, so nothing in it can justify admission however good the number
        looks; offering a status argument here would make the one thing this method must not
        do a keyword away. Admission stays reachable only through :meth:`admit`, which reads
        a decision record.

        ``decision_path`` on the resulting entry holds the sheet's path. The field names
        where the evidence came from, and for a candidate that is a screen rather than a
        decision — which the entry's ``decision_outcome`` states in as many words.
        """
        if not by.strip():
            raise ValueError("seed_from_screen requires `by`: filing evidence is somebody's act")
        if not reason.strip():
            raise ValueError("seed_from_screen requires a written `reason`")
        if evidence.underlying is not None and evidence.underlying != underlying:
            raise CrossProductEvidenceError(
                f"{sheet_path} screened {template.template_id} on {evidence.underlying} and "
                f"this candidate is filed for {underlying}; the row's numbers describe the "
                "former market"
            )
        entry = AdmissionRecord(
            template_id=template.template_id,
            underlying=underlying,
            parameters=template.resolve(
                parameters if parameters is not None else evidence.parameters
            ),
            hypothesis_id=None,
            decision_path=str(sheet_path),
            decision_outcome=SCREENED_NOT_GATED,
            trial_ids=tuple(str(trial_id) for trial_id in trial_ids),
            evidence=evidence,
            status=AdmissionStatus.CANDIDATE,
            admitted_at=self._now(),
            admitted_by=by,
            reason=reason,
            notes=notes,
        )
        self._entries.append(entry)
        return entry

    def demote(
        self,
        *,
        template_id: str,
        by: str,
        reason: str,
        underlying: str | None = None,
        parameters: Mapping[str, float] | None = None,
    ) -> AdmissionRecord:
        """Record that one admission is no longer live, against a written reason.

        ``parameters`` names which admission when the template is filed at more than one
        point; with one point it may be omitted. The evidence card and the point are carried
        forward from the entry being demoted rather than cleared: what the offline loop
        measured did not stop being true, and a demotion whose entry showed no evidence
        would be unreviewable.
        """
        if not by.strip():
            raise ValueError("demote requires `by`: a demotion is somebody's decision")
        if not reason.strip():
            raise ValueError("demote requires a written `reason`")
        previous = self.current(template_id, underlying=underlying, parameters=parameters)
        if previous is None:
            raise KeyError(
                f"template {template_id!r} has no entry in this library"
                + (f" at [{parameter_key(parameters)}]" if parameters is not None else "")
                + ", so there is nothing to demote"
            )
        if previous.status is AdmissionStatus.DEMOTED:
            raise ValueError(
                f"template {template_id!r} at [{previous.parameter_key}] is already demoted"
            )
        entry = AdmissionRecord(
            template_id=template_id,
            underlying=previous.underlying,
            parameters=previous.parameters,
            hypothesis_id=previous.hypothesis_id,
            decision_path=previous.decision_path,
            decision_outcome=previous.decision_outcome,
            trial_ids=previous.trial_ids,
            evidence=previous.evidence,
            status=AdmissionStatus.DEMOTED,
            admitted_at=self._now(),
            admitted_by=by,
            reason=reason,
            notes=previous.notes,
        )
        self._entries.append(entry)
        return entry

    def save(self) -> Path:
        """Write the library, refusing to drop entries another writer added.

        The stored entries must be a prefix of the in-memory ones, which catches a save
        made against a version somebody else has since added to. It is a check, not a lock —
        see the module docstring for exactly what that leaves open.

        The comparison runs through :meth:`AdmissionRecord.from_dict`, so adding an optional
        field to an entry does not make every previously written library unappendable.

        The write goes to a temp file and is renamed into place, so a reader never observes
        a partially written library.
        """
        if self._path.exists():
            raw = json.loads(self._path.read_text()).get("entries") or []
            mine = [entry.as_dict() for entry in self._entries]
            # Compared through the reader, not as raw JSON. An entry written before an
            # optional field existed carries no key for it while a freshly serialised one
            # carries an explicit null; the two describe the same admission, and a raw
            # comparison would report a concurrent writer who was never there. Round-tripping
            # puts both sides in the same shape, so the check answers the question it asks.
            try:
                stored = [AdmissionRecord.from_dict(row).as_dict() for row in raw]
            except (KeyError, TypeError, ValueError) as error:
                raise LibraryFileError(
                    f"the library at {self._path} holds an entry this reader cannot "
                    f"deserialise, so it cannot be appended to: {error}"
                ) from error
            if len(stored) > len(mine) or stored != mine[: len(stored)]:
                raise AppendOnlyLibraryError(
                    f"the library at {self._path} holds {len(stored)} entries that are not "
                    f"a prefix of the {len(mine)} about to be written — another writer has "
                    "changed it since this one loaded. Reload and re-apply."
                )
        self._path.parent.mkdir(parents=True, exist_ok=True)
        document = (
            json.dumps(
                {
                    "schema_version": LIBRARY_SCHEMA_VERSION,
                    "entries": [entry.as_dict() for entry in self._entries],
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


def _passes(outcome: str | None, evidence: EvidenceCard) -> bool:
    """Whether a decision record cleared everything it was graded against.

    Both the record-level outcome and the in-sample gate status must say so. They are two
    readings of the same run and normally agree; requiring both means a record that carries
    only one of them — an older shape, a hand-edited file — is treated as not passing rather
    than as passing on the strength of the field that happens to be present.
    """
    return outcome == PASSING_OUTCOME and evidence.gate_status == PASSING_GATE_STATUS


def _measured_run(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    """The record's in-sample run summary, or an empty mapping when it carries none."""
    runs = payload.get("runs")
    run = runs.get("in_sample") if isinstance(runs, Mapping) else None
    return run if isinstance(run, Mapping) else {}


def _parameter_point(value: Any) -> dict[str, float] | None:
    """A parameter point read from a document, or ``None`` when there is not one there.

    Every value must be a number. A point carrying a string is not a point this library can
    compare, and coercing one would let a mismatch through under a key that reads as a match.
    """
    if not isinstance(value, Mapping) or not value:
        return None
    point: dict[str, float] = {}
    for name, raw in value.items():
        number = _as_float(raw)
        if number is None:
            return None
        point[str(name)] = number
    return point


def _measured_hold(payload: Mapping[str, Any]) -> int | None:
    """The hold the record's in-sample run actually traded, if it reports one.

    ``None`` when the record measured a strategy with no hold at all — one held to cash
    settlement, say — which is a different shape of evidence rather than a disagreement, and
    is left for the human reading ``measured_strategy`` on the card to judge.
    """
    parameters = _measured_run(payload).get("strategy_parameters")
    if not isinstance(parameters, Mapping):
        return None
    return _as_int(parameters.get("hold_sessions"))


def _read_decision_record(source: Path) -> Mapping[str, Any]:
    if not source.exists():
        raise DecisionRecordError(
            f"no decision record at {source}. A template cannot be admitted without one: "
            "the evidence card is copied out of it, and there is nothing here to invent it "
            "from."
        )
    try:
        payload = json.loads(source.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise DecisionRecordError(f"decision record at {source} does not parse: {error}") from error
    if not isinstance(payload, Mapping):
        raise DecisionRecordError(f"decision record at {source} is not a JSON object")
    return payload


def _trial_ids(payload: Mapping[str, Any]) -> tuple[str, ...]:
    """Every trial id the record names, deduplicated and ordered.

    Read from the graded verdicts and from the run evidence, because a record can carry a
    holdout run whose trial is not the in-sample one, and an admission that named only
    half of them would under-report what the template cost in trials.
    """
    found: dict[str, None] = {}
    for key in ("in_sample", "holdout"):
        section = payload.get(key)
        if isinstance(section, Mapping):
            trial_id = section.get("trial_id")
            if isinstance(trial_id, str):
                found.setdefault(trial_id, None)
    runs = payload.get("runs")
    if isinstance(runs, Mapping):
        for run in runs.values():
            if isinstance(run, Mapping) and isinstance(run.get("trial_id"), str):
                found.setdefault(str(run["trial_id"]), None)
    return tuple(found)


def _as_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if number != number else number


def _as_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_str(value: Any) -> str | None:
    return None if value is None else str(value)
