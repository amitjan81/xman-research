"""The producer's manifest, read as an optional oracle.

The capture pipeline in the sibling ``xman`` repository records one row per published
session: the sha256 it wrote, how many rows and symbols it contained, its coverage
percentage, and whether it was published or quarantined. That is genuinely useful
provenance and C2 surfaces it.

**It is never required.** Research is expected to run on a machine that has been handed
a copy of the parquet tree and nothing else — the manifest lives outside the corpus
directory, at a path derived from the producer's deployment layout, and there is no
reason a researcher's laptop would have it. So every field here is optional, absence is
reported (:attr:`ManifestReader.available`) rather than raised, and a resolution against
a manifest-less tree differs only in that the provenance fields are ``None``.

**Opened strictly read-only, and the URI is load-bearing.** The corpus and its manifest
are real captured data that cannot be re-acquired, so nothing in this package may create
a file underneath it. ``immutable=1`` is what guarantees that: a plain ``mode=ro`` open
of a WAL-mode database still makes SQLite create ``-shm``/``-wal`` siblings next to it.
The manifest is ``journal_mode=delete`` today, so that would not bite right now — which
is exactly why it is pinned now rather than after the producer changes journal mode.

The trade-off ``immutable=1`` buys: SQLite is told the file will not change while open,
so a concurrent producer write could be read torn. Accepted — the manifest is written
once nightly by a batch job, connections here live for microseconds, and a torn read is
recoverable while a stray file in the corpus is not.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

__all__ = ["PUBLISHED", "QUARANTINED", "ManifestReader", "ManifestRow"]

PUBLISHED = "published"
QUARANTINED = "quarantined"


@dataclass(frozen=True, slots=True)
class ManifestRow:
    """What the producer recorded about one published session."""

    underlying: str
    session_date: dt.date
    parquet_path: str
    sha256: str
    rows: int
    symbols: int
    coverage_pct: float
    status: str
    reason: str | None
    published_at: str

    @property
    def is_quarantined(self) -> bool:
        return self.status == QUARANTINED


class ManifestReader:
    """Read-only accessor for the producer's ``manifest.sqlite``.

    Degrades to "no manifest" for every reason it could fail — the file is absent, the
    path is a directory, the schema predates the ``sessions`` table, the file is not a
    database. A research run must not stop because optional provenance was unreadable;
    it must only stop reporting provenance it does not have.
    """

    def __init__(self, path: Path | None) -> None:
        self._path = path

    @property
    def path(self) -> Path | None:
        return self._path

    @property
    def available(self) -> bool:
        """Whether rows can actually be read, not merely whether a path was configured."""
        with self._connect() as connection:
            return connection is not None

    def rows_for(
        self, underlying: str, session_dates: Iterable[dt.date]
    ) -> dict[dt.date, ManifestRow]:
        """Return the manifest rows for ``session_dates``, keyed by date.

        Dates with no row are simply absent from the mapping. That is the normal case
        on a tree whose manifest was copied at a different time from its parquet files,
        and it is not an error: the file on disk is the fact, the manifest is commentary.
        """
        return self.rows_and_availability(underlying, session_dates)[0]

    def rows_and_availability(
        self, underlying: str, session_dates: Iterable[dt.date]
    ) -> tuple[dict[dt.date, ManifestRow], bool]:
        """:meth:`rows_for` and :attr:`available` from a **single** open.

        A resolution needs both facts, and asking for them separately opened the
        database twice per call. Note what the shape forbids: an early return on an
        empty ``session_dates`` would answer "unavailable" for every empty range, which
        is a different claim from "no rows were asked for" — and one the summary would
        then print as a false "manifest unavailable" note.
        """
        wanted = sorted(set(session_dates))
        found: dict[dt.date, ManifestRow] = {}
        with self._connect() as connection:
            if connection is None:
                return {}, False
            if not wanted:
                return {}, True
            placeholders = ",".join("?" for _ in wanted)
            cursor = connection.execute(
                "SELECT underlying, session_date, parquet_path, sha256, rows, symbols, "
                "coverage_pct, status, reason, published_at FROM sessions "
                f"WHERE underlying = ? AND session_date IN ({placeholders})",
                [underlying, *(d.isoformat() for d in wanted)],
            )
            for record in cursor.fetchall():
                session_date = dt.date.fromisoformat(record[1])
                found[session_date] = ManifestRow(
                    underlying=record[0],
                    session_date=session_date,
                    parquet_path=record[2],
                    sha256=record[3],
                    rows=int(record[4]),
                    symbols=int(record[5]),
                    coverage_pct=float(record[6]),
                    status=record[7],
                    reason=record[8],
                    published_at=record[9],
                )
        return found, True

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection | None]:
        """Yield a read-only connection, or ``None`` for any reason there cannot be one.

        Always closed on the way out, including on error. A leaked handle against a
        database opened ``immutable=1`` is harmless to the file, but a research process
        is a long-lived notebook kernel and leaking one per resolution is how a session
        runs out of descriptors hours later.
        """
        if self._path is None or not self._path.is_file():
            yield None
            return
        connection: sqlite3.Connection | None = None
        try:
            uri = f"{self._path.resolve().as_uri()}?mode=ro&immutable=1"
            connection = sqlite3.connect(uri, uri=True, timeout=5.0)
            connection.execute("SELECT 1 FROM sessions LIMIT 1").fetchall()
        except sqlite3.Error:
            if connection is not None:
                connection.close()
            yield None
            return
        try:
            yield connection
        finally:
            connection.close()
