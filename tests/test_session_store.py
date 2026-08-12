"""C2 — the session store, against a synthetic corpus.

The expected trading days in every assertion below are written as **literals**, not
derived from the calendar the code under test uses. Deriving them would make the test
agree with the implementation by construction and prove nothing about whether either
matches NSE. The literals were taken once from pandas_market_calendars 5.4.0 — plus the cited
corrections in ``NSE_ERRATA`` where that package is known wrong — and are checkable by
hand: January 2026's holidays are Republic Day (Monday the 26th) and the 15th, on which
NSE was shut for the Maharashtra municipal corporation elections.
"""

from __future__ import annotations

import csv
import dataclasses
import datetime as dt
import hashlib
import json
import sqlite3
import stat
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from xman_research.clock import ManualClock
from xman_research.session_store import (
    DERIVATION_VERSION,
    NSE_ERRATA,
    CalendarCoverageError,
    CalendarErratum,
    ChecksumMismatchError,
    EmptyRangeError,
    MissingSessionsError,
    SessionNotFoundError,
    SessionRef,
    SessionStore,
    TradingCalendar,
    content_digest,
)

FIXTURES = Path(__file__).parent / "fixtures" / "session_store"
PINNED_NOW = datetime(2026, 8, 12, 9, 15, tzinfo=UTC)

# Real NSE trading days, written down rather than computed. See the module docstring.
JAN_05_TO_16 = (
    dt.date(2026, 1, 5),
    dt.date(2026, 1, 6),
    dt.date(2026, 1, 7),
    dt.date(2026, 1, 8),
    dt.date(2026, 1, 9),
    dt.date(2026, 1, 12),
    dt.date(2026, 1, 13),
    dt.date(2026, 1, 14),
    # 2026-01-15 is absent: NSE was closed for the Maharashtra municipal corporation
    # elections. pandas_market_calendars 5.4.0 has it as a session; NSE_ERRATA corrects it.
    dt.date(2026, 1, 16),
)


def _build_corpus(root: Path, *, with_manifest: bool) -> Path:
    """Materialise the checked-in fixture spec into a corpus tree under ``root``.

    Returns the manifest path (which may not exist, when ``with_manifest`` is false).
    """
    spec = json.loads((FIXTURES / "corpus_sessions.json").read_text())
    underlying = spec["underlying"]
    directory = root / "datasets" / "dhan" / underlying
    directory.mkdir(parents=True)

    with (FIXTURES / "session_rows.csv").open() as handle:
        rows = list(csv.DictReader(handle))
    frame = pd.DataFrame(rows).replace("", None)
    for column in frame.columns:
        if column != "symbol":
            frame[column] = pd.to_numeric(frame[column])
    frame["minute_ts"] = frame["minute_ts"].astype("int64")

    nfo = json.loads((FIXTURES / "refdata_nfo_instruments.json").read_text())
    underlier = json.loads((FIXTURES / "refdata_underlier_instruments.json").read_text())

    manifest_rows = []
    for session in spec["sessions"]:
        stem = session["date"]
        parquet_path = directory / f"{stem}.parquet"
        frame.to_parquet(parquet_path, index=False)
        # The producer's scan index sits alongside. Nothing in this package may touch it,
        # so the fixture carries one to make an accidental read or rewrite detectable.
        (directory / f"{stem}.parquet.scan.npz").write_bytes(b"not-a-real-npz")
        refdata = directory / f"{stem}.refdata"
        refdata.mkdir()
        (refdata / "nfo_instruments.json").write_text(json.dumps(nfo))
        (refdata / "underlier_instruments.json").write_text(json.dumps(underlier))
        manifest_rows.append(
            (
                underlying,
                stem,
                str(parquet_path),
                # The producer hashes the frame's CSV rendering, not the file's bytes.
                # The fixture mirrors that exactly, or it would test a contract nobody has.
                content_digest(pd.read_parquet(parquet_path)),
                len(rows),
                3,
                session["coverage_pct"],
                session["status"],
                session.get("reason"),
                "2026-02-04T22:50:13+00:00",
            )
        )

    manifest_path = root / "manifest.sqlite"
    if with_manifest:
        connection = sqlite3.connect(manifest_path)
        with connection:
            connection.execute(
                "CREATE TABLE sessions (underlying TEXT NOT NULL, session_date TEXT NOT NULL, "
                "parquet_path TEXT NOT NULL, sha256 TEXT NOT NULL, rows INTEGER NOT NULL, "
                "symbols INTEGER NOT NULL, coverage_pct REAL NOT NULL, status TEXT NOT NULL, "
                "reason TEXT, published_at TEXT NOT NULL, "
                "PRIMARY KEY (underlying, session_date))"
            )
            connection.executemany(
                "INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?)", manifest_rows
            )
        connection.close()
    return manifest_path


@pytest.fixture
def clock() -> ManualClock:
    return ManualClock(PINNED_NOW, step=timedelta(seconds=1))


@pytest.fixture
def corpus_root(tmp_path: Path) -> Path:
    _build_corpus(tmp_path, with_manifest=True)
    return tmp_path / "datasets" / "dhan"


@pytest.fixture
def store(tmp_path: Path, corpus_root: Path, clock: ManualClock) -> SessionStore:
    return SessionStore(corpus_root, clock=clock, manifest_path=tmp_path / "manifest.sqlite")


@pytest.fixture
def store_without_manifest(tmp_path: Path, clock: ManualClock) -> SessionStore:
    _build_corpus(tmp_path, with_manifest=False)
    return SessionStore(
        tmp_path / "datasets" / "dhan", clock=clock, manifest_path=tmp_path / "manifest.sqlite"
    )


# --------------------------------------------------------------------------------------
# Criterion 1 — resolution reports missing sessions rather than skipping them
# --------------------------------------------------------------------------------------


def test_range_entirely_inside_the_corpus_is_complete(store: SessionStore) -> None:
    resolution = store.resolve("NIFTY", dt.date(2026, 1, 5), dt.date(2026, 1, 16))

    assert resolution.expected == JAN_05_TO_16
    assert resolution.missing == ()
    assert resolution.unexpected == ()
    assert resolution.is_complete
    assert not resolution.is_empty
    assert len(resolution.sessions()) == 9


def test_resolved_sessions_come_back_in_date_order(store: SessionStore) -> None:
    sessions = store.resolve("NIFTY", dt.date(2026, 1, 5), dt.date(2026, 1, 16)).sessions()

    dates = [ref.session_date for ref in sessions]
    assert dates == sorted(dates)
    assert dates[0] == dt.date(2026, 1, 5)


def test_range_spanning_a_gap_reports_the_missing_days(store: SessionStore) -> None:
    resolution = store.resolve("NIFTY", dt.date(2026, 1, 19), dt.date(2026, 1, 23))

    assert resolution.expected == (
        dt.date(2026, 1, 19),
        dt.date(2026, 1, 20),
        dt.date(2026, 1, 21),
        dt.date(2026, 1, 22),
        dt.date(2026, 1, 23),
    )
    assert resolution.missing == (dt.date(2026, 1, 20), dt.date(2026, 1, 21))
    assert resolution.found_count == 3
    assert not resolution.is_complete


def test_sessions_refuses_while_a_gap_exists(store: SessionStore) -> None:
    resolution = store.resolve("NIFTY", dt.date(2026, 1, 19), dt.date(2026, 1, 23))

    with pytest.raises(MissingSessionsError) as excinfo:
        resolution.sessions()

    assert "2026-01-20" in str(excinfo.value)
    # The gap report travels with the exception, so a handler can act on it.
    assert excinfo.value.resolution.missing_count == 2


def test_gaps_can_be_accepted_but_only_with_a_written_reason(store: SessionStore) -> None:
    resolution = store.resolve("NIFTY", dt.date(2026, 1, 19), dt.date(2026, 1, 23))

    assert len(resolution.accept_gaps("two-day vendor outage, documented in ops log")) == 3

    for empty in ("", "   "):
        with pytest.raises(ValueError, match="written reason"):
            resolution.accept_gaps(empty)


def test_resolution_cannot_be_iterated_around_the_gate(store: SessionStore) -> None:
    """The gate is only a gate if there is no second door.

    ``for ref in resolution`` and ``len(resolution)`` would each be a way to reach the
    files without ever seeing the gap report, so neither is implemented.
    """
    resolution = store.resolve("NIFTY", dt.date(2026, 1, 19), dt.date(2026, 1, 23))

    with pytest.raises(TypeError):
        list(resolution)  # type: ignore[call-overload]
    with pytest.raises(TypeError):
        len(resolution)  # type: ignore[arg-type]


def test_serialising_a_resolution_does_not_hand_over_the_sessions(store: SessionStore) -> None:
    """``asdict`` is a logging reflex, not an adversarial reach — and it was a third door.

    While the refs were an ordinary dataclass field, ``dataclasses.asdict(res)["_found"]``
    returned every session of a gappy resolution without a gap ever being confronted, and
    without the caller typing an underscore. The gate cannot be made absolute in Python;
    it can stop being trivially bypassable by well-meaning code.
    """
    resolution = store.resolve("NIFTY", dt.date(2026, 1, 19), dt.date(2026, 1, 23))

    serialised = dataclasses.asdict(resolution)

    assert "_found" not in serialised
    assert not any(isinstance(value, SessionRef) for value in serialised.values())
    assert not any(
        isinstance(value, tuple) and any(isinstance(item, SessionRef) for item in value)
        for value in serialised.values()
    )
    # The gap report itself is still fully serialisable — that is what asdict is for.
    assert serialised["missing"] == (dt.date(2026, 1, 20), dt.date(2026, 1, 21))


def test_an_underlying_that_is_a_path_is_refused(store: SessionStore) -> None:
    """``NIFTY/../..`` would resolve against a directory outside the corpus root."""
    for hostile in ("NIFTY/../..", "../NIFTY", "", ".."):
        with pytest.raises(ValueError, match="underlying must be"):
            store.resolve(hostile, dt.date(2026, 1, 5), dt.date(2026, 1, 6))


def test_range_entirely_after_the_corpus_ends_is_all_missing(store: SessionStore) -> None:
    """The case that is true of the real corpus right now, and the one clipping would hide."""
    resolution = store.resolve("NIFTY", dt.date(2026, 2, 16), dt.date(2026, 2, 20))

    assert resolution.expected_count == 5
    assert resolution.missing_count == 5
    assert resolution.found_count == 0
    assert not resolution.is_empty  # five sessions were expected; none arrived
    assert not resolution.is_complete
    with pytest.raises(MissingSessionsError):
        resolution.sessions()


# --------------------------------------------------------------------------------------
# Closed markets are not gaps
# --------------------------------------------------------------------------------------


def test_weekends_and_republic_day_are_not_reported_as_missing(store: SessionStore) -> None:
    """2026-01-24/25 is a weekend and 2026-01-26 is Republic Day. None is a capture gap."""
    resolution = store.resolve("NIFTY", dt.date(2026, 1, 23), dt.date(2026, 1, 28))

    assert resolution.expected == (
        dt.date(2026, 1, 23),
        dt.date(2026, 1, 27),
        dt.date(2026, 1, 28),
    )
    assert dt.date(2026, 1, 26) not in resolution.expected
    assert resolution.missing == ()
    assert resolution.is_complete


def test_a_range_of_only_non_trading_days_is_empty_not_complete(store: SessionStore) -> None:
    """A Saturday-to-Sunday range expects nothing — and must not read as a clean run."""
    resolution = store.resolve("NIFTY", dt.date(2026, 1, 24), dt.date(2026, 1, 25))

    assert resolution.expected == ()
    assert resolution.is_empty
    assert "no trading days" in resolution.summary()
    with pytest.raises(EmptyRangeError):
        resolution.sessions()


def test_an_empty_range_is_refused_by_accept_gaps_as_well(store: SessionStore) -> None:
    """The second door has to hold the same line, or the guarantee is decorative.

    ``try: res.sessions() / except SessionStoreError: res.accept_gaps(reason)`` is an
    entirely ordinary shape, and while ``accept_gaps`` answered an empty range it turned
    a typo'd date into a green run over zero sessions — through one generic ``except``.
    There is no gap to accept in a range that expected nothing.
    """
    resolution = store.resolve("NIFTY", dt.date(2026, 1, 24), dt.date(2026, 1, 25))

    with pytest.raises(EmptyRangeError):
        resolution.accept_gaps("a standard, entirely reasonable pipeline-wide reason")


def test_an_empty_range_does_not_report_itself_as_complete(store: SessionStore) -> None:
    """``not () and not ()`` is vacuously true, and ``if res.is_complete:`` is a guard."""
    resolution = store.resolve("NIFTY", dt.date(2026, 1, 24), dt.date(2026, 1, 25))

    assert resolution.is_empty
    assert not resolution.is_complete
    assert resolution.completeness_pct == 0.0  # and not contradicting is_complete


def test_an_empty_range_does_not_falsely_claim_the_manifest_was_unreadable(
    store: SessionStore,
) -> None:
    """Asking for zero rows is not the same fact as the manifest being absent.

    The availability answer used to come from a second, independent open; folding it
    into the one query risks answering "unavailable" whenever no dates were asked for,
    and the empty summary is where that lie would surface.
    """
    resolution = store.resolve("NIFTY", dt.date(2026, 1, 24), dt.date(2026, 1, 25))

    assert resolution.manifest_available
    assert "manifest unavailable" not in resolution.summary()


def test_an_empty_range_still_reports_a_genuinely_absent_manifest(
    store_without_manifest: SessionStore,
) -> None:
    """And the note is not dropped just because the range expected nothing."""
    resolution = store_without_manifest.resolve("NIFTY", dt.date(2026, 1, 24), dt.date(2026, 1, 25))

    assert not resolution.manifest_available
    assert "manifest unavailable" in resolution.summary()


def test_start_after_end_is_refused(store: SessionStore) -> None:
    with pytest.raises(ValueError, match="after end"):
        store.resolve("NIFTY", dt.date(2026, 1, 16), dt.date(2026, 1, 5))


def test_a_range_past_the_holiday_tables_horizon_is_refused(store: SessionStore) -> None:
    """Past the last known holiday, silence would mean 'no holidays', not 'unknown'.

    The 2027 end date is coupled to the packaged holiday table: pandas_market_calendars
    5.4.0 stops at 2026-12-25. When a future release extends past 2027-06-30 this test
    goes red reading "DID NOT RAISE", which means "the horizon moved", not "the guard
    broke" — move the date out and re-check ``TradingCalendar.coverage_end``.
    """
    with pytest.raises(CalendarCoverageError, match="holiday data ends"):
        store.resolve("NIFTY", dt.date(2026, 12, 1), dt.date(2027, 6, 30))


# --------------------------------------------------------------------------------------
# The calendar can be wrong in both directions, and both are reported
# --------------------------------------------------------------------------------------


def _plant_session(corpus_root: Path, stem: str) -> Path:
    """Copy an existing fixture session onto ``stem`` — a file for a day nobody expects."""
    planted = corpus_root / "NIFTY" / f"{stem}.parquet"
    planted.write_bytes((corpus_root / "NIFTY" / "2026-01-05.parquet").read_bytes())
    return planted


def test_a_session_on_a_day_the_calendar_calls_closed_is_reported(
    store: SessionStore, corpus_root: Path
) -> None:
    """The Muhurat case: real captured data on a day the holiday table calls closed.

    Resolving only over ``expected`` meant such a file was never looked at, never
    counted, and reachable through no API at all — criterion 1 pointed the other way,
    with real data as the casualty. It is a *result*, symmetric with a missing session.
    """
    _plant_session(corpus_root, "2026-01-26")  # Republic Day, per the packaged table

    resolution = store.resolve("NIFTY", dt.date(2026, 1, 23), dt.date(2026, 1, 28))

    assert dt.date(2026, 1, 26) not in resolution.expected
    assert resolution.unexpected == (dt.date(2026, 1, 26),)
    assert "UNEXPECTED" in resolution.summary()
    assert "2026-01-26" in resolution.summary()
    assert resolution.provenance()["unexpected"] == ["2026-01-26"]
    # Nothing is missing, so it is complete — but a disagreement is not a green tick.
    assert resolution.is_complete
    assert "#b06000" in resolution._repr_html_()


def test_an_unexpected_session_is_handed_over_rather_than_dropped(
    store: SessionStore, corpus_root: Path
) -> None:
    """It is real captured data. Reporting it and then withholding it helps nobody."""
    _plant_session(corpus_root, "2026-01-26")

    sessions = store.resolve("NIFTY", dt.date(2026, 1, 23), dt.date(2026, 1, 28)).sessions()

    dates = [ref.session_date for ref in sessions]
    assert dates == [
        dt.date(2026, 1, 23),
        dt.date(2026, 1, 26),  # the day the calendar calls closed
        dt.date(2026, 1, 27),
        dt.date(2026, 1, 28),
    ]


def test_a_range_of_only_a_closed_day_that_holds_data_is_not_empty(
    store: SessionStore, corpus_root: Path
) -> None:
    """A range expecting nothing, and a range holding nothing, part company here.

    Refusing this range as empty would be the same silent exclusion in a louder costume.
    """
    _plant_session(corpus_root, "2026-01-24")  # a Saturday
    _plant_session(corpus_root, "2026-01-26")  # Republic Day

    resolution = store.resolve("NIFTY", dt.date(2026, 1, 24), dt.date(2026, 1, 26))

    assert resolution.expected == ()
    assert not resolution.is_empty
    assert resolution.unexpected == (dt.date(2026, 1, 24), dt.date(2026, 1, 26))
    assert len(resolution.sessions()) == 2
    assert "2 sessions on disk say otherwise" in resolution.summary()
    assert "2/0 sessions" not in resolution.summary()  # nor any other reader-bug rendering


def test_the_errata_layer_corrects_a_day_the_packaged_table_gets_wrong() -> None:
    """The mechanism, proved with a synthetic entry, and the one real entry separately.

    Testing only the shipped NSE entry would make the single datum its own proof of
    mechanism, so the two are checked apart.
    """
    synthetic = CalendarErratum(
        session_date=dt.date(2026, 1, 20),
        reason="synthetic — mechanism test only",
        source="tests/test_session_store.py",
    )
    corrected = TradingCalendar("NSE", errata=(synthetic,))

    days = corrected.trading_days(dt.date(2026, 1, 19), dt.date(2026, 1, 23))
    assert dt.date(2026, 1, 20) not in days
    assert dt.date(2026, 1, 21) in days
    # The correction is the only difference: without it the day is an ordinary session.
    uncorrected = TradingCalendar("NSE", errata=()).trading_days(
        dt.date(2026, 1, 19), dt.date(2026, 1, 23)
    )
    assert dt.date(2026, 1, 20) in uncorrected
    assert set(uncorrected) - set(days) == {dt.date(2026, 1, 20)}


def test_the_shipped_nse_errata_are_cited_and_applied_by_default() -> None:
    """Every correction carries the evidence for it — an uncited one is a guess."""
    assert dt.date(2026, 1, 15) in {entry.session_date for entry in NSE_ERRATA}
    assert all(entry.reason.strip() and entry.source.strip() for entry in NSE_ERRATA)

    default = TradingCalendar("NSE")
    assert default.errata == NSE_ERRATA
    assert dt.date(2026, 1, 15) not in default.trading_days(
        dt.date(2026, 1, 12), dt.date(2026, 1, 16)
    )


# --------------------------------------------------------------------------------------
# The manifest is an oracle, never a dependency
# --------------------------------------------------------------------------------------


def test_manifest_provenance_is_surfaced_when_available(store: SessionStore) -> None:
    resolution = store.resolve("NIFTY", dt.date(2026, 1, 5), dt.date(2026, 1, 9))

    assert resolution.manifest_available
    by_date = {ref.session_date: ref for ref in resolution.sessions()}
    assert by_date[dt.date(2026, 1, 9)].coverage_pct == pytest.approx(99.4)
    assert by_date[dt.date(2026, 1, 5)].status == "published"
    assert len(by_date[dt.date(2026, 1, 5)].sha256 or "") == 64


def test_resolution_degrades_gracefully_without_a_manifest(
    store_without_manifest: SessionStore,
) -> None:
    resolution = store_without_manifest.resolve("NIFTY", dt.date(2026, 1, 5), dt.date(2026, 1, 16))

    assert not resolution.manifest_available
    assert resolution.missing == ()
    assert resolution.is_complete
    sessions = resolution.sessions()
    assert len(sessions) == 9
    assert all(ref.sha256 is None and ref.status is None for ref in sessions)
    assert "manifest unavailable" in resolution.summary()


def test_a_corrupt_manifest_is_treated_as_absent_not_fatal(
    tmp_path: Path, corpus_root: Path, clock: ManualClock
) -> None:
    broken = tmp_path / "broken.sqlite"
    broken.write_bytes(b"this is not a database")
    store = SessionStore(corpus_root, clock=clock, manifest_path=broken)

    resolution = store.resolve("NIFTY", dt.date(2026, 1, 5), dt.date(2026, 1, 16))

    assert not resolution.manifest_available
    assert len(resolution.sessions()) == 9


def test_a_quarantined_session_is_excluded_and_named(store: SessionStore) -> None:
    """Present-but-untrustworthy is its own category — neither loaded nor silently absent."""
    resolution = store.resolve("NIFTY", dt.date(2026, 2, 2), dt.date(2026, 2, 3))

    assert resolution.missing == ()
    assert resolution.quarantined == (dt.date(2026, 2, 3),)
    assert not resolution.is_complete
    assert "QUARANTINED" in resolution.summary()
    with pytest.raises(MissingSessionsError):
        resolution.sessions()
    # By default the quarantined session stays out even here: accepting a gap is not the
    # same decision as trusting data the producer marked bad.
    accepted = resolution.accept_gaps("carrying on across the quarantined day")
    assert [ref.session_date for ref in accepted] == [dt.date(2026, 2, 2)]


def test_a_quarantined_session_is_reachable_but_only_through_its_own_door(
    store: SessionStore,
) -> None:
    """Excluding it by default must not mean nobody can ever look at it again.

    Re-checking a quarantine decision is a legitimate act, and it needs the file. It gets
    its own flag rather than riding along on any ``accept_gaps`` reason, so a caller who
    wrote "known vendor outage" cannot silently receive data the producer called bad.
    """
    resolution = store.resolve("NIFTY", dt.date(2026, 2, 2), dt.date(2026, 2, 3))

    accepted = resolution.accept_gaps(
        "re-checking the quarantine decision", include_quarantined=True
    )

    assert [ref.session_date for ref in accepted] == [dt.date(2026, 2, 2), dt.date(2026, 2, 3)]
    assert accepted[1].status == "quarantined"
    assert not store.load_session(accepted[1]).empty  # the point: the file is reachable


# --------------------------------------------------------------------------------------
# Criterion 2 — raw is immutable, and what was read is recorded
# --------------------------------------------------------------------------------------


def test_the_store_never_writes_into_the_corpus(tmp_path: Path, clock: ManualClock) -> None:
    """The read-only guarantee, proved by removing write permission rather than by promise.

    Two halves, because they catch different bugs. Read-only **directories** prove
    nothing is *created* — no WAL sibling, no scan index, no cache file; this is the
    check that would have caught a plain ``mode=ro`` sqlite open against a WAL-mode
    manifest. Read-only **files**, plus a content hash either side, prove nothing is
    *mutated in place* — an in-place same-name ``to_parquet`` rewrite or a truncated
    index refresh leaves the directory listing identical and would pass the first half
    alone.
    """
    _build_corpus(tmp_path, with_manifest=True)
    corpus = tmp_path / "datasets" / "dhan"
    manifest = tmp_path / "manifest.sqlite"
    before = sorted(p.name for p in (corpus / "NIFTY").iterdir())
    everything = sorted(p for p in tmp_path.rglob("*"))
    digests = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in everything if p.is_file()}

    # tmp_path holds the manifest, so locking it down is what proves the sqlite open
    # mode cannot leave a -wal/-shm sibling in the producer's directory.
    locked_files = [p for p in everything if p.is_file()]
    locked_dirs = [p for p in everything if p.is_dir()] + [tmp_path]
    locked_dirs.sort(key=lambda p: len(p.parts), reverse=True)
    for path in locked_files:
        path.chmod(stat.S_IRUSR)
    for directory in locked_dirs:
        directory.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        store = SessionStore(corpus, clock=clock, manifest_path=manifest)
        resolution = store.resolve("NIFTY", dt.date(2026, 1, 5), dt.date(2026, 1, 16))
        refs = resolution.sessions()
        assert resolution.manifest_available  # the manifest really was read
        assert not store.load_session(refs[0], verify=True).empty
        assert store.load_refdata(refs[0]).underlier_instruments[0]["TradingSymbol"] == "NIFTY"
        assert sorted(p.name for p in (corpus / "NIFTY").iterdir()) == before
        assert sorted(p.name for p in tmp_path.iterdir()) == ["datasets", "manifest.sqlite"]
    finally:
        for directory in reversed(locked_dirs):
            directory.chmod(stat.S_IRWXU)
        for path in locked_files:
            path.chmod(stat.S_IRUSR | stat.S_IWUSR)

    assert sorted(p for p in tmp_path.rglob("*")) == everything, "a file or directory appeared"
    assert {
        p: hashlib.sha256(p.read_bytes()).hexdigest() for p in everything if p.is_file()
    } == digests, "an existing file was rewritten in place"


def test_loading_returns_the_producers_frame_unmodified(store: SessionStore) -> None:
    """No renaming, no retyping, no reindexing — any of those would be a derivation."""
    ref = store.resolve("NIFTY", dt.date(2026, 1, 5), dt.date(2026, 1, 5)).sessions()[0]

    frame = store.load_session(ref)

    assert list(frame.columns) == [
        "minute_ts", "symbol", "open", "high", "low", "close",
        "iv", "oi", "volume", "spot", "delta", "gamma", "theta", "vega",
    ]  # fmt: skip
    assert frame["minute_ts"].dtype == "int64"
    assert list(frame.index) == list(range(len(frame)))


def test_checksum_verification_catches_a_mutated_session(store: SessionStore) -> None:
    """A changed *number* is caught. The check is over content, not over file bytes."""
    ref = store.resolve("NIFTY", dt.date(2026, 1, 5), dt.date(2026, 1, 5)).sessions()[0]
    assert store.verify_checksum(ref) is not None

    frame = pd.read_parquet(ref.parquet_path)
    frame.loc[0, "close"] = 99999.0
    frame.to_parquet(ref.parquet_path, index=False)

    with pytest.raises(ChecksumMismatchError, match="mutated after"):
        store.load_session(ref, verify=True)


def test_verification_survives_a_reencoded_but_unchanged_file(store: SessionStore) -> None:
    """Re-writing identical data with a different parquet encoding must still verify.

    This is why the producer hashes CSV rather than the file, and hashing the file
    instead would have made this case a false alarm — as it does against the real
    corpus, where a byte-level check disagrees on all 119 sessions.
    """
    ref = store.resolve("NIFTY", dt.date(2026, 1, 5), dt.date(2026, 1, 5)).sessions()[0]
    before = ref.parquet_path.read_bytes()

    pd.read_parquet(ref.parquet_path).to_parquet(ref.parquet_path, index=False, compression="gzip")

    assert ref.parquet_path.read_bytes() != before
    assert store.verify_checksum(ref) == ref.sha256


def test_verification_without_a_manifest_reports_not_checked_rather_than_pass(
    store_without_manifest: SessionStore,
) -> None:
    ref = store_without_manifest.resolve(
        "NIFTY", dt.date(2026, 1, 5), dt.date(2026, 1, 5)
    ).sessions()[0]

    assert store_without_manifest.verify_checksum(ref) is None


def test_every_resolution_records_the_derivation_version_and_the_time(
    store: SessionStore,
) -> None:
    resolution = store.resolve("NIFTY", dt.date(2026, 1, 19), dt.date(2026, 1, 23))

    provenance = resolution.provenance()
    assert provenance["derivation_version"] == DERIVATION_VERSION
    assert provenance["missing"] == ["2026-01-20", "2026-01-21"]
    assert provenance["calendar"] == "NSE"
    assert len(provenance["session_sha256"]) == 3
    assert resolution.resolved_at == PINNED_NOW  # injected clock, no wall-clock leak
    assert json.dumps(provenance)  # a trial log row must be able to hold it


def test_refdata_is_read_verbatim(store: SessionStore) -> None:
    ref = store.resolve("NIFTY", dt.date(2026, 1, 5), dt.date(2026, 1, 5)).sessions()[0]

    refdata = store.load_refdata(ref)

    assert len(refdata.nfo_instruments) == 2
    assert refdata.nfo_instruments[0]["TradingSymbol"] == "NIFTY-16Jun2026-23400-CE"
    assert refdata.nfo_instruments[0]["LotSize"] == 65
    assert refdata.session_date == dt.date(2026, 1, 5)


def test_loading_a_session_that_is_not_there_is_an_error_not_an_empty_frame(
    store: SessionStore,
) -> None:
    ref = store.resolve("NIFTY", dt.date(2026, 1, 5), dt.date(2026, 1, 5)).sessions()[0]
    ref.parquet_path.unlink()

    with pytest.raises(SessionNotFoundError):
        store.load_session(ref)


# --------------------------------------------------------------------------------------
# Configuration and presentation
# --------------------------------------------------------------------------------------


def test_the_corpus_root_is_configuration(
    tmp_path: Path, corpus_root: Path, clock: ManualClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XMAN_RESEARCH_CORPUS_ROOT", str(corpus_root))
    monkeypatch.setenv("XMAN_RESEARCH_MANIFEST_PATH", str(tmp_path / "manifest.sqlite"))

    store = SessionStore(clock=clock)

    assert store.root == corpus_root
    assert store.underlyings() == ("NIFTY",)
    assert store.resolve("NIFTY", dt.date(2026, 1, 5), dt.date(2026, 1, 16)).is_complete


def test_the_gap_is_visible_in_the_repr_and_in_a_notebook(store: SessionStore) -> None:
    resolution = store.resolve("NIFTY", dt.date(2026, 1, 19), dt.date(2026, 1, 23))

    assert "MISSING" in repr(resolution)
    assert "2026-01-20" in repr(resolution)
    assert "#b3261e" in resolution._repr_html_()  # red, in a notebook cell


def test_gaps_are_grouped_by_trading_day_adjacency_not_calendar_days(
    store: SessionStore,
) -> None:
    """A weekend must not split one outage into two, and must not join two into one.

    The fixture is missing Tue 2026-01-20 and Wed 2026-01-21 — one run. Widening the
    range to include the range's other absent stretch must report two runs, not a single
    span implying everything between them is gone.
    """
    one_run = store.resolve("NIFTY", dt.date(2026, 1, 19), dt.date(2026, 1, 23))
    assert one_run.missing_runs() == ((dt.date(2026, 1, 20), dt.date(2026, 1, 21)),)
    assert "in 1 run:" in one_run.summary()

    # 2026-01-20/21 are absent, then everything from 2026-02-04 on is absent.
    wide = store.resolve("NIFTY", dt.date(2026, 1, 19), dt.date(2026, 2, 6))
    runs = wide.missing_runs()
    assert len(runs) == 2
    assert runs[0] == (dt.date(2026, 1, 20), dt.date(2026, 1, 21))
    assert runs[1][0] == dt.date(2026, 2, 4)
    assert "in 2 runs:" in wide.summary()
    # Friday 2026-01-23 to Tuesday 2026-01-27 spans a weekend and Republic Day, and both
    # sides are present, so no run may bridge them.
    assert all(dt.date(2026, 1, 23) not in run for run in runs)


def test_an_unknown_underlying_resolves_to_everything_missing(store: SessionStore) -> None:
    """Not an exception: 'we have no data for this' is a resolution, and a loud one."""
    resolution = store.resolve("BANKNIFTY", dt.date(2026, 1, 5), dt.date(2026, 1, 16))

    assert resolution.missing_count == 9
    assert resolution.found_count == 0


@pytest.fixture(autouse=True)
def _no_ambient_configuration(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Keep the developer's own environment out of every test in this module."""
    for name in ("XMAN_RESEARCH_CORPUS_ROOT", "XMAN_RESEARCH_MANIFEST_PATH"):
        monkeypatch.delenv(name, raising=False)
    yield
