"""The nightly scan: what it ranks, what it refuses, and what it says about both.

Unit assertions and the end-to-end integration run share one synthetic corpus, because the
interesting properties of a ranker are only visible once a whole sheet exists: an ordering
needs two ideas, a skip reason needs a candidate that survived far enough to be skipped for
that reason rather than an earlier one, and determinism needs a document to compare.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from alpha_helpers import (
    DECISION_MINUTE_INDEX,
    FLAT_SPOT,
    LOT_SIZE,
    STEP,
    trading_days,
    write_corpus,
)
from xman_research import ManualClock, StaticCodeVersion
from xman_research.alpha.explain import (
    RATIONALE_SCHEMA_VERSION,
    TriggerExplanation,
    invalidators_for,
)
from xman_research.alpha.features import FeatureBuilder
from xman_research.alpha.library import AdmissionStatus, TemplateLibrary
from xman_research.alpha.ranker import (
    SKIP_INFEASIBLE,
    SKIP_NO_ENTRY,
    SKIP_NO_FEATURES,
    SKIP_TEMPLATE_NOT_REGISTERED,
    SKIP_TRIGGER_DID_NOT_FIRE,
    IdeaSheet,
    NightlyScan,
)
from xman_research.alpha.templates import (
    Comparator,
    ConditionerSpec,
    HoldNShortStraddle,
    StrategyTemplate,
    TemplateRegistry,
    default_registry,
)
from xman_research.session_store import SessionStore

DECISION_RECORD = Path("research/h1/decision.json")
SESSION_COUNT = 30
LAST_SESSION = dt.date(2026, 4, 24)


@pytest.fixture
def corpus(synthetic_store) -> tuple[SessionStore, list[dt.date]]:
    """Thirty sessions on a gently trending path, quoting one expiry two weeks out."""
    sessions = trading_days(SESSION_COUNT, ending=LAST_SESSION)
    write_corpus(
        synthetic_store.root,
        sessions=sessions,
        spot_for=lambda index: FLAT_SPOT + STEP * (index % 3),
        expiry=sessions[-1] + dt.timedelta(days=14),
    )
    return synthetic_store(), sessions


def _library(tmp_path: Path, clock: ManualClock, *template_ids: str) -> TemplateLibrary:
    library = TemplateLibrary(tmp_path / "templates.json", clock=clock)
    registry = default_registry()
    for template_id in template_ids:
        library.admit(
            template=registry.get(template_id),
            decision_path=DECISION_RECORD,
            by="tester",
            reason="exercising the ranker against the anchor hypothesis's evidence",
        )
    return library


def _scan(
    store: SessionStore,
    library: TemplateLibrary,
    as_of: dt.date,
    *,
    registry: TemplateRegistry | None = None,
    top_n: int = 10,
    clock: ManualClock | None = None,
    **kwargs,
) -> IdeaSheet:
    return NightlyScan(
        store=store,
        registry=registry if registry is not None else default_registry(),
        library=library,
        as_of=as_of,
        universe=["NIFTY"],
        top_n=top_n,
        feature_builder=FeatureBuilder(store, regime_lookback_sessions=10),
        clock=clock or ManualClock(dt.datetime(2026, 4, 24, 18, 0, tzinfo=dt.UTC)),
        code_version=StaticCodeVersion("0" * 40, dirty=False),
        **kwargs,
    ).run()


# ------------------------------------------------------------------------ end to end


def test_a_scan_over_one_admitted_template_produces_a_ranked_idea(
    corpus: tuple[SessionStore, list[dt.date]], tmp_path: Path, clock: ManualClock
) -> None:
    store, sessions = corpus
    sheet = _scan(store, _library(tmp_path, clock, "short_atm_straddle_hold_n"), sessions[-1])

    assert len(sheet.ideas) == 1
    idea = sheet.ideas[0]
    assert idea.rank == 1
    assert idea.template_id == "short_atm_straddle_hold_n"
    assert idea.underlying == "NIFTY"
    assert idea.score > 0
    assert idea.granted_lots >= 1
    assert idea.margin_total > 0
    assert sheet.no_ideas_reason is None
    assert sheet.as_of == sessions[-1].isoformat()


def test_the_sheet_serialises_to_json_with_every_rationale_intact(
    corpus: tuple[SessionStore, list[dt.date]], tmp_path: Path, clock: ManualClock
) -> None:
    store, sessions = corpus
    sheet = _scan(store, _library(tmp_path, clock, "short_atm_straddle_hold_n"), sessions[-1])
    document = json.loads(json.dumps(sheet.as_dict()))

    assert document["schema_version"] >= 1
    for idea in document["ideas"]:
        rationale = idea["rationale"]
        assert rationale["schema_version"] == RATIONALE_SCHEMA_VERSION
        assert rationale["thesis"]
        assert rationale["trigger"]["fired"] is True
        assert rationale["evidence"]["n_observations"] == 79
        assert rationale["trade"]["legs"]
        assert rationale["trade"]["hold_sessions"] == 1
        assert rationale["invalidators"]
        assert rationale["provenance"]


def test_two_scans_of_the_same_inputs_produce_identical_documents(
    corpus: tuple[SessionStore, list[dt.date]], tmp_path: Path, clock: ManualClock
) -> None:
    """The two quantities that legitimately vary — wall clock and code version — are injected."""
    store, sessions = corpus
    library = _library(tmp_path, clock, "short_atm_straddle_hold_n")
    first = _scan(store, library, sessions[-1]).as_dict()
    second = _scan(store, library, sessions[-1]).as_dict()
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_the_sheet_stamps_the_injected_clock_and_code_version(
    corpus: tuple[SessionStore, list[dt.date]], tmp_path: Path, clock: ManualClock
) -> None:
    store, sessions = corpus
    sheet = _scan(store, _library(tmp_path, clock, "short_atm_straddle_hold_n"), sessions[-1])
    assert sheet.generated_at.startswith("2026-04-24T18:00")
    assert sheet.code_version == "0" * 40


# ------------------------------------------------------------------------- ordering


def test_ideas_are_ordered_by_score_and_ties_break_deterministically(
    corpus: tuple[SessionStore, list[dt.date]], tmp_path: Path, clock: ManualClock
) -> None:
    """A second template on the same trade, firing at less than full strength, ranks below."""
    store, sessions = corpus
    registry = default_registry()
    registry.register(
        StrategyTemplate(
            template_id="a_weaker_sibling",
            name="a weaker sibling",
            thesis="the same trade, gated on a condition it barely clears today",
            products=("NIFTY",),
            hold_sessions=1,
            parameters={},
            # Reads the implied level rather than the spread, so the strength is the
            # fixture's own implied volatility and does not depend on the price path.
            conditioner=ConditionerSpec(
                feature="atm_iv",
                comparator=Comparator.AT_LEAST,
                threshold=0.0,
                saturation_span=1.0,
                lookback_sessions=1,
            ),
            builder=lambda params, underlying, signal: HoldNShortStraddle(
                min_calendar_days_to_expiry=4
            ),
        )
    )
    library = TemplateLibrary(tmp_path / "templates.json", clock=clock)
    for template_id in ("short_atm_straddle_hold_n", "a_weaker_sibling"):
        library.admit(
            template=registry.get(template_id),
            decision_path=DECISION_RECORD,
            by="tester",
            reason="two templates so the ordering has something to order",
        )

    sheet = _scan(store, library, sessions[-1], registry=registry)
    assert [idea.template_id for idea in sheet.ideas] == [
        "short_atm_straddle_hold_n",
        "a_weaker_sibling",
    ]
    assert [idea.rank for idea in sheet.ideas] == [1, 2]
    assert sheet.ideas[0].signal_strength == 1.0
    assert sheet.ideas[1].signal_strength < 1.0


def test_top_n_truncates_after_ranking_not_before(
    corpus: tuple[SessionStore, list[dt.date]], tmp_path: Path, clock: ManualClock
) -> None:
    store, sessions = corpus
    sheet = _scan(
        store, _library(tmp_path, clock, "short_atm_straddle_hold_n"), sessions[-1], top_n=1
    )
    assert len(sheet.ideas) == 1


# ---------------------------------------------------------------------------- skips


def test_a_template_whose_conditioner_does_not_fire_is_skipped_with_the_reading(
    corpus: tuple[SessionStore, list[dt.date]], tmp_path: Path, clock: ManualClock
) -> None:
    store, sessions = corpus
    sheet = _scan(store, _library(tmp_path, clock, "short_atm_straddle_iv_rv"), sessions[-1])
    assert sheet.ideas == ()
    assert len(sheet.skipped) == 1
    skip = sheet.skipped[0]
    assert skip.reason == SKIP_TRIGGER_DID_NOT_FIRE
    assert "iv_minus_rv_20" in skip.detail
    assert sheet.no_ideas_reason is not None
    assert SKIP_TRIGGER_DID_NOT_FIRE in sheet.no_ideas_reason


def test_a_template_the_library_admits_but_no_registry_holds_is_skipped_by_name(
    corpus: tuple[SessionStore, list[dt.date]], tmp_path: Path, clock: ManualClock
) -> None:
    store, sessions = corpus
    library = _library(tmp_path, clock, "short_atm_straddle_hold_n")
    sheet = _scan(store, library, sessions[-1], registry=TemplateRegistry())
    assert sheet.ideas == ()
    assert sheet.skipped[0].reason == SKIP_TEMPLATE_NOT_REGISTERED


def test_a_candidate_the_market_could_not_absorb_is_skipped_with_the_binding_cap(
    synthetic_store, tmp_path: Path, clock: ManualClock
) -> None:
    """A contract nothing traded in is infeasible, and the sheet says which cap bound it."""
    sessions = trading_days(SESSION_COUNT, ending=LAST_SESSION)
    write_corpus(
        synthetic_store.root,
        sessions=sessions,
        spot_for=lambda index: FLAT_SPOT + STEP * (index % 3),
        expiry=sessions[-1] + dt.timedelta(days=14),
        volume=0.0,
    )
    sheet = _scan(
        synthetic_store(),
        _library(tmp_path, clock, "short_atm_straddle_hold_n"),
        sessions[-1],
    )
    assert sheet.ideas == ()
    assert sheet.skipped[0].reason == SKIP_INFEASIBLE
    assert "nothing traded" in sheet.skipped[0].detail


def test_a_session_whose_only_expiry_is_too_close_produces_no_entry(
    synthetic_store, tmp_path: Path, clock: ManualClock
) -> None:
    sessions = trading_days(SESSION_COUNT, ending=LAST_SESSION)
    write_corpus(
        synthetic_store.root,
        sessions=sessions,
        spot_for=lambda _: FLAT_SPOT,
        expiry=sessions[-1] + dt.timedelta(days=1),
    )
    sheet = _scan(
        synthetic_store(),
        _library(tmp_path, clock, "short_atm_straddle_hold_n"),
        sessions[-1],
    )
    assert sheet.ideas == ()
    assert sheet.skipped[0].reason == SKIP_NO_ENTRY


def test_an_empty_library_says_so_rather_than_returning_a_blank_sheet(
    corpus: tuple[SessionStore, list[dt.date]], tmp_path: Path, clock: ManualClock
) -> None:
    store, sessions = corpus
    empty = TemplateLibrary(tmp_path / "templates.json", clock=clock)
    sheet = _scan(store, empty, sessions[-1])
    assert sheet.ideas == ()
    assert sheet.no_ideas_reason is not None
    assert "admits no templates" in sheet.no_ideas_reason


def test_a_demoted_template_is_no_longer_proposed(
    corpus: tuple[SessionStore, list[dt.date]], tmp_path: Path, clock: ManualClock
) -> None:
    store, sessions = corpus
    library = _library(tmp_path, clock, "short_atm_straddle_hold_n")
    assert _scan(store, library, sessions[-1]).ideas
    library.demote(
        template_id="short_atm_straddle_hold_n", by="tester", reason="live outcomes disagree"
    )
    assert library.status("short_atm_straddle_hold_n") is AdmissionStatus.DEMOTED
    assert _scan(store, library, sessions[-1]).ideas == ()


def test_a_candidate_that_was_never_admitted_is_not_proposed(
    corpus: tuple[SessionStore, list[dt.date]], tmp_path: Path, clock: ManualClock
) -> None:
    store, sessions = corpus
    library = TemplateLibrary(tmp_path / "templates.json", clock=clock)
    library.admit(
        template=default_registry().get("short_atm_straddle_hold_n"),
        decision_path=DECISION_RECORD,
        by="tester",
        reason="filed as evidence only",
        status=AdmissionStatus.CANDIDATE,
    )
    assert _scan(store, library, sessions[-1]).ideas == ()


# -------------------------------------------------------------------------- honesty


def test_a_sheet_resting_on_evidence_that_failed_its_gate_says_so_on_its_face(
    corpus: tuple[SessionStore, list[dt.date]], tmp_path: Path, clock: ManualClock
) -> None:
    """The shipped H1 record failed its gate, and an operator must not have to dig for that."""
    store, sessions = corpus
    sheet = _scan(store, _library(tmp_path, clock, "short_atm_straddle_hold_n"), sessions[-1])
    assert sheet.rests_on_unpassed_evidence is True
    assert sheet.ideas[0].rationale.gate_status == "failed"


def test_expected_edge_comes_from_the_admission_record_not_from_a_run(
    corpus: tuple[SessionStore, list[dt.date]], tmp_path: Path, clock: ManualClock
) -> None:
    store, sessions = corpus
    library = _library(tmp_path, clock, "short_atm_straddle_hold_n")
    card = library.admitted()[0].evidence
    idea = _scan(store, library, sessions[-1]).ideas[0]
    assert idea.expected_edge == pytest.approx(card.mean_return_at_hold)
    assert idea.regime_factor == 1.0


def test_the_score_is_expected_edge_times_strength_over_the_margin_ratio(
    corpus: tuple[SessionStore, list[dt.date]], tmp_path: Path, clock: ManualClock
) -> None:
    store, sessions = corpus
    idea = _scan(store, _library(tmp_path, clock, "short_atm_straddle_hold_n"), sessions[-1]).ideas[
        0
    ]
    assert idea.score == pytest.approx(
        idea.expected_edge * idea.signal_strength / idea.margin_ratio
    )


def test_the_trade_spec_names_real_trading_symbols_and_a_balanced_structure(
    corpus: tuple[SessionStore, list[dt.date]], tmp_path: Path, clock: ManualClock
) -> None:
    store, sessions = corpus
    trade = (
        _scan(store, _library(tmp_path, clock, "short_atm_straddle_hold_n"), sessions[-1])
        .ideas[0]
        .rationale.trade
    )

    assert len(trade.legs) == 2
    assert {leg.option_type for leg in trade.legs} == {"CE", "PE"}
    assert len({leg.strike for leg in trade.legs}) == 1
    assert len({leg.lots for leg in trade.legs}) == 1
    assert all(leg.side == "sell" for leg in trade.legs)
    assert all(leg.lot_size == LOT_SIZE for leg in trade.legs)
    assert trade.max_loss is None
    assert "unbounded" in trade.max_loss_reason
    assert trade.premium_received is not None and trade.premium_received > 0


def test_every_number_in_a_rationale_names_a_source(
    corpus: tuple[SessionStore, list[dt.date]], tmp_path: Path, clock: ManualClock
) -> None:
    store, sessions = corpus
    rationale = (
        _scan(store, _library(tmp_path, clock, "short_atm_straddle_hold_n"), sessions[-1])
        .ideas[0]
        .rationale
    )
    for quantity in (
        "thesis",
        "evidence",
        "regime",
        "trade.legs",
        "trade.margin",
        "expected_edge",
        "signal_strength",
        "score",
        "feasibility",
        "annualised_sharpe",
        "mean_return_at_hold",
    ):
        assert rationale.provenance.get(quantity)


def test_an_idea_surfaces_its_breached_invalidators_beside_the_score(
    corpus: tuple[SessionStore, list[dt.date]], tmp_path: Path, clock: ManualClock
) -> None:
    store, sessions = corpus
    idea = _scan(store, _library(tmp_path, clock, "short_atm_straddle_hold_n"), sessions[-1]).ideas[
        0
    ]
    assert set(idea.breached_invalidators) <= {rule.name for rule in idea.rationale.invalidators}
    assert idea.as_dict()["breached_invalidators"] == list(idea.breached_invalidators)


# ---------------------------------------------------------------------- invalidators


def test_invalidators_are_derived_from_the_same_features_the_trigger_read(
    corpus: tuple[SessionStore, list[dt.date]], tmp_path: Path, clock: ManualClock
) -> None:
    del tmp_path, clock
    store, sessions = corpus
    frame = FeatureBuilder(store, regime_lookback_sessions=10).build("NIFTY", sessions[-1])
    template = default_registry().get("short_atm_straddle_iv_rv")
    rules = invalidators_for(template, frame, expiry=sessions[-1], spot=FLAT_SPOT)
    names = {rule.name for rule in rules}
    assert {"overnight_gap", "implied_below_realised", "contract_expires_inside_hold"} <= names
    assert "iv_minus_rv_20_below_threshold" in names
    for rule in rules:
        assert rule.rule


def test_a_conditioner_reading_a_missing_feature_reports_it_as_unfired(
    corpus: tuple[SessionStore, list[dt.date]], tmp_path: Path, clock: ManualClock
) -> None:
    del tmp_path, clock
    store, sessions = corpus
    frame = FeatureBuilder(store, regime_lookback_sessions=10).build("NIFTY", sessions[-1])
    absent = ConditionerSpec(
        feature="a_feature_nobody_computes",
        comparator=Comparator.AT_LEAST,
        threshold=0.0,
        saturation_span=1.0,
        lookback_sessions=1,
    )
    trigger = TriggerExplanation.from_conditioner(absent, frame)
    assert trigger.fired is False
    assert trigger.strength == 0.0
    assert trigger.value is None


# ------------------------------------------------------------------------- refusals


def test_a_scan_refuses_a_top_n_below_one(
    corpus: tuple[SessionStore, list[dt.date]], tmp_path: Path, clock: ManualClock
) -> None:
    store, sessions = corpus
    with pytest.raises(ValueError, match="top_n must be at least 1"):
        _scan(store, _library(tmp_path, clock), sessions[-1], top_n=0)


def test_a_scan_refuses_an_empty_universe(
    corpus: tuple[SessionStore, list[dt.date]], tmp_path: Path, clock: ManualClock
) -> None:
    store, sessions = corpus
    with pytest.raises(ValueError, match="at least one underlying"):
        NightlyScan(
            store=store,
            registry=default_registry(),
            library=_library(tmp_path, clock),
            as_of=sessions[-1],
            universe=[],
        )


# ------------------------------------------------------------- look-ahead and resilience


def test_bars_printed_after_the_decision_minute_move_no_part_of_the_sheet(
    synthetic_store, tmp_path: Path, clock: ManualClock
) -> None:
    """The feature tests pin the frame; this pins everything downstream of it.

    A post-decision print could in principle move the spot the at-the-money strike is chosen
    from, and therefore the legs, the margin and the score. It does not, because the scan
    reads the session through the same truncated view the features do — and this is what
    says so.
    """
    sessions = trading_days(SESSION_COUNT, ending=LAST_SESSION)
    expiry = sessions[-1] + dt.timedelta(days=14)
    write_corpus(
        synthetic_store.root,
        sessions=sessions,
        spot_for=lambda index: FLAT_SPOT + STEP * (index % 3),
        expiry=expiry,
    )
    library = _library(tmp_path, clock, "short_atm_straddle_hold_n")
    quiet = _scan(synthetic_store(), library, sessions[-1]).as_dict()

    write_corpus(
        synthetic_store.root,
        sessions=[sessions[-1]],
        spot_for=lambda _: FLAT_SPOT + STEP * ((SESSION_COUNT - 1) % 3),
        expiry=expiry,
        spot_by_minute={index: FLAT_SPOT * 1.5 for index in range(DECISION_MINUTE_INDEX + 1, 375)},
        spot_by_minute_on=sessions[-1],
    )
    violent = _scan(synthetic_store(), library, sessions[-1]).as_dict()
    assert violent == quiet


def test_one_unreadable_product_does_not_silence_the_others(
    corpus: tuple[SessionStore, list[dt.date]], tmp_path: Path, clock: ManualClock
) -> None:
    """A universe is a list, and products are onboarded one at a time."""
    store, sessions = corpus
    sheet = NightlyScan(
        store=store,
        registry=default_registry(),
        library=_library(tmp_path, clock, "short_atm_straddle_hold_n"),
        as_of=sessions[-1],
        universe=["NIFTY", "BANKNIFTY"],
        feature_builder=FeatureBuilder(store, regime_lookback_sessions=10),
        clock=ManualClock(dt.datetime(2026, 4, 24, 18, 0, tzinfo=dt.UTC)),
        code_version=StaticCodeVersion("0" * 40, dirty=False),
    ).run()

    assert [idea.underlying for idea in sheet.ideas] == ["NIFTY"]
    unreadable = [skip for skip in sheet.skipped if skip.reason == SKIP_NO_FEATURES]
    assert [skip.underlying for skip in unreadable] == ["BANKNIFTY"]
    assert unreadable[0].detail


def test_a_scan_whose_every_product_is_unreadable_refuses_rather_than_reporting_a_quiet_night(
    corpus: tuple[SessionStore, list[dt.date]], tmp_path: Path, clock: ManualClock
) -> None:
    store, sessions = corpus
    with pytest.raises(Exception, match=r"BANKNIFTY|not a supported underlying"):
        NightlyScan(
            store=store,
            registry=default_registry(),
            library=_library(tmp_path, clock, "short_atm_straddle_hold_n"),
            as_of=sessions[-1],
            universe=["BANKNIFTY"],
            feature_builder=FeatureBuilder(store, regime_lookback_sessions=10),
            clock=ManualClock(dt.datetime(2026, 4, 24, 18, 0, tzinfo=dt.UTC)),
            code_version=StaticCodeVersion("0" * 40, dirty=False),
        ).run()
