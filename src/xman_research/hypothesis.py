"""The hypothesis record.

Three fields carry the discipline, and the record refuses to exist without them:

* **mechanism** — *why* this should work. An economic reason, not a restatement of the
  rule. "Sell 30-delta strangles at 09:30" is a rule; "index options carry a variance
  risk premium because hedgers pay up for protection" is a mechanism. A rule with no
  mechanism is a pattern found in noise until proven otherwise.
* **null_hypothesis** — what a result would look like if this does *not* work. Written
  before the run, it is the only thing that makes a disappointing result interpretable
  rather than negotiable.
* **thresholds** — the decision criteria, written before any run. Every numeric one names
  a metric :mod:`xman_research.validation` measures, checked here at construction: a
  criterion nothing computes cannot be graded, and freezing one into a content-addressed
  id makes the record ungradeable for as long as it exists.

A fourth field is optional and carries the criteria of a *different* stage:

* **screen_criteria** — what a stage-one screen required of an instance before it was
  worth taking to a gate. Recorded on the record because a later reader needs to know
  what the screen was looking for, and kept out of ``thresholds`` because a stage-two
  gate is not asked to grade it — see :attr:`HypothesisRecord.screen_criteria`.

The record is **immutable**. Changing a threshold after seeing a result is the single
most common way research lies to itself, so there is no setter and no ``replace()``
that keeps the id. :meth:`HypothesisRecord.amend` exists instead: it returns a *new*
record, with a new id, pointing at its parent. The amendment is then visible in the
family trial count (see :meth:`xman_research.trial_log.TrialLog.count_family_trials`),
which is exactly the behaviour wanted — a threshold changed mid-campaign does not
reset the multiple-testing burden.

The id is content-addressed: the same record content is always the same id, and any
change of content is a different id.

**The limit that follows from that, and it is the sharpest one in this package.** The
family trial count is authoritative only if the researcher *amends*. :meth:`amend` keeps
the parent link, so the amendment's trials and the original's are counted together.
Constructing a fresh :class:`HypothesisRecord` instead — the thing a researcher does
naturally when they sit down the next morning and retype their idea — mints an id with
no parent, a new family, and a count of zero. And because **every** field is id-bearing,
including ``name`` and ``notes``, even a purely cosmetic rewording produces a different
record: "H1 — index VRP" and "H1 — index variance risk premium" are two hypotheses as far
as the count is concerned. This is correct behaviour for a content-addressed id and it is
a live way to reset the multiple-testing burden without meaning to. No code in this
package can distinguish it from genuinely new research; C6 consumes the count as
authoritative, so the discipline it rests on has to be understood by whoever reads it.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from contextvars import ContextVar
from dataclasses import dataclass, field, fields
from types import MappingProxyType
from typing import Any

from xman_research._canonical import canonical_json, json_safe
from xman_research.metric_vocabulary import (
    HOLDOUT_THRESHOLD_PREFIX,
    MEASURED_METRICS,
    is_gradeable_metric,
)

__all__ = ["HypothesisRecord", "HypothesisValidationError", "require_gradeable_thresholds"]

ID_PREFIX = "h_"
# 128 bits of the digest. 64 was enough for any plausible number of hypotheses, but the
# id is the join key between a record and its trials, and widening it costs nothing.
ID_HEX_LENGTH = 32

# A hypothesis whose thresholds nest deeper than this is not a decision criterion, and
# a cyclic one cannot be frozen at all. Refused at construction, where nothing is at
# stake — unlike the trial-log path, where refusing to serialise would cost a row.
MAX_FREEZE_DEPTH = 60

OMITTED_WHEN_EMPTY = frozenset({"screen_criteria"})
"""Fields left out of :meth:`HypothesisRecord.content` when they hold nothing.

An id is content-addressed and is quoted outside this package — in gate files, decision
records, and the ``hypothesis_id`` column of every trial row — so an id already minted
has to stay minted. A field that always encodes, even as ``{}``, changes the canonical
JSON of *every* record and re-mints all of them; a field listed here encodes only when a
record actually carries it, so records that do not are byte-identical to what they were
before the field existed. The cost is that ``screen_criteria={}`` and no
``screen_criteria`` at all are the same record, which is the intended reading: a
hypothesis with no screen-stage bars did not have any.

Only container-valued fields belong here. The test is falsiness, so a field whose default
is a scalar — ``0``, ``""`` — would be omitted at that value too, which would make two
different records hash alike."""


_REBUILDING: ContextVar[bool] = ContextVar("rebuilding_stored_hypothesis", default=False)
"""Whether the record being constructed is one already registered somewhere.

Set only by :meth:`HypothesisRecord.from_stored`. Everything about a record is validated
on both paths except the metric vocabulary, which is a rule about what may be registered
*next* rather than a fact about what a stored record is. A log is append-only evidence: a
record registered under an older vocabulary must still be readable, or the log holding it
cannot be opened — and neither can the amendment that brings it into line, which is the
one operation that record still needs."""


class HypothesisValidationError(ValueError):
    """Raised when a hypothesis record is missing something it cannot do without."""


def _require_prose(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HypothesisValidationError(
            f"{field_name} is required and must be non-blank prose; "
            f"got {value!r}. A hypothesis without a {field_name} is not a hypothesis."
        )
    return value.strip()


def _deep_freeze(value: Any, field_name: str, depth: int = 0) -> Any:
    """Recursively replace containers with immutable equivalents.

    Freezing only the top level is not freezing: ``thresholds={"bands": inner}`` would
    keep ``inner`` as the caller's own dict, so mutating it afterwards would change the
    record's content while :attr:`HypothesisRecord.id` — derived from that content at
    construction — stayed put. The record would then persist under an id that no longer
    describes it, which is the "changed a threshold after seeing the result" failure the
    content-addressed id exists to make impossible.
    """
    if depth >= MAX_FREEZE_DEPTH:
        raise HypothesisValidationError(
            f"{field_name} nests deeper than {MAX_FREEZE_DEPTH} levels, or contains a "
            "cycle; a decision criterion that deep cannot be read, let alone judged."
        )
    if isinstance(value, Mapping):
        return MappingProxyType(
            {
                key: _deep_freeze(item, field_name, depth + 1)
                for key, item in sorted(value.items(), key=lambda kv: str(kv[0]))
            }
        )
    if isinstance(value, list | tuple):
        return tuple(_deep_freeze(item, field_name, depth + 1) for item in value)
    if isinstance(value, set | frozenset):
        return frozenset(_deep_freeze(item, field_name, depth + 1) for item in value)
    return value


def _freeze_mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if value is None:
        return MappingProxyType({})
    if not isinstance(value, Mapping):
        raise HypothesisValidationError(
            f"{field_name} must be a mapping, got {type(value).__name__}"
        )
    frozen: dict[str, Any] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not key.strip():
            raise HypothesisValidationError(f"{field_name} has a blank key: {key!r}")
        frozen[key.strip()] = _deep_freeze(item, field_name, 1)
    return MappingProxyType(dict(sorted(frozen.items())))


def _require_thresholds(value: Any) -> Mapping[str, Any]:
    frozen = _freeze_mapping(value, "thresholds")
    if not frozen:
        raise HypothesisValidationError(
            "thresholds are required and must be non-empty: the decision criteria are "
            "written down before the run, or the run cannot be judged afterwards."
        )
    for key, item in frozen.items():
        if item is None or (isinstance(item, str) and not item.strip()):
            raise HypothesisValidationError(f"threshold {key!r} is blank: {item!r}")
    if not _REBUILDING.get():
        require_gradeable_thresholds(frozen)
    return frozen


def require_gradeable_thresholds(thresholds: Mapping[str, Any]) -> None:
    """Refuse criteria no component measures, or explain why they cannot be graded.

    Called when a record is constructed and again when one is registered. The second call
    is not redundant: :meth:`HypothesisRecord.from_stored` exists so a log holding a record
    from an older vocabulary stays readable, and it is public, so construction is not the
    only way a record reaches a log. Registration is the moment a record becomes binding
    evidence, and it is the moment that has to hold.
    """
    ungradeable = sorted(
        key
        for key, item in thresholds.items()
        if _is_criterion(item) and not is_gradeable_metric(key)
    )
    if not ungradeable:
        return
    raise HypothesisValidationError(
        f"thresholds name {', '.join(ungradeable)}, which no component measures. A "
        "numeric threshold is graded by xman_research.validation, and the metrics it "
        f"computes are: {', '.join(sorted(MEASURED_METRICS))} — each optionally "
        f"prefixed {HOLDOUT_THRESHOLD_PREFIX!r} to bind the holdout run instead. "
        "Registering a criterion outside that vocabulary makes the record ungradeable "
        "for good: the gate must carry every numeric threshold the record registered, "
        "and a gate naming a metric outside the vocabulary is refused when it is read. "
        "A bar the screen applies to itself belongs in screen_criteria, which no gate "
        "is asked to grade."
    )


def _is_criterion(value: Any) -> bool:
    """Whether a threshold value is a bar the validator will be asked to grade.

    Mirrors :meth:`~xman_research.validation.gate.DecisionGate.check_binding`, which
    reconciles a registered threshold against the gate file only when its value is a
    number. Anything else — prose, a nested table of parameters — is recorded with the
    record but never graded, so it is not held to the measurable vocabulary. ``bool`` is a
    Python ``int`` and binding grades it as one, so it counts as a criterion here too — the
    two predicates decide the same keys or the guards can disagree again.
    """
    return isinstance(value, int | float)


def _normalise_predictors(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str) or not isinstance(value, Iterable):
        raise HypothesisValidationError(
            f"predictors must be an iterable of names, got {type(value).__name__}"
        )
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise HypothesisValidationError(f"predictor names must be non-blank strings: {item!r}")
        seen.add(item.strip())
    # Sorted, so that reordering the same predictors does not mint a different id.
    return tuple(sorted(seen))


@dataclass(frozen=True, eq=False)
class HypothesisRecord:
    """An immutable, content-addressed hypothesis.

    Equality and hashing are by :attr:`id`, which is derived from every other field.
    """

    name: str
    mechanism: str
    null_hypothesis: str
    thresholds: Mapping[str, Any]
    predictors: tuple[str, ...] = ()
    entry_rule: Mapping[str, Any] = field(default_factory=dict)
    exit_rule: Mapping[str, Any] = field(default_factory=dict)
    notes: str = ""
    parent_id: str | None = None
    screen_criteria: Mapping[str, Any] = field(default_factory=dict)
    """What a stage-one screen required before an instance was worth gating.

    Separate from :attr:`thresholds` because the two are answered by different components
    at different times. ``thresholds`` are graded by :mod:`xman_research.validation`, and
    :meth:`~xman_research.validation.gate.DecisionGate.check_binding` requires the gate
    file to carry every numeric one — so a key here that the validator cannot measure
    would make the record ungradeable, which is why ``thresholds`` refuses one. A screen
    criterion is stated against quantities the screen computes rather than ones the
    validator does, and it is recorded for the reader — the sheet's ranking can be read
    back against the bar it was ranked for. Nothing filters on it: no gate is asked to
    grade it, and the screen does not drop a row for missing it.

    A criterion is only as good as its definition, so record the definition alongside the
    number: ``{"alpha_to_advance": 0.5, "alpha_to_advance_definition": "..."}``. The two
    readings of a word like *alpha* can disagree on the ranking, and a bar with no stated
    quantity is decided by whoever reads it last.
    """
    id: str = field(init=False, default="")

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        set_(self, "name", _require_prose(self.name, "name"))
        set_(self, "mechanism", _require_prose(self.mechanism, "mechanism"))
        set_(self, "null_hypothesis", _require_prose(self.null_hypothesis, "null_hypothesis"))
        set_(self, "thresholds", _require_thresholds(self.thresholds))
        set_(self, "predictors", _normalise_predictors(self.predictors))
        set_(self, "entry_rule", _freeze_mapping(self.entry_rule, "entry_rule"))
        set_(self, "exit_rule", _freeze_mapping(self.exit_rule, "exit_rule"))
        set_(self, "notes", self.notes.strip() if isinstance(self.notes, str) else "")
        if self.parent_id is not None:
            set_(self, "parent_id", _require_prose(self.parent_id, "parent_id"))
        set_(self, "screen_criteria", _freeze_mapping(self.screen_criteria, "screen_criteria"))
        set_(self, "id", self._derive_id())

    @classmethod
    def from_stored(cls, **stored: Any) -> HypothesisRecord:
        """Rebuild a record that is already registered, exactly as it was stored.

        The id is re-derived from the rebuilt content, so this is not a way to get a
        record past a check and into a log: a rebuilt record that does not hash to the id
        it was filed under is caught by the caller that read it. What it skips is the
        metric-vocabulary check on ``thresholds``, which governs what may be registered
        now — see :data:`_REBUILDING`.
        """
        token = _REBUILDING.set(True)
        try:
            return cls(**stored)
        finally:
            _REBUILDING.reset(token)

    def _derive_id(self) -> str:
        digest = hashlib.sha256(canonical_json(self.content()).encode("utf-8")).hexdigest()
        return f"{ID_PREFIX}{digest[:ID_HEX_LENGTH]}"

    def content(self) -> dict[str, Any]:
        """The id-bearing content of this record: every field except the id itself.

        A field listed in :data:`OMITTED_WHEN_EMPTY` is left out entirely when it holds
        nothing, so a record that does not use it hashes exactly as it would if the field
        did not exist. The id is the join key between a record and the trials filed against
        it, and it is quoted in committed gate files and decision records — a field added
        to this class must therefore leave every id already minted where it is, and adding
        one that always encodes (even as ``{}``) would re-mint all of them.
        """
        return {
            f.name: json_safe(getattr(self, f.name))
            for f in fields(self)
            if f.name != "id" and not (f.name in OMITTED_WHEN_EMPTY and not getattr(self, f.name))
        }

    def amend(self, **changes: Any) -> HypothesisRecord:
        """Return a new record with ``changes`` applied and this record as its parent.

        This is the only sanctioned way to change a hypothesis. The original record and
        the trials run against it stay exactly where they are.
        """
        unknown = set(changes) - {f.name for f in fields(self) if f.init}
        if unknown:
            raise HypothesisValidationError(f"unknown field(s) for amend: {sorted(unknown)}")
        if "parent_id" in changes:
            # Silently ignoring it would let a caller believe they had re-parented the
            # amendment — and the parent chain is what makes the family trial count
            # span a campaign. Every other unrecognised field raises; so does this one.
            raise HypothesisValidationError(
                "parent_id cannot be set through amend: the parent of an amendment is "
                "always the record it was amended from. Construct a HypothesisRecord "
                "directly if you need a different parent."
            )
        base: dict[str, Any] = {
            f.name: getattr(self, f.name) for f in fields(self) if f.init and f.name != "parent_id"
        }
        base.update({k: v for k, v in changes.items() if k != "parent_id"})
        return HypothesisRecord(**base, parent_id=self.id)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, HypothesisRecord):
            return NotImplemented
        return self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)
