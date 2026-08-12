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
not solve it. What the triggers do buy is that no *accident*, and no ordinary code path,
can rewrite history.

Schema note for the deferred hash chain: rows are self-contained and nothing depends on
the column set, so a later ``chain_prev``/``chain_hash`` pair can be added by migration
without touching what is written here.
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

from xman_research._canonical import json_safe
from xman_research.clock import Clock, require_aware
from xman_research.code_version import CodeVersion, CodeVersionProvider
from xman_research.hypothesis import HypothesisRecord

__all__ = [
    "AppendOnlyViolation",
    "DataWindow",
    "TrialLog",
    "TrialOutcome",
    "TrialRecord",
    "UnknownHypothesisError",
    "new_trial_id",
]

SCHEMA_VERSION = 1

# RAISE(ABORT, ...) surfaces through the sqlite3 driver as IntegrityError.
AppendOnlyViolation = sqlite3.IntegrityError


class UnknownHypothesisError(LookupError):
    """Raised when a trial or a query names a hypothesis that was never registered."""


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
        with self._conn:
            self._conn.executescript(_SCHEMA)
            self._conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

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
        return HypothesisRecord(
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

    def family_ids(self, hypothesis_id: str) -> tuple[str, ...]:
        """Every hypothesis in ``hypothesis_id``'s amendment tree, including itself."""
        self._require_hypothesis(hypothesis_id)
        rows = self._conn.execute(_FAMILY_SQL, (hypothesis_id,)).fetchall()
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
        """
        self._require_hypothesis(hypothesis_id)
        if not isinstance(data_window, DataWindow):
            raise TypeError(f"data_window must be a DataWindow, got {type(data_window).__name__}")
        resolved_outcome = TrialOutcome(outcome)
        version = self._code_version()
        row_id = trial_id or new_trial_id()
        created_at = self._timestamp()
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
                    json.dumps(json_safe(dict(params)), sort_keys=True),
                    data_window.start.isoformat(),
                    data_window.end.isoformat(),
                    version.sha,
                    int(version.dirty),
                    json.dumps(json_safe(dict(metrics)), sort_keys=True),
                    str(resolved_outcome),
                    error,
                    notes,
                ),
            )
        return TrialRecord(
            trial_id=row_id,
            hypothesis_id=hypothesis_id,
            created_at=datetime.fromisoformat(created_at),
            params=MappingProxyType(dict(params)),
            data_window=data_window,
            code_version=version,
            metrics=MappingProxyType(dict(metrics)),
            outcome=resolved_outcome,
            error=error,
            notes=notes,
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

    def _require_hypothesis(self, hypothesis_id: str) -> None:
        if not self.has_hypothesis(hypothesis_id):
            raise UnknownHypothesisError(
                f"no hypothesis registered with id {hypothesis_id!r}; register it before "
                "logging or counting trials"
            )

    def _timestamp(self) -> str:
        return require_aware(self._clock.now(), "clock.now()").isoformat()


def new_trial_id() -> str:
    """Mint an identity for a trial that is about to run."""
    return f"t_{uuid.uuid4().hex[:16]}"


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
