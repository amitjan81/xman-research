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
LAST_SESSION = dt.date(2026, 6, 12)

pytestmark = pytest.mark.skipif(not NIFTY.is_dir(), reason=f"real corpus not present at {NIFTY}")


@pytest.fixture
def store() -> SessionStore:
    return SessionStore(
        CORPUS_ROOT,
        clock=ManualClock(datetime(2026, 8, 12, 9, 15, tzinfo=UTC)),
        manifest_path=MANIFEST_PATH,
    )


def test_the_dead_capture_window_is_reported_as_missing(store: SessionStore) -> None:
    """The headline criterion, against the live failure it was written for.

    Capture died on 2026-06-14. A range that runs from inside the corpus to today must
    say so — loudly, with the count — rather than hand back the sessions it happens to
    have and let a Sharpe ratio be computed over a two-month hole.
    """
    resolution = store.resolve("NIFTY", dt.date(2026, 6, 1), dt.date(2026, 8, 12))

    assert not resolution.is_complete
    assert resolution.missing_count > 30, "the known outage is roughly two months of sessions"
    assert min(resolution.missing) > LAST_SESSION
    assert max(resolution.missing) == dt.date(2026, 8, 12)
    assert "MISSING" in resolution.summary()

    with pytest.raises(MissingSessionsError):
        resolution.sessions()

    # The sessions are reachable, but only deliberately and with a reason on the record.
    accepted = resolution.accept_gaps("known vendor outage from 2026-06-14; see ops log")
    assert all(ref.session_date <= LAST_SESSION for ref in accepted)


def test_the_outage_boundary_is_where_the_corpus_actually_stops(store: SessionStore) -> None:
    """Pin the edge: the last captured session resolves, the next trading day does not."""
    ending = store.resolve("NIFTY", LAST_SESSION, LAST_SESSION)
    assert ending.is_complete

    after = store.resolve("NIFTY", LAST_SESSION + dt.timedelta(days=1), dt.date(2026, 8, 12))
    assert after.found_count == 0
    assert after.missing_count == after.expected_count > 0


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

    on_disk = {p.name[: -len(".parquet")] for p in NIFTY.glob("*.parquet")}
    resolved = {ref.session_date.isoformat() for ref in resolution.accept_gaps("cross-check")}
    assert resolved == on_disk, "a parquet file exists for a day the calendar calls closed"

    assert resolution.manifest_available
    assert all(ref.sha256 is not None for ref in resolution.accept_gaps("cross-check"))
    assert all(ref.status == "published" for ref in resolution.accept_gaps("cross-check"))


def test_the_one_gap_inside_the_captured_span_is_reported(store: SessionStore) -> None:
    """There is a hole *inside* the corpus, not only after it.

    2026-01-15 is a Thursday that the NSE calendar calls a trading day, and neither the
    parquet tree nor the producer's manifest has it. The cause is not established here —
    it is either a capture failure or a market holiday the calendar package does not
    carry, and this reader is not the component that can tell. Reporting it is the
    correct behaviour either way; asserting a cause would be a guess dressed as a test.
    """
    resolution = store.resolve("NIFTY", dt.date(2026, 1, 12), dt.date(2026, 1, 16))

    assert resolution.missing == (dt.date(2026, 1, 15),)
    assert not (NIFTY / "2026-01-15.parquet").exists()


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
    corpus — all 119 — because the producer deliberately hashes the frame's CSV
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

    assert resolution.missing == (dt.date(2026, 1, 15),)
    assert resolution.expected_count == resolution.found_count + 1
