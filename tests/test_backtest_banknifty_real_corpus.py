"""The full chain on BANKNIFTY, against the real corpus.

The engine is `underlying`-parameterised, and this is what makes that a fact rather than a
signature. It resolves a real BANKNIFTY month with a real hole in it, loads a session,
builds the contract universe from the producer's own refdata, and runs the short straddle
over five sessions that contain an expiry — so entry, marking and cash settlement all
happen on an underlying that is not NIFTY.

**Read-only, and skipped cleanly when the corpus is absent.** Nothing here opens a file for
writing except the temporary trial log.

**The window sits inside the in-sample range and nowhere near the holdout.** BANKNIFTY
sessions from 2026-06-01 are sealed (``research/banknifty/README.md``); a test is not a
pre-registered decision and does not get to spend them.
"""

from __future__ import annotations

import datetime as dt
import os
from itertools import pairwise
from pathlib import Path

import pytest

from xman_research import (
    DataWindow,
    HypothesisRecord,
    ResearchSession,
    StaticCodeVersion,
    TrialLog,
)
from xman_research.backtest import (
    BacktestConfig,
    ContractUniverse,
    Feasibility,
    ShortAtmStraddle,
    audit_lot_size,
    epoch_for,
    run_backtest,
)
from xman_research.clock import ManualClock
from xman_research.models.bn_benchmark import HOLDOUT_FIRST_DATE
from xman_research.session_store import DEFAULT_CORPUS_ROOT, MissingSessionsError, SessionStore

CORPUS_ROOT = Path(os.environ.get("XMAN_RESEARCH_CORPUS_ROOT") or DEFAULT_CORPUS_ROOT)
UNDERLYING = "BANKNIFTY"

#: One in-sample month with a known hole: 2024-10-09 is quarantined and was never
#: published, so this range must come through ``accept_gaps`` and not through
#: ``sessions()``. It is also a *weekly*-expiry month — BANKNIFTY's weeklies end on
#: 2024-11-13 — which is what lets a five-session run reach a settlement at all.
MONTH_START = dt.date(2024, 10, 1)
MONTH_END = dt.date(2024, 10, 31)
KNOWN_MISSING = dt.date(2024, 10, 9)

#: Five consecutive published sessions containing the 2024-10-16 expiry.
RUN_START = dt.date(2024, 10, 14)
RUN_END = dt.date(2024, 10, 18)
EXPIRY = dt.date(2024, 10, 16)

#: Every date this module reads is in October 2024, decades of trading days before the
#: sealed holdout. Checked at import so a future edit of the constants above cannot slip
#: past a corpus-absent skip.
assert MONTH_END < HOLDOUT_FIRST_DATE, "this module may not read sealed holdout sessions"

#: What the bars say the lot size was on this contract, against the 30 its refdata
#: declares — the first BANKNIFTY regime in ``BANKNIFTY_LOT_SIZE_EPOCHS``.
MEASURED_LOT_SIZE = 15
DECLARED_LOT_SIZE = 30

GAP_REASON = (
    "BANKNIFTY full-chain test over 2024-10-14..2024-10-18. The point of this run is the "
    "mechanics on a non-NIFTY underlying, not the P&L. Quarantined sessions are excluded, "
    "not read."
)

pytestmark = pytest.mark.skipif(
    not (CORPUS_ROOT / UNDERLYING).is_dir(),
    reason=f"real corpus not present at {CORPUS_ROOT / UNDERLYING}",
)


@pytest.fixture(scope="module")
def store() -> SessionStore:
    return SessionStore(root=CORPUS_ROOT)


@pytest.fixture(scope="module")
def result(store: SessionStore, tmp_path_factory: pytest.TempPathFactory):
    log = TrialLog(
        tmp_path_factory.mktemp("xman_research_bn_e2e") / "research.db",
        clock=ManualClock(dt.datetime(2026, 8, 25, 9, 15, tzinfo=dt.UTC)),
        code_version=StaticCodeVersion("0" * 40, dirty=False),
    )
    session = ResearchSession(log)
    hypothesis = HypothesisRecord(
        name="BN-M1 — BANKNIFTY variance risk premium (full-chain test)",
        mechanism=(
            "Bank-index hedgers pay up for downside protection, so implied variance sits "
            "above subsequently realised variance; a short straddle held to cash "
            "settlement collects the difference."
        ),
        null_hypothesis="The premium is zero or negative after statutory costs.",
        thresholds={"deflated_sharpe": 0.0, "cost_breakeven_multiple": 2.0},
    )
    with session.trial(hypothesis, data_window=DataWindow(RUN_START, RUN_END)) as trial:
        produced = run_backtest(
            trial,
            store=store,
            strategy=ShortAtmStraddle(),
            config=BacktestConfig(underlying=UNDERLYING, gap_reason=GAP_REASON),
        )
    yield produced, session, hypothesis
    session.close()


def test_the_month_resolves_with_its_known_hole(store: SessionStore) -> None:
    """A quarantined session is absent from disk, so the range refuses until it is owned."""
    resolution = store.resolve(UNDERLYING, MONTH_START, MONTH_END)

    assert resolution.underlying == UNDERLYING
    assert KNOWN_MISSING in resolution.missing
    assert not resolution.is_complete
    with pytest.raises(MissingSessionsError):
        resolution.sessions()

    refs = resolution.accept_gaps(GAP_REASON)
    assert refs
    assert all(ref.underlying == UNDERLYING for ref in refs)
    assert KNOWN_MISSING not in {ref.session_date for ref in refs}


def test_a_session_loads_and_its_universe_is_built_from_the_producers_refdata(
    store: SessionStore,
) -> None:
    """The chain the engine walks, walked by hand: parquet -> refdata -> contracts."""
    refs = store.resolve(UNDERLYING, RUN_START, RUN_END).accept_gaps(GAP_REASON)
    ref = refs[0]
    frame = store.load_session(ref)
    refdata = store.load_refdata(ref)

    assert not frame.empty
    assert UNDERLYING in set(frame["symbol"])

    universe = ContractUniverse.from_refdata(refdata, UNDERLYING)
    assert len(universe) > 0
    assert EXPIRY in universe.expiries()
    assert universe.nearest_expiry(ref.session_date) == EXPIRY

    strikes = universe.strikes(EXPIRY)
    assert len(strikes) > 1
    steps = {round(later - earlier) for earlier, later in pairwise(strikes)}
    assert steps == {100}, f"BANKNIFTY's strike step is 100, got {sorted(steps)}"

    assert {contract.lot_size for contract in universe} == {DECLARED_LOT_SIZE}


def test_the_declared_lot_size_is_contradicted_and_the_epoch_names_the_regime(
    store: SessionStore,
) -> None:
    """The corpus fact, on real bars: refdata says 30, the volume says 15."""
    ref = store.resolve(UNDERLYING, RUN_START, RUN_END).accept_gaps(GAP_REASON)[0]
    audit = audit_lot_size(
        session_date=ref.session_date,
        underlying=UNDERLYING,
        frame=store.load_session(ref),
        refdata=store.load_refdata(ref),
    )

    assert audit.declared_lot_sizes == (DECLARED_LOT_SIZE,)
    assert audit.contradicts_declared
    assert audit.best_alternative == MEASURED_LOT_SIZE
    assert audit.best_alternative_share >= 0.99
    assert audit.reference_lot_size == MEASURED_LOT_SIZE

    epoch = epoch_for(EXPIRY, underlying=UNDERLYING)
    assert epoch is not None
    assert epoch.lot_size == MEASURED_LOT_SIZE
    assert "This is a recorded regime" in audit.contradiction_message()


def test_the_straddle_runs_five_sessions_and_settles_on_banknifty(result) -> None:
    """Entry, marking and cash settlement, all on an underlying that is not NIFTY."""
    produced, _, _ = result

    assert produced.underlying == UNDERLYING
    assert produced.sessions_run == 5
    assert len(produced.daily) == 5
    assert produced.config_provenance["gap_reason"] == GAP_REASON

    filled = [fill for fill in produced.fills if fill.filled]
    assert filled, "no entry filled — the strategy never traded on BANKNIFTY"
    # A straddle is two legs, filled together or not at all.
    assert len(filled) % 2 == 0
    assert all(fill.feasibility.verdict is Feasibility.FILLABLE for fill in filled)

    # The window was chosen to contain the 2024-10-16 expiry, so the position it opened
    # before that date has to have been settled by the exchange rather than held out.
    assert produced.settlements, "the run held a position through its expiry and never settled"
    assert all(record.session_date == EXPIRY for record in produced.settlements)
    assert all(record.feasibility.verdict is Feasibility.SETTLED for record in produced.settlements)
    assert all(
        EXPIRY.strftime("%d%b%Y") in record.trading_symbol for record in produced.settlements
    )

    # Having settled, the book is flat and the strategy opens the next weekly cycle — which
    # the window then ends on. That position is *open at run end*, not lost: it is marked at
    # its last price and the run says so, rather than letting the window's edge decide which
    # trades the strategy took.
    #
    # The symbols are a PIN on corpus content, not a derivation: they name the strike the
    # 2024-10-17 ATM lookup selected. A republished corpus that moves that strike fails
    # here, which is the intended signal — the run changed, and the reader should know.
    assert produced.open_at_end == (
        f"{UNDERLYING}-23Oct2024-51800-CE",
        f"{UNDERLYING}-23Oct2024-51800-PE",
    )
    assert any(stamp.startswith("book.open_at_run_end") for stamp in produced.unverified_inputs)


def test_the_run_stamps_what_it_could_not_verify(result) -> None:
    produced, _, _ = result
    stamps = set(produced.unverified_inputs)

    assert any(stamp.startswith("corpus.declared_lot_size_contradicted") for stamp in stamps)
    assert any(stamp.startswith("margin.simplified_approximation") for stamp in stamps)

    audit = produced.data_provenance["lot_size_audit"]
    assert audit["sessions_audited"] == 5
    assert len(audit["sessions_contradicting_declared_lot_size"]) == 5


def test_the_run_landed_as_one_row_in_the_trial_log(result) -> None:
    """The chain's last link: a backtest that produced no logged trial produced nothing."""
    produced, session, hypothesis = result

    trials = session.log.trials(hypothesis.id)
    assert len(trials) == 1
    row = trials[0]
    assert row.trial_id == produced.trial_id
    assert row.metric("sessions_run") == 5
    assert row.metric("fingerprint") == produced.fingerprint()
    assert row.params["strategy"] == "short_atm_straddle"
