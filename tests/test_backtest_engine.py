"""The engine: the trial token, the session loop, settlement, and reproducibility.

Runs against a two-session synthetic corpus written in the producer's layout, so the
store, the refdata bundle and the frame schema are all real — only the numbers are chosen
to be checkable by hand.
"""

from __future__ import annotations

import datetime as dt

import pytest

from conftest import SyntheticContract, write_synthetic_session
from xman_research import DataWindow, HypothesisRecord, ResearchSession, TrialContext
from xman_research.backtest import (
    BacktestConfig,
    Feasibility,
    ParticipationLimits,
    ShortAtmStraddle,
    TokenAlreadyUsedError,
    run_backtest,
)
from xman_research.session_store import MissingSessionsError

ENTRY_DAY = dt.date(2026, 1, 5)
EXPIRY_DAY = dt.date(2026, 1, 6)
STRIKE = 23_000.0
LOT = 65
PREMIUM = 100.0

# The last half hour of the expiry session ramps 23,100 -> 23,129, so settlement is
# 23,114.5: the call finishes 114.5 in the money and the put finishes worthless.
SETTLEMENT_RAMP = {345 + step: 23_100.0 + float(step) for step in range(30)}
SETTLED_VALUE = 23_114.5


def _contracts(volume: float = 1_300_000.0, oi: float = 6_500_000.0) -> list[SyntheticContract]:
    return [
        SyntheticContract(STRIKE, option_type, EXPIRY_DAY, PREMIUM, volume, oi)
        for option_type in ("CE", "PE")
    ]


@pytest.fixture
def store(synthetic_store):
    root = synthetic_store.root
    write_synthetic_session(root, ENTRY_DAY, spot=23_000.0, contracts=_contracts())
    write_synthetic_session(
        root,
        EXPIRY_DAY,
        spot=23_000.0,
        contracts=_contracts(),
        spot_by_minute=SETTLEMENT_RAMP,
    )
    return synthetic_store()


@pytest.fixture
def window() -> DataWindow:
    return DataWindow(ENTRY_DAY, EXPIRY_DAY)


def _run(session: ResearchSession, h1: HypothesisRecord, store, window: DataWindow, **kwargs):
    with session.trial(h1, data_window=window) as trial:
        return run_backtest(
            trial, store=store, strategy=ShortAtmStraddle(), config=BacktestConfig(**kwargs)
        )


# ---------------------------------------------------------------------- the token gate


def test_a_second_backtest_against_the_same_token_is_refused(
    session: ResearchSession, h1: HypothesisRecord, store, window: DataWindow
) -> None:
    """The mitigation C4's review asked for: one token, one run.

    Without this, a body that sweeps 200 parameter values logs one trial containing a
    200-way selection, and the trial count deflated Sharpe corrects with is wrong by two
    orders of magnitude — in the direction of passing.
    """
    with session.trial(h1, data_window=window) as trial:
        run_backtest(trial, store=store, strategy=ShortAtmStraddle())

        with pytest.raises(TokenAlreadyUsedError, match="already run a backtest"):
            run_backtest(trial, store=store, strategy=ShortAtmStraddle(lots=2))


def test_a_sweep_must_mint_one_trial_per_backtest(
    session: ResearchSession, h1: HypothesisRecord, store, window: DataWindow
) -> None:
    """Three variants, three tokens, three trials in the log. That is the true count."""
    for lots in (1, 2, 3):
        with session.trial(h1, data_window=window, params={"lots": lots}) as trial:
            run_backtest(
                trial, store=store, strategy=ShortAtmStraddle(lots=lots), config=BacktestConfig()
            )

    assert session.count_trials(h1) == 3


def test_the_backtest_refuses_anything_that_is_not_a_trial_context(store) -> None:
    with pytest.raises(TypeError, match="TrialContext"):
        run_backtest("not-a-token", store=store, strategy=ShortAtmStraddle())  # type: ignore[arg-type]


def test_a_failed_run_still_burns_its_token(
    session: ResearchSession, h1: HypothesisRecord, store
) -> None:
    """Release-on-failure would hand back a retry loop, and a retry loop is a sweep."""
    bad_window = DataWindow(dt.date(2026, 1, 5), dt.date(2026, 1, 9))

    with session.trial(h1, data_window=bad_window) as trial:
        with pytest.raises(MissingSessionsError):
            run_backtest(trial, store=store, strategy=ShortAtmStraddle())
        with pytest.raises(TokenAlreadyUsedError):
            run_backtest(trial, store=store, strategy=ShortAtmStraddle())


def test_a_gap_can_be_accepted_only_against_a_written_reason(
    session: ResearchSession, h1: HypothesisRecord, synthetic_store
) -> None:
    """The store's asymmetry is not softened by being wrapped.

    Only the entry session is written, so the expiry session is missing. Without a reason
    the run refuses; with one it proceeds, the reason is recorded on the result, and the
    straddle is still open at the end because the session that would have settled it does
    not exist — a partial window is visible in the output, not just in the config.
    """
    root = synthetic_store.root
    write_synthetic_session(root, ENTRY_DAY, spot=23_000.0, contracts=_contracts())
    store = synthetic_store()
    gappy = DataWindow(ENTRY_DAY, EXPIRY_DAY)

    with session.trial(h1, data_window=gappy) as trial, pytest.raises(MissingSessionsError):
        run_backtest(trial, store=store, strategy=ShortAtmStraddle())

    reason = "the expiry session is not captured; running for the entry mechanics only"
    with session.trial(h1, data_window=gappy) as trial:
        result = run_backtest(
            trial,
            store=store,
            strategy=ShortAtmStraddle(),
            config=BacktestConfig(gap_reason=reason),
        )

    assert result.sessions_run == 1
    assert result.config_provenance["gap_reason"] == reason
    assert result.data_provenance["missing"] == [EXPIRY_DAY.isoformat()]
    assert result.settlements == ()
    assert result.daily[-1].open_positions == 2


def test_the_window_comes_from_the_token_and_cannot_be_restated(
    session: ResearchSession, h1: HypothesisRecord, store, window: DataWindow
) -> None:
    """There is no start/end on the config, so the trial row and the run cannot disagree."""
    assert not hasattr(BacktestConfig(), "start")
    result = _run(session, h1, store, window)

    assert (result.start, result.end) == (window.start, window.end)


# ------------------------------------------------------------------------- the run


def test_the_straddle_is_sold_and_cash_settled(
    session: ResearchSession, h1: HypothesisRecord, store, window: DataWindow
) -> None:
    """Two legs sold on the entry day, both settled on the expiry day.

    Gross premium received: 2 legs x 100 x 65 = 13,000.
    Settlement at 23,114.5: the short call pays 114.5 x 65 = 7,442.50, the put pays 0.
    """
    result = _run(session, h1, store, window)

    assert result.sessions_run == 2
    assert [fill.trading_symbol for fill in result.fills] == [
        "NIFTY-06Jan2026-23000-CE",
        "NIFTY-06Jan2026-23000-PE",
    ]
    assert all(fill.filled_lots == 1 for fill in result.fills)
    assert sum(fill.gross_value for fill in result.fills) == pytest.approx(13_000.0)

    settled = {record.trading_symbol: record for record in result.settlements}
    assert len(settled) == 2
    call = settled["NIFTY-06Jan2026-23000-CE"]
    put = settled["NIFTY-06Jan2026-23000-PE"]
    assert call.settlement_value == pytest.approx(SETTLED_VALUE)
    assert call.intrinsic_per_unit == pytest.approx(114.5)
    assert put.intrinsic_per_unit == 0.0
    assert call.units == -LOT


def test_the_assigned_short_pays_no_exercise_stt_at_settlement(
    session: ResearchSession, h1: HypothesisRecord, store, window: DataWindow
) -> None:
    """End to end, the attribution that flatters a short-variance result stays honest."""
    result = _run(session, h1, store, window)

    assert result.total_costs.stt_on_exercise == 0.0
    assert result.total_costs.stt > 0.0


def test_every_entry_and_every_exit_carries_a_feasibility_verdict(
    session: ResearchSession, h1: HypothesisRecord, store, window: DataWindow
) -> None:
    """The acceptance criterion, asserted on the objects rather than on a summary."""
    result = _run(session, h1, store, window)

    assert result.fills and result.settlements
    assert all(fill.feasibility.verdict is Feasibility.FILLABLE for fill in result.fills)
    assert all(record.feasibility.verdict is Feasibility.SETTLED for record in result.settlements)
    counts = result.feasibility_counts()
    assert counts["fillable"] == 2
    assert counts["settled"] == 2


def test_a_participation_cap_binds_and_the_resize_is_recorded_end_to_end(
    session: ResearchSession, h1: HypothesisRecord, synthetic_store
) -> None:
    """A thin contract: 1% of 6,500 traded units is 65 units, which is exactly one lot,
    so a five-lot request is cut to one and the record says which cap did it."""
    root = synthetic_store.root
    thin = [
        SyntheticContract(STRIKE, option_type, EXPIRY_DAY, PREMIUM, 6_500.0, 6_500_000.0)
        for option_type in ("CE", "PE")
    ]
    write_synthetic_session(root, ENTRY_DAY, spot=23_000.0, contracts=thin)
    write_synthetic_session(
        root, EXPIRY_DAY, spot=23_000.0, contracts=thin, spot_by_minute=SETTLEMENT_RAMP
    )
    store = synthetic_store()

    with session.trial(h1, data_window=DataWindow(ENTRY_DAY, EXPIRY_DAY)) as trial:
        result = run_backtest(trial, store=store, strategy=ShortAtmStraddle(lots=5))

    resized = result.resized_fills()
    assert len(resized) == 2
    assert all(fill.requested_lots == 5 and fill.filled_lots == 1 for fill in resized)
    assert all(fill.feasibility.binding_cap == "volume" for fill in resized)
    assert result.metrics()["fills_resized"] == 2


def test_an_untradeable_contract_produces_an_infeasible_verdict_and_no_position(
    session: ResearchSession, h1: HypothesisRecord, synthetic_store
) -> None:
    """Zero volume all session: the strategy wants the trade and the market refuses it."""
    root = synthetic_store.root
    dead = [
        SyntheticContract(STRIKE, option_type, EXPIRY_DAY, PREMIUM, 0.0, 6_500_000.0)
        for option_type in ("CE", "PE")
    ]
    write_synthetic_session(root, ENTRY_DAY, spot=23_000.0, contracts=dead)
    write_synthetic_session(
        root, EXPIRY_DAY, spot=23_000.0, contracts=dead, spot_by_minute=SETTLEMENT_RAMP
    )
    store = synthetic_store()

    with session.trial(h1, data_window=DataWindow(ENTRY_DAY, EXPIRY_DAY)) as trial:
        result = run_backtest(trial, store=store, strategy=ShortAtmStraddle())

    assert all(fill.filled_lots == 0 for fill in result.fills)
    assert result.metrics()["fills_infeasible"] > 0
    assert result.settlements == ()
    assert result.total_costs.total == 0.0


def test_margin_is_charged_while_the_short_is_open_and_released_after_settlement(
    session: ResearchSession, h1: HypothesisRecord, store, window: DataWindow
) -> None:
    result = _run(session, h1, store, window)

    entry_day, expiry_day = result.daily
    assert entry_day.open_positions == 2
    assert entry_day.margin.total > 0
    assert expiry_day.open_positions == 0
    assert expiry_day.margin.total == 0.0
    assert result.peak_margin == entry_day.margin.total
    assert result.return_on_peak_margin is not None


def test_the_result_reports_its_unverified_inputs(
    session: ResearchSession, h1: HypothesisRecord, store, window: DataWindow
) -> None:
    """A headline number computed on a guessed rate has to say so."""
    result = _run(session, h1, store, window)

    assert "margin.simplified_approximation" in result.unverified_inputs
    assert any(name.startswith("stt") for name in result.unverified_inputs)


# ------------------------------------------------------------------- reproducibility


def test_the_same_inputs_reproduce_the_result_exactly(
    session: ResearchSession, h1: HypothesisRecord, store, window: DataWindow
) -> None:
    """Acceptance criterion 5, as one assertion over the whole run."""
    first = _run(session, h1, store, window)
    second = _run(session, h1, store, window)

    assert first.trial_id != second.trial_id
    assert first.fingerprint() == second.fingerprint()
    assert first.net_pnl == second.net_pnl
    assert first.as_dict()["fills"] == second.as_dict()["fills"]


def test_a_different_parameter_changes_the_fingerprint(
    session: ResearchSession, h1: HypothesisRecord, store, window: DataWindow
) -> None:
    """A fingerprint that never changes is not evidence of anything."""
    base = _run(session, h1, store, window)
    slipped = _run(
        session, h1, store, window, limits=ParticipationLimits(max_pct_of_bar_volume=0.5)
    )

    assert base.fingerprint() != slipped.fingerprint()


def test_no_timestamp_reaches_the_fingerprint(
    session: ResearchSession, h1: HypothesisRecord, store, window: DataWindow
) -> None:
    """The store stamps ``resolved_at``; the fingerprint must not inherit it.

    The suite's clock advances a second per reading, so two runs genuinely carry different
    ``resolved_at`` values — which makes the equal fingerprints in the reproducibility
    test above evidence rather than coincidence. Asserted here explicitly so that adding a
    clock-derived field to the result cannot pass unnoticed.
    """
    first = _run(session, h1, store, window)
    second = _run(session, h1, store, window)

    assert first.data_provenance["resolved_at"] != second.data_provenance["resolved_at"]
    assert first.fingerprint() == second.fingerprint()
    assert "run_at" not in first.as_dict()
    assert "resolved_at" not in first.config_provenance


def test_an_unmarkable_short_is_carried_at_its_last_mark_not_at_zero(
    session: ResearchSession, h1: HypothesisRecord, synthetic_store
) -> None:
    """The bug this test exists for: a short marked to zero books its premium as profit.

    The straddle is written against a later expiry so it is still open on the second
    session, which prints only the underlying — neither leg can be marked. Carried at the
    last mark, the book's open value stays at minus the premium and equity is unchanged.
    Marked to zero, equity would jump by the full 13,000 of premium sold — a gain
    conjured out of a data gap, in the one direction that flatters the only strategy this
    package ships.
    """
    later = dt.date(2026, 1, 13)
    contracts = [
        SyntheticContract(STRIKE, option_type, later, PREMIUM) for option_type in ("CE", "PE")
    ]
    root = synthetic_store.root
    write_synthetic_session(root, ENTRY_DAY, spot=23_000.0, contracts=contracts)
    write_synthetic_session(root, EXPIRY_DAY, spot=23_000.0, contracts=[])
    store = synthetic_store()

    with session.trial(h1, data_window=DataWindow(ENTRY_DAY, EXPIRY_DAY)) as trial:
        result = run_backtest(trial, store=store, strategy=ShortAtmStraddle())

    entry_day, blind_day = result.daily
    assert entry_day.stale_marks == 0
    assert blind_day.stale_marks == 2
    assert blind_day.open_position_value == pytest.approx(-13_000.0)
    assert blind_day.equity == pytest.approx(entry_day.equity)


# ------------------------------------------------------------- the trial log seam


def test_the_run_lands_in_the_trial_log_with_its_metrics(
    session: ResearchSession, h1: HypothesisRecord, store, window: DataWindow
) -> None:
    """C4's log is where the count lives; C5 must write into it, not beside it."""
    result = _run(session, h1, store, window)
    (row,) = session.trials(h1)

    assert row.metrics["net_pnl"] == pytest.approx(result.net_pnl)
    assert row.metrics["fingerprint"] == result.fingerprint()
    assert row.params["backtest_token_consumed"] is True
    assert row.params["strategy"] == "short_atm_straddle"
    assert "unverified inputs" in (row.notes or "")


def test_a_trial_context_is_what_the_entrypoint_wants(
    session: ResearchSession, h1: HypothesisRecord, store, window: DataWindow
) -> None:
    """The decorated-evaluation shape from C4 works unchanged — this is the notebook path."""

    @session.evaluation(h1, data_window=window)
    def evaluate(trial: TrialContext) -> dict[str, float]:
        result = run_backtest(trial, store=store, strategy=ShortAtmStraddle())
        return {"net_pnl": result.net_pnl}

    metrics = evaluate()

    assert "net_pnl" in metrics
    assert session.count_trials(h1) == 1
