"""The append-only trial log.

The load-bearing property of this module: **the trial count is read from the log, and
there is no API by which a caller can supply one.** Deflated Sharpe needs the true
number of trials, and the researcher is exactly the party with an incentive to
understate it, so the number must come from a record the evaluation path writes for
itself.

Append-only is enforced *in the database*, by triggers that abort every ``UPDATE`` and
``DELETE`` against both tables. A convention-only "append-only" log is not append-only;
it is a habit. Rows can still be removed by someone with a ``sqlite3`` shell and intent
— that is the deferred tamper-evidence problem (spec §7), and the MVP deliberately does
not solve it.

**The precise reach of the triggers, because the obvious reading of them is wrong.**
``INSERT OR REPLACE`` resolves a conflict by deleting the existing row and inserting the
new one, and SQLite fires that delete's ``BEFORE DELETE`` trigger **only when
``PRAGMA recursive_triggers`` is ON**. It is OFF by default. Without it, the single most
common upsert idiom in Python silently rewrote a logged trial, and — worse — rewrote a
registered hypothesis's mechanism and thresholds *in place, under the same id*, which is
the "changed a threshold after seeing the result" lie this package exists to prevent. It
needed no intent; the idiom does it by accident.

:class:`TrialLog` therefore turns ``recursive_triggers`` ON for its own connection. Note
what that does and does not buy: **the pragma is connection-scoped and is not stored in
the database file.** Every connection this class opens is protected, on this file, in
this process, for as long as this process lives. A *foreign* connection — a ``sqlite3``
shell, a pandas ``read_sql`` helper, another program's ORM — starts with the pragma OFF
and can still ``INSERT OR REPLACE`` over a row. Ordinary code paths inside this package
cannot rewrite history; the file itself is not armoured, and only tamper-evidence
(spec §7) would make it so.

The cheap partial defence against exactly that: :meth:`TrialLog.get_hypothesis`
re-derives the content id of every record it reads and refuses it if the stored id
disagrees. A hypothesis rewritten through a foreign connection keeps its old id while
its content changes, so the mismatch is detectable on read even though the write could
not be blocked.

Schema note for the deferred hash chain: rows are self-contained and nothing depends on
the column set, so a later ``chain_prev``/``chain_hash`` pair can be added by migration
without touching what is written here.

Two limits of the *count* that no code in this module can close, stated here because
C6's deflated-Sharpe correction consumes the number as authoritative:

* **The count is authoritative only if the researcher amends rather than re-registers.**
  :meth:`~xman_research.hypothesis.HypothesisRecord.amend` keeps the family and its
  accumulated trials; constructing a fresh record instead mints a new id with no parent,
  a new family, and a count of zero. Because ``name`` and ``notes`` are id-bearing, even
  a *cosmetic* rewording of the same hypothesis produces a different record — which is
  correct for content-addressing and is a live way to reset the multiple-testing burden
  without meaning to.
* **Nothing binds an evaluation to a canonical database.** ``open_session`` takes a path,
  so 200 trials against ``scratch.db`` followed by the winner against ``research.db``
  leaves the second file reporting a count of 1. C6 should read its database path from
  configuration rather than accept it as an argument, so that "which log" is not a
  per-call decision the researcher makes while looking at their results.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType, TracebackType
from typing import Any

from xman_research._canonical import json_safe, safe_json_dumps, safe_repr
from xman_research.clock import Clock, require_aware
from xman_research.code_version import CodeVersion, CodeVersionProvider
from xman_research.hypothesis import HypothesisRecord

__all__ = [
    "AppendOnlyViolation",
    "DataWindow",
    "LogIntegrityError",
    "SchemaVersionError",
    "TrialLog",
    "TrialOutcome",
    "TrialRecord",
    "UnknownHypothesisError",
    "UnknownTrialError",
    "new_trial_id",
]

SCHEMA_VERSION = 1

# RAISE(ABORT, ...) surfaces through the sqlite3 driver as IntegrityError.
AppendOnlyViolation = sqlite3.IntegrityError


class UnknownHypothesisError(LookupError):
    """Raised when a trial or a query names a hypothesis that was never registered."""


class UnknownTrialError(LookupError):
    """Raised when a ``trial_id`` names no row the log can resolve.

    The alternative — returning ``None`` — made a mistyped or foreign id
    indistinguishable from *no* id, and every check that resolves a ``trial_id`` in
    order to stop trusting a caller-typed value then silently went back to trusting it.
    An identity that does not resolve is bad evidence, not absent evidence, and the
    difference is the whole reason the resolution exists.
    """


class LogIntegrityError(RuntimeError):
    """Raised when the log's own invariants do not hold — evidence of tampering.

    Two conditions raise it: a stored hypothesis whose content no longer hashes to the
    id it is filed under, and a parent chain that contains a cycle. Neither is
    constructible through this API, so either one means the file was written by
    something else.
    """


class SchemaVersionError(RuntimeError):
    """Raised when the database was written by a different version of this schema."""


class TrialOutcome(StrEnum):
    """What became of an evaluation.

    ``ERROR`` matters as much as ``COMPLETED``: a trial that raised is still a trial.
    If failed runs were not logged, a researcher could un-try a variant by making it
    throw, and the trial count would undercount by exactly the number of embarrassing
    attempts.
    """

    COMPLETED = "completed"
    ERROR = "error"
    NOT_EVALUABLE = "not_evaluable"


@dataclass(frozen=True, slots=True)
class DataWindow:
    """The span of history an evaluation was run against."""

    start: date
    end: date

    def __post_init__(self) -> None:
        if not isinstance(self.start, date) or not isinstance(self.end, date):
            raise ValueError("DataWindow start and end must be dates")
        if self.end < self.start:
            raise ValueError(f"DataWindow end {self.end} precedes start {self.start}")

    def __str__(self) -> str:
        return f"{self.start.isoformat()}..{self.end.isoformat()}"


# Metric names this package has renamed, mapped to the older names that meant the *same
# quantity*. Read-side only: the rows themselves are append-only and are never rewritten.
#
# The single entry is deliberately one-directional and it is the whole point of the
# table. ``adjusted_sharpe`` was the per-period Pézier-White figure, and it was renamed
# because the gate was reading `tails.annualised_adjusted_sharpe` under the same label —
# two numbers a factor of sqrt(252) = 15.9 apart sharing one name. So the legacy key
# resolves to the *per-period* name and must never resolve to the annualised one; an
# alias table that pointed both ways would restore the exact defect the rename fixed.
_LEGACY_METRIC_NAMES: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {"adjusted_sharpe_per_period": ("adjusted_sharpe",)}
)


@dataclass(frozen=True, slots=True)
class TrialRecord:
    """One row of the trial log, as read back."""

    trial_id: str
    hypothesis_id: str
    created_at: datetime
    params: Mapping[str, Any]
    data_window: DataWindow
    code_version: CodeVersion
    metrics: Mapping[str, Any]
    outcome: TrialOutcome
    error: str | None
    notes: str | None

    @property
    def recorded_no_result(self) -> bool:
        """Whether this row raised *and* carries no metrics at all.

        Two facts already stored in the row, and nothing else. It is not a claim that
        the infrastructure broke rather than the idea failing — that judgement is
        exactly the discretion the append-only log exists to remove, and nothing here
        makes it. The row is still a trial, still counted, and still undeletable; this
        only marks it as a trial that produced no number to judge.

        ``NOT_EVALUABLE`` is deliberately excluded even though it can also carry empty
        metrics: a run that was judged un-gradeable is a run that happened and reached a
        verdict, which is a research trial in every sense that matters to the deflation.
        """
        return self.outcome is TrialOutcome.ERROR and not self.metrics

    def metric(self, name: str, default: Any = None) -> Any:
        """One metric, resolving the names this package has renamed since.

        The log is append-only by database trigger, so rows written before a rename
        cannot be migrated in place — correctly. That leaves the schema split across the
        rename, and a reader that asks for the current name gets nothing from an older
        row. This resolves the split at read time, current name first, so a row written
        either side of it answers the same question.
        """
        if name in self.metrics:
            return self.metrics[name]
        for legacy in _LEGACY_METRIC_NAMES.get(name, ()):
            if legacy in self.metrics:
                return self.metrics[legacy]
        return default


_SCHEMA = """
CREATE TABLE IF NOT EXISTS hypotheses (
    id              TEXT PRIMARY KEY,
    parent_id       TEXT,
    name            TEXT NOT NULL,
    mechanism       TEXT NOT NULL,
    null_hypothesis TEXT NOT NULL,
    thresholds_json TEXT NOT NULL,
    predictors_json TEXT NOT NULL,
    entry_rule_json TEXT NOT NULL,
    exit_rule_json  TEXT NOT NULL,
    notes           TEXT NOT NULL DEFAULT '',
    registered_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trials (
    seq             INTEGER PRIMARY KEY AUTOINCREMENT,
    trial_id        TEXT NOT NULL UNIQUE,
    hypothesis_id   TEXT NOT NULL REFERENCES hypotheses(id),
    created_at      TEXT NOT NULL,
    params_json     TEXT NOT NULL,
    window_start    TEXT NOT NULL,
    window_end      TEXT NOT NULL,
    code_sha        TEXT NOT NULL,
    code_dirty      INTEGER NOT NULL,
    metrics_json    TEXT NOT NULL,
    outcome         TEXT NOT NULL,
    error           TEXT,
    notes           TEXT
);

CREATE INDEX IF NOT EXISTS trials_by_hypothesis ON trials(hypothesis_id);
CREATE INDEX IF NOT EXISTS hypotheses_by_parent ON hypotheses(parent_id);

CREATE TRIGGER IF NOT EXISTS trials_no_update BEFORE UPDATE ON trials
BEGIN
    SELECT RAISE(ABORT, 'trial log is append-only: UPDATE on trials is forbidden');
END;

CREATE TRIGGER IF NOT EXISTS trials_no_delete BEFORE DELETE ON trials
BEGIN
    SELECT RAISE(ABORT, 'trial log is append-only: DELETE on trials is forbidden');
END;

CREATE TRIGGER IF NOT EXISTS hypotheses_no_update BEFORE UPDATE ON hypotheses
BEGIN
    SELECT RAISE(ABORT, 'hypothesis records are immutable: UPDATE is forbidden, amend instead');
END;

CREATE TRIGGER IF NOT EXISTS hypotheses_no_delete BEFORE DELETE ON hypotheses
BEGIN
    SELECT RAISE(ABORT, 'hypothesis records are immutable: DELETE is forbidden');
END;
"""

# Walk from any member up to the root of its parent chain, then back down over every
# descendant of that root. "Family" is the whole tree, not the ancestor chain: 200
# variants of H1 are 200 trials in H1's selection universe, and that is the number
# deflated Sharpe needs. UNION (not UNION ALL) terminates even on a cyclic parent_id.
_FAMILY_SQL = """
WITH RECURSIVE ancestors(id, parent_id) AS (
    SELECT id, parent_id FROM hypotheses WHERE id = ?
    UNION
    SELECT h.id, h.parent_id FROM hypotheses h JOIN ancestors a ON h.id = a.parent_id
),
roots(id) AS (
    SELECT id FROM ancestors
    WHERE parent_id IS NULL OR parent_id NOT IN (SELECT id FROM hypotheses)
),
family(id) AS (
    SELECT id FROM roots
    UNION
    SELECT h.id FROM hypotheses h JOIN family f ON h.parent_id = f.id
)
SELECT id FROM family
"""


class TrialLog:
    """A SQLite-backed, append-only log of hypotheses and the evaluations run on them.

    One file, no server. ``clock`` and ``code_version`` are required constructor
    arguments with no defaults: the log's whole value is that its timestamps and
    provenance are not guesses, so the wiring boundary has to name them.

    Durability caveat, stated plainly: a trial row is written **once**, after the
    evaluation finishes (it cannot be written first and updated later — the triggers
    forbid exactly that). A hard process kill mid-evaluation therefore loses that
    trial. The alternative — a start row and an end row, counted with
    ``COUNT(DISTINCT trial_id)`` — is more robust and more machinery; at MVP scale,
    where evaluations are seconds long and the operator is one person at a notebook,
    the single-row form is the right trade. Revisit when evaluations get long enough
    that a crash mid-run is a realistic way to lose a trial.
    """

    def __init__(
        self,
        db_path: Path | str,
        *,
        clock: Clock,
        code_version: CodeVersionProvider,
    ) -> None:
        self._db_path = Path(db_path)
        self._clock = clock
        self._code_version = code_version
        if str(self._db_path) != ":memory:":
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        # Without this, INSERT OR REPLACE deletes the conflicting row *without* firing
        # the BEFORE DELETE triggers, and both append-only and hypothesis immutability
        # are defeated by the ordinary upsert idiom. See the module docstring for what
        # this does and does not cover — it is connection-scoped, not stored in the file.
        self._conn.execute("PRAGMA recursive_triggers = ON")
        with self._conn:
            self._conn.executescript(_SCHEMA)
            self._stamp_schema_version()

    # ---------------------------------------------------------------- lifecycle

    @property
    def db_path(self) -> Path:
        return self._db_path

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> TrialLog:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    # ------------------------------------------------------------- hypotheses

    def register_hypothesis(self, record: HypothesisRecord) -> HypothesisRecord:
        """Persist ``record``. Idempotent — re-registering the same record is a no-op.

        Idempotence is safe precisely because the id is content-addressed: a record
        with the same id has the same content by construction, so nothing is being
        overwritten. ``INSERT OR IGNORE`` skips rather than replaces, so the
        immutability triggers are never in play.
        """
        if record.parent_id is not None and not self.has_hypothesis(record.parent_id):
            raise UnknownHypothesisError(
                f"parent hypothesis {record.parent_id!r} is not registered; "
                "register the parent before its amendment"
            )
        with self._conn:
            self._conn.execute(
                """
                INSERT OR IGNORE INTO hypotheses (
                    id, parent_id, name, mechanism, null_hypothesis, thresholds_json,
                    predictors_json, entry_rule_json, exit_rule_json, notes, registered_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.parent_id,
                    record.name,
                    record.mechanism,
                    record.null_hypothesis,
                    json.dumps(json_safe(record.thresholds), sort_keys=True),
                    json.dumps(list(record.predictors)),
                    json.dumps(json_safe(record.entry_rule), sort_keys=True),
                    json.dumps(json_safe(record.exit_rule), sort_keys=True),
                    record.notes,
                    self._timestamp(),
                ),
            )
        return record

    def has_hypothesis(self, hypothesis_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM hypotheses WHERE id = ?", (hypothesis_id,)
        ).fetchone()
        return row is not None

    def get_hypothesis(self, hypothesis_id: str) -> HypothesisRecord:
        """Rebuild a registered record. The id of the result equals ``hypothesis_id``."""
        row = self._conn.execute(
            "SELECT * FROM hypotheses WHERE id = ?", (hypothesis_id,)
        ).fetchone()
        if row is None:
            raise UnknownHypothesisError(f"no hypothesis registered with id {hypothesis_id!r}")
        record = HypothesisRecord(
            name=row["name"],
            mechanism=row["mechanism"],
            null_hypothesis=row["null_hypothesis"],
            thresholds=json.loads(row["thresholds_json"]),
            predictors=tuple(json.loads(row["predictors_json"])),
            entry_rule=json.loads(row["entry_rule_json"]),
            exit_rule=json.loads(row["exit_rule_json"]),
            notes=row["notes"],
            parent_id=row["parent_id"],
        )
        # The id is derived from the content, so re-deriving it on read is a free
        # integrity check: a record rewritten in place — which this connection's
        # triggers prevent, but a foreign connection's do not — keeps the id it is
        # filed under while its content changes, and that is what this catches.
        if record.id != hypothesis_id:
            raise LogIntegrityError(
                f"hypothesis {hypothesis_id!r} does not hash to its stored id (content "
                f"hashes to {record.id!r}). The record was rewritten after registration; "
                "the trials filed against this id were run on a different hypothesis "
                "than the one stored."
            )
        return record

    def family_ids(self, hypothesis_id: str) -> tuple[str, ...]:
        """Every hypothesis in ``hypothesis_id``'s amendment tree, including itself."""
        self._require_hypothesis(hypothesis_id)
        rows = self._conn.execute(_FAMILY_SQL, (hypothesis_id,)).fetchall()
        if not rows:
            # A cyclic parent chain has no root, so ``roots`` is empty and the whole
            # family collapses to nothing — and an empty family means a count of *zero*,
            # the most flattering answer the multiple-testing correction could be given.
            # Cycles are unconstructible through this API, so reaching here means the
            # file was written by something else; say so instead of returning the number
            # that makes every result look best.
            raise LogIntegrityError(
                f"hypothesis {hypothesis_id!r} is registered but its family resolved to "
                "no members: the parent chain contains a cycle. Refusing to report a "
                "trial count that would silently be zero."
            )
        return tuple(sorted(row["id"] for row in rows))

    # ------------------------------------------------------------------ trials

    def append_trial(
        self,
        *,
        hypothesis_id: str,
        params: Mapping[str, Any],
        data_window: DataWindow,
        metrics: Mapping[str, Any],
        outcome: TrialOutcome | str = TrialOutcome.COMPLETED,
        error: str | None = None,
        notes: str | None = None,
        trial_id: str | None = None,
    ) -> TrialRecord:
        """Append one evaluation to the log and return it as read back.

        ``trial_id`` is an identity, not a count: the evaluation seam mints one when a
        trial *starts* so the running evaluation can refer to itself. Supplying it
        cannot change how many trials exist — a duplicate id is rejected by the unique
        constraint, and every call appends exactly one row.

        **Everything past the hypothesis and window checks degrades rather than raises.**
        This method is called from a ``finally`` after the evaluation body has run, so an
        exception here does not fail a trial — it deletes one: the researcher keeps the
        result and the log never hears about it. An unrecognised ``outcome``, a
        non-string ``notes``, a param holding a circular reference: each of those used to
        cost the whole row, and each is now recorded approximately, with a note saying so.
        The two things that *do* still raise are checked before the body ever runs, by
        the callers in :mod:`xman_research.evaluation`.
        """
        self._require_hypothesis(hypothesis_id)
        if not isinstance(data_window, DataWindow):
            raise TypeError(f"data_window must be a DataWindow, got {type(data_window).__name__}")
        resolved_outcome, outcome_note = _coerce_outcome(outcome)
        version = self._code_version()
        row_id = trial_id or new_trial_id()
        created_at = self._timestamp()
        safe_params = json_safe(_safe_mapping(params))
        safe_metrics = json_safe(_safe_mapping(metrics))
        safe_error = _coerce_text(error)
        safe_notes = _coerce_text(notes)
        if outcome_note is not None:
            safe_notes = outcome_note if not safe_notes else f"{safe_notes}; {outcome_note}"
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO trials (
                    trial_id, hypothesis_id, created_at, params_json, window_start,
                    window_end, code_sha, code_dirty, metrics_json, outcome, error, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row_id,
                    hypothesis_id,
                    created_at,
                    safe_json_dumps(safe_params),
                    data_window.start.isoformat(),
                    data_window.end.isoformat(),
                    version.sha,
                    int(version.dirty),
                    safe_json_dumps(safe_metrics),
                    str(resolved_outcome),
                    safe_error,
                    safe_notes,
                ),
            )
        # The returned record is what was *stored*, not what was passed: if a param
        # degraded to a repr on the way in, the caller should see the degraded form
        # rather than an in-memory copy that flatters the row.
        return TrialRecord(
            trial_id=row_id,
            hypothesis_id=hypothesis_id,
            created_at=datetime.fromisoformat(created_at),
            params=MappingProxyType(dict(safe_params)),
            data_window=data_window,
            code_version=version,
            metrics=MappingProxyType(dict(safe_metrics)),
            outcome=resolved_outcome,
            error=safe_error,
            notes=safe_notes,
        )

    def trials(self, hypothesis_id: str) -> tuple[TrialRecord, ...]:
        """Every trial logged against exactly this hypothesis, in append order."""
        self._require_hypothesis(hypothesis_id)
        rows = self._conn.execute(
            "SELECT * FROM trials WHERE hypothesis_id = ? ORDER BY seq", (hypothesis_id,)
        ).fetchall()
        return tuple(_row_to_trial(row) for row in rows)

    def family_trials(self, hypothesis_id: str) -> tuple[TrialRecord, ...]:
        """Every trial logged against any member of this hypothesis's family."""
        ids = self.family_ids(hypothesis_id)
        placeholders = ",".join("?" for _ in ids)
        rows = self._conn.execute(
            f"SELECT * FROM trials WHERE hypothesis_id IN ({placeholders}) ORDER BY seq",
            ids,
        ).fetchall()
        return tuple(_row_to_trial(row) for row in rows)

    def require_family_trial(self, hypothesis_id: str, trial_id: str) -> TrialRecord:
        """The row ``trial_id`` names within this hypothesis's family, or refuse.

        Refusing is the point. Callers resolve a ``trial_id`` precisely so they can stop
        trusting a value the caller typed — a timestamp, most importantly. Returning
        ``None`` for an id that resolves to nothing hands those callers the same
        observation they get for *no* id at all, so the check they were performing
        quietly reverts to the state it was written to replace.

        The two failures are diagnosed apart because they mean different things. An id
        that names nothing is a typo or a run from another database; an id that names a
        row in *another* family is a real, correctly-formed identity pointed at the
        wrong hypothesis, which is the harder case to notice by eye and the easier one
        to produce by copy-paste.
        """
        self._require_hypothesis(hypothesis_id)
        family = set(self.family_ids(hypothesis_id))
        row = self._conn.execute("SELECT * FROM trials WHERE trial_id = ?", (trial_id,)).fetchone()
        if row is None:
            raise UnknownTrialError(
                f"trial_id {trial_id!r} names no trial in this log ({self.db_path}). An "
                "unresolvable id is not the same as no id: it is evidence that does not "
                "check out, and treating it as absent would silently restore the "
                "caller-supplied value this lookup exists to replace."
            )
        record = _row_to_trial(row)
        if record.hypothesis_id not in family:
            raise UnknownTrialError(
                f"trial_id {trial_id!r} is logged against hypothesis "
                f"{record.hypothesis_id!r}, which belongs to another hypothesis family — "
                f"not {hypothesis_id!r}'s. The id is real, so it looks legitimate; it is "
                "evidence about a different idea."
            )
        return record

    def count_trials(self, hypothesis_id: str) -> int:
        """How many evaluations were run against exactly this hypothesis.

        Read from the log. There is no argument by which a caller can influence it.
        """
        self._require_hypothesis(hypothesis_id)
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM trials WHERE hypothesis_id = ?", (hypothesis_id,)
        ).fetchone()
        return int(row["n"])

    def count_family_trials(self, hypothesis_id: str) -> int:
        """How many evaluations were run against this hypothesis's whole family.

        This is the number deflated Sharpe needs. Trying 200 variants of H1 is 200
        trials against H1's family, however many separate records those variants were
        written as — which is why amending a hypothesis does not reset the count.
        """
        ids = self.family_ids(hypothesis_id)
        placeholders = ",".join("?" for _ in ids)
        row = self._conn.execute(
            f"SELECT COUNT(*) AS n FROM trials WHERE hypothesis_id IN ({placeholders})",
            ids,
        ).fetchone()
        return int(row["n"])

    # ----------------------------------------------------------------- internals

    def _stamp_schema_version(self) -> None:
        """Stamp the schema version, or refuse a file written by a different one.

        Stamping unconditionally would relabel a database this code cannot actually
        read as one it can, which turns a loud open-time failure into quiet
        mis-parsing of an append-only record.
        """
        found = int(self._conn.execute("PRAGMA user_version").fetchone()[0])
        if found == SCHEMA_VERSION:
            return
        if found != 0:
            raise SchemaVersionError(
                f"{self._db_path} was written with schema version {found}, but this code "
                f"speaks version {SCHEMA_VERSION}. Refusing to open it rather than "
                "guessing at the column meanings of a record that is meant to be evidence."
            )
        self._conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def _require_hypothesis(self, hypothesis_id: str) -> None:
        if not self.has_hypothesis(hypothesis_id):
            raise UnknownHypothesisError(
                f"no hypothesis registered with id {hypothesis_id!r}; register it before "
                "logging or counting trials"
            )

    def _timestamp(self) -> str:
        return require_aware(self._clock.now(), "clock.now()").isoformat()


def new_trial_id() -> str:
    """Mint an identity for a trial that is about to run.

    Full 128 bits of the uuid, not a truncation: ``trial_id`` carries a UNIQUE
    constraint, so a collision is not a cosmetic clash — it is an ``INSERT`` that
    fails, in a ``finally``, for a trial that already ran. That is the same lost-row
    failure the rest of this module works to make unreachable.
    """
    return f"t_{uuid.uuid4().hex}"


def _coerce_outcome(outcome: TrialOutcome | str) -> tuple[TrialOutcome, str | None]:
    """Resolve ``outcome``, degrading an unrecognised value instead of raising.

    ``TrialOutcome(outcome)`` raises on anything unexpected, and this runs after the
    evaluation body — so a context whose ``outcome`` was assigned some other value used
    to lose the row entirely. ``ERROR`` is the honest landing place: the run did not
    produce a result this log can vouch for, and the original value is kept in the note.
    """
    try:
        return TrialOutcome(outcome), None
    except (ValueError, TypeError):
        return (
            TrialOutcome.ERROR,
            f"unrecognised outcome {safe_repr(outcome)}; recorded as error",
        )


def _coerce_text(value: Any) -> str | None:
    """A value bound into a TEXT column, or ``None`` — never something sqlite3 refuses."""
    if value is None or isinstance(value, str):
        return value
    return safe_repr(value)


def _safe_mapping(value: Any) -> dict[Any, Any]:
    """``dict(value)`` that cannot raise, for params and metrics off the context."""
    try:
        return dict(value)
    except Exception:
        return {"__unmappable__": safe_repr(value)}


def _row_to_trial(row: sqlite3.Row) -> TrialRecord:
    return TrialRecord(
        trial_id=row["trial_id"],
        hypothesis_id=row["hypothesis_id"],
        created_at=datetime.fromisoformat(row["created_at"]),
        params=MappingProxyType(json.loads(row["params_json"])),
        data_window=DataWindow(
            start=date.fromisoformat(row["window_start"]),
            end=date.fromisoformat(row["window_end"]),
        ),
        code_version=CodeVersion(sha=row["code_sha"], dirty=bool(row["code_dirty"])),
        metrics=MappingProxyType(json.loads(row["metrics_json"])),
        outcome=TrialOutcome(row["outcome"]),
        error=row["error"],
        notes=row["notes"],
    )
