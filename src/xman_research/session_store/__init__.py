"""MVP component C2 — the session store.

The reader side of the corpus the sibling ``xman`` repository captures. Its headline
guarantee: **a range resolves to files *and* to the trading days that should have been
there, and you cannot get the files without having been shown the gaps.**

Typical use::

    from datetime import date
    from xman_research.session_store import SessionStore

    store = SessionStore()                       # or SessionStore(root=..., clock=...)
    res = store.resolve("NIFTY", date(2026, 1, 5), date(2026, 8, 12))
    print(res)                                   # the gap report, always
    for ref in res.sessions():                   # refuses while a gap exists
        frame = store.load_session(ref)

Kept out on purpose, per spec §7: no versioning, no as-of queries, no bitemporal
storage. The store holds current data and re-runs regenerate.

This subpackage is C2's whole footprint. It is deliberately **not** re-exported from
``xman_research/__init__.py`` — that file belongs to C4 — so the two components share
no file that a merge has to reconcile by hand.
"""

from xman_research.session_store.manifest import (
    PUBLISHED,
    QUARANTINED,
    ManifestReader,
    ManifestRow,
)
from xman_research.session_store.store import (
    DEFAULT_CORPUS_ROOT,
    DEFAULT_MANIFEST_PATH,
    DERIVATION_VERSION,
    ChecksumMismatchError,
    EmptyRangeError,
    MissingSessionsError,
    RefData,
    Resolution,
    SessionNotFoundError,
    SessionRef,
    SessionStore,
    SessionStoreError,
    content_digest,
)
from xman_research.session_store.trading_calendar import (
    NSE_CALENDAR,
    CalendarCoverageError,
    TradingCalendar,
)

__all__ = [
    "DEFAULT_CORPUS_ROOT",
    "DEFAULT_MANIFEST_PATH",
    "DERIVATION_VERSION",
    "NSE_CALENDAR",
    "PUBLISHED",
    "QUARANTINED",
    "CalendarCoverageError",
    "ChecksumMismatchError",
    "EmptyRangeError",
    "ManifestReader",
    "ManifestRow",
    "MissingSessionsError",
    "RefData",
    "Resolution",
    "SessionNotFoundError",
    "SessionRef",
    "SessionStore",
    "SessionStoreError",
    "TradingCalendar",
    "content_digest",
]
