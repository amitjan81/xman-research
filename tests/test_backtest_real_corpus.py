"""The full chain against the real corpus: store -> backtest -> a row in the trial log.

This is C5's E2E evidence. It is the only test that touches captured data, and it skips
cleanly when the corpus is absent so the suite still runs on a machine that does not have
it. Everything it reads is read-only — the corpus is irreplaceable and no code in this
package opens a file for writing.

**The gap path is exercised on purpose, not incidentally.** The real corpus has a missing
session inside its span, so a window chosen for being clean would leave the honesty path
untested and would silently start failing the day capture changes. This asks the store
first, and where the range is incomplete it passes a written reason and asserts the reason
reaches the result — which is what a researcher would have to do, and what the trial row
must record about why a number was computed over a partial window.
"""

from __future__ import annotations

import datetime as dt
import os
from pathlib import Path

import pytest

from xman_research import DataWindow, HypothesisRecord, ResearchSession
from xman_research.backtest import (
    BacktestConfig,
    Feasibility,
    ShortAtmStraddle,
    run_backtest,
)
from xman_research.session_store import DEFAULT_CORPUS_ROOT, MissingSessionsError, SessionStore

CORPUS_ROOT = Path(os.environ.get("XMAN_RESEARCH_CORPUS_ROOT") or DEFAULT_CORPUS_ROOT)
UNDERLYING = "NIFTY"

#: A span inside the captured range (2025-12-16 .. 2026-06-12) that covers several weekly
#: expiry cycles, so entries, settlements and rollovers all appear.
START = dt.date(2026, 2, 2)
END = dt.date(2026, 3, 31)

pytestmark = pytest.mark.skipif(
    not (CORPUS_ROOT / UNDERLYING).is_dir(),
    reason=f"real corpus not present at {CORPUS_ROOT / UNDERLYING}",
)


@pytest.fixture(scope="module")
def store() -> SessionStore:
    return SessionStore(root=CORPUS_ROOT)


@pytest.fixture(scope="module")
def gap_reason(store: SessionStore) -> str | None:
    """A written reason when the range has holes, ``None`` when it is clean."""
    resolution = store.resolve(UNDERLYING, START, END)
    if resolution.is_complete:
        return None
    return (
        "C5 full-chain test: the captured range has known holes and the point of this "
        f"run is the mechanics, not the P&L. {resolution.summary()}"
    )


@pytest.fixture(scope="module")
def result(store: SessionStore, gap_reason: str | None):
    import tempfile

    from xman_research import StaticCodeVersion, TrialLog
    from xman_research.clock import ManualClock

    log = TrialLog(
        Path(tempfile.mkdtemp(prefix="xman_research_c5_e2e_")) / "research.db",
        clock=ManualClock(dt.datetime(2026, 8, 12, 9, 15, tzinfo=dt.UTC)),
        code_version=StaticCodeVersion("0" * 40, dirty=False),
    )
    session = ResearchSession(log)
    hypothesis = HypothesisRecord(
        name="H1 — index variance risk premium (C5 full-chain)",
        mechanism=(
            "Index hedgers pay up for downside protection, so implied variance sits above "
            "subsequently realised variance; a short straddle held to cash settlement "
            "collects the difference as compensation for bearing crash risk."
        ),
        null_hypothesis=(
            "The premium is zero or negative after statutory costs and feasibility constraints."
        ),
        thresholds={"deflated_sharpe": 0.0, "cost_breakeven_multiple": 2.0},
        predictors=["iv_30d", "realised_vol_20d"],
    )
    with session.trial(hypothesis, data_window=DataWindow(START, END)) as trial:
        produced = run_backtest(
            trial,
            store=store,
            strategy=ShortAtmStraddle(),
            config=BacktestConfig(underlying=UNDERLYING, gap_reason=gap_reason),
        )
    yield produced, session, hypothesis
    session.close()


def test_the_range_resolves_and_the_gap_decision_is_recorded(result) -> None:
    """Whichever door the range came through, the result says which one it was."""
    produced, _, _ = result

    assert produced.sessions_run > 0
    assert produced.data_provenance["underlying"] == UNDERLYING
    assert produced.config_provenance["gap_reason"] == produced.config_provenance["gap_reason"]
    if produced.data_provenance["missing"]:
        assert produced.config_provenance["gap_reason"]


def test_a_clean_window_still_refuses_without_a_reason(store: SessionStore) -> None:
    """The store's asymmetry survives being wrapped: no reason, no run over a gap.

    Uses a window that certainly has holes — it runs past the end of capture, which is the
    live case: the vendor subscription lapsed on 2026-06-14 and every session after
    2026-06-12 is permanently absent.
    """
    log_window = DataWindow(dt.date(2026, 6, 1), dt.date(2026, 7, 31))
    resolution = store.resolve(UNDERLYING, log_window.start, log_window.end)

    assert not resolution.is_complete
    with pytest.raises(MissingSessionsError):
        resolution.sessions()


def test_the_backtest_traded_settled_and_priced_against_real_data(result) -> None:
    """The loop closes: entries filled, expiries settled, costs charged, all non-trivial."""
    produced, _, _ = result

    assert produced.fills, "no entry was attempted against the real corpus"
    assert produced.settlements, "no expiry settled — the window covers several"
    assert produced.total_costs.total > 0
    assert produced.total_costs.stt > 0
    assert all(
        record.settlement_value > 0 and record.feasibility.verdict is Feasibility.SETTLED
        for record in produced.settlements
    )
    assert len(produced.daily) == produced.sessions_run


def test_every_intent_carries_a_verdict_and_the_counts_add_up(result) -> None:
    produced, _, _ = result
    counts = produced.feasibility_counts()

    assert sum(counts.values()) == len(produced.fills) + len(produced.settlements)
    assert counts["settled"] == len(produced.settlements)


def test_the_run_is_reproducible_against_the_real_corpus(
    result, store: SessionStore, gap_reason: str | None
) -> None:
    """Re-running the same inputs over 119 real sessions must give the identical hash."""
    produced, session, hypothesis = result

    with session.trial(hypothesis, data_window=DataWindow(START, END)) as trial:
        again = run_backtest(
            trial,
            store=store,
            strategy=ShortAtmStraddle(),
            config=BacktestConfig(underlying=UNDERLYING, gap_reason=gap_reason),
        )

    assert again.fingerprint() == produced.fingerprint()


def test_the_trial_log_holds_the_run(result) -> None:
    """The evidence C4 exists to produce: the backtest is in the log, with its metrics."""
    produced, session, hypothesis = result
    rows = session.trials(hypothesis)

    assert rows
    first = rows[0]
    assert first.metrics["fingerprint"] == produced.fingerprint()
    assert first.metrics["sessions_run"] == produced.sessions_run
    assert first.params["strategy"] == "short_atm_straddle"


def test_volume_and_open_interest_are_still_in_units_not_contracts(store: SessionStore) -> None:
    """The participation caps depend on this, and a backfill could silently change it.

    Every non-null volume and open-interest value in a real session divides exactly by the
    contract's lot size. If a future vendor switch starts reporting contracts, the caps
    would be too permissive by a factor of the lot size — 65 times too much size, silently.
    """
    resolution = store.resolve(UNDERLYING, dt.date(2026, 6, 9), dt.date(2026, 6, 9))
    (ref,) = resolution.sessions()
    frame = store.load_session(ref)
    refdata = store.load_refdata(ref)
    lot_sizes = {int(row["LotSize"]) for row in refdata.nfo_instruments}

    assert len(lot_sizes) == 1
    lot_size = lot_sizes.pop()
    options = frame[frame["symbol"] != UNDERLYING]
    volumes = options["volume"].dropna()
    open_interest = options["oi"].dropna()

    assert not volumes.empty
    assert (volumes % lot_size == 0).all()
    assert (open_interest % lot_size == 0).all()
