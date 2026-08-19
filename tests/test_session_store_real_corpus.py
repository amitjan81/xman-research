"""C2 against the real captured corpus — this component's end-to-end evidence.

Everything else in the suite proves the store behaves correctly against a corpus this
repository built for itself. This module is the only place the reader meets the corpus
the *producer* actually wrote, and it is therefore the only test that can catch the
class of bug where both halves of a synthetic fixture share the same wrong assumption.

It skips cleanly when the corpus is absent, so a machine with only the package checked
out still gets a green suite — the skip is honest, not a pass.

**Strictly read-only.** The tree it reads is real captured data that cannot be
re-acquired: the vendor subscription behind it lapsed on 2026-06-14 and every session
since is permanently gone. Nothing here writes, and the store has no code path that
could.

**Nothing in this module pins the corpus's extent, and that is the point.** Three
separate times, assertions here were written against the corpus's boundaries as they
stood on the day — 119 sessions, then 161, then 161 again with a different end — and
three times a backfill or a recovery turned a correct test red without a line of
production code changing. The extent of a data set is not a property of this reader, so
asserting it measures the state of a pipeline rather than the behaviour of the code.

What is asserted instead are **relationships between three artefacts that are produced
independently**: the parquet files the producer wrote, the rows in its manifest, and the
NSE trading calendar. Those three agreeing is a real and falsifiable claim — it breaks
if the calendar is wrong about a holiday, if the producer writes a file for a closed
day, or if the reader resolves a session the manifest never recorded — and it survives
the corpus growing, because growth moves all three together.

**Findings still get pinned; extents do not.** The distinction is the whole lesson. A
measurement about specific historical sessions (December 2025's contradicted lot size,
say, or the 2026-01-15 calendar erratum) is a claim about the world that a test should
state and defend. "There are 161 sessions" is a claim about how much of the world has
been downloaded so far.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest

from xman_research.clock import ManualClock
from xman_research.session_store import MissingSessionsError, SessionStore, content_digest

CORPUS_ROOT = Path("/home/qa/runtime/data/backtest/datasets/dhan")
MANIFEST_PATH = Path("/home/qa/runtime/data/backtest/dhan/manifest.sqlite")
NIFTY = CORPUS_ROOT / "NIFTY"

#: How far past the end of capture the "dead window" tests reach, in calendar days.
#:
#: **Derived from the corpus, never from the wall clock or a fixed date.** The horizon is
#: this many days after the last session actually on disk, and the injected clock is set
#: to it, so the range being asked about is always genuinely past the end of capture no
#: matter how far capture has got. Seven weeks because that is comfortably more than any
#: holiday cluster in the NSE calendar, so the window always contains trading days and the
#: outage it describes is never empty by accident.
HORIZON_DAYS = 49

#: **These tests assume the corpus's tail is clean, and will redden if it stops being so.**
#: Recorded rather than fixed, because each failure would be flagging a real defect in the
#: data — a confusing red is the right outcome, an amber-proofed green is not. Three
#: standing assumptions, so that whoever meets the failure recognises it:
#:
#: 1. ``test_the_dead_capture_window_is_reported_as_missing`` resolves from 14 days before
#:    the last captured session and asserts the outage is *one unbroken run*. A capture
#:    hole inside those 14 days makes it two runs and fails that assertion.
#: 2. ``test_the_continuously_captured_tail_has_no_holiday_gaps`` derives its stretch from
#:    the day after the last hole and requires at least 20 sessions of it. A hole landing
#:    within the final 20 sessions shortens the tail below the floor and fails.
#: 3. Every fixture taking ``horizon`` resolves ``HORIZON_DAYS`` past the end of capture,
#:    and the packaged NSE holiday table ends **2026-12-25** — beyond that
#:    :class:`CalendarCoverageError` refuses the range rather than guessing. So once
#:    capture extends past roughly 2026-11-06 these tests need the calendar refreshed to
#:    cover 2027, whose first NSE holiday is Republic Day on 2027-01-26.

#: The one genuine hole inside the December-2025-onward capture, and why it is not one.
#: A finding about a specific date, so it is pinned — see the module docstring on the
#: difference between a finding and an extent.
NSE_ELECTION_CLOSURE = dt.date(2026, 1, 15)

pytestmark = pytest.mark.skipif(not NIFTY.is_dir(), reason=f"real corpus not present at {NIFTY}")


def _sessions_on_disk() -> tuple[dt.date, ...]:
    """Every session the producer actually wrote, read off disk at collection time."""
    return tuple(
        sorted(dt.date.fromisoformat(p.name[: -len(".parquet")]) for p in NIFTY.glob("*.parquet"))
    )


@pytest.fixture(scope="module")
def on_disk() -> tuple[dt.date, ...]:
    dates = _sessions_on_disk()
    assert dates, f"the corpus directory {NIFTY} exists but holds no parquet files"
    return dates


@pytest.fixture(scope="module")
def horizon(on_disk: tuple[dt.date, ...]) -> dt.date:
    """A date safely past the end of capture, derived from where capture actually got to."""
    return on_disk[-1] + dt.timedelta(days=HORIZON_DAYS)


@pytest.fixture
def store(horizon: dt.date) -> SessionStore:
    """The store, with its clock pinned to the horizon.

    The clock is injected rather than read from the machine: a store that asks "what
    should exist by now?" against the real time of day would give a different answer every
    run, and the sessions it expects are exactly what these tests measure.
    """
    clock = ManualClock(datetime(horizon.year, horizon.month, horizon.day, 9, 15, tzinfo=UTC))
    return SessionStore(CORPUS_ROOT, clock=clock, manifest_path=MANIFEST_PATH)


def test_the_dead_capture_window_is_reported_as_missing(
    store: SessionStore, on_disk: tuple[dt.date, ...], horizon: dt.date
) -> None:
    """The headline criterion, against the live failure it was written for.

    Capture stops somewhere. A range that runs from inside the corpus to past that point
    must say so — loudly, with the count — rather than hand back the sessions it happens
    to have and let a Sharpe ratio be computed over the hole.

    The window is anchored to where capture actually stopped, so this keeps testing the
    same behaviour as the corpus grows instead of testing last month's boundary.

    **Assumption 1 above:** the "one unbroken outage" assertion holds only while no capture
    hole falls in the 14 days before the last captured session.
    """
    last_captured = on_disk[-1]
    resolution = store.resolve("NIFTY", last_captured - dt.timedelta(days=14), horizon)

    assert not resolution.is_complete
    assert resolution.missing_count > 0
    assert resolution.missing_runs() == (resolution.missing,), "one unbroken outage"
    assert min(resolution.missing) > last_captured, "a captured session was reported missing"
    assert max(resolution.missing) <= horizon

    # Every missing day is a day the calendar calls open and the producer did not write.
    # This is what stops the criterion degrading into "the calendar surprised us".
    for day in resolution.missing:
        assert not (NIFTY / f"{day.isoformat()}.parquet").exists()
    assert "MISSING" in resolution.summary()

    with pytest.raises(MissingSessionsError):
        resolution.sessions()

    # The sessions are reachable, but only deliberately and with a reason on the record.
    accepted = resolution.accept_gaps("capture stops at the end of the corpus; see ops log")
    assert accepted, "the range covers captured sessions, so accepting gaps must yield some"
    assert all(ref.session_date <= last_captured for ref in accepted)


def test_the_outage_boundary_is_where_the_corpus_actually_stops(
    store: SessionStore, on_disk: tuple[dt.date, ...], horizon: dt.date
) -> None:
    """Pin the edge: the last captured session resolves, everything after it does not."""
    last_captured = on_disk[-1]

    ending = store.resolve("NIFTY", last_captured, last_captured)
    assert ending.is_complete

    after = store.resolve("NIFTY", last_captured + dt.timedelta(days=1), horizon)
    assert after.found_count == 0
    assert after.missing_count == after.expected_count > 0


def test_the_reader_agrees_with_the_producer_and_the_calendar(
    store: SessionStore, on_disk: tuple[dt.date, ...]
) -> None:
    """Reader vs producer vs calendar, over the whole corpus — the cross-check a fixture cannot do.

    Three independently produced artefacts have to tell one story: the parquet files, the
    producer's manifest, and the NSE calendar. A disagreement means one of the three is
    wrong, and it is worth failing over rather than discovering downstream.

    **The corpus is no longer whole in its interior, and this test says so rather than
    asserting it away.** It now carries a historical backfill reaching to 2021 alongside
    the original December-2025-onward capture, and the historical portion has genuine
    holes. So the claim here is the arithmetic one — every file resolves, every resolved
    session has a manifest row, no file exists for a day the market was shut, and found
    plus missing accounts for everything the calendar expected — not the much stronger and
    now false claim that nothing is missing.
    """
    resolution = store.resolve("NIFTY", on_disk[0], on_disk[-1])

    # accept_gaps, not sessions(): the span has real holes and reaching for sessions()
    # would raise. The reason is written because the store requires one, and because a
    # scan over "whatever was captured" is exactly what this test means to do.
    refs = resolution.accept_gaps(
        "reader/producer/calendar cross-check: the comparison is over whatever the "
        "producer wrote, and a hole in the calendar cannot hide a disagreement in the "
        "sessions that do exist"
    )

    assert tuple(ref.session_date for ref in refs) == on_disk, "reader and producer disagree"
    assert resolution.unexpected == (), "a parquet file exists for a day the calendar calls closed"
    assert resolution.found_count + resolution.missing_count == resolution.expected_count
    assert set(resolution.missing).isdisjoint(on_disk), "a session on disk was called missing"

    assert resolution.manifest_available
    assert all(ref.sha256 is not None for ref in refs), "a resolved session has no manifest row"
    assert all(ref.status == "published" for ref in refs)


def test_the_apparent_gap_inside_the_captured_span_was_a_calendar_error(
    store: SessionStore,
) -> None:
    """2026-01-15 is absent from the corpus because NSE was shut, not because capture failed.

    It read as the one hole inside the corpus for as long as the cause was unknown. It is
    now established: the exchange was closed for the Maharashtra municipal corporation
    elections and pandas_market_calendars 5.4.0 does not carry the date. NSE_ERRATA
    corrects it, with the citation attached.

    Reporting a gap that is not one is not a harmless conservatism — it teaches the
    researcher to type an accept_gaps reason without reading the report, which is exactly
    how the gate this component exists to provide stops working.
    """
    resolution = store.resolve("NIFTY", dt.date(2026, 1, 12), dt.date(2026, 1, 16))

    assert not (NIFTY / f"{NSE_ELECTION_CLOSURE.isoformat()}.parquet").exists()
    assert NSE_ELECTION_CLOSURE not in resolution.expected
    assert resolution.missing == ()
    assert resolution.is_complete
    assert [ref.session_date for ref in resolution.sessions()] == [
        dt.date(2026, 1, 12),
        dt.date(2026, 1, 13),
        dt.date(2026, 1, 14),
        dt.date(2026, 1, 16),
    ]


def test_a_clean_range_inside_the_corpus_resolves_and_loads(store: SessionStore) -> None:
    """A real session round-trips: resolve, checksum against the manifest, load, refdata."""
    resolution = store.resolve("NIFTY", dt.date(2026, 5, 4), dt.date(2026, 5, 8))

    assert resolution.is_complete
    sessions = resolution.sessions()
    assert len(sessions) == 5

    frame = store.load_session(sessions[0], verify=True)
    assert list(frame.columns) == [
        "minute_ts", "symbol", "open", "high", "low", "close",
        "iv", "oi", "volume", "spot", "delta", "gamma", "theta", "vega",
    ]  # fmt: skip
    assert len(frame) > 1000
    assert "NIFTY" in set(frame["symbol"])

    refdata = store.load_refdata(sessions[0])
    assert len(refdata.nfo_instruments) > 0
    assert refdata.underlier_instruments[0]["TradingSymbol"] == "NIFTY"


def test_the_manifest_digest_is_over_content_not_over_the_parquet_bytes(
    store: SessionStore,
) -> None:
    """Pin the contract that the obvious implementation gets wrong.

    Hashing the parquet file disagrees with the manifest on **every** session in the
    corpus, because the producer deliberately hashes the frame's CSV rendering, so that a
    file rewritten by a newer pyarrow with identical data still verifies. This test fails
    if either side of that contract moves, including if a pandas upgrade changes CSV float
    formatting under us.
    """
    ref = store.resolve("NIFTY", dt.date(2026, 5, 4), dt.date(2026, 5, 4)).sessions()[0]
    frame = store.load_session(ref)

    assert content_digest(frame) == ref.sha256
    assert hashlib.sha256(ref.parquet_path.read_bytes()).hexdigest() != ref.sha256


def test_the_continuously_captured_tail_has_no_holiday_gaps(
    store: SessionStore, on_disk: tuple[dt.date, ...]
) -> None:
    """Over the stretch capture ran without interruption, the only gaps are real holidays.

    If the calendar were wrong about NSE holidays, this range would report every holiday it
    did not know about as a missing session — the exact way criterion 1 degrades into noise
    nobody reads. That claim can only be made where capture is genuinely continuous, so the
    stretch is *derived*: it starts the day after the last real hole and runs to the end of
    the corpus. Backfilling a hole lengthens it; nothing makes it go stale.
    """
    whole = store.resolve("NIFTY", on_disk[0], on_disk[-1])
    tail_start = max(whole.missing) + dt.timedelta(days=1) if whole.missing else on_disk[0]

    resolution = store.resolve("NIFTY", tail_start, on_disk[-1])

    assert resolution.missing == ()
    assert resolution.is_complete
    assert resolution.expected_count == resolution.found_count > 0
    # The tail must be a meaningful stretch, or this test passes on a single session and
    # says nothing about the calendar at all. **Assumption 2 above:** a future hole inside
    # the last 20 sessions fails this line, and that failure is a real data defect rather
    # than a stale fixture — do not relax the floor to make it green.
    assert resolution.found_count >= 20, "the continuously captured tail is too short to test"


def test_the_whole_span_accounts_for_every_session_it_expected(
    store: SessionStore, on_disk: tuple[dt.date, ...], horizon: dt.date
) -> None:
    """The headline numbers, in one place — as arithmetic rather than as remembered totals.

    Everything between the first captured session and the horizon, which is the range a
    researcher asking "what do we have?" would actually type. The dead window at the end
    is one unbroken run, and every session in it is genuinely absent from disk.
    """
    resolution = store.resolve("NIFTY", on_disk[0], horizon)

    assert resolution.found_count == len(on_disk)
    assert resolution.expected_count == resolution.found_count + resolution.missing_count
    assert resolution.unexpected == ()

    dead_window = tuple(day for day in resolution.missing if day > on_disk[-1])
    assert dead_window, "the horizon is past the end of capture, so the window cannot be empty"
    assert resolution.missing_runs()[-1] == dead_window, "the outage at the end is one run"
    assert f"{dead_window[0].isoformat()}..{dead_window[-1].isoformat()}" in resolution.summary()
    assert f"({len(dead_window)} days)" in resolution.summary()
