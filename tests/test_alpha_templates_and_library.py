"""Templates, the registry, and the admission library.

The properties held here are the ones that make the nightly scan's output believable: a
template can only be built for a product and a parameter point it declares, a template can
only be admitted against a decision record that exists and parses, and every number on an
evidence card can be traced back to a field of that record.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from xman_research import ManualClock
from xman_research.alpha.library import (
    AdmissionRecord,
    AdmissionStatus,
    AdmittedParametersMismatchError,
    AmbiguousParameterPointError,
    AppendOnlyLibraryError,
    DecisionRecordError,
    EvidenceCard,
    LibraryFileError,
    TemplateLibrary,
    UnpassedEvidenceError,
)
from xman_research.alpha.templates import (
    ATR_14,
    Comparator,
    ConditionerSpec,
    HoldNShortStraddle,
    HoldNShortStrangle,
    ParameterRange,
    StrategyTemplate,
    TemplateRegistry,
    UnknownTemplateError,
    _exit_intents,
    default_registry,
    parameter_key,
)
from xman_research.backtest.costs import Side
from xman_research.backtest.engine import Strategy, TradeIntent
from xman_research.backtest.market import Contract

#: The written override every admission in this file needs: the shipped H1 decision record
#: reports a failed gate, and `TemplateLibrary.admit` refuses to admit on it silently.
OVERRIDE = "test fixture: the anchor record failed its gate and is admitted anyway"

#: Anchored to the repository, not to the working directory: a test that only passes
#: when pytest happens to be invoked from the repo root is a test with a hidden
#: precondition.
DECISION_RECORD = Path(__file__).resolve().parents[1] / "research" / "h1" / "decision.json"


@pytest.fixture
def registry() -> TemplateRegistry:
    return default_registry()


@pytest.fixture
def library(tmp_path: Path, clock: ManualClock) -> TemplateLibrary:
    return TemplateLibrary(tmp_path / "templates.json", clock=clock)


# ------------------------------------------------------------------------------- registry


def test_the_shipped_registry_holds_every_shape_unconditioned_and_conditioned(
    registry: TemplateRegistry,
) -> None:
    """Each structure ships as its own benchmark family plus one template per conditioner."""
    shapes = ("short_atm_straddle", "short_atm_strangle", "iron_condor")
    kinds = ("iv_rv", "ema_atr_band", "post_gap", "expiry_distance", "day_of_week")
    expected = tuple(f"{shape}_{suffix}" for shape in shapes for suffix in ("hold_n", *kinds))
    assert registry.ids() == expected
    for shape in shapes:
        assert registry.get(f"{shape}_hold_n").conditioner is None
        for kind in kinds:
            assert registry.get(f"{shape}_{kind}").conditioner is not None


def test_two_registries_do_not_share_state(registry: TemplateRegistry) -> None:
    """A module-level singleton would let one caller's registration change another's view."""
    other = default_registry()
    other.register(
        StrategyTemplate(
            template_id="extra",
            name="extra",
            thesis="a template registered by one caller only",
            products=("NIFTY",),
            hold_sessions=1,
            parameters={},
            conditioner=None,
            builder=lambda params, underlying, series: HoldNShortStraddle(),
        )
    )
    assert "extra" in other
    assert "extra" not in registry


def test_a_duplicate_template_id_is_refused_rather_than_overwritten(
    registry: TemplateRegistry,
) -> None:
    with pytest.raises(ValueError, match="already registered"):
        registry.register(registry.get("short_atm_straddle_hold_n"))


def test_an_unregistered_id_names_what_is_registered(registry: TemplateRegistry) -> None:
    with pytest.raises(UnknownTemplateError, match="short_atm_straddle_hold_n"):
        registry.get("no_such_template")


def test_for_product_selects_only_templates_declaring_it(registry: TemplateRegistry) -> None:
    assert len(registry.for_product("NIFTY")) == len(registry)
    assert registry.for_product("BANKNIFTY") == ()


# ------------------------------------------------------------------------------- building


def test_every_shipped_template_builds_something_satisfying_the_engine_protocol(
    registry: TemplateRegistry,
) -> None:
    for template in registry:
        built = template.build(
            None,
            "NIFTY",
            feature_series={
                name: {dt.date(2026, 4, 24): 0.5}
                for name in ("iv_minus_rv_20", "atr_14", "ema20_z_abs", "overnight_gap_sigmas")
            },
        )
        assert isinstance(built, Strategy)
        assert built.name
        assert dict(built.parameters())


def test_build_refuses_a_product_the_template_was_not_measured_on(
    registry: TemplateRegistry,
) -> None:
    with pytest.raises(ValueError, match="says nothing about"):
        registry.get("short_atm_straddle_hold_n").build(None, "BANKNIFTY")


def test_build_refuses_a_parameter_outside_its_declared_range(
    registry: TemplateRegistry,
) -> None:
    template = registry.get("short_atm_straddle_hold_n")
    with pytest.raises(ValueError, match="outside the declared range"):
        template.build({"target_notional": 1.0}, "NIFTY")


def test_build_refuses_a_parameter_the_template_does_not_declare(
    registry: TemplateRegistry,
) -> None:
    template = registry.get("short_atm_straddle_hold_n")
    with pytest.raises(ValueError, match="declares no parameter"):
        template.build({"delta": 0.3}, "NIFTY")


def test_resolve_fills_declared_defaults(registry: TemplateRegistry) -> None:
    resolved = registry.get("short_atm_straddle_iv_rv").resolve({})
    assert resolved == {
        "hold_sessions": 1.0,
        "target_notional": 1_500_000.0,
        "iv_rv_threshold": 0.03,
    }


def test_a_parameter_range_refuses_a_default_outside_itself() -> None:
    with pytest.raises(ValueError, match="outside the declared range"):
        ParameterRange(low=0.0, high=1.0, default=2.0)


def test_a_hold_outside_one_to_five_sessions_is_refused() -> None:
    with pytest.raises(ValueError, match="hold_sessions must be between"):
        HoldNShortStraddle(hold_sessions=6)


def test_a_template_with_no_thesis_is_refused() -> None:
    with pytest.raises(ValueError, match="states no thesis"):
        StrategyTemplate(
            template_id="silent",
            name="silent",
            thesis="   ",
            products=("NIFTY",),
            hold_sessions=1,
            parameters={},
            conditioner=None,
            builder=lambda params, underlying, series: HoldNShortStraddle(),
        )


# --------------------------------------------------------------------------- conditioner


def test_a_conditioner_fires_only_past_its_threshold_and_never_on_a_missing_feature() -> None:
    spec = ConditionerSpec(
        feature="iv_minus_rv_20",
        comparator=Comparator.AT_LEAST,
        threshold=0.03,
        saturation_span=0.06,
        lookback_sessions=20,
    )
    assert not spec.fires(0.02)
    assert spec.fires(0.03)
    assert not spec.fires(None)
    assert spec.strength(None) == 0.0
    assert spec.strength(0.02) == 0.0
    assert spec.strength(0.03) == 0.0
    assert spec.strength(0.06) == pytest.approx(0.5)
    assert spec.strength(0.50) == 1.0


def test_an_at_most_conditioner_measures_strength_in_the_other_direction() -> None:
    spec = ConditionerSpec(
        feature="ema20_z",
        comparator=Comparator.AT_MOST,
        threshold=0.0,
        saturation_span=2.0,
        lookback_sessions=20,
    )
    assert spec.fires(-1.0)
    assert not spec.fires(0.5)
    assert spec.strength(-1.0) == pytest.approx(0.5)


def test_a_conditioned_strategy_with_no_feature_series_declines_to_enter() -> None:
    """The unsafe direction is a conditional strategy silently trading unconditionally."""
    session_date = dt.date(2026, 4, 24)
    strategy = HoldNShortStraddle(
        conditioner=ConditionerSpec(
            feature="iv_minus_rv_20",
            comparator=Comparator.AT_LEAST,
            threshold=0.0,
            saturation_span=0.06,
            lookback_sessions=20,
        )
    )
    assert strategy._may_enter(session_date) is False
    strategy.feature_series = {"iv_minus_rv_20": {session_date: 0.1}}
    assert strategy._may_enter(session_date) is True


# -------------------------------------------------------------------------------- library


def test_admit_refuses_a_decision_record_that_does_not_exist(
    library: TemplateLibrary, registry: TemplateRegistry, tmp_path: Path
) -> None:
    with pytest.raises(DecisionRecordError, match="no decision record at"):
        library.admit(
            override_reason=OVERRIDE,
            template=registry.get("short_atm_straddle_hold_n"),
            decision_path=tmp_path / "absent.json",
            by="tester",
            reason="testing the refusal",
        )


def test_admit_refuses_a_decision_record_that_does_not_parse(
    library: TemplateLibrary, registry: TemplateRegistry, tmp_path: Path
) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text("{not json")
    with pytest.raises(DecisionRecordError, match="does not parse"):
        library.admit(
            override_reason=OVERRIDE,
            template=registry.get("short_atm_straddle_hold_n"),
            decision_path=broken,
            by="tester",
            reason="testing the refusal",
        )


def test_admit_refuses_json_that_is_not_a_decision_record(
    library: TemplateLibrary, registry: TemplateRegistry, tmp_path: Path
) -> None:
    wrong = tmp_path / "wrong.json"
    wrong.write_text(json.dumps({"hello": "world"}))
    with pytest.raises(DecisionRecordError, match="no `in_sample` verdict"):
        library.admit(
            override_reason=OVERRIDE,
            template=registry.get("short_atm_straddle_hold_n"),
            decision_path=wrong,
            by="tester",
            reason="testing the refusal",
        )


def test_admit_demands_a_name_and_a_reason(
    library: TemplateLibrary, registry: TemplateRegistry
) -> None:
    template = registry.get("short_atm_straddle_hold_n")
    with pytest.raises(ValueError, match="requires `by`"):
        library.admit(
            override_reason=OVERRIDE,
            template=template,
            decision_path=DECISION_RECORD,
            by="  ",
            reason="r",
        )
    with pytest.raises(ValueError, match="requires a written `reason`"):
        library.admit(
            override_reason=OVERRIDE,
            template=template,
            decision_path=DECISION_RECORD,
            by="t",
            reason="",
        )


def test_admitting_unpassed_evidence_is_refused_without_a_written_override(
    library: TemplateLibrary, registry: TemplateRegistry
) -> None:
    """The shipped H1 record FAILED its gate, and the ranker proposes real trades."""
    with pytest.raises(UnpassedEvidenceError, match="not a pass"):
        library.admit(
            template=registry.get("short_atm_straddle_hold_n"),
            decision_path=DECISION_RECORD,
            by="tester",
            reason="the anchor hypothesis's evidence, verdict and all",
        )
    assert library.entries() == ()


def test_unpassed_evidence_may_be_filed_as_a_candidate_with_no_override(
    library: TemplateLibrary, registry: TemplateRegistry
) -> None:
    """Recording what was measured is not the same act as letting the ranker trade it."""
    entry = library.admit(
        template=registry.get("short_atm_straddle_hold_n"),
        decision_path=DECISION_RECORD,
        by="tester",
        reason="filing the anchor hypothesis's evidence",
        status=AdmissionStatus.CANDIDATE,
    )
    assert entry.status is AdmissionStatus.CANDIDATE
    assert entry.evidence.passed_gate is False


def test_an_override_is_recorded_on_the_entry_and_carries_the_verdict_verbatim(
    library: TemplateLibrary, registry: TemplateRegistry
) -> None:
    """An admission over a failed gate is somebody's decision, and the entry shows it."""
    entry = library.admit(
        template=registry.get("short_atm_straddle_hold_n"),
        decision_path=DECISION_RECORD,
        by="tester",
        reason="the anchor hypothesis's evidence, verdict and all",
        override_reason=OVERRIDE,
    )
    assert entry.decision_outcome == "fails_threshold"
    assert entry.evidence.gate_status == "failed"
    assert entry.evidence.passed_gate is False
    assert entry.status is AdmissionStatus.ADMITTED
    # A field of its own, not a sentence inside free-text notes: a reader scanning statuses
    # must see it without reading prose.
    assert entry.override_reason == OVERRIDE
    assert entry.notes is None


def test_the_evidence_card_takes_the_mean_return_net_of_costs(
    library: TemplateLibrary, registry: TemplateRegistry
) -> None:
    payload = json.loads(DECISION_RECORD.read_text())
    metrics = payload["in_sample"]["metrics"]
    entry = library.admit(
        override_reason=OVERRIDE,
        template=registry.get("short_atm_straddle_hold_n"),
        decision_path=DECISION_RECORD,
        by="tester",
        reason="checking the cost treatment",
    )
    expected = metrics["mean_gross_return"] - metrics["mean_cost_drag"]
    assert entry.evidence.mean_return_per_session == pytest.approx(expected)
    assert entry.evidence.mean_return_at_hold == pytest.approx(expected * 1)
    assert entry.evidence.annualised_sharpe == metrics["annualised_sharpe"]
    assert entry.evidence.n_observations == metrics["sample_length"]
    assert tuple(metrics["unverified_inputs"]) == entry.evidence.cost_stamps


def test_the_evidence_card_reports_no_hit_rate_rather_than_inventing_one(
    library: TemplateLibrary, registry: TemplateRegistry
) -> None:
    entry = library.admit(
        override_reason=OVERRIDE,
        template=registry.get("short_atm_straddle_hold_n"),
        decision_path=DECISION_RECORD,
        by="tester",
        reason="checking an unreported measurement stays unreported",
    )
    assert entry.evidence.hit_rate is None
    assert "not reported" in entry.evidence.provenance["hit_rate"]


def test_the_cost_epoch_list_is_not_read_as_a_volatility_regime_table(
    library: TemplateLibrary, registry: TemplateRegistry
) -> None:
    """``epochs.regimes`` partitions the window by statutory cost changes, not by volatility."""
    entry = library.admit(
        override_reason=OVERRIDE,
        template=registry.get("short_atm_straddle_hold_n"),
        decision_path=DECISION_RECORD,
        by="tester",
        reason="checking the two partitions are not conflated",
    )
    assert entry.evidence.regime_table is None
    assert entry.evidence.regime_factor("iv_rv_high") == 1.0
    assert entry.evidence.regime_factor(None) == 1.0


def test_a_card_with_a_regime_table_scales_only_the_regimes_it_names() -> None:
    card = EvidenceCard(
        n_observations=100,
        annualised_sharpe=1.0,
        deflated_sharpe=0.5,
        max_drawdown=0.05,
        hit_rate=None,
        mean_return_per_session=0.001,
        mean_return_at_hold=0.001,
        hold_sessions=1,
        gate_status="passed",
        outcome="passes",
        window="2026-01-01..2026-04-30",
        measured_strategy="short_atm_straddle",
        measured_strategy_parameters={"target_notional": 1_500_000.0},
        cost_stamps=(),
        regime_table={"iv_rv_high": 1.5},
        provenance={},
    )
    assert card.regime_factor("iv_rv_high") == 1.5
    assert card.regime_factor("iv_rv_low") == 1.0
    assert card.regime_factor(None) == 1.0


def test_every_card_number_names_the_field_it_came_from(
    library: TemplateLibrary, registry: TemplateRegistry
) -> None:
    entry = library.admit(
        override_reason=OVERRIDE,
        template=registry.get("short_atm_straddle_hold_n"),
        decision_path=DECISION_RECORD,
        by="tester",
        reason="auditability",
    )
    provenance = entry.evidence.provenance
    for measured in (
        "n_observations",
        "annualised_sharpe",
        "deflated_sharpe",
        "max_drawdown",
        "gate_status",
        "outcome",
        "window",
        "cost_stamps",
    ):
        assert str(DECISION_RECORD) in provenance[measured]
    assert provenance["mean_return_per_session"].startswith("derived:")
    assert provenance["mean_return_at_hold"].startswith("derived:")
    assert "hold to cash settlement" in provenance["mean_return_at_hold"]


def test_status_is_the_latest_entry_and_history_keeps_every_one(
    library: TemplateLibrary, registry: TemplateRegistry
) -> None:
    template = registry.get("short_atm_straddle_hold_n")
    library.admit(
        template=template,
        decision_path=DECISION_RECORD,
        by="tester",
        reason="filing evidence first",
        status=AdmissionStatus.CANDIDATE,
    )
    assert library.status(template.template_id) is AdmissionStatus.CANDIDATE
    assert library.admitted() == ()

    library.admit(
        override_reason=OVERRIDE,
        template=template,
        decision_path=DECISION_RECORD,
        by="tester",
        reason="promoting it",
    )
    assert library.status(template.template_id) is AdmissionStatus.ADMITTED
    assert len(library.admitted()) == 1

    library.demote(template_id=template.template_id, by="tester", reason="outcome drifted")
    assert library.status(template.template_id) is AdmissionStatus.DEMOTED
    assert library.admitted() == ()
    assert len(library.history(template.template_id)) == 3


def test_a_demotion_carries_the_evidence_forward_rather_than_clearing_it(
    library: TemplateLibrary, registry: TemplateRegistry
) -> None:
    template = registry.get("short_atm_straddle_hold_n")
    admitted = library.admit(
        override_reason=OVERRIDE,
        template=template,
        decision_path=DECISION_RECORD,
        by="tester",
        reason="admitting",
    )
    demoted = library.demote(
        template_id=template.template_id, by="tester", reason="live outcomes disagree"
    )
    assert demoted.evidence == admitted.evidence
    assert demoted.reason == "live outcomes disagree"


def test_demote_refuses_a_template_the_library_has_never_seen(library: TemplateLibrary) -> None:
    with pytest.raises(KeyError, match="nothing to demote"):
        library.demote(template_id="never_filed", by="tester", reason="r")


def test_demote_refuses_to_demote_twice(
    library: TemplateLibrary, registry: TemplateRegistry
) -> None:
    template = registry.get("short_atm_straddle_hold_n")
    library.admit(
        override_reason=OVERRIDE,
        template=template,
        decision_path=DECISION_RECORD,
        by="tester",
        reason="admitting",
    )
    library.demote(template_id=template.template_id, by="tester", reason="first")
    with pytest.raises(ValueError, match="already demoted"):
        library.demote(template_id=template.template_id, by="tester", reason="second")


def test_admit_refuses_to_record_a_demotion_that_would_carry_no_reason(
    library: TemplateLibrary, registry: TemplateRegistry
) -> None:
    with pytest.raises(ValueError, match="use demote"):
        library.admit(
            override_reason=OVERRIDE,
            template=registry.get("short_atm_straddle_hold_n"),
            decision_path=DECISION_RECORD,
            by="tester",
            reason="r",
            status=AdmissionStatus.DEMOTED,
        )


def test_the_library_round_trips_through_json_unchanged(
    library: TemplateLibrary, registry: TemplateRegistry
) -> None:
    template = registry.get("short_atm_straddle_hold_n")
    library.admit(
        override_reason=OVERRIDE,
        template=template,
        decision_path=DECISION_RECORD,
        by="tester",
        reason="admitting",
    )
    library.demote(template_id=template.template_id, by="tester", reason="demoting")
    path = library.save()

    reloaded = TemplateLibrary.load(path)
    assert reloaded.entries() == library.entries()
    assert reloaded.status(template.template_id) is AdmissionStatus.DEMOTED


def test_a_missing_library_file_loads_as_an_empty_library(tmp_path: Path) -> None:
    library = TemplateLibrary.load(tmp_path / "not-written-yet.json")
    assert library.entries() == ()
    assert library.admitted() == ()


def test_a_library_from_an_unknown_schema_version_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "future.json"
    path.write_text(json.dumps({"schema_version": 99, "entries": []}))
    with pytest.raises(LibraryFileError, match="schema_version"):
        TemplateLibrary.load(path)


def test_a_library_that_is_not_a_json_object_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "a-list.json"
    path.write_text(json.dumps([{"template_id": "x"}]))
    with pytest.raises(LibraryFileError, match="not a JSON object"):
        TemplateLibrary.load(path)


def test_the_evidence_card_names_the_strategy_the_record_measured(
    library: TemplateLibrary, registry: TemplateRegistry
) -> None:
    """Admitting on evidence from a different trade is a human's call — and must be visible."""
    entry = library.admit(
        override_reason=OVERRIDE,
        template=registry.get("short_atm_straddle_hold_n"),
        decision_path=DECISION_RECORD,
        by="tester",
        reason="the mismatch must be inspectable",
    )
    assert entry.evidence.measured_strategy == "short_atm_straddle"
    assert entry.evidence.measured_strategy_parameters
    assert "runs.in_sample.strategy" in entry.evidence.provenance["measured_strategy"]


def test_saving_over_entries_another_writer_added_is_refused(
    tmp_path: Path, clock: ManualClock, registry: TemplateRegistry
) -> None:
    """Two processes both loaded the file; the first to save must not vanish."""
    path = tmp_path / "shared.json"
    template = registry.get("short_atm_straddle_hold_n")

    first = TemplateLibrary(path, clock=clock)
    first.admit(
        template=template,
        decision_path=DECISION_RECORD,
        by="first",
        reason="one",
        override_reason=OVERRIDE,
    )
    second = TemplateLibrary(path, clock=clock)
    second.admit(
        template=template,
        decision_path=DECISION_RECORD,
        by="second",
        reason="two",
        override_reason=OVERRIDE,
    )
    second.save()

    with pytest.raises(AppendOnlyLibraryError, match="not a prefix"):
        first.save()


def test_an_admission_record_round_trips_through_its_dict(
    library: TemplateLibrary, registry: TemplateRegistry
) -> None:
    entry = library.admit(
        override_reason=OVERRIDE,
        template=registry.get("short_atm_straddle_hold_n"),
        decision_path=DECISION_RECORD,
        by="tester",
        reason="round trip",
        notes="a note",
    )
    assert AdmissionRecord.from_dict(entry.as_dict()) == entry


def test_the_admission_timestamp_comes_from_the_injected_clock(
    library: TemplateLibrary, registry: TemplateRegistry, clock: ManualClock
) -> None:
    """Nothing in this package reads the wall clock; a stored time is evidence of when."""
    del clock
    entry = library.admit(
        override_reason=OVERRIDE,
        template=registry.get("short_atm_straddle_hold_n"),
        decision_path=DECISION_RECORD,
        by="tester",
        reason="pinned time",
    )
    assert entry.admitted_at.startswith("2026-08-12T09:15")


# ------------------------------------------------------- the hold-N state machine


def _short_position(symbol: str, expiry: dt.date):
    """One short leg, as `_exit_intents` reads it: a contract, signed units, and the flag."""
    contract = Contract(
        trading_symbol=symbol,
        underlying="NIFTY",
        expiry=expiry,
        strike=23_000.0,
        option_type="CE" if symbol.endswith("CE") else "PE",
        lot_size=65,
        tick_size=0.05,
    )
    return SimpleNamespace(contract=contract, units=-65, is_short=True)


#: A short whose contract outlives any hold this file walks, so the exit is always
#: expressible and the walk reports the counter's decision rather than a settlement.
_LIVE_SHORT = (_short_position("NIFTY-WALK-CE", dt.date(2026, 12, 31)),)


class _LadderUniverse:
    """A strike ladder of a stated coarseness, and the contracts listed on it."""

    def __init__(self, expiry: dt.date, spot: float, step: float) -> None:
        self._expiry = expiry
        self._step = step
        self._spot = spot

    def nearest_expiry(self, on: dt.date) -> dt.date:
        del on
        return self._expiry

    def atm_strike(self, spot: float, expiry: dt.date) -> float:
        del expiry
        return round(spot / self._step) * self._step

    def get(self, expiry: dt.date, strike: float, option_type: str):
        return Contract(
            trading_symbol=f"NIFTY-{expiry:%d%b%Y}-{strike:g}-{option_type}",
            underlying="NIFTY",
            expiry=expiry,
            strike=strike,
            option_type=option_type,
            lot_size=65,
            tick_size=0.05,
        )

    def by_symbol(self, trading_symbol: str):
        return trading_symbol


class _LadderSession:
    """A session view with a coarse strike ladder and a flat spot."""

    def __init__(self, session_date: dt.date, *, expiry: dt.date, spot: float, step: float) -> None:
        self.session_date = session_date
        self.universe = _LadderUniverse(expiry, spot, step)
        self._spot = spot

    def spot_at(self, minute) -> float:
        del minute
        return self._spot


class _FakeBook:
    """The two members :meth:`HoldNShortStraddle.decide` reads of its book.

    A whole :class:`~xman_research.backtest.engine.BookView` needs `Position` objects with
    contracts; what the counter's behaviour actually depends on is whether the book is flat
    and, at exit, which shorts it holds. Both are supplied directly so each step of the walk
    below says plainly what state the strategy was handed.
    """

    def __init__(self, positions: tuple = ()) -> None:
        self._positions = positions

    @property
    def is_flat(self) -> bool:
        return not self._positions

    def positions(self) -> tuple:
        return self._positions


class _FakeUniverse:
    """Answers the one question the exit rule asks: is this leg still listed today."""

    def __init__(self, positions=()) -> None:
        self._listed = {position.contract.trading_symbol for position in positions}

    def by_symbol(self, trading_symbol: str):
        return trading_symbol if trading_symbol in self._listed else None


class _FakeSession:
    """The two attributes the conditioner gate, the hold counter and the exit rule read."""

    def __init__(self, session_date: dt.date, positions=()) -> None:
        self.session_date = session_date
        self.universe = _FakeUniverse(positions)


def _walk(strategy, days, holding_after_entry: bool = True) -> list[str]:
    """Drive ``decide`` across ``days``, reporting what it asked for on each.

    ``entry`` and ``exit`` are reported from the intent tags; ``hold`` means the strategy
    was holding and asked for nothing. The book is faked from the walk's own history rather
    than from a running engine, which is the point: the counter is what is under test, and
    an engine would decide the same question the counter is supposed to answer.
    """
    seen: list[str] = []
    holding = False
    for day, entered in days:
        book = _FakeBook(() if not holding else _LIVE_SHORT)
        intents = strategy.decide(
            session=_FakeSession(day, book.positions()), minute=None, book=book
        )
        tags = {intent.tag for intent in intents}
        if "entry" in tags:
            seen.append("entry")
            holding = holding_after_entry and entered
        elif "exit" in tags:
            seen.append("exit")
            holding = False
        else:
            seen.append("hold" if holding else "no_entry")
    return seen


class _AlwaysEnters(HoldNShortStraddle):
    """A hold-N straddle whose market-side refusals are removed, so only the clock is left.

    The entry rules — a listed expiry far enough out, a positive spot, both legs present, a
    size above half a contract — are exercised against real sessions elsewhere. Removing
    them here isolates the one thing this test is about: when the counter says to exit.
    """

    def _entry(self, *, session, minute):
        del session, minute
        return (
            TradeIntent(
                trading_symbol="NIFTY-TEST-CE",
                side=Side.SELL,
                lots=1,
                tag="entry",
                leg_group="g",
            ),
        )


def _sessions(count: int) -> list[dt.date]:
    start = dt.date(2026, 4, 6)
    return [start + dt.timedelta(days=index) for index in range(count)]


def test_a_one_session_hold_enters_and_exits_on_the_next_session() -> None:
    days = _sessions(4)
    walk = _walk(_AlwaysEnters(hold_sessions=1), [(day, True) for day in days])
    assert walk == ["entry", "exit", "entry", "exit"]


def test_a_three_session_hold_waits_three_sessions_before_exiting() -> None:
    days = _sessions(6)
    walk = _walk(_AlwaysEnters(hold_sessions=3), [(day, True) for day in days])
    assert walk == ["entry", "hold", "hold", "exit", "entry", "hold"]


def test_a_second_decision_minute_on_the_entry_session_does_not_age_the_position() -> None:
    """The counter advances on a change of session date, not on a call."""
    strategy = _AlwaysEnters(hold_sessions=1)
    first, second = _sessions(2)
    walk = _walk(strategy, [(first, True), (first, True), (second, True)])
    assert walk == ["entry", "hold", "exit"]


def test_an_entry_the_market_refused_leaves_the_strategy_flat_and_ready_to_re_enter() -> None:
    """A refused entry must not start the clock on a position that was never opened."""
    days = _sessions(3)
    walk = _walk(
        _AlwaysEnters(hold_sessions=1), [(day, True) for day in days], holding_after_entry=False
    )
    assert walk == ["entry", "entry", "entry"]


def test_a_position_that_settled_inside_the_hold_leaves_the_strategy_ready_to_re_enter() -> None:
    """A contract expiring inside the hold cash-settles; the next session is flat again."""
    strategy = _AlwaysEnters(hold_sessions=3)
    first, second, third = _sessions(3)
    assert [
        intent.tag
        for intent in strategy.decide(session=_FakeSession(first), minute=None, book=_FakeBook())
    ] == ["entry"]
    # The engine settles the contract, so the strategy next sees a flat book mid-hold.
    intents = strategy.decide(session=_FakeSession(second), minute=None, book=_FakeBook())
    assert [intent.tag for intent in intents] == ["entry"]
    # ...and the counter restarted with it, rather than carrying the dead position's age.
    assert (
        strategy.decide(
            session=_FakeSession(third, _LIVE_SHORT), minute=None, book=_FakeBook(_LIVE_SHORT)
        )
        == ()
    )


def test_a_strategy_first_handed_a_book_it_did_not_open_still_exits() -> None:
    """Unreachable through the engine, which always starts flat, but the invariant holds."""
    strategy = _AlwaysEnters(hold_sessions=1)
    first, second = _sessions(2)
    assert (
        strategy.decide(
            session=_FakeSession(first, _LIVE_SHORT), minute=None, book=_FakeBook(_LIVE_SHORT)
        )
        == ()
    )
    intents = strategy.decide(
        session=_FakeSession(second, _LIVE_SHORT), minute=None, book=_FakeBook(_LIVE_SHORT)
    )
    assert [intent.tag for intent in intents] == ["exit"]


def test_the_exit_buys_back_every_short_as_one_group_and_skips_a_contract_expiring_today() -> None:
    """Closing one leg of a straddle and not the other would leave a naked short."""
    from xman_research.backtest.market import Contract

    def position(symbol: str, expiry: dt.date):
        contract = Contract(
            trading_symbol=symbol,
            underlying="NIFTY",
            expiry=expiry,
            strike=23_000.0,
            option_type="CE" if symbol.endswith("CE") else "PE",
            lot_size=65,
            tick_size=0.05,
        )
        return SimpleNamespace(contract=contract, units=-65, is_short=True)

    exit_day = dt.date(2026, 4, 9)
    book = _FakeBook(
        (
            position("NIFTY-A-CE", exit_day + dt.timedelta(days=7)),
            position("NIFTY-A-PE", exit_day + dt.timedelta(days=7)),
            position("NIFTY-B-CE", exit_day),
        )
    )
    intents = _exit_intents(_FakeSession(exit_day, book.positions()), book, "g")
    assert {intent.trading_symbol for intent in intents} == {"NIFTY-A-CE", "NIFTY-A-PE"}
    assert len({intent.leg_group for intent in intents}) == 1
    assert all(intent.side is Side.BUY for intent in intents)


def test_a_single_point_band_needs_the_gate_only_shape(registry: TemplateRegistry) -> None:
    """A depth-based strength over a band with no interior is identically zero forever."""
    with pytest.raises(ValueError, match="single-point band"):
        ConditionerSpec(
            feature="day_of_week",
            comparator=Comparator.WITHIN,
            threshold=1.0,
            upper_threshold=1.0,
            saturation_span=1.0,
            lookback_sessions=1,
        )


def test_the_weekday_conditioner_fires_at_full_strength_rather_than_at_zero(
    registry: TemplateRegistry,
) -> None:
    """The ranker multiplies strength into the score, so a permanent zero is a mute template."""
    spec = registry.get("short_atm_straddle_day_of_week").conditioner
    assert spec is not None
    assert spec.fires(1.0) is True
    assert spec.strength(1.0) == 1.0
    assert spec.fires(2.0) is False
    assert spec.strength(2.0) == 0.0


def test_two_legs_at_different_offsets_landing_on_one_strike_refuse_the_session() -> None:
    """A strangle whose legs round onto the ATM rung is a straddle wearing another name."""
    expiry = dt.date(2026, 5, 5)
    session = _LadderSession(dt.date(2026, 4, 24), expiry=expiry, spot=23_000.0, step=500.0)
    strangle = HoldNShortStrangle(
        atr_multiple=0.5,
        min_calendar_days_to_expiry=4,
        # An average true range of 100 puts each leg 50 points from spot, well inside the
        # 500-point ladder, so both round onto the at-the-money rung.
        feature_series={ATR_14: {session.session_date: 100.0}},
    )
    assert strangle.decide(session=session, minute=None, book=_FakeBook()) == ()

    # Four times as wide clears the rung and the structure trades.
    wide = HoldNShortStrangle(
        atr_multiple=0.5,
        min_calendar_days_to_expiry=4,
        feature_series={ATR_14: {session.session_date: 2_000.0}},
    )
    intents = wide.decide(session=session, minute=None, book=_FakeBook())
    assert len(intents) == 2
    assert len({intent.trading_symbol for intent in intents}) == 2


def test_an_exit_skips_a_leg_the_session_no_longer_lists_and_closes_the_rest() -> None:
    """No closing order can be expressed against a contract that is not in the universe."""
    listed = _LIVE_SHORT[0]
    delisted = _short_position("NIFTY-GONE-PE", dt.date(2026, 12, 31))
    book = _FakeBook((listed, delisted))
    # The universe holds only the first leg — the second has left the instrument master.
    session = _FakeSession(dt.date(2026, 4, 24), (listed,))
    intents = _exit_intents(session, book, "g")
    assert [intent.trading_symbol for intent in intents] == [listed.contract.trading_symbol]
    assert {intent.leg_group for intent in intents} == {"g"}


def test_saving_over_entries_written_before_an_optional_field_existed_still_appends(
    tmp_path: Path, clock: ManualClock, registry: TemplateRegistry
) -> None:
    """Adding an optional field must not make every library written before it unappendable.

    The append-only check compares stored entries against what is about to be written. Raw,
    an older entry has no key for a newly added optional field while a fresh one has an
    explicit null, so the two would differ and `save` would report a concurrent writer that
    never existed.
    """
    path = tmp_path / "older.json"
    library = TemplateLibrary(path, clock=clock)
    library.admit(
        template=registry.get("short_atm_straddle_hold_n"),
        decision_path=DECISION_RECORD,
        by="first",
        reason="one",
        status=AdmissionStatus.CANDIDATE,
    )
    library.save()

    # Strip the field, as a library written before it existed would be.
    document = json.loads(path.read_text())
    for entry in document["entries"]:
        del entry["override_reason"]
    path.write_text(json.dumps(document, indent=2, sort_keys=True))

    reloaded = TemplateLibrary.load(path, clock=clock)
    reloaded.admit(
        template=registry.get("short_atm_strangle_hold_n"),
        decision_path=DECISION_RECORD,
        by="second",
        reason="two",
        status=AdmissionStatus.CANDIDATE,
    )
    assert reloaded.save() == path
    assert len(TemplateLibrary.load(path).entries()) == 2


def _record_measuring_hold(tmp_path: Path, hold: int) -> Path:
    """A decision record whose in-sample run reports a hold of ``hold`` sessions."""
    payload = json.loads(DECISION_RECORD.read_text())
    payload["runs"]["in_sample"]["strategy_parameters"] = {"hold_sessions": hold}
    path = tmp_path / f"decision_hold_{hold}.json"
    path.write_text(json.dumps(payload))
    return path


def test_admit_refuses_a_record_measuring_a_hold_the_ranker_will_not_trade(
    library: TemplateLibrary, registry: TemplateRegistry, tmp_path: Path
) -> None:
    """A hold-3 record's numbers describe a different trade from the hold-1 the ranker builds."""
    with pytest.raises(AdmittedParametersMismatchError, match="two different trades"):
        library.admit(
            template=registry.get("short_atm_straddle_hold_n"),
            decision_path=_record_measuring_hold(tmp_path, 3),
            by="tester",
            reason="evidence from a longer hold",
            override_reason=OVERRIDE,
        )
    assert library.entries() == ()


def test_the_card_carries_the_hold_the_record_measured_when_the_two_agree(
    library: TemplateLibrary, registry: TemplateRegistry, tmp_path: Path
) -> None:
    entry = library.admit(
        template=registry.get("short_atm_straddle_hold_n"),
        decision_path=_record_measuring_hold(tmp_path, 1),
        by="tester",
        reason="evidence at the hold the ranker trades",
        override_reason=OVERRIDE,
    )
    assert entry.evidence.hold_sessions == 1
    assert entry.evidence.measured_strategy_parameters == {"hold_sessions": 1}


def test_a_record_reporting_no_hold_at_all_falls_back_to_the_template(
    library: TemplateLibrary, registry: TemplateRegistry
) -> None:
    """H1 measured a straddle held to cash settlement, which reports no hold to compare."""
    entry = library.admit(
        template=registry.get("short_atm_straddle_hold_n"),
        decision_path=DECISION_RECORD,
        by="tester",
        reason="a differently shaped piece of evidence, judged by a human",
        override_reason=OVERRIDE,
    )
    assert entry.evidence.hold_sessions == 1


# ------------------------------------------------- the admitted parameter point


def _decision_record(
    tmp_path: Path, *, template_parameters: dict[str, float] | None, hold_sessions: int = 3
) -> Path:
    """A minimal decision record in the shape the stage-two runner writes."""
    run: dict[str, object] = {
        "trial_id": "t-1",
        "strategy": f"hold_{hold_sessions}_short_atm_straddle",
        "strategy_parameters": {"hold_sessions": hold_sessions, "target_notional": 1_500_000.0},
        "metrics": {},
    }
    if template_parameters is not None:
        run["template_parameters"] = template_parameters
    path = tmp_path / "decision.json"
    path.write_text(
        json.dumps(
            {
                "outcome": "fails_threshold",
                "hypothesis_id": "h_point",
                "in_sample": {
                    "window": "2025-10-01..2026-03-31",
                    "trial_id": "t-1",
                    "metrics": {
                        "gate_status": "failed",
                        "sample_length": 119,
                        "annualised_sharpe": 0.4,
                        "deflated_sharpe": 0.1,
                        "max_drawdown": 0.05,
                        "mean_gross_return": 0.002,
                        "mean_cost_drag": 0.0005,
                        "unverified_inputs": [],
                    },
                },
                "runs": {"in_sample": run},
            }
        )
    )
    return path


def test_an_admission_carries_the_point_the_record_measured(tmp_path: Path) -> None:
    """With no point supplied, the record's own point is the one admitted."""
    template = default_registry().get("short_atm_straddle_hold_n")
    point = template.resolve({"hold_sessions": 3})
    record = _decision_record(tmp_path, template_parameters=point)
    library = TemplateLibrary(tmp_path / "library.json")
    entry = library.admit(
        template=template,
        decision_path=record,
        by="tester",
        reason="the record's own point",
        override_reason="evidence failed its gate; admitted for this test",
    )
    assert entry.parameters == point
    assert entry.parameter_key == parameter_key(point)
    assert entry.evidence.parameters == point
    assert entry.evidence.hold_sessions == 3


def test_admitting_a_point_the_record_did_not_measure_is_refused(tmp_path: Path) -> None:
    """The guard compares points, not just holds: a different structure width is caught."""
    template = default_registry().get("short_atm_strangle_hold_n")
    record = _decision_record(
        tmp_path, template_parameters=template.resolve({"atr_multiple": 0.5, "hold_sessions": 3})
    )
    library = TemplateLibrary(tmp_path / "library.json")
    with pytest.raises(AdmittedParametersMismatchError, match="two different trades"):
        library.admit(
            template=template,
            decision_path=record,
            by="tester",
            reason="a wider strangle than the record measured",
            parameters={"atr_multiple": 1.0, "hold_sessions": 3},
            override_reason="evidence failed its gate",
        )


def test_a_record_with_no_point_still_has_its_hold_checked(tmp_path: Path) -> None:
    """Weaker, and deliberately kept: a hold is all a point-less record can be checked on."""
    template = default_registry().get("short_atm_straddle_hold_n")
    record = _decision_record(tmp_path, template_parameters=None, hold_sessions=3)
    library = TemplateLibrary(tmp_path / "library.json")
    with pytest.raises(AdmittedParametersMismatchError, match="names no template"):
        library.admit(
            template=template,
            decision_path=record,
            by="tester",
            reason="hold 1 against a hold-3 record",
            parameters={"hold_sessions": 1},
            override_reason="evidence failed its gate",
        )


def test_one_template_admitted_at_two_points_is_two_admissions(tmp_path: Path) -> None:
    """The ranker instantiates each, so the library must not collapse them."""
    template = default_registry().get("short_atm_straddle_hold_n")
    library = TemplateLibrary(tmp_path / "library.json")
    for hold in (1, 3):
        point = template.resolve({"hold_sessions": hold})
        library.admit(
            template=template,
            decision_path=_decision_record(
                tmp_path / f"h{hold}", template_parameters=point, hold_sessions=hold
            ),
            by="tester",
            reason=f"hold {hold}",
            override_reason="evidence failed its gate",
        )
    admitted = library.admitted()
    assert len(admitted) == 2
    assert {entry.parameter_key for entry in admitted} == {
        parameter_key(template.resolve({"hold_sessions": hold})) for hold in (1, 3)
    }

    # A bare id now names two different trades, and demoting one must not touch the other.
    with pytest.raises(AmbiguousParameterPointError, match="parameter points"):
        library.current(template.template_id)
    library.demote(
        template_id=template.template_id,
        by="tester",
        reason="hold 1 drifted",
        parameters={"hold_sessions": 1},
    )
    survivors = library.admitted()
    assert len(survivors) == 1
    assert survivors[0].parameters["hold_sessions"] == 3
