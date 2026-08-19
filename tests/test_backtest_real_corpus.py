"""The full chain against the real corpus: store -> backtest -> a row in the trial log.

This is C5's E2E evidence. It is the only test that touches captured data, and it skips
cleanly when the corpus is absent so the suite still runs on a machine that does not have
it. Everything it reads is read-only — the corpus is irreplaceable and no code in this
package opens a file for writing.

**The gap path is exercised on purpose, not incidentally** — but not by this window.
Measured against the calendar, every window inside the captured range resolves complete,
including the one this file runs; the corpus has no hole in its interior, only an end. So
the fixture asks the store first and passes a written reason only if the range is
incomplete, and the assertion pins whichever answer it got — ``None`` here — rather than
assuming the interesting one.

The wrapper's refusal path is held on the synthetic corpus, by
``test_backtest_engine.py::test_a_gap_can_be_accepted_only_against_a_written_reason``,
which builds a hole rather than borrowing one. It used to be held here instead, by a
window running into the 2026-06-15..2026-08-12 vendor outage — and the 2026-08-13 backfill
filled that outage in, which is exactly why a refusal test must not depend on the real
corpus staying broken. What is left here is the fact only the real corpus can state:
that the window is now whole, and that asking past its end still refuses.
"""

from __future__ import annotations

import datetime as dt
import os
from pathlib import Path

import pytest

from xman_research import DataWindow, HypothesisRecord, ResearchSession
from xman_research.backtest import (
    NIFTY_LOT_SIZE_EPOCHS,
    BacktestConfig,
    Feasibility,
    LotSizeAudit,
    ShortAtmStraddle,
    audit_lot_size,
    epoch_for,
    run_backtest,
)
from xman_research.session_store import DEFAULT_CORPUS_ROOT, SessionStore

CORPUS_ROOT = Path(os.environ.get("XMAN_RESEARCH_CORPUS_ROOT") or DEFAULT_CORPUS_ROOT)
UNDERLYING = "NIFTY"

#: A span inside the captured range (2025-12-16 .. 2026-08-12) that covers several weekly
#: expiry cycles, so entries, settlements and rollovers all appear.
#:
#: **It deliberately crosses 1 April 2026**, the date the STT rates rise from 0.1% to
#: 0.15% on premium and from 0.125% to 0.15% on exercise. A window that stopped in March
#: would exercise the dated-schedule machinery only against a unit fixture, which is the
#: arrangement that lets a date-boundary bug live in the table and pass the suite. Here
#: the boundary is crossed by real sessions carrying real turnover, so both regimes are
#: charged in the same run and the E2E numbers below reflect the change.
#:
#: It also starts after 2025-12-30, and still should: the December sessions carry a lot
#: size their own refdata contradicts. That no longer refuses the run — it stamps it — so
#: the reason is now about keeping this window's numbers clean rather than about being
#: allowed to compute them at all. See :mod:`xman_research.backtest.lot_size`.
START = dt.date(2026, 2, 2)
END = dt.date(2026, 4, 30)

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


def test_the_range_resolves_and_the_gap_decision_is_recorded(
    result, gap_reason: str | None
) -> None:
    """Whichever door the range came through, the result says which one it was."""
    produced, _, _ = result

    assert produced.sessions_run > 0
    assert produced.data_provenance["underlying"] == UNDERLYING

    # The original form of this assertion was `gap_reason == gap_reason`, true of every
    # possible value. Comparing the recorded field against the fixture is better but still
    # weak on its own -- the fixture is what built the result, so it cannot distinguish a
    # faithfully recorded reason from an echo. The discriminating check is against the
    # *literal* expected content, and against the independent `missing` field: a holey
    # range must carry a written reason, and a clean one must carry none.
    recorded = produced.config_provenance["gap_reason"]
    assert recorded == gap_reason
    if produced.data_provenance["missing"]:
        assert recorded is not None, "a range with holes ran without a recorded reason"
        assert "C5 full-chain test" in recorded
        assert "the mechanics, not the P&L" in recorded
    else:
        assert recorded is None, "a complete range recorded a gap reason it did not need"


def test_the_backfilled_window_is_whole(store: SessionStore) -> None:
    """The one fact here that only the real corpus can state: that window is now whole.

    Was ``test_a_holey_window_refuses_without_a_reason``. Its window — June into July 2026
    — was chosen because it certainly had holes, the vendor subscription having lapsed on
    2026-06-14. The 2026-08-13 backfill landed those 42 sessions, so the window resolves
    complete and the old assertion is simply false about the world.

    **A second, subtler version of the same mistake has also been removed.** The
    replacement kept a refusal assertion here, resolving ``CAPTURE_END + 1 .. +8`` and
    describing it as "the one hole no backfill can ever fill ... sessions that have not
    happened yet". Seven of those eight sessions had happened and were captured; the window
    was incomplete only because its far end was tomorrow, and it passed on a one-day
    margin. A guarantee that depends on the real corpus's shape is not a guarantee, even
    when the shape it depends on is "the future has not arrived".

    So the refusal now lives entirely on the synthetic corpus, where the hole is
    constructed —
    ``test_backtest_engine.py::test_a_gap_can_be_accepted_only_against_a_written_reason``
    for the partial case and
    ``::test_a_window_entirely_past_the_end_of_the_corpus_refuses`` for the total one.
    What is left here is only what a synthetic fixture cannot say.
    """
    filled = store.resolve(UNDERLYING, dt.date(2026, 6, 1), dt.date(2026, 7, 31))
    assert filled.is_complete
    assert filled.missing == ()
    assert len(filled.sessions()) == filled.expected_count > 0


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
    """Re-running the same inputs over the same real sessions must give the identical hash."""
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


#: The ten sessions whose bars contradict their own refdata. Written out rather than
#: derived so the test states the expected answer and the scan has to reproduce it: a
#: check that compares the corpus against itself cannot notice the corpus changing.
DECEMBER_LOT_75_SESSIONS = (
    dt.date(2025, 12, 16),
    dt.date(2025, 12, 17),
    dt.date(2025, 12, 18),
    dt.date(2025, 12, 19),
    dt.date(2025, 12, 22),
    dt.date(2025, 12, 23),
    dt.date(2025, 12, 24),
    dt.date(2025, 12, 26),
    dt.date(2025, 12, 29),
    dt.date(2025, 12, 30),
)


#: The scan's range is **the whole corpus, read off disk**, not a pinned window.
#:
#: It was ``2025-12-16..2026-08-12``, 161 sessions, and before that 119 — a constant that
#: had to be edited by hand every time the corpus grew, and that silently excluded whatever
#: had arrived since. What it was excluding by the time anyone looked was the entire
#: 2021-2025 historical backfill: 1,072 sessions carrying the lot-25 and lot-50 epochs this
#: module exists to describe, unexamined behind a number nobody thought to change.
#:
#: Deriving it costs about 3.5 minutes of scan on the current corpus and removes the
#: failure mode permanently. Growth widens the scan instead of hiding from it.
def _corpus_sessions() -> tuple[dt.date, ...]:
    """Every session the producer wrote, newest corpus included."""
    root = CORPUS_ROOT / UNDERLYING
    return tuple(
        sorted(dt.date.fromisoformat(p.name[: -len(".parquet")]) for p in root.glob("*.parquet"))
    )


@pytest.fixture(scope="module")
def corpus_audits(store: SessionStore) -> tuple[LotSizeAudit, ...]:
    """Every session in the corpus, audited once. The scan the old test did not do."""
    on_disk = _corpus_sessions()
    resolution = store.resolve(UNDERLYING, on_disk[0], on_disk[-1])
    refs = resolution.accept_gaps(
        "lot-size audit: the scan is over whatever was captured, and a hole in the "
        "calendar cannot hide a lot-size contradiction in the sessions that exist"
    )
    return tuple(
        audit_lot_size(
            session_date=ref.session_date,
            underlying=UNDERLYING,
            frame=store.load_session(ref),
            refdata=store.load_refdata(ref),
        )
        for ref in refs
    )


def test_volume_is_in_units_not_contracts_on_every_session(
    corpus_audits: tuple[LotSizeAudit, ...],
) -> None:
    """The property the old single-session test meant to protect, checked corpus-wide.

    "Units, not contracts" is the claim that a volume figure is a share count and so is a
    multiple of *a* lot size. If a vendor switch started reporting contracts, the values
    would be small integers divisible by nothing in particular and every participation cap
    would be too permissive by a factor of the lot size. That claim does hold everywhere —
    it is the stronger claim, that the lot size is the one the refdata *declares*, that
    fails, and it fails on ten sessions the old test never looked at.
    """
    assert len(corpus_audits) == len(_corpus_sessions()) > 1_000
    for audit in corpus_audits:
        supported = max(audit.declared_volume_share, audit.best_alternative_share)
        assert supported >= 0.99, (
            f"{audit.session_date}: no candidate lot size explains its volume "
            f"(best {supported:.1%}) — the units-vs-contracts convention may have changed"
        )


def test_the_december_2025_sessions_contradict_their_own_declared_lot_size(
    corpus_audits: tuple[LotSizeAudit, ...],
) -> None:
    """The finding, asserted as a finding: exactly ten sessions, declared 65, actually 75.

    This is the test that must fail if anyone "fixes" the tripwire by relaxing it, and the
    test that will fail — correctly, loudly — on the day the producer regenerates December's
    refdata. At that point the epoch record in ``lot_size.py`` becomes history rather than
    a live defect, and this assertion is the thing that says so.
    """
    contradicted = {a.session_date for a in corpus_audits if a.contradicts_declared}

    # **A subset assertion, where this used to be an equality.** Over the old 161-session
    # window these ten WERE every contradicted session. Over the whole corpus 1,077 of
    # 1,233 sessions contradict their declared lot size, because the publish-time
    # dependence reaches the entire historical backfill and not just December. The ten stay
    # pinned because they are the finding this module was built on; the count around them
    # is an extent and is derived.
    assert set(DECEMBER_LOT_75_SESSIONS) <= contradicted
    assert len(contradicted) > len(DECEMBER_LOT_75_SESSIONS), (
        "the corpus-wide contradiction is the headline finding of the full scan"
    )
    for audit in corpus_audits:
        if audit.session_date in DECEMBER_LOT_75_SESSIONS:
            assert audit.declared_lot_sizes == (65,)
            assert audit.best_alternative == 75
            assert audit.best_alternative_share == 1.0
            assert audit.declared_volume_share < 0.10
            assert audit.reference_lot_size == 75


def test_no_refdata_bundle_anywhere_in_the_corpus_declares_lot_size_75(
    corpus_audits: tuple[LotSizeAudit, ...],
) -> None:
    """The producer-side evidence: the bundles are publish-time-stamped, not date-stamped.

    Every session in the corpus declares 65 — all 1,233 of them, including the 1,077 where
    65 was not the lot size the bars support. That is what publish-time dependence looks
    like from the reader's side, and it is why the December regime is recorded from
    measurement rather than read from a file. Over the full corpus this is a considerably
    stronger statement than it was over 161 sessions.
    """
    declared = {lot for audit in corpus_audits for lot in audit.declared_lot_sizes}

    assert declared == {65}


def test_the_recorded_epoch_agrees_with_what_the_bars_measured() -> None:
    """Spec 3 C3: the regime is written down, keyed on expiry, with its evidence."""
    assert epoch_for(dt.date(2025, 12, 30)).lot_size == 75
    assert epoch_for(dt.date(2025, 12, 16)).lot_size == 75
    assert epoch_for(dt.date(2026, 1, 6)).lot_size == 65
    assert epoch_for(dt.date(2026, 6, 25)).lot_size == 65
    assert all(epoch.evidence for epoch in NIFTY_LOT_SIZE_EPOCHS)


def test_a_backtest_touching_december_2025_computes_and_carries_the_stamp(
    store: SessionStore,
) -> None:
    """The contract that replaced the refusal, pinned as a contract rather than deleted.

    Was ``test_a_backtest_touching_december_2025_is_refused_not_computed``, and the
    behaviour it asserted is gone by decision, not by accident: as of 2026-08-13 the
    declared lot size is used for every calculation even where the session's own bars
    contradict it, and the run is stamped rather than blocked.

    That makes the *stamp reaching the verdict* the thing worth pinning, and it is a
    stronger property than the refusal was. A refusal is self-announcing — nobody can
    fail to notice a run that did not happen. A stamp can be dropped anywhere along a
    chain of four components and the result still looks like a perfectly ordinary number,
    which is the failure this asserts against: the flag has to be in
    ``unverified_inputs`` (what C6 reads to decide whether a result is evaluable) *and*
    the contradicted dates have to be in the provenance (what a human reads to find out
    which sessions), because those are two different readers and either one alone would
    leave the other blind.
    """
    import tempfile

    from xman_research import StaticCodeVersion, TrialLog
    from xman_research.clock import ManualClock

    log = TrialLog(
        Path(tempfile.mkdtemp(prefix="xman_research_lot_")) / "research.db",
        clock=ManualClock(dt.datetime(2026, 8, 12, 9, 15, tzinfo=dt.UTC)),
        code_version=StaticCodeVersion("0" * 40, dirty=False),
    )
    session = ResearchSession(log)
    hypothesis = HypothesisRecord(
        name="H1 — a window reaching into the December lot-75 regime",
        mechanism="Irrelevant: what is under test is the stamp, not the P&L.",
        null_hypothesis="Irrelevant.",
        thresholds={"deflated_sharpe": 0.0},
        predictors=["iv_30d"],
    )
    window = DataWindow(dt.date(2025, 12, 16), dt.date(2026, 1, 9))
    try:
        with session.trial(hypothesis, data_window=window) as trial:
            produced = run_backtest(
                trial,
                store=store,
                strategy=ShortAtmStraddle(),
                config=BacktestConfig(
                    underlying=UNDERLYING,
                    gap_reason="lot-size stamp test: gaps are not what is under test",
                ),
            )
    finally:
        session.close()

    # It computed. A run that quietly produced nothing would satisfy every assertion
    # about stamps below while testing none of them.
    assert produced.sessions_run > 0
    assert produced.fills

    assert "corpus.declared_lot_size_contradicted:unverified" in produced.unverified_inputs
    contradicted = produced.data_provenance["lot_size_audit"][
        "sessions_contradicting_declared_lot_size"
    ]
    assert contradicted == [day.isoformat() for day in DECEMBER_LOT_75_SESSIONS]

    # And the stamp says what it means. The text is what a reader of the flag gets, so it
    # has to name the measurement and what survives it, not merely that something is off.
    december = next(a for a in corpus_audits_for(store) if a.session_date == dt.date(2025, 12, 16))
    message = december.contradiction_message()
    assert "declares lot size 65" in message
    assert "computed on the declared value anyway and stamped" in message


def corpus_audits_for(store: SessionStore) -> tuple[LotSizeAudit, ...]:
    """Audit the December sessions alone — the module fixture scans all 161, which this
    test does not need and should not wait for."""
    resolution = store.resolve(
        UNDERLYING, DECEMBER_LOT_75_SESSIONS[0], DECEMBER_LOT_75_SESSIONS[-1]
    )
    return tuple(
        audit_lot_size(
            session_date=ref.session_date,
            underlying=UNDERLYING,
            frame=store.load_session(ref),
            refdata=store.load_refdata(ref),
        )
        for ref in resolution.sessions()
    )


def test_the_open_interest_outliers_are_reported_without_being_diagnosed(
    corpus_audits: tuple[LotSizeAudit, ...],
) -> None:
    """A localised data-quality defect, kept separate from the lot-size verdict.

    Four symbols across three March sessions, plus one December pair, carry open interest
    that divides by no candidate lot size. They are reported per session and they do **not**
    refuse the run — the distinction the two thresholds in ``lot_size.py`` exist to draw,
    since a check that convicted on any non-divisible row would have called these a lot-size
    regime and a check that only looked at totals would have missed them entirely.
    """
    by_session = {a.session_date: a.non_conforming_symbols for a in corpus_audits}

    assert by_session[dt.date(2026, 3, 25)] == (
        "NIFTY-30Mar2026-23000-CE",
        "NIFTY-30Mar2026-23000-PE",
    )
    assert by_session[dt.date(2026, 3, 30)] == (
        "NIFTY-30Mar2026-22000-CE",
        "NIFTY-30Mar2026-22000-PE",
        "NIFTY-30Mar2026-23000-CE",
        "NIFTY-30Mar2026-23000-PE",
    )
    assert by_session[dt.date(2026, 3, 24)] == ()
    assert by_session[dt.date(2026, 4, 1)] == ()
    # The same shape in December, measured against 75 — the lot the bars support, not the
    # 65 the refdata declares. Finding it at all depends on the tie-break to the largest
    # candidate: against 15 or 25 these rows would have looked conforming.
    assert by_session[dt.date(2025, 12, 30)] == (
        "NIFTY-30Dec2025-26000-CE",
        "NIFTY-30Dec2025-26000-PE",
    )
    assert by_session[dt.date(2025, 12, 16)] == ()
    # Present, and not grounds for refusal.
    for audit in corpus_audits:
        if audit.session_date in (dt.date(2026, 3, 25), dt.date(2026, 3, 30)):
            assert not audit.contradicts_declared


def test_a_run_over_the_march_outliers_says_so_in_its_unverified_inputs(result) -> None:
    """The E2E window covers 2026-03-25/27/30, so the flag has to reach the result."""
    produced, _, _ = result

    assert "corpus.open_interest_not_divisible_by_lot_size:unverified" in produced.unverified_inputs
    audit_summary = produced.data_provenance["lot_size_audit"]
    assert audit_summary["sessions_contradicting_declared_lot_size"] == []
    assert "NIFTY-30Mar2026-23000-CE" in audit_summary["symbols_with_non_conforming_open_interest"]
