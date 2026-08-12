"""The reader side of the corpus contract.

The capture pipeline in the sibling ``xman`` repository writes one parquet file per
underlying per session, plus a ``.refdata`` sibling directory. This module reads them.
**The contract between the two repositories is the file layout, the schema and the
manifest — not a Python API**: research must not import from a live trading repository,
because a research bug would then be one import away from the code that places orders,
and a trading refactor would be one rename away from invalidating a result. Nothing
here imports ``xman``, and nothing here should.

Two properties are load-bearing, and both are structural rather than documented.

**Read-only by construction.** There is no code path in this package that opens a file
for writing, creates a directory, or refreshes an index. The corpus is real captured
data that cannot be re-acquired — a vendor subscription lapsed on 2026-06-14 and the
sessions since then do not exist anywhere. ``tests/test_session_store.py`` proves the
property behaviourally by running a full resolve-and-load against a corpus directory
whose write permission has been removed, which is stronger than any promise in a
docstring.

**A gap is a result, not an absence.** :meth:`Resolution.sessions` refuses to hand over
the files it found while any expected session is missing. A researcher who wants them
anyway calls :meth:`Resolution.accept_gaps` with a written reason. That asymmetry is
the entire point of the component: a Sharpe ratio computed over a range with a two-month
hole in it, that does not mention the hole, is a wrong answer wearing a right answer's
clothes — and the ordinary way to produce one is not dishonesty but a ``for`` loop over
``glob("*.parquet")``, which cannot tell an absent file from a day the market was shut.

The same asymmetry is enforced in the other direction, which is easier to miss: a
session **present** on a day the calendar calls closed is reported as
:attr:`Resolution.unexpected` rather than quietly excluded. Iterating only the expected
days is the same silent skip wearing the calendar's authority, and the calendar is not
always right — see :data:`~xman_research.session_store.trading_calendar.NSE_ERRATA`.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from collections.abc import Iterable, Sequence
from dataclasses import InitVar, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from xman_research.clock import Clock, SystemClock
from xman_research.session_store.manifest import ManifestReader, ManifestRow
from xman_research.session_store.trading_calendar import NSE_CALENDAR, TradingCalendar

if TYPE_CHECKING:  # pragma: no cover - import cost is paid only by type checkers
    import pandas as pd

__all__ = [
    "DEFAULT_CORPUS_ROOT",
    "DEFAULT_MANIFEST_PATH",
    "DERIVATION_VERSION",
    "ChecksumMismatchError",
    "EmptyRangeError",
    "MissingSessionsError",
    "RefData",
    "Resolution",
    "SessionNotFoundError",
    "SessionRef",
    "SessionStore",
    "SessionStoreError",
    "content_digest",
]

#: Bumped whenever a change here alters what a caller receives for the same files on
#: disk. Recorded on every :class:`Resolution` so a stored result can be tied to the
#: reader that produced it — the reader half of the spec's "derived is regenerable from
#: raw plus a recorded derivation version". The reader still performs no derivation on
#: the frame itself: :meth:`SessionStore.load_session` hands back the producer's frame
#: untouched. Any future normalisation (a tz-aware index, a renamed column, an int cast
#: on ``oi``) is a derivation and must bump this.
#:
#: **The resolution's answer counts too, not only the frame.** The set of expected
#: sessions is part of what a caller receives, so a change to
#: :data:`~xman_research.session_store.trading_calendar.NSE_ERRATA` — adding a cited
#: holiday, or dropping one once pandas_market_calendars carries the fix — bumps this
#: version as surely as a column rename would. Two gap reports produced either side of
#: an errata change are not comparable, and this field is the only thing that says so.
#: (Chosen over recording the applied errata dates inside :meth:`Resolution.provenance`,
#: so that there is exactly one authority on comparability rather than two.)
#:
#: ``2`` — the calendar errata layer, and present-but-unexpected sessions being resolved
#: and reported rather than silently ignored. Both change the answer for unchanged files.
DERIVATION_VERSION = "session-store/2"

#: Defaults, not constants. The corpus root is configuration — overridden by the
#: constructor argument, then by these environment variables, then by these values.
#: Tests point it at a fixture tree; a second machine points it at a copied tree.
DEFAULT_CORPUS_ROOT = Path("/home/qa/runtime/data/backtest/datasets/dhan")
DEFAULT_MANIFEST_PATH = Path("/home/qa/runtime/data/backtest/dhan/manifest.sqlite")

CORPUS_ROOT_ENV = "XMAN_RESEARCH_CORPUS_ROOT"
MANIFEST_PATH_ENV = "XMAN_RESEARCH_MANIFEST_PATH"

_PARQUET_SUFFIX = ".parquet"
_REFDATA_SUFFIX = ".refdata"
_NFO_INSTRUMENTS = "nfo_instruments.json"
_UNDERLIER_INSTRUMENTS = "underlier_instruments.json"


class SessionStoreError(Exception):
    """Base for every refusal this package raises."""


class MissingSessionsError(SessionStoreError):
    """Sessions the calendar expected are not on disk, and the caller asked for the rest.

    Carries the :class:`Resolution` so a handler can report the gap rather than only
    the fact that there was one.
    """

    def __init__(self, message: str, resolution: Resolution) -> None:
        super().__init__(message)
        self.resolution = resolution


class EmptyRangeError(SessionStoreError):
    """The range contains no exchange sessions at all.

    Distinct from "every session is missing", and refused for the same reason: a
    backtest that silently runs over zero sessions reports a clean result about
    nothing. Reaching this usually means a typo, or a range that landed on a weekend.
    """


class SessionNotFoundError(SessionStoreError):
    """A load was attempted for a session that is not in the corpus."""


class ChecksumMismatchError(SessionStoreError):
    """A session's content digest differs from what the producer recorded for it.

    Either the raw was mutated after publication — the immutability guarantee broken —
    or the manifest and the tree came from different points in time. Both are worth
    stopping for; neither should be discovered from a strange backtest result.

    Note what this is *not*: a byte-level comparison of the parquet file. See
    :func:`content_digest`, which explains why, and why the byte-level version would
    fire on all 119 sessions of the real corpus while nothing is wrong with any of them.
    """


@dataclass(frozen=True, slots=True)
class RefData:
    """The refdata sibling of one session: the instrument definitions in force that day.

    Handed back as the producer wrote it. Strikes, lot sizes, tick sizes and trading
    symbols are the exchange's to define and this platform's to read verbatim — the
    engine never composes them, and neither does research.
    """

    session_date: dt.date
    nfo_instruments: tuple[dict[str, Any], ...]
    underlier_instruments: tuple[dict[str, Any], ...]


@dataclass(frozen=True, slots=True)
class SessionRef:
    """A session that is present on disk, plus whatever the producer said about it."""

    underlying: str
    session_date: dt.date
    parquet_path: Path
    refdata_path: Path | None
    manifest_row: ManifestRow | None

    @property
    def has_refdata(self) -> bool:
        return self.refdata_path is not None

    @property
    def sha256(self) -> str | None:
        """The producer's recorded checksum, or ``None`` when no manifest was readable."""
        return self.manifest_row.sha256 if self.manifest_row else None

    @property
    def coverage_pct(self) -> float | None:
        return self.manifest_row.coverage_pct if self.manifest_row else None

    @property
    def status(self) -> str | None:
        return self.manifest_row.status if self.manifest_row else None


@dataclass(frozen=True, repr=False)
class Resolution:
    """The answer to "(underlying, start, end) → which files?", gaps included.

    Deliberately **not iterable and without** ``__len__``. Both would be a quiet way
    back to the ``for session in resolution`` loop that skips the gap report, which is
    the failure this class exists to make impossible. The sessions come out of exactly
    two doors: :meth:`sessions`, which refuses while there is a gap, and
    :meth:`accept_gaps`, which requires the caller to write down why.

    The resolved refs are held **outside** the dataclass fields, reached only through
    those two methods. That is not decoration: as an ordinary field, a plain
    ``dataclasses.asdict(resolution)["_found"]`` handed over every session on a gappy
    resolution without a gap ever being confronted — and reaching for ``asdict`` to log
    an object is a reflex, not an attack. Python cannot make the gate absolute (the
    attribute is still there for anyone who goes looking), but it can stop the casual
    route, and ``asdict`` was the casual route. The cost is that the generated
    ``__eq__`` compares the report and not the refs, which is the right comparison for
    two resolutions of the same range anyway.
    """

    underlying: str
    start: dt.date
    end: dt.date
    expected: tuple[dt.date, ...]
    missing: tuple[dt.date, ...]
    quarantined: tuple[dt.date, ...]
    unexpected: tuple[dt.date, ...]
    resolved_at: dt.datetime
    derivation_version: str
    calendar_name: str
    manifest_available: bool
    found: InitVar[tuple[SessionRef, ...]]
    quarantined_refs: InitVar[tuple[SessionRef, ...]]

    def __post_init__(
        self, found: tuple[SessionRef, ...], quarantined_refs: tuple[SessionRef, ...]
    ) -> None:
        object.__setattr__(self, "_refs", found)
        object.__setattr__(self, "_quarantined_refs", quarantined_refs)

    @property
    def expected_count(self) -> int:
        return len(self.expected)

    @property
    def found_count(self) -> int:
        """Sessions resolved: the expected ones that are present, plus any unexpected."""
        return len(self._refs)

    @property
    def missing_count(self) -> int:
        return len(self.missing)

    @property
    def unexpected_count(self) -> int:
        return len(self.unexpected)

    @property
    def expected_present_count(self) -> int:
        """Resolved sessions the calendar actually expected — the completeness numerator."""
        expected = set(self.expected)
        return sum(1 for ref in self._refs if ref.session_date in expected)

    @property
    def is_empty(self) -> bool:
        """Nothing was expected in this range, and nothing was found either.

        Kept separate from :attr:`is_complete` on purpose. An empty range is vacuously
        complete, and reading that as "complete, carry on" is precisely how a typo in a
        date turns into a green result over no data. Both doors to the sessions refuse
        on it, so the vacuous case cannot be mistaken for a clean run through either.

        A range the calendar calls empty but which nevertheless holds a session on disk
        is **not** empty — that is the Muhurat case, and there is real data to hand over.
        """
        return not self.expected and not self.unexpected

    @property
    def is_complete(self) -> bool:
        """Nothing expected is absent or quarantined — and the range was not empty.

        Speaks only to :attr:`missing` and :attr:`quarantined`. An empty range is
        explicitly *not* complete: ``not () and not ()`` is vacuously true, and a caller
        guarding ``if resolution.is_complete:`` would read a range typo'd onto a weekend
        as a clean run over no data. :attr:`unexpected` does not falsify it either — a
        session the calendar did not expect is a calendar/producer disagreement, not a
        hole in the data — but it is always named in :meth:`summary`.
        """
        return not self.is_empty and not self.missing and not self.quarantined

    @property
    def completeness_pct(self) -> float:
        if not self.expected:
            # Nothing expected: 0% over a genuinely empty range, and 100% when the only
            # sessions here are ones the calendar did not expect but the producer captured.
            return 100.0 if self.unexpected else 0.0
        return 100.0 * self.expected_present_count / self.expected_count

    def sessions(self) -> tuple[SessionRef, ...]:
        """The resolved sessions in date order — or a refusal.

        Raises :class:`EmptyRangeError` if the range holds no sessions at all, and
        :class:`MissingSessionsError` if any expected session is absent or quarantined.
        This is the door to use by default; reaching for :meth:`accept_gaps` should be
        a decision, not a habit.

        Sessions present on disk that the calendar did not expect **are** returned here:
        they are real captured data, and dropping them would be criterion 1 inverted —
        the silent skip this component exists to remove, pointed the other way. They are
        reported in :meth:`summary` and listed in :attr:`unexpected`, so they arrive
        named rather than smuggled.
        """
        if self.is_empty:
            raise EmptyRangeError(
                f"{self.underlying} {self.start}..{self.end} contains no {self.calendar_name} "
                f"sessions — the range covers only non-trading days."
            )
        if not self.is_complete:
            raise MissingSessionsError(self.summary(), self)
        return self._refs

    def accept_gaps(
        self, reason: str, *, include_quarantined: bool = False
    ) -> tuple[SessionRef, ...]:
        """The resolved sessions despite the gaps, against a written reason.

        The reason is mandatory and is not checked for truthfulness — it cannot be. Its
        job is to make ignoring a gap a deliberate, attributable act rather than an
        omission, and to give the trial log something to record about why a result was
        computed over a partial window.

        ``include_quarantined`` adds back the sessions the producer marked untrustworthy.
        They are excluded by default and behind their own flag rather than behind the
        reason string, because "carry on across a two-day vendor outage" and "compute on
        data the producer says is bad" are two different decisions, and a caller who
        wrote the first reason must not silently receive the second.

        Raises :class:`EmptyRangeError` on an empty range — checked before the reason,
        since no reason accepts a gap in a range that has nothing to accept. Without it,
        the common ``except SessionStoreError: refs = res.accept_gaps(...)`` shape would
        turn a date typo back into a green run over zero sessions.
        """
        if self.is_empty:
            raise EmptyRangeError(
                f"{self.underlying} {self.start}..{self.end} contains no {self.calendar_name} "
                f"sessions — there is no gap to accept, only an empty range."
            )
        if not reason or not reason.strip():
            raise ValueError(
                "accept_gaps requires a written reason — proceeding over a known gap "
                "without one is the omission this API exists to prevent."
            )
        if not include_quarantined or not self._quarantined_refs:
            return self._refs
        return tuple(sorted(self._refs + self._quarantined_refs, key=lambda ref: ref.session_date))

    def summary(self) -> str:
        """One paragraph a human can act on. Also this object's ``repr``."""
        label = f"{self.underlying} {self.start}..{self.end} [{self.calendar_name}]"
        if self.is_empty:
            head = f"{label}: no trading days in this range."
        elif not self.expected:
            # "1/0 sessions (100.0% complete)" for a calendar-empty range that
            # nevertheless holds a file reads as a bug in the reader. It is a
            # calendar/producer disagreement, and it gets said in words.
            head = (
                f"{label}: the {self.calendar_name} calendar expected no sessions here, "
                f"but {self.found_count} is on disk"
            )
        else:
            head = (
                f"{label}: {self.expected_present_count}/{self.expected_count} sessions "
                f"({self.completeness_pct:.1f}% complete)"
            )
        parts = [head]
        if self.unexpected:
            # Not run-grouped: _runs positions dates by their index in `expected`, which
            # these are by definition not in, so every one would render as its own run.
            parts.append(
                f"UNEXPECTED {len(self.unexpected)} session(s) present on a day the "
                f"{self.calendar_name} calendar calls closed — the calendar and the "
                f"producer disagree: {', '.join(d.isoformat() for d in self.unexpected)}."
            )
        if self.missing:
            runs = self.missing_runs()
            plural = "" if len(runs) == 1 else "s"
            parts.append(
                f"MISSING {len(self.missing)} trading day(s) in {len(runs)} run{plural}: "
                f"{'; '.join(_render_run(run) for run in runs)}"
            )
        if self.quarantined:
            parts.append(
                "QUARANTINED by the producer, excluded: "
                f"{'; '.join(_render_run(run) for run in self.quarantined_runs())}"
            )
        if self.is_complete:
            parts.append("no gaps.")
        if not self.manifest_available:
            parts.append("manifest unavailable — sha256/coverage/status not reported.")
        return " ".join(parts)

    def missing_runs(self) -> tuple[tuple[dt.date, ...], ...]:
        """Group the missing days into consecutive-*trading-day* runs.

        Adjacency is measured in exchange sessions, not calendar days, so a Friday and
        the following Monday are one run and a weekend never splits one. This is what
        makes the summary honest at a glance: the real corpus's 43 missing days are one
        isolated day plus a 42-day outage, and rendering that as a single
        ``2026-01-15..2026-08-12 (43 days)`` span would describe an eight-month hole
        that does not exist.
        """
        return _runs(self.missing, self.expected)

    def quarantined_runs(self) -> tuple[tuple[dt.date, ...], ...]:
        """The quarantined days, grouped the same way."""
        return _runs(self.quarantined, self.expected)

    def provenance(self) -> dict[str, Any]:
        """A JSON-safe record of what was read, for a trial log row.

        Includes the per-session checksums when a manifest was readable, so a stored
        result names not just the range it covered but the exact bytes behind it.
        """
        return {
            "underlying": self.underlying,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "derivation_version": self.derivation_version,
            "calendar": self.calendar_name,
            "resolved_at": self.resolved_at.isoformat(),
            "expected_count": self.expected_count,
            "found_count": self.found_count,
            "missing": [d.isoformat() for d in self.missing],
            "quarantined": [d.isoformat() for d in self.quarantined],
            "unexpected": [d.isoformat() for d in self.unexpected],
            "manifest_available": self.manifest_available,
            "session_sha256": {
                ref.session_date.isoformat(): ref.sha256
                for ref in self._refs
                if ref.sha256 is not None
            },
        }

    def __repr__(self) -> str:
        return f"<Resolution {self.summary()}>"

    def _repr_html_(self) -> str:
        """Notebook rendering — the gap in red, because §4.3 of the spec is a notebook.

        A researcher who types ``res`` in a cell must *see* the hole. That is the
        strongest available form of "hard to ignore" in the workflow this platform is
        actually used through. Amber for a complete range that carries unexpected
        sessions: nothing is missing, but the calendar and the producer disagree about
        what a session is, and that deserves a second look rather than a green tick.
        """
        if not self.is_complete:
            colour = "#b3261e"
        elif self.unexpected:
            colour = "#b06000"
        else:
            colour = "#137333"
        body = _html_escape(self.summary())
        return f'<pre style="white-space:pre-wrap;color:{colour}">{body}</pre>'


class SessionStore:
    """Read-only reader over a corpus of per-session parquet files.

    Layout, as written by the producer::

        <root>/<UNDERLYING>/<YYYY-MM-DD>.parquet
        <root>/<UNDERLYING>/<YYYY-MM-DD>.refdata/{nfo,underlier}_instruments.json

    A ``<YYYY-MM-DD>.parquet.scan.npz`` may also sit alongside. It is the producer's
    index and this package never reads, writes or refreshes it — building a scan index
    is the one plausible way a reader accidentally writes into an immutable corpus.
    """

    def __init__(
        self,
        root: Path | str | None = None,
        *,
        clock: Clock | None = None,
        manifest_path: Path | str | None = None,
        calendar: TradingCalendar | None = None,
        derivation_version: str = DERIVATION_VERSION,
    ) -> None:
        self._root = Path(root) if root is not None else _default_root()
        self._clock = clock if clock is not None else SystemClock()
        self._manifest = ManifestReader(
            Path(manifest_path) if manifest_path is not None else _default_manifest_path()
        )
        self._calendar = calendar if calendar is not None else TradingCalendar(NSE_CALENDAR)
        self._derivation_version = derivation_version

    @property
    def root(self) -> Path:
        return self._root

    @property
    def derivation_version(self) -> str:
        return self._derivation_version

    @property
    def manifest_available(self) -> bool:
        return self._manifest.available

    def underlyings(self) -> tuple[str, ...]:
        """Underlyings present in the corpus, in name order."""
        if not self._root.is_dir():
            return ()
        return tuple(sorted(p.name for p in self._root.iterdir() if p.is_dir()))

    def resolve(self, underlying: str, start: dt.date, end: dt.date) -> Resolution:
        """Resolve a range to files, and to the sessions that should have been there.

        ``expected`` is the exchange calendar's answer for the whole range and is
        **not** clipped to what the corpus happens to contain. Clipping would make the
        headline guarantee vacuous: a range running past the end of capture would
        report itself complete, which is exactly the case that is true right now — the
        corpus stops on 2026-06-12 and capture has been dead since 2026-06-14.

        The directory is also scanned for sessions the calendar did *not* expect. Only
        iterating ``expected`` meant a file on a day the calendar calls a holiday was
        never opened, never counted and reachable through no API at all — criterion 1
        inverted, with real captured data as the casualty. See :attr:`Resolution.unexpected`.
        """
        if start > end:
            raise ValueError(f"start {start} is after end {end}")
        _check_underlying(underlying)

        expected = self._calendar.trading_days(start, end)
        expected_set = set(expected)
        directory = self._root / underlying

        present = [
            session_date
            for session_date in expected
            if (directory / f"{session_date.isoformat()}{_PARQUET_SUFFIX}").is_file()
        ]
        present_set = set(present)
        missing = tuple(d for d in expected if d not in present_set)
        unexpected = tuple(
            d
            for d in _session_dates_on_disk(directory)
            if start <= d <= end and d not in expected_set
        )
        on_disk = sorted(present_set | set(unexpected))

        manifest_rows, manifest_available = self._manifest.rows_and_availability(
            underlying, on_disk
        )
        quarantined_set = {
            d for d in on_disk if (row := manifest_rows.get(d)) is not None and row.is_quarantined
        }
        refs = {d: self._build_ref(underlying, directory, d, manifest_rows.get(d)) for d in on_disk}

        return Resolution(
            underlying=underlying,
            start=start,
            end=end,
            expected=expected,
            missing=missing,
            quarantined=tuple(sorted(quarantined_set)),
            unexpected=unexpected,
            resolved_at=self._clock.now(),
            derivation_version=self._derivation_version,
            calendar_name=self._calendar.name,
            manifest_available=manifest_available,
            found=tuple(ref for d, ref in refs.items() if d not in quarantined_set),
            quarantined_refs=tuple(ref for d, ref in refs.items() if d in quarantined_set),
        )

    def load_session(self, ref: SessionRef, *, verify: bool = False) -> pd.DataFrame:
        """Read one session's parquet file, exactly as the producer wrote it.

        No column is renamed, retyped or reindexed — ``minute_ts`` stays an epoch-microsecond
        ``int64`` and ``oi``/``volume`` stay ``float64`` (the producer widens them because
        spot rows carry ``NaN`` there). Normalising any of that would be a derivation, and
        a derivation this reader performs silently is one a stored result cannot be tied
        back to. If it is wanted, it belongs behind a bumped ``DERIVATION_VERSION``.

        ``verify=True`` re-derives the producer's recorded digest from the frame just
        read — no second read of the file. Off by default because rendering the frame to
        CSV costs roughly as much again as loading it; worth turning on for any run whose
        result will be acted upon.
        """
        import pandas as pd

        if not ref.parquet_path.is_file():
            raise SessionNotFoundError(f"no parquet at {ref.parquet_path}")
        frame = pd.read_parquet(ref.parquet_path)
        if verify:
            self.verify_checksum(ref, frame)
        return frame

    def load_refdata(self, ref: SessionRef) -> RefData:
        """Read the instrument definitions in force for that session."""
        if ref.refdata_path is None or not ref.refdata_path.is_dir():
            raise SessionNotFoundError(f"no refdata bundle for {ref.underlying} {ref.session_date}")
        return RefData(
            session_date=ref.session_date,
            nfo_instruments=tuple(_read_json_list(ref.refdata_path / _NFO_INSTRUMENTS)),
            underlier_instruments=tuple(_read_json_list(ref.refdata_path / _UNDERLIER_INSTRUMENTS)),
        )

    def verify_checksum(self, ref: SessionRef, frame: pd.DataFrame | None = None) -> str | None:
        """Re-derive a session's content digest and compare it with the manifest.

        Returns the computed digest, or ``None`` when no manifest checksum was available
        to compare against — an honest "not checked" rather than a pass. Raises
        :class:`ChecksumMismatchError` on a genuine disagreement. See :func:`content_digest`
        for what the digest is actually over; it is not the parquet file's bytes.

        This is the only check anywhere that the corpus is in fact immutable. The
        producer writes the digest and never looks at it again, so until this ran,
        "raw is immutable" was an intention rather than an observation.
        """
        import pandas as pd

        expected = ref.sha256
        if expected is None:
            return None
        if frame is None:
            frame = pd.read_parquet(ref.parquet_path)
        digest = content_digest(frame)
        if digest != expected:
            raise ChecksumMismatchError(
                f"{ref.underlying} {ref.session_date}: content sha256 {digest} does not "
                f"match the manifest's {expected} — the session was mutated after "
                f"publication, the manifest and the parquet tree are from different "
                f"points in time, or pandas' CSV rendering changed under us."
            )
        return digest

    def _build_ref(
        self,
        underlying: str,
        directory: Path,
        session_date: dt.date,
        manifest_row: ManifestRow | None,
    ) -> SessionRef:
        stem = session_date.isoformat()
        refdata = directory / f"{stem}{_REFDATA_SUFFIX}"
        return SessionRef(
            underlying=underlying,
            session_date=session_date,
            parquet_path=directory / f"{stem}{_PARQUET_SUFFIX}",
            refdata_path=refdata if refdata.is_dir() else None,
            manifest_row=manifest_row,
        )


def _session_dates_on_disk(directory: Path) -> tuple[dt.date, ...]:
    """Every ``<YYYY-MM-DD>.parquet`` in ``directory``, as dates, in order.

    Names that are not a date are skipped rather than raised on: the corpus belongs to
    the producer, and a reader that refuses to resolve a range because somebody left a
    ``backup.parquet`` in the tree has made the corpus harder to use, not safer. The
    producer's ``.parquet.scan.npz`` index does not match the glob and is never touched.
    """
    dates: list[dt.date] = []
    for path in directory.glob(f"*{_PARQUET_SUFFIX}"):
        try:
            dates.append(dt.date.fromisoformat(path.name[: -len(_PARQUET_SUFFIX)]))
        except ValueError:
            continue
    return tuple(sorted(dates))


def _check_underlying(underlying: str) -> None:
    """Refuse an underlying that is a path rather than a name.

    ``store.resolve("NIFTY/../..", ...)`` would otherwise walk out of the corpus root.
    Everything here is read-only, so the worst case is telling a caller whether files
    exist somewhere else on the machine — but a root that is not a root is worth one
    line to prevent rather than an argument about severity.
    """
    if not underlying or underlying in {".", ".."}:
        raise ValueError(f"underlying must be a non-empty name, got {underlying!r}")
    if "/" in underlying or "\\" in underlying or os.sep in underlying:
        raise ValueError(f"underlying must be a name, not a path, got {underlying!r}")


def _default_root() -> Path:
    return Path(os.environ.get(CORPUS_ROOT_ENV) or DEFAULT_CORPUS_ROOT)


def _default_manifest_path() -> Path:
    return Path(os.environ.get(MANIFEST_PATH_ENV) or DEFAULT_MANIFEST_PATH)


def _read_json_list(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    with path.open("rb") as handle:
        payload = json.load(handle)
    if isinstance(payload, list):
        return payload
    raise SessionStoreError(f"{path} is not a JSON list, got {type(payload).__name__}")


def content_digest(frame: pd.DataFrame) -> str:
    """Reproduce the producer's ``sha256`` for a session.

    **The manifest's digest is over content, not over file bytes**, and getting that
    wrong is a trap worth naming: the obvious implementation — hash the parquet file —
    disagrees with the manifest on every session in the corpus, all 119 of them. The
    producer hashes the normalised frame rendered as CSV, on purpose, because parquet
    encodings differ across pyarrow versions for identical data. So a file rewritten by
    a newer pyarrow with the same numbers still verifies, which is the property actually
    wanted; a changed number does not, which is the property actually checked.

    The cost of that choice is a dependency on ``DataFrame.to_csv`` formatting being
    stable across pandas versions — float repr in particular. That is not guaranteed by
    pandas, so this is a real fragility rather than a theoretical one, and the mitigation
    is that it is *checked*: :func:`~xman_research.session_store.store.SessionStore.verify_checksum`
    is the first code anywhere to re-verify these digests, and the real-corpus test
    re-derives one against the live manifest on every run. If a pandas upgrade breaks the
    rendering, that test goes red and says so, rather than every verification silently
    turning into a false alarm.
    """
    return hashlib.sha256(frame.to_csv(index=False).encode()).hexdigest()


def _runs(days: Iterable[dt.date], expected: Sequence[dt.date]) -> tuple[tuple[dt.date, ...], ...]:
    """Split ``days`` into runs that are consecutive within ``expected``."""
    position = {day: index for index, day in enumerate(expected)}
    ordered = sorted(set(days))
    grouped: list[list[dt.date]] = []
    for day in ordered:
        index = position.get(day)
        previous = grouped[-1][-1] if grouped else None
        if (
            grouped
            and index is not None
            and previous is not None
            and position.get(previous) == index - 1
        ):
            grouped[-1].append(day)
        else:
            grouped.append([day])
    return tuple(tuple(run) for run in grouped)


def _render_run(run: Sequence[dt.date]) -> str:
    """``2026-01-15`` for a single day, ``2026-06-15..2026-08-12 (42 days)`` for a span.

    A gap report nobody reads because it is a wall of ISO dates has failed at its one job.
    """
    if len(run) == 1:
        return run[0].isoformat()
    if len(run) <= 4:
        return ", ".join(day.isoformat() for day in run)
    return f"{run[0].isoformat()}..{run[-1].isoformat()} ({len(run)} days)"


def _html_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
