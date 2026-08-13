"""C2 against the real captured corpus — this component's end-to-end evidence.

Everything else in the suite proves the store behaves correctly against a corpus this
repository built for itself. This module is the only place the reader meets the corpus
the *producer* actually wrote, and it is therefore the only test that can catch the
class of bug where both halves of a synthetic fixture share the same wrong assumption.

It skips cleanly when the corpus is absent, so a machine with only the package checked
out still gets a green suite — the skip is honest, not a pass.

**Strictly read-only.** The tree it reads is real captured data. Nothing here writes, and
the store has no code path that could.

**The vendor outage was backfilled on 2026-08-13**, and several assertions in this file
were pinned to it. They have been re-pointed at what is true now rather than deleted: the
corpus ran 2025-12-16..2026-06-12 with 42 sessions missing to a lapsed subscription, and
now runs 2025-12-16..2026-08-12 with none. The *guarantees* those tests bought — that a
hole is reported precisely, refused by default, and reachable only against a written
reason — did not go away with the hole, and a gap test with no gap left to find is worth
nothing. They live on the synthetic corpus in ``tests/test_session_store.py``
(``test_range_spanning_a_gap_reports_the_missing_days``,
``test_sessions_refuses_while_a_gap_exists``,
``test_gaps_can_be_accepted_but_only_with_a_written_reason``,
``test_gaps_are_grouped_by_trading_day_adjacency_not_calendar_days``), where a hole can be
constructed on demand and therefore stays covered however complete the real corpus
becomes. What is pinned *here* is the thing only the real corpus can say: that it is
complete, and where it stops.
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

# The corpus's own boundaries, as they stand.
FIRST_SESSION = dt.date(2025, 12, 16)
LAST_SESSION = dt.date(2026, 8, 12)
TODAY = dt.date(2026, 8, 12)

# Counts, re-derived rather than remembered: 161 parquet files and 161 producer manifest
# rows between FIRST_SESSION and LAST_SESSION, against 161 calendar sessions once
# NSE_ERRATA removes 2026-01-15 (pandas_market_calendars 5.4.0 offers 162).
#
# Was 119 + a 42-session hole until the 2026-08-13 backfill landed the outage window.
# 119 + 42 = 161, and the arithmetic is the point: the sessions that arrived are exactly
# the ones this file used to assert were missing, so the same total now has to be reached
# with nothing missing at all.
CAPTURED_SESSIONS = 161
BACKFILLED_SESSIONS = 42
FIRST_BACKFILLED = dt.date(2026, 6, 15)

pytestmark = pytest.mark.skipif(not NIFTY.is_dir(), reason=f"real corpus not present at {NIFTY}")


@pytest.fixture
def store() -> SessionStore:
    return SessionStore(
        CORPUS_ROOT,
        clock=ManualClock(datetime(2026, 8, 12, 9, 15, tzinfo=UTC)),
        manifest_path=MANIFEST_PATH,
    )


def test_the_backfilled_outage_window_is_now_whole(store: SessionStore) -> None:
    """The exact window this file used to assert was dead, asserted present.

    Kept, rather than deleted with the outage, because it is the only assertion that
    notices a *regression* of the backfill. If those 42 sessions were ever removed,
    quarantined or republished under a different status, the range that most obviously
    depends on them would silently go back to being a hole — and every test that merely
    counts the corpus would still pass, because the count would still be self-consistent.

    The gap-reporting machinery this used to exercise is covered on the synthetic corpus;
    see the module docstring for the four tests that hold it.
    """
    resolution = store.resolve("NIFTY", dt.date(2026, 6, 1), TODAY)

    assert resolution.is_complete
    assert resolution.missing == ()
    assert "MISSING" not in resolution.summary()

    # sessions(), not accept_gaps(): there is nothing to accept, and reaching for the gap
    # door would misrepresent a complete range as a partial one.
    dates = [ref.session_date for ref in resolution.sessions()]
    assert dates[-1] == LAST_SESSION
    backfilled = [day for day in dates if day >= FIRST_BACKFILLED]
    assert len(backfilled) == BACKFILLED_SESSIONS


def test_the_corpus_boundary_is_where_the_corpus_actually_stops(store: SessionStore) -> None:
    """Pin the edge: the last captured session resolves, the next trading day does not.

    The edge moved from 2026-06-12 to 2026-08-12; the guarantee did not. The store does
    not clamp a range to its clock, so asking past the end is a legitimate question with a
    loud answer, and that is what makes this the assertion that catches the corpus
    silently growing or shrinking under a fixed set of counts.
    """
    ending = store.resolve("NIFTY", LAST_SESSION, LAST_SESSION)
    assert ending.is_complete

    after = store.resolve(
        "NIFTY", LAST_SESSION + dt.timedelta(days=1), LAST_SESSION + dt.timedelta(days=8)
    )
    assert after.found_count == 0
    assert after.missing_count == after.expected_count > 0
    with pytest.raises(MissingSessionsError):
        after.sessions()


def test_the_reader_agrees_with_the_producer_over_the_captured_span(
    store: SessionStore,
) -> None:
    """Reader vs producer, over the whole corpus — the cross-check a fixture cannot do.

    Every parquet file on disk is a day the NSE calendar calls a trading day (no file
    exists for a day the market was shut), and the manifest has a row for every file
    the reader resolved. A disagreement here means the calendar, the producer or this
    reader is wrong, and it is worth failing over rather than discovering downstream.
    """
    resolution = store.resolve("NIFTY", FIRST_SESSION, LAST_SESSION)

    # sessions(), not accept_gaps(): over the captured span there is now nothing to accept,
    # and reaching for the gap door would misrepresent a complete range as a partial one.
    sessions = resolution.sessions()
    on_disk = {p.name[: -len(".parquet")] for p in NIFTY.glob("*.parquet")}
    assert {ref.session_date.isoformat() for ref in sessions} == on_disk
    assert resolution.unexpected == (), "a parquet file exists for a day the calendar calls closed"
    assert len(sessions) == CAPTURED_SESSIONS

    assert resolution.manifest_available
    assert all(ref.sha256 is not None for ref in sessions)
    assert all(ref.status == "published" for ref in sessions)


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

    assert not (NIFTY / "2026-01-15.parquet").exists()
    assert dt.date(2026, 1, 15) not in resolution.expected
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
    corpus — all 161 — because the producer deliberately hashes the frame's CSV
    rendering, so that a file rewritten by a newer pyarrow with identical data still
    verifies. This test fails if either side of that contract moves, including if a
    pandas upgrade changes CSV float formatting under us.
    """
    ref = store.resolve("NIFTY", dt.date(2026, 5, 4), dt.date(2026, 5, 4)).sessions()[0]
    frame = store.load_session(ref)

    assert content_digest(frame) == ref.sha256
    assert hashlib.sha256(ref.parquet_path.read_bytes()).hexdigest() != ref.sha256


def test_weekends_and_real_holidays_are_never_counted_as_capture_gaps(
    store: SessionStore,
) -> None:
    """Over the whole captured span, the only reported gap is the genuine one.

    If the calendar were wrong about NSE holidays, this range would report every
    holiday it did not know about as a missing session — the exact way criterion 1
    degrades into noise nobody reads.
    """
    resolution = store.resolve("NIFTY", FIRST_SESSION, LAST_SESSION)

    assert resolution.missing == ()
    assert resolution.expected_count == resolution.found_count == CAPTURED_SESSIONS
    assert resolution.is_complete


def test_the_whole_span_reports_a_complete_corpus_and_nothing_spurious(
    store: SessionStore,
) -> None:
    """The headline numbers, in one place: 161 found of 161 expected, nothing missing.

    Everything between the first captured session and today, which is the range a
    researcher asking "what do we have?" would actually type. It read "119 found of 161
    expected, 42 missing in 1 run" until the backfill.

    ``unexpected`` is the assertion that keeps this honest in the other direction. A
    completeness check alone would pass if the backfill had written files the exchange
    calendar calls closed — the corpus would be *more* than complete, which is a producer
    bug, not a success. Found, expected and unexpected have to agree simultaneously.
    """
    resolution = store.resolve("NIFTY", FIRST_SESSION, TODAY)

    assert resolution.expected_count == CAPTURED_SESSIONS == 161
    assert resolution.found_count == CAPTURED_SESSIONS
    assert resolution.missing_count == 0
    assert resolution.missing_runs() == ()
    assert resolution.unexpected == ()
    assert resolution.is_complete
    assert "MISSING" not in resolution.summary()
