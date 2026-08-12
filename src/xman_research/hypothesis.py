"""The hypothesis record.

Three fields carry the discipline, and the record refuses to exist without them:

* **mechanism** — *why* this should work. An economic reason, not a restatement of the
  rule. "Sell 30-delta strangles at 09:30" is a rule; "index options carry a variance
  risk premium because hedgers pay up for protection" is a mechanism. A rule with no
  mechanism is a pattern found in noise until proven otherwise.
* **null_hypothesis** — what a result would look like if this does *not* work. Written
  before the run, it is the only thing that makes a disappointing result interpretable
  rather than negotiable.
* **thresholds** — the decision criteria, written before any run.

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
from dataclasses import dataclass, field, fields
from types import MappingProxyType
from typing import Any

from xman_research._canonical import canonical_json, json_safe

__all__ = ["HypothesisRecord", "HypothesisValidationError"]

ID_PREFIX = "h_"
# 128 bits of the digest. 64 was enough for any plausible number of hypotheses, but the
# id is the join key between a record and its trials, and widening it costs nothing.
ID_HEX_LENGTH = 32

# A hypothesis whose thresholds nest deeper than this is not a decision criterion, and
# a cyclic one cannot be frozen at all. Refused at construction, where nothing is at
# stake — unlike the trial-log path, where refusing to serialise would cost a row.
MAX_FREEZE_DEPTH = 60


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
    return frozen


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
        set_(self, "id", self._derive_id())

    def _derive_id(self) -> str:
        digest = hashlib.sha256(canonical_json(self.content()).encode("utf-8")).hexdigest()
        return f"{ID_PREFIX}{digest[:ID_HEX_LENGTH]}"

    def content(self) -> dict[str, Any]:
        """The id-bearing content of this record: every field except the id itself."""
        return {f.name: json_safe(getattr(self, f.name)) for f in fields(self) if f.name != "id"}

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
