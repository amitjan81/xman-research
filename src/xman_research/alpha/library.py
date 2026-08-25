"""Which templates the scan may rank, and the evidence that says so.

**The library is the seam between the two loops.** The offline discovery loop runs on a
research clock — a hypothesis, a pre-registered gate, a sealed holdout, a decision record.
The nightly ranker runs on a market clock and has no opinions of its own: it may only
instantiate templates this library has admitted, and every expectation it attaches to an
idea is copied out of the admission record rather than measured at scan time. Re-measuring
nightly would be a fresh selection over the same corpus every evening, with the trial
count nowhere recorded.

**Admission is not a verdict.** :meth:`TemplateLibrary.admit` refuses a decision record
that is missing or unparseable, because those mean there is no evidence to carry. It does
not refuse a record whose gate *failed*: the verdict is a fact about the strategy, it is
copied into the evidence card verbatim, and a human who admits a failed template against
their own name has made a decision the record then shows. What the framework guarantees is
that the decision is visible — :attr:`EvidenceCard.passed_gate` is false, and any idea
sheet resting on such an admission says so on its face.

**Append-only, like the trial log.** Status changes are entries, not edits: the current
status of a template is the last entry naming it. A file whose stored entries are not a
prefix of what is about to be written is refused rather than overwritten, so a second
process's admissions cannot be silently dropped by a first process's save.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from xman_research.alpha.templates import StrategyTemplate
from xman_research.clock import Clock, SystemClock

__all__ = [
    "DEFAULT_LIBRARY_PATH",
    "LIBRARY_SCHEMA_VERSION",
    "AdmissionRecord",
    "AdmissionStatus",
    "AppendOnlyLibraryError",
    "DecisionRecordError",
    "EvidenceCard",
    "TemplateLibrary",
]

#: Where the library lives relative to the repository root. The path is a research artefact
#: and is expected to be committed: an idea sheet is only reproducible if the admissions it
#: rested on are recoverable.
DEFAULT_LIBRARY_PATH = Path("research/library/templates.json")

LIBRARY_SCHEMA_VERSION = 1


class DecisionRecordError(ValueError):
    """A decision record that is missing, unreadable, or not a decision record."""


class AppendOnlyLibraryError(RuntimeError):
    """The stored library is not a prefix of what is about to be written."""


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
    cost_stamps: tuple[str, ...]
    regime_table: Mapping[str, float] | None
    provenance: Mapping[str, str]

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
            "hold_sessions": self.hold_sessions,
            "gate_status": self.gate_status,
            "outcome": self.outcome,
            "window": self.window,
            "cost_stamps": list(self.cost_stamps),
            "regime_table": dict(self.regime_table) if self.regime_table else None,
            "provenance": dict(self.provenance),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> EvidenceCard:
        table = payload.get("regime_table")
        return cls(
            n_observations=payload.get("n_observations"),
            annualised_sharpe=payload.get("annualised_sharpe"),
            deflated_sharpe=payload.get("deflated_sharpe"),
            max_drawdown=payload.get("max_drawdown"),
            hit_rate=payload.get("hit_rate"),
            mean_return_per_session=payload.get("mean_return_per_session"),
            mean_return_at_hold=payload.get("mean_return_at_hold"),
            hold_sessions=int(payload["hold_sessions"]),
            gate_status=payload.get("gate_status"),
            outcome=payload.get("outcome"),
            window=payload.get("window"),
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

        **The cost-epoch list is not a regime table.** A decision record's ``epochs.regimes``
        holds statutory-cost epoch boundaries — the dates a tax rate changed — and the
        ranker's regime tag is a volatility tercile. They are different partitions that
        share a word, so nothing here maps one onto the other and the table is ``None``
        until a per-regime measurement exists to fill it.
        """
        in_sample = payload.get("in_sample")
        if not isinstance(in_sample, Mapping):
            raise DecisionRecordError(
                f"{source} has no `in_sample` verdict — it is not a decision record this "
                "library can read evidence from"
            )
        metrics = in_sample.get("metrics")
        if not isinstance(metrics, Mapping):
            raise DecisionRecordError(f"{source} has no `in_sample.metrics` to read")

        gross = _as_float(metrics.get("mean_gross_return"))
        drag = _as_float(metrics.get("mean_cost_drag"))
        net = None if gross is None else gross - (drag or 0.0)
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
            "gate_status": f"{source}:in_sample.metrics.gate_status",
            "outcome": f"{source}:outcome",
            "window": f"{source}:in_sample.window",
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
            hold_sessions=hold_sessions,
            gate_status=_as_str(metrics.get("gate_status")),
            outcome=_as_str(payload.get("outcome")),
            window=_as_str(in_sample.get("window")),
            cost_stamps=tuple(str(stamp) for stamp in metrics.get("unverified_inputs") or ()),
            regime_table=None,
            provenance=provenance,
        )


@dataclass(frozen=True, slots=True)
class AdmissionRecord:
    """One status change for one template, with the evidence that justified it.

    Entries are never edited. A template admitted and later demoted has two entries, and
    the demotion carries the reason the admission is no longer believed.
    """

    template_id: str
    hypothesis_id: str | None
    decision_path: str
    decision_outcome: str | None
    trial_ids: tuple[str, ...]
    evidence: EvidenceCard
    status: AdmissionStatus
    admitted_at: str
    admitted_by: str
    reason: str
    notes: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "template_id": self.template_id,
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
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> AdmissionRecord:
        return cls(
            template_id=str(payload["template_id"]),
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
        self._persisted = len(self._entries)

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
            raise DecisionRecordError(
                f"library at {target} is not readable JSON: {error}"
            ) from error
        version = payload.get("schema_version")
        if version != LIBRARY_SCHEMA_VERSION:
            raise DecisionRecordError(
                f"library at {target} declares schema_version {version!r}; this reader "
                f"understands {LIBRARY_SCHEMA_VERSION}"
            )
        entries = [AdmissionRecord.from_dict(row) for row in payload.get("entries") or ()]
        library = cls(target, clock=clock, entries=entries)
        library._persisted = len(entries)
        return library

    @property
    def path(self) -> Path:
        return self._path

    def entries(self) -> tuple[AdmissionRecord, ...]:
        """Every status change, oldest first."""
        return tuple(self._entries)

    def history(self, template_id: str) -> tuple[AdmissionRecord, ...]:
        return tuple(entry for entry in self._entries if entry.template_id == template_id)

    def current(self, template_id: str) -> AdmissionRecord | None:
        """The latest entry naming ``template_id``, or ``None`` if it has none."""
        history = self.history(template_id)
        return history[-1] if history else None

    def status(self, template_id: str) -> AdmissionStatus | None:
        entry = self.current(template_id)
        return entry.status if entry else None

    def admitted(self) -> tuple[AdmissionRecord, ...]:
        """The current entry of every template whose latest status is ``ADMITTED``.

        Ordered by template id so a scan over the library is deterministic.
        """
        latest = {entry.template_id: entry for entry in self._entries}
        return tuple(
            latest[template_id]
            for template_id in sorted(latest)
            if latest[template_id].status is AdmissionStatus.ADMITTED
        )

    def admit(
        self,
        *,
        template: StrategyTemplate,
        decision_path: Path | str,
        by: str,
        reason: str,
        status: AdmissionStatus = AdmissionStatus.ADMITTED,
        notes: str | None = None,
    ) -> AdmissionRecord:
        """File evidence for ``template`` from the decision record at ``decision_path``.

        Refuses when the record does not exist or does not parse — those mean there is no
        evidence, and a template admitted without evidence would hand the ranker an
        expected edge it invented. Does **not** refuse a record whose gate failed; see the
        module docstring for why that is a human's decision and how it stays visible.

        ``by`` and ``reason`` are mandatory and are not checked for truthfulness. Their job
        is to make an admission an attributable act rather than an appearance in a file.
        """
        if status is AdmissionStatus.DEMOTED:
            raise ValueError("use demote() to record a demotion, so it carries its own reason")
        if not by.strip():
            raise ValueError("admit requires `by`: an admission is somebody's decision")
        if not reason.strip():
            raise ValueError("admit requires a written `reason`")

        source = Path(decision_path)
        payload = _read_decision_record(source)
        evidence = EvidenceCard.from_decision_record(
            payload, hold_sessions=template.hold_sessions, source=str(source)
        )
        entry = AdmissionRecord(
            template_id=template.template_id,
            hypothesis_id=_as_str(payload.get("hypothesis_id")),
            decision_path=str(source),
            decision_outcome=_as_str(payload.get("outcome")),
            trial_ids=_trial_ids(payload),
            evidence=evidence,
            status=status,
            admitted_at=self._now(),
            admitted_by=by,
            reason=reason,
            notes=notes,
        )
        self._entries.append(entry)
        return entry

    def demote(self, *, template_id: str, by: str, reason: str) -> AdmissionRecord:
        """Record that ``template_id`` is no longer admitted, against a written reason.

        The evidence card is carried forward from the entry being demoted rather than
        cleared: what the offline loop measured did not stop being true, and a demotion
        whose entry showed no evidence would be unreviewable.
        """
        if not by.strip():
            raise ValueError("demote requires `by`: a demotion is somebody's decision")
        if not reason.strip():
            raise ValueError("demote requires a written `reason`")
        previous = self.current(template_id)
        if previous is None:
            raise KeyError(
                f"template {template_id!r} has no entry in this library, so there is "
                "nothing to demote"
            )
        if previous.status is AdmissionStatus.DEMOTED:
            raise ValueError(f"template {template_id!r} is already demoted")
        entry = AdmissionRecord(
            template_id=template_id,
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

        The stored entries must be a prefix of the in-memory ones. That check is what makes
        "append-only" a property of the file rather than of this object's manners: two
        processes that both loaded the file and both admitted a template would otherwise
        leave whichever saved last as the only survivor.
        """
        if self._path.exists():
            stored = json.loads(self._path.read_text()).get("entries") or []
            mine = [entry.as_dict() for entry in self._entries]
            if len(stored) > len(mine) or stored != mine[: len(stored)]:
                raise AppendOnlyLibraryError(
                    f"the library at {self._path} holds {len(stored)} entries that are not "
                    f"a prefix of the {len(mine)} about to be written — another writer has "
                    "changed it since this one loaded. Reload and re-apply."
                )
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
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
        self._persisted = len(self._entries)
        return self._path

    def _now(self) -> str:
        return self._clock.now().isoformat()


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
