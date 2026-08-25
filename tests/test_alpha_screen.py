"""The screening harness: expansion, alignment, ranking, round-trip, and one whole run.

The alignment tests are the ones that matter most. A conditional candidate that declines to
enter still has a daily record with flat equity, and treating that as a *missing* rather
than a *zero* observation shortens the candidate's population relative to the benchmark's —
which flatters every conditioner by the same amount, so no comparison inside the sheet can
catch it. ``test_a_flat_session_counts_as_a_zero...`` is built to fail if that regresses:
the synthetic candidate is deliberately flat on the sessions the benchmark moves on.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from alpha_helpers import FLAT_SPOT, trading_days, write_corpus
from xman_research import ManualClock, StaticCodeVersion
from xman_research.alpha.features import FeatureBuilder
from xman_research.alpha.library import AdmissionStatus, TemplateLibrary
from xman_research.alpha.screen import (
    CandidateSpec,
    ScreenedInstance,
    ScreeningRun,
    ScreeningRunError,
    ScreenSheet,
    _excess_series,
    _ranked,
    evidence_card_from_screen,
)
from xman_research.alpha.spec import ScreenSpecError, load_screen_spec
from xman_research.alpha.templates import default_registry
from xman_research.backtest.engine import BacktestConfig
from xman_research.hypothesis import HypothesisRecord
from xman_research.session_store import SessionStore
from xman_research.trial_log import DataWindow, TrialLog, UnknownHypothesisError
from xman_research.validation.series import ReturnSeries

#: Long enough for the twenty-session realised-volatility window every conditioner reads to
#: warm up, short enough that a whole run stays inside a couple of seconds.
SESSION_COUNT = 45
LAST_SESSION = dt.date(2026, 4, 24)

BENCHMARK = CandidateSpec("short_atm_straddle_hold_n", {"hold_sessions": (1.0,)})


@pytest.fixture
def registry():
    return default_registry()


def _hypothesis() -> HypothesisRecord:
    return HypothesisRecord(
        name="Screening: which short-variance structure is best paid",
        mechanism=(
            "Index option implied variance sits above subsequently realised variance "
            "because someone must warehouse the convexity index hedgers buy. Which "
            "structure collects the most of that spread per unit of risk is an empirical "
            "question this screen asks over an in-sample window."
        ),
        null_hypothesis=(
            "No screened structure or conditioner beats the unconditional short "
            "at-the-money straddle held for the same number of sessions."
        ),
        thresholds={"alpha_to_advance": 0.5},
    )


# ------------------------------------------------------------------------- expansion


def test_a_grid_expands_to_the_product_of_its_axes_in_a_deterministic_order(registry) -> None:
    spec = CandidateSpec(
        "short_atm_strangle_hold_n",
        {"hold_sessions": (1.0, 3.0), "atr_multiple": (0.5, 1.0)},
    )
    instances = spec.expand(registry)
    assert [instance.instance_id for instance in instances] == [
        "short_atm_strangle_hold_n@NIFTY[atr_multiple=0.5,hold_sessions=1]",
        "short_atm_strangle_hold_n@NIFTY[atr_multiple=0.5,hold_sessions=3]",
        "short_atm_strangle_hold_n@NIFTY[atr_multiple=1,hold_sessions=1]",
        "short_atm_strangle_hold_n@NIFTY[atr_multiple=1,hold_sessions=3]",
    ]
    assert spec.expand(registry) == instances
    assert [instance.hold_sessions for instance in instances] == [1, 3, 1, 3]


def test_an_empty_grid_expands_to_the_single_default_instance(registry) -> None:
    instances = CandidateSpec("iron_condor_hold_n").expand(registry)
    assert len(instances) == 1
    assert instances[0].hold_sessions == 1


def test_a_hold_outside_one_to_five_sessions_is_refused_at_expansion(registry) -> None:
    spec = CandidateSpec("short_atm_straddle_hold_n", {"hold_sessions": (1.0, 6.0)})
    with pytest.raises(ValueError, match="outside the declared range"):
        spec.expand(registry)


def test_a_parameter_the_template_does_not_declare_is_refused(registry) -> None:
    spec = CandidateSpec("short_atm_straddle_hold_n", {"atr_multiple": (1.0,)})
    with pytest.raises(ValueError, match="declares no parameter"):
        spec.expand(registry)


def test_an_axis_with_no_values_is_refused_when_the_spec_is_built() -> None:
    """An empty axis expands to nothing at all, silently screening less than was asked."""
    with pytest.raises(ScreeningRunError, match="lists no values"):
        CandidateSpec("short_atm_straddle_hold_n", {"hold_sessions": ()})


# ----------------------------------------------------------------------- the excess series


def _series(dates, net, label):
    return ReturnSeries(
        dates=tuple(dates), net=tuple(net), drag=tuple(0.0 for _ in net), label=label
    )


def test_the_excess_is_the_candidate_minus_the_benchmark_session_by_session() -> None:
    days = [dt.date(2026, 4, day) for day in (20, 21, 22)]
    excess = _excess_series(
        _series(days, [0.03, 0.01, -0.02], "candidate"),
        _series(days, [0.01, 0.01, 0.01], "benchmark"),
    )
    assert excess is not None
    assert excess.net == pytest.approx((0.02, 0.0, -0.03))
    assert excess.drag == (0.0, 0.0, 0.0)


def test_a_flat_session_counts_as_a_zero_and_not_as_a_missing_observation() -> None:
    """The bias this guards is invisible from inside the sheet — see the module docstring.

    The candidate trades one of three sessions. Aligned correctly its excess is
    ``(-0.01, -0.01, +0.04)``; drop the sessions it sat out and the excess would be the
    single positive number, which is the flattering answer.
    """
    days = [dt.date(2026, 4, day) for day in (20, 21, 22)]
    excess = _excess_series(
        _series([days[2], days[2] + dt.timedelta(days=1)], [0.05, 0.0], "conditional"),
        _series(days, [0.01, 0.01, 0.01], "benchmark"),
    )
    assert excess is not None
    assert excess.dates == (days[0], days[1], days[2], days[2] + dt.timedelta(days=1))
    assert excess.net == pytest.approx((-0.01, -0.01, 0.04, 0.0))


# ---------------------------------------------------------------------------- ranking


def _row(instance_id: str, alpha: float | None, max_drawdown: float) -> ScreenedInstance:
    spec = CandidateSpec("short_atm_straddle_hold_n")
    instance = spec.expand(default_registry())[0]
    object.__setattr__(instance, "template_id", instance_id)
    return ScreenedInstance(
        instance=instance,
        trial_id=f"trial-{instance_id}",
        outcome="screened",
        strategy_name="s",
        strategy_parameters={},
        fingerprint="f",
        alpha=alpha,
        annualised_sharpe=alpha,
        mean_return_per_session=0.0,
        mean_return_at_hold=0.0,
        max_drawdown=max_drawdown,
        n_observations=10,
        sessions_entered=1,
        feasibility={},
        cost_stamps=(),
        risk_matched=None,
        regime_breakdown={},
    )


def test_rows_rank_by_alpha_descending_and_break_ties_on_the_shallower_drawdown() -> None:
    ranked = _ranked(
        [
            _row("deep", 1.0, max_drawdown=0.40),
            _row("weak", 0.2, max_drawdown=0.01),
            _row("shallow", 1.0, max_drawdown=0.05),
        ]
    )
    assert [row.instance.template_id for row in ranked] == ["shallow", "deep", "weak"]


def test_an_unmeasured_row_ranks_last_rather_than_as_a_zero() -> None:
    ranked = _ranked([_row("none", None, 0.0), _row("loser", -3.0, 0.9)])
    assert [row.instance.template_id for row in ranked] == ["loser", "none"]
    assert ranked[-1].measured is False


# ----------------------------------------------------------------------- the whole run


def _log(path: Path) -> TrialLog:
    return TrialLog(
        path,
        clock=ManualClock(dt.datetime(2026, 5, 1, tzinfo=dt.UTC)),
        code_version=StaticCodeVersion("abc123", dirty=False),
    )


def _run(store: SessionStore, log_path: Path, sessions, *, candidates) -> ScreenSheet:
    log = _log(log_path)
    try:
        return ScreeningRun(
            store=store,
            registry=default_registry(),
            trial_log=log,
            hypothesis=_hypothesis(),
            window=DataWindow(sessions[0], sessions[-1]),
            benchmark=BENCHMARK,
            candidates=candidates,
            config=BacktestConfig(underlying="NIFTY"),
            feature_builder=FeatureBuilder(store, regime_lookback_sessions=20),
            clock=ManualClock(dt.datetime(2026, 5, 1, tzinfo=dt.UTC)),
            code_version=StaticCodeVersion("abc123", dirty=False),
        ).run()
    finally:
        log.close()


@pytest.fixture
def corpus(synthetic_store):
    sessions = trading_days(SESSION_COUNT, ending=LAST_SESSION)
    write_corpus(
        synthetic_store.root,
        sessions=sessions,
        spot_for=lambda index: FLAT_SPOT * (1.0 + 0.002 * (index % 5 - 2)),
        expiry=sessions[-1] + dt.timedelta(days=14),
    )
    return synthetic_store(), sessions


def test_every_instance_produces_a_trial_row_and_the_sheet_counts_them(
    corpus, tmp_path: Path
) -> None:
    store, sessions = corpus
    log_path = tmp_path / "screen.db"
    sheet = _run(
        store,
        log_path,
        sessions,
        candidates=[
            CandidateSpec("short_atm_straddle_hold_n", {"hold_sessions": (1.0, 2.0)}),
            CandidateSpec("short_atm_strangle_hold_n", {"atr_multiple": (0.5,)}),
        ],
    )
    assert len(sheet.instances) == 3
    assert sheet.n_trials_logged == 4  # three candidates plus the benchmark
    assert len(set(sheet.trial_ids)) == 4

    log = _log(log_path)
    try:
        rows = log.family_trials(_hypothesis().id)
    finally:
        log.close()
    assert {row.trial_id for row in rows} == set(sheet.trial_ids)
    assert all(row.params["instance_id"] for row in rows)


def test_two_runs_of_the_same_screen_agree_on_every_number_that_is_not_an_identity(
    corpus, tmp_path: Path
) -> None:
    """Trial ids differ by construction — the token is single-use — so fingerprints decide."""
    store, sessions = corpus
    candidates = [CandidateSpec("short_atm_strangle_hold_n", {"atr_multiple": (0.5, 1.0)})]
    first = _run(store, tmp_path / "one.db", sessions, candidates=candidates)
    second = _run(store, tmp_path / "two.db", sessions, candidates=candidates)

    assert [row.fingerprint for row in first.instances] == [
        row.fingerprint for row in second.instances
    ]
    assert [row.alpha for row in first.instances] == [row.alpha for row in second.instances]
    assert [row.instance.instance_id for row in first.instances] == [
        row.instance.instance_id for row in second.instances
    ]
    assert first.trial_ids != second.trial_ids


def test_an_instance_that_reproduces_the_benchmark_has_no_alpha_rather_than_a_zero(
    corpus, tmp_path: Path
) -> None:
    """Zero over zero is not zero, and a fabricated zero would seat the row mid-ranking."""
    store, sessions = corpus
    sheet = _run(
        store,
        tmp_path / "screen.db",
        sessions,
        candidates=[CandidateSpec("short_atm_straddle_hold_n", {"hold_sessions": (1.0,)})],
    )
    assert sheet.benchmark.alpha is None
    assert sheet.instances[0].alpha is None
    assert sheet.instances[0].measured is False
    assert "no dispersion" in sheet.instances[0].reason
    # The run itself did move, so its own Sharpe is a number even though the spread is not.
    assert sheet.instances[0].annualised_sharpe is not None


def test_a_benchmark_spec_that_expands_to_more_than_one_instance_is_refused(
    corpus, tmp_path: Path
) -> None:
    store, sessions = corpus
    log = _log(tmp_path / "screen.db")
    try:
        run = ScreeningRun(
            store=store,
            registry=default_registry(),
            trial_log=log,
            hypothesis=_hypothesis(),
            window=DataWindow(sessions[0], sessions[-1]),
            benchmark=CandidateSpec("short_atm_straddle_hold_n", {"hold_sessions": (1.0, 2.0)}),
            candidates=[CandidateSpec("short_atm_strangle_hold_n")],
        )
        with pytest.raises(ScreeningRunError, match="not a benchmark"):
            run.run()
    finally:
        log.close()


def test_a_screen_with_no_candidates_is_refused_before_a_trial_is_spent(
    corpus, tmp_path: Path
) -> None:
    store, sessions = corpus
    log_path = tmp_path / "screen.db"
    log = _log(log_path)
    try:
        with pytest.raises(ScreeningRunError, match="names no candidates"):
            ScreeningRun(
                store=store,
                registry=default_registry(),
                trial_log=log,
                hypothesis=_hypothesis(),
                window=DataWindow(sessions[0], sessions[-1]),
                benchmark=BENCHMARK,
                candidates=[],
            ).run()
        # The hypothesis was never even registered, which is a stronger statement than an
        # empty trial list: the refusal landed before anything touched the log.
        with pytest.raises(UnknownHypothesisError):
            log.family_trials(_hypothesis().id)
    finally:
        log.close()


# -------------------------------------------------------------------------- the sheet


def test_a_sheet_round_trips_through_json_unchanged(corpus, tmp_path: Path) -> None:
    store, sessions = corpus
    sheet = _run(
        store,
        tmp_path / "screen.db",
        sessions,
        candidates=[CandidateSpec("short_atm_strangle_hold_n", {"atr_multiple": (0.5,)})],
    )
    document = json.dumps(sheet.as_dict(), sort_keys=True)
    restored = ScreenSheet.from_dict(json.loads(document))
    assert json.dumps(restored.as_dict(), sort_keys=True) == document
    assert restored.n_trials_logged == sheet.n_trials_logged
    assert restored.window == sheet.window


def test_a_sheet_of_an_unknown_schema_is_refused_rather_than_read(corpus, tmp_path: Path) -> None:
    store, sessions = corpus
    sheet = _run(
        store,
        tmp_path / "screen.db",
        sessions,
        candidates=[CandidateSpec("short_atm_strangle_hold_n")],
    )
    payload = sheet.as_dict()
    payload["schema_version"] = 99
    with pytest.raises(ScreeningRunError, match="schema_version"):
        ScreenSheet.from_dict(payload)


def test_the_sheet_states_what_alpha_means_and_why_the_trial_count_is_large(
    corpus, tmp_path: Path
) -> None:
    store, sessions = corpus
    sheet = _run(
        store,
        tmp_path / "screen.db",
        sessions,
        candidates=[CandidateSpec("short_atm_strangle_hold_n")],
    )
    provenance = sheet.provenance
    assert "annualised Sharpe" in provenance["alpha_definition"]
    assert "risk_matched" in provenance["alpha_definition"]
    assert _hypothesis().id in provenance["trial_count_note"]
    assert provenance["code_version"] == "abc123"
    assert "stage 1" in provenance["stage"]
    assert provenance["corpus"]


# ------------------------------------------------------------------ the evidence handoff


def test_a_screened_instance_seeds_the_library_as_a_candidate_and_never_as_admitted(
    corpus, tmp_path: Path, clock: ManualClock
) -> None:
    store, sessions = corpus
    sheet = _run(
        store,
        tmp_path / "screen.db",
        sessions,
        candidates=[CandidateSpec("short_atm_strangle_hold_n", {"atr_multiple": (0.5,)})],
    )
    top = sheet.instances[0]
    card = evidence_card_from_screen(sheet, top.instance.instance_id, source="sheet.json")

    assert card.gate_status is None
    assert card.passed_gate is False
    assert card.deflated_sharpe is None
    assert card.hold_sessions == top.instance.hold_sessions
    assert "no threshold" in card.provenance["gate_status"]

    library = TemplateLibrary(tmp_path / "library.json", clock=clock)
    entry = library.seed_from_screen(
        template=default_registry().get(top.instance.template_id),
        evidence=card,
        sheet_path="sheet.json",
        by="tester",
        reason="the screen's top instance",
        trial_ids=(top.trial_id,),
    )
    assert entry.status is AdmissionStatus.CANDIDATE
    assert entry.decision_path == "sheet.json"
    assert entry.trial_ids == (top.trial_id,)
    assert library.admitted() == ()


def test_seeding_from_a_screen_offers_no_way_to_admit() -> None:
    """The one thing this route must not do is not a keyword away from doing it."""
    import inspect

    parameters = inspect.signature(TemplateLibrary.seed_from_screen).parameters
    assert "status" not in parameters


# ---------------------------------------------------------------------------- the spec


SPEC = """
underlying = "NIFTY"
trial_log = "research/screen/trials.db"
decision_time = "14:50"

[window]
start = 2025-10-01
end = 2026-03-31

[hypothesis]
name = "Screening: which short-variance structure is best paid"
mechanism = "Implied variance sits above realised because someone warehouses the convexity."
null_hypothesis = "No screened structure beats the unconditional straddle."
thresholds = {alpha_to_advance = 0.5}

[benchmark]
template = "short_atm_straddle_hold_n"
grid = {hold_sessions = [3]}

[[candidates]]
template = "short_atm_strangle_hold_n"
grid = {hold_sessions = [3], atr_multiple = [0.5, 1.0]}
"""


def test_a_spec_reads_its_window_hypothesis_benchmark_and_grid(tmp_path: Path) -> None:
    path = tmp_path / "spec.toml"
    path.write_text(SPEC)
    spec = load_screen_spec(path)
    assert spec.window == DataWindow(dt.date(2025, 10, 1), dt.date(2026, 3, 31))
    assert spec.benchmark.grid == {"hold_sessions": (3.0,)}
    assert spec.candidates[0].grid["atr_multiple"] == (0.5, 1.0)
    assert spec.trial_log_path == Path("research/screen/trials.db")
    assert spec.decision_time == dt.time(14, 50)
    assert spec.gaps_reason is None
    assert spec.hypothesis.thresholds["alpha_to_advance"] == 0.5


def test_a_spec_with_no_hypothesis_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "spec.toml"
    path.write_text(SPEC.replace("[hypothesis]", "[unused]"))
    with pytest.raises(ScreenSpecError, match="no `\\[hypothesis\\]` table"):
        load_screen_spec(path)


def test_a_spec_with_no_candidates_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "spec.toml"
    path.write_text(SPEC.split("[[candidates]]")[0])
    with pytest.raises(ScreenSpecError, match="names no `\\[\\[candidates\\]\\]`"):
        load_screen_spec(path)


def test_a_spec_with_nowhere_to_log_is_refused(tmp_path: Path) -> None:
    """A screen with no trial log is a search: nothing records how many tries it took."""
    path = tmp_path / "spec.toml"
    path.write_text(SPEC.replace('trial_log = "research/screen/trials.db"', ""))
    with pytest.raises(ScreenSpecError, match="names no `trial_log`"):
        load_screen_spec(path)


def test_an_empty_gaps_reason_accepts_no_gaps(tmp_path: Path) -> None:
    path = tmp_path / "spec.toml"
    path.write_text(SPEC + '\ngaps_reason = "   "\n')
    assert load_screen_spec(path).gaps_reason is None
