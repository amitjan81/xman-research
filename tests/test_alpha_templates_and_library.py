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

import pytest

from xman_research import ManualClock
from xman_research.alpha.library import (
    AdmissionRecord,
    AdmissionStatus,
    AppendOnlyLibraryError,
    DecisionRecordError,
    EvidenceCard,
    TemplateLibrary,
)
from xman_research.alpha.templates import (
    Comparator,
    ConditionedShortStraddle,
    ConditionerSpec,
    HoldNShortStraddle,
    ParameterRange,
    StrategyTemplate,
    TemplateRegistry,
    UnknownTemplateError,
    default_registry,
)
from xman_research.backtest.engine import Strategy

DECISION_RECORD = Path("research/h1/decision.json")


@pytest.fixture
def registry() -> TemplateRegistry:
    return default_registry()


@pytest.fixture
def library(tmp_path: Path, clock: ManualClock) -> TemplateLibrary:
    return TemplateLibrary(tmp_path / "templates.json", clock=clock)


# ------------------------------------------------------------------------------- registry


def test_the_shipped_registry_holds_the_benchmark_family_and_its_conditional_sibling(
    registry: TemplateRegistry,
) -> None:
    assert registry.ids() == ("short_atm_straddle_hold_n", "short_atm_straddle_iv_rv")
    assert registry.get("short_atm_straddle_hold_n").conditioner is None
    assert registry.get("short_atm_straddle_iv_rv").conditioner is not None


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
            builder=lambda params, underlying, signal: HoldNShortStraddle(),
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
    assert len(registry.for_product("NIFTY")) == 2
    assert registry.for_product("BANKNIFTY") == ()


# ------------------------------------------------------------------------------- building


def test_every_shipped_template_builds_something_satisfying_the_engine_protocol(
    registry: TemplateRegistry,
) -> None:
    for template in registry:
        built = template.build(None, "NIFTY", signal_by_session={dt.date(2026, 4, 24): 0.5})
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
    assert resolved == {"target_notional": 1_500_000.0, "iv_rv_threshold": 0.03}


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
            builder=lambda params, underlying, signal: HoldNShortStraddle(),
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


def test_a_conditioned_strategy_with_no_signal_series_declines_to_enter() -> None:
    """The unsafe direction is a conditional strategy silently trading unconditionally."""
    strategy = ConditionedShortStraddle(
        conditioner=ConditionerSpec(
            feature="iv_minus_rv_20",
            comparator=Comparator.AT_LEAST,
            threshold=0.0,
            saturation_span=0.06,
            lookback_sessions=20,
        )
    )
    assert strategy._may_enter(session=_FakeSession(dt.date(2026, 4, 24)), minute=None) is False
    strategy.signal_by_session = {dt.date(2026, 4, 24): 0.1}
    assert strategy._may_enter(session=_FakeSession(dt.date(2026, 4, 24)), minute=None) is True


class _FakeSession:
    """The one attribute the conditioner gate reads. A whole SessionView is not needed."""

    def __init__(self, session_date: dt.date) -> None:
        self.session_date = session_date


# -------------------------------------------------------------------------------- library


def test_admit_refuses_a_decision_record_that_does_not_exist(
    library: TemplateLibrary, registry: TemplateRegistry, tmp_path: Path
) -> None:
    with pytest.raises(DecisionRecordError, match="no decision record at"):
        library.admit(
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
        library.admit(template=template, decision_path=DECISION_RECORD, by="  ", reason="r")
    with pytest.raises(ValueError, match="requires a written `reason`"):
        library.admit(template=template, decision_path=DECISION_RECORD, by="t", reason="")


def test_admit_does_not_gate_on_the_verdict_and_carries_it_verbatim(
    library: TemplateLibrary, registry: TemplateRegistry
) -> None:
    """The shipped H1 record FAILED its gate, and admitting it is a human's call to make.

    What the framework guarantees is that the call is visible: the verdict is on the card,
    ``passed_gate`` is false, and the ranker flags any sheet resting on it.
    """
    entry = library.admit(
        template=registry.get("short_atm_straddle_hold_n"),
        decision_path=DECISION_RECORD,
        by="tester",
        reason="the anchor hypothesis's evidence, verdict and all",
    )
    assert entry.decision_outcome == "fails_threshold"
    assert entry.evidence.gate_status == "failed"
    assert entry.evidence.passed_gate is False
    assert entry.status is AdmissionStatus.ADMITTED


def test_the_evidence_card_takes_the_mean_return_net_of_costs(
    library: TemplateLibrary, registry: TemplateRegistry
) -> None:
    payload = json.loads(DECISION_RECORD.read_text())
    metrics = payload["in_sample"]["metrics"]
    entry = library.admit(
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
        template=template, decision_path=DECISION_RECORD, by="tester", reason="admitting"
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
    library.admit(template=template, decision_path=DECISION_RECORD, by="tester", reason="admitting")
    library.demote(template_id=template.template_id, by="tester", reason="first")
    with pytest.raises(ValueError, match="already demoted"):
        library.demote(template_id=template.template_id, by="tester", reason="second")


def test_admit_refuses_to_record_a_demotion_that_would_carry_no_reason(
    library: TemplateLibrary, registry: TemplateRegistry
) -> None:
    with pytest.raises(ValueError, match="use demote"):
        library.admit(
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
    library.admit(template=template, decision_path=DECISION_RECORD, by="tester", reason="admitting")
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
    with pytest.raises(DecisionRecordError, match="schema_version"):
        TemplateLibrary.load(path)


def test_saving_over_entries_another_writer_added_is_refused(
    tmp_path: Path, clock: ManualClock, registry: TemplateRegistry
) -> None:
    """Two processes both loaded the file; the first to save must not vanish."""
    path = tmp_path / "shared.json"
    template = registry.get("short_atm_straddle_hold_n")

    first = TemplateLibrary(path, clock=clock)
    first.admit(template=template, decision_path=DECISION_RECORD, by="first", reason="one")
    second = TemplateLibrary(path, clock=clock)
    second.admit(template=template, decision_path=DECISION_RECORD, by="second", reason="two")
    second.save()

    with pytest.raises(AppendOnlyLibraryError, match="not a prefix"):
        first.save()


def test_an_admission_record_round_trips_through_its_dict(
    library: TemplateLibrary, registry: TemplateRegistry
) -> None:
    entry = library.admit(
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
        template=registry.get("short_atm_straddle_hold_n"),
        decision_path=DECISION_RECORD,
        by="tester",
        reason="pinned time",
    )
    assert entry.admitted_at.startswith("2026-08-12T09:15")
