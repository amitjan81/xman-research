"""The idea ledger, over a corpus small enough to compute by hand.

Every settlement figure asserted here is worked out in the test itself rather than captured
from a run, and the drift thresholds are exercised at the boundary rather than near it: the
CUSUM series are built from exact binary fractions so ``cusum <= threshold`` is decided by
arithmetic and not by the last bit of a square root.

The pair of CUSUM tests share one multiset of drifts and differ only in the **order** of it.
That is the property the statistic exists for — a template that gives back the same shortfall
in one sustained run is drifting, and one that alternates around its expectation is not — and
a test that changed the numbers as well as the order would not show it.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from alpha_helpers import FLAT_SPOT, STEP, trading_days, write_corpus
from conftest import ManualClock, SyntheticContract, synthetic_symbol, write_synthetic_session
from xman_research.alpha.features import DEFAULT_DECISION_TIME, FeatureBuilder
from xman_research.alpha.library import AdmissionStatus, TemplateLibrary
from xman_research.alpha.ranker import NightlyScan
from xman_research.alpha.templates import default_registry
from xman_research.alpha.tracking import (
    CUSUM_K,
    DEFAULT_CAPITAL_BASE,
    LEDGER_SCHEMA_VERSION,
    STATUS_SETTLED,
    STATUS_UNMARKABLE,
    UNMARKABLE_CONTRACT_ABSENT,
    UNMARKABLE_NO_ENTRY_PRICE,
    UNMARKABLE_NO_PRINT,
    VERDICT_CUSUM_BREACH,
    VERDICT_NEGATIVE_MEAN_BREACH,
    VERDICT_NOT_ENOUGH_SETTLED,
    VERDICT_WITHIN_TOLERANCE,
    ConflictingSheetError,
    IdeaLedger,
    PresentedIdea,
    Settlement,
    apply_demotions,
    cusum_low,
    one_sided_t_statistic,
)
from xman_research.code_version import StaticCodeVersion

UNDERLYING = "NIFTY"
SPOT = 23_000.0
STRIKE = 23_000.0
LOTS = 1
LOT_SIZE = 65
UNITS = LOTS * LOT_SIZE
TEMPLATE = "short_atm_straddle_hold_n"
GENERATED_AT = "2026-04-22T18:00:00+00:00"
CODE_VERSION = "0" * 40

#: Exact binary fractions, so every partial sum and the sample deviation below are exact and
#: the boundary comparison in the CUSUM rule is decided by arithmetic rather than rounding.
DRIFT_STEP = 2.0**-13
EXPECTED_EDGE = 2.0**-12


@pytest.fixture
def clock() -> ManualClock:
    return ManualClock(dt.datetime(2026, 4, 30, 18, 0, tzinfo=dt.UTC))


def _leg(option_type: str, price: float | None, *, expiry: dt.date, strike: float = STRIKE) -> dict:
    contract = SyntheticContract(
        strike=strike, option_type=option_type, expiry=expiry, close=price or 0.0
    )
    return {
        "trading_symbol": synthetic_symbol(UNDERLYING, contract),
        "side": "sell",
        "lots": LOTS,
        "units": UNITS,
        "lot_size": LOT_SIZE,
        "strike": strike,
        "option_type": option_type,
        "expiry": expiry.isoformat(),
        "price_at_decision_minute": price,
    }


def _sheet(
    *,
    as_of: dt.date,
    legs: list[dict],
    hold_sessions: int = 1,
    expected_edge: float = 0.001,
    template_id: str = TEMPLATE,
    parameters: dict | None = None,
    granted_lots: int = LOTS,
) -> dict:
    """One night's sheet in the shape ``cli scan`` writes, carrying a single idea."""
    return {
        "schema_version": 1,
        "as_of": as_of.isoformat(),
        "generated_at": GENERATED_AT,
        "code_version": CODE_VERSION,
        "universe": [UNDERLYING],
        "decision_time": DEFAULT_DECISION_TIME.isoformat(timespec="minutes"),
        "top_n": 10,
        "participation": {},
        "ideas": [
            {
                "rank": 1,
                "template_id": template_id,
                "parameters": parameters or {"hold_sessions": float(hold_sessions)},
                "parameter_key": "",
                "underlying": UNDERLYING,
                "score": 1.5,
                "expected_edge": expected_edge,
                "signal_strength": 1.0,
                "regime_factor": 1.0,
                "margin_total": 100_000.0,
                "margin_ratio": 0.1,
                "requested_lots": granted_lots,
                "granted_lots": granted_lots,
                "breached_invalidators": [],
                "as_of_inside_evidence_window": False,
                "feasibility": [],
                "rationale": {"trade": {"legs": legs, "hold_sessions": hold_sessions}},
            }
        ],
        "skipped": [],
        "rests_on_unpassed_evidence": False,
        "rests_on_in_sample_evidence": False,
        "no_ideas_reason": None,
    }


def _corpus(root: Path, sessions: list[dt.date], contracts_by_session: dict) -> None:
    for session_date in sessions:
        write_synthetic_session(
            root,
            session_date,
            underlying=UNDERLYING,
            spot=SPOT,
            contracts=contracts_by_session[session_date],
            lot_size=LOT_SIZE,
        )


def _straddle(expiry: dt.date, call: float, put: float) -> list[SyntheticContract]:
    return [
        SyntheticContract(strike=STRIKE, option_type="CE", expiry=expiry, close=call),
        SyntheticContract(strike=STRIKE, option_type="PE", expiry=expiry, close=put),
    ]


# --------------------------------------------------------------------------------------
# Recording
# --------------------------------------------------------------------------------------


def test_record_sheet_round_trips_through_disk(tmp_path: Path, clock: ManualClock) -> None:
    expiry = dt.date(2026, 5, 7)
    as_of = dt.date(2026, 4, 22)
    legs = [_leg("CE", 200.0, expiry=expiry), _leg("PE", 180.0, expiry=expiry)]
    ledger = IdeaLedger(tmp_path / "ledger.json", clock=clock)
    recorded = ledger.record_sheet(_sheet(as_of=as_of, legs=legs, expected_edge=0.0012))
    ledger.save()

    assert len(recorded) == 1
    document = json.loads((tmp_path / "ledger.json").read_text())
    assert document["schema_version"] == LEDGER_SCHEMA_VERSION

    reloaded = IdeaLedger.load(tmp_path / "ledger.json")
    idea = reloaded.presented()[0]
    assert idea.key == (as_of.isoformat(), TEMPLATE, "hold_sessions=1.0", UNDERLYING)
    assert idea.expected_edge == pytest.approx(0.0012)
    assert idea.hold_sessions == 1
    assert idea.granted_lots == LOTS
    assert [leg["trading_symbol"] for leg in idea.legs] == [leg["trading_symbol"] for leg in legs]
    assert reloaded.open_ideas() == (idea,)


def test_recording_the_same_sheet_twice_adds_nothing(tmp_path: Path, clock: ManualClock) -> None:
    expiry = dt.date(2026, 5, 7)
    sheet = _sheet(
        as_of=dt.date(2026, 4, 22),
        legs=[_leg("CE", 200.0, expiry=expiry), _leg("PE", 180.0, expiry=expiry)],
    )
    ledger = IdeaLedger(tmp_path / "ledger.json", clock=clock)
    assert len(ledger.record_sheet(sheet)) == 1
    assert ledger.record_sheet(sheet) == ()
    assert len(ledger.presented()) == 1

    ledger.save()
    # Saving a ledger that recorded nothing new must still be an append of zero entries, not
    # a rewrite the append-only check rejects.
    ledger.save()
    assert len(IdeaLedger.load(tmp_path / "ledger.json").presented()) == 1


def test_a_changed_sheet_for_a_recorded_night_is_refused(
    tmp_path: Path, clock: ManualClock
) -> None:
    expiry = dt.date(2026, 5, 7)
    as_of = dt.date(2026, 4, 22)
    ledger = IdeaLedger(tmp_path / "ledger.json", clock=clock)
    ledger.record_sheet(
        _sheet(as_of=as_of, legs=[_leg("CE", 200.0, expiry=expiry)], expected_edge=0.001)
    )
    with pytest.raises(ConflictingSheetError, match="already holds a different idea"):
        ledger.record_sheet(
            _sheet(as_of=as_of, legs=[_leg("CE", 200.0, expiry=expiry)], expected_edge=0.002)
        )


# --------------------------------------------------------------------------------------
# Settlement arithmetic
# --------------------------------------------------------------------------------------


def test_settles_a_short_straddle_at_the_exit_session_close(
    tmp_path: Path, synthetic_store, clock: ManualClock
) -> None:
    """Sold at 200 and 180, bought back at 150 and 210 — a gain of 1300 on 65 units a leg."""
    sessions = trading_days(3, ending=dt.date(2026, 4, 24))
    expiry = dt.date(2026, 5, 7)
    _corpus(
        synthetic_store.root,
        sessions,
        {
            sessions[0]: _straddle(expiry, call=200.0, put=180.0),
            sessions[1]: _straddle(expiry, call=150.0, put=210.0),
            sessions[2]: _straddle(expiry, call=140.0, put=220.0),
        },
    )
    ledger = IdeaLedger(tmp_path / "ledger.json", clock=clock)
    ledger.record_sheet(
        _sheet(
            as_of=sessions[0],
            legs=[_leg("CE", 200.0, expiry=expiry), _leg("PE", 180.0, expiry=expiry)],
            hold_sessions=1,
            expected_edge=0.001,
        )
    )
    settled = ledger.settle(as_of_end=sessions[2], store=synthetic_store())

    assert len(settled) == 1
    entry = settled[0]
    assert entry.status == STATUS_SETTLED
    assert entry.exit_as_of == sessions[1].isoformat()
    # short call: -65 * (150 - 200) = +3250; short put: -65 * (210 - 180) = -1950.
    assert entry.pnl == pytest.approx(1300.0)
    assert entry.realised_return == pytest.approx(1300.0 / DEFAULT_CAPITAL_BASE)
    assert entry.drift == pytest.approx(0.0013 - 0.001)
    assert ledger.open_ideas() == ()


def test_a_leg_expiring_before_the_exit_settles_at_intrinsic(
    tmp_path: Path, synthetic_store, clock: ManualClock
) -> None:
    """The call is 100 in the money at a flat 23,000 spot; the put pays nothing."""
    sessions = trading_days(3, ending=dt.date(2026, 4, 24))
    expiry = sessions[1]
    strike = SPOT - 100.0
    _corpus(
        synthetic_store.root,
        sessions,
        {
            sessions[0]: [
                SyntheticContract(strike=strike, option_type="CE", expiry=expiry, close=200.0),
                SyntheticContract(strike=strike, option_type="PE", expiry=expiry, close=180.0),
            ],
            sessions[1]: [
                SyntheticContract(strike=strike, option_type="CE", expiry=expiry, close=120.0),
                SyntheticContract(strike=strike, option_type="PE", expiry=expiry, close=20.0),
            ],
            sessions[2]: _straddle(dt.date(2026, 5, 7), call=140.0, put=220.0),
        },
    )
    ledger = IdeaLedger(tmp_path / "ledger.json", clock=clock)
    ledger.record_sheet(
        _sheet(
            as_of=sessions[0],
            legs=[
                _leg("CE", 200.0, expiry=expiry, strike=strike),
                _leg("PE", 180.0, expiry=expiry, strike=strike),
            ],
            hold_sessions=2,
        )
    )
    settled = ledger.settle(as_of_end=sessions[2], store=synthetic_store())

    assert len(settled) == 1
    entry = settled[0]
    assert entry.status == STATUS_SETTLED
    assert {leg.exit_source for leg in entry.legs} == {"intrinsic_at_expiry"}
    assert {leg.exit_as_of for leg in entry.legs} == {expiry.isoformat()}
    call, put = sorted(entry.legs, key=lambda leg: leg.trading_symbol)
    # 22,900 call at a 23,000 settlement is worth 100; the put expires worthless.
    assert call.exit_price == pytest.approx(100.0)
    assert put.exit_price == pytest.approx(0.0)
    # short call: -65 * (100 - 200) = +6500; short put: -65 * (0 - 180) = +11700.
    assert entry.pnl == pytest.approx(18_200.0)


def test_a_contract_outside_the_captured_ladder_is_unmarkable_and_named_so(
    tmp_path: Path, synthetic_store, clock: ManualClock
) -> None:
    """The exit session's instrument master never held this strike — a capture limit."""
    sessions = trading_days(2, ending=dt.date(2026, 4, 23))
    expiry = dt.date(2026, 5, 7)
    _corpus(
        synthetic_store.root,
        sessions,
        {
            sessions[0]: _straddle(expiry, call=200.0, put=180.0),
            # The ladder has moved: the traded 23,000 strike is simply not listed here.
            sessions[1]: [
                SyntheticContract(strike=SPOT + 500.0, option_type=right, expiry=expiry, close=90.0)
                for right in ("CE", "PE")
            ],
        },
    )
    ledger = IdeaLedger(tmp_path / "ledger.json", clock=clock)
    ledger.record_sheet(
        _sheet(
            as_of=sessions[0],
            legs=[_leg("CE", 200.0, expiry=expiry), _leg("PE", 180.0, expiry=expiry)],
        )
    )
    entry = ledger.settle(as_of_end=sessions[1], store=synthetic_store())[0]

    assert entry.status == STATUS_UNMARKABLE
    assert entry.realised_return is None
    assert entry.pnl is None
    assert entry.unmarkable_causes == (UNMARKABLE_CONTRACT_ABSENT,)
    assert "instrument master" in entry.reason


def test_a_listed_contract_with_no_print_is_a_different_unmarkable_cause(
    tmp_path: Path, synthetic_store, clock: ManualClock
) -> None:
    """Listed on the exit session and traded nowhere at the decision minute — a liquidity fact."""
    import pandas as pd

    sessions = trading_days(2, ending=dt.date(2026, 4, 23))
    expiry = dt.date(2026, 5, 7)
    _corpus(
        synthetic_store.root,
        sessions,
        {
            sessions[0]: _straddle(expiry, call=200.0, put=180.0),
            sessions[1]: _straddle(expiry, call=150.0, put=210.0),
        },
    )
    silent = _leg("CE", 200.0, expiry=expiry)["trading_symbol"]
    parquet = synthetic_store.root / UNDERLYING / f"{sessions[1].isoformat()}.parquet"
    frame = pd.read_parquet(parquet)
    # The instrument master keeps the contract; the price file loses every bar of it, which
    # is what an option nobody traded looks like in the capture.
    frame[frame["symbol"] != silent].to_parquet(parquet, index=False)

    ledger = IdeaLedger(tmp_path / "ledger.json", clock=clock)
    ledger.record_sheet(
        _sheet(
            as_of=sessions[0],
            legs=[_leg("CE", 200.0, expiry=expiry), _leg("PE", 180.0, expiry=expiry)],
        )
    )
    entry = ledger.settle(as_of_end=sessions[1], store=synthetic_store())[0]

    assert entry.status == STATUS_UNMARKABLE
    assert entry.unmarkable_causes == (UNMARKABLE_NO_PRINT,)
    marks = {leg.trading_symbol: leg for leg in entry.legs}
    assert marks[silent].unmarkable_cause == UNMARKABLE_NO_PRINT
    # The other leg priced perfectly well; one unmarkable leg makes the *idea* unmarkable
    # without pretending the rest of it was.
    assert [leg.exit_price for leg in entry.legs if leg.trading_symbol != silent] == [210.0]


def test_an_idea_presented_without_a_price_was_never_markable(
    tmp_path: Path, synthetic_store, clock: ManualClock
) -> None:
    sessions = trading_days(2, ending=dt.date(2026, 4, 23))
    expiry = dt.date(2026, 5, 7)
    _corpus(
        synthetic_store.root,
        sessions,
        {
            sessions[0]: _straddle(expiry, call=200.0, put=180.0),
            sessions[1]: _straddle(expiry, call=150.0, put=210.0),
        },
    )
    ledger = IdeaLedger(tmp_path / "ledger.json", clock=clock)
    ledger.record_sheet(
        _sheet(
            as_of=sessions[0],
            legs=[_leg("CE", None, expiry=expiry), _leg("PE", 180.0, expiry=expiry)],
        )
    )
    entry = ledger.settle(as_of_end=sessions[1], store=synthetic_store())[0]

    assert entry.status == STATUS_UNMARKABLE
    assert entry.unmarkable_causes == (UNMARKABLE_NO_ENTRY_PRICE,)


def test_an_idea_whose_hold_has_not_elapsed_stays_open(
    tmp_path: Path, synthetic_store, clock: ManualClock
) -> None:
    sessions = trading_days(2, ending=dt.date(2026, 4, 23))
    expiry = dt.date(2026, 5, 7)
    _corpus(
        synthetic_store.root,
        sessions,
        {
            sessions[0]: _straddle(expiry, call=200.0, put=180.0),
            sessions[1]: _straddle(expiry, call=150.0, put=210.0),
        },
    )
    ledger = IdeaLedger(tmp_path / "ledger.json", clock=clock)
    ledger.record_sheet(
        _sheet(
            as_of=sessions[0],
            legs=[_leg("CE", 200.0, expiry=expiry), _leg("PE", 180.0, expiry=expiry)],
            hold_sessions=3,
        )
    )
    assert ledger.settle(as_of_end=sessions[1], store=synthetic_store()) == ()
    assert len(ledger.open_ideas()) == 1


# --------------------------------------------------------------------------------------
# The statistics, hand computed
# --------------------------------------------------------------------------------------


def test_cusum_is_the_minimum_contiguous_run_of_shortfall() -> None:
    assert cusum_low(()) == 0.0
    # Never negative, so the running sum is clamped at zero throughout.
    assert cusum_low((1.0, 2.0, 3.0)) == 0.0
    # S = -1, -3, 0 (clamped from +2), -1. The lowest point is -3.
    assert cusum_low((-1.0, -2.0, 5.0, -1.0)) == pytest.approx(-3.0)
    # A shortfall given back in one run counts once, not twice.
    assert cusum_low((-1.0, 4.0, -1.0)) == pytest.approx(-1.0)


def test_one_sided_t_statistic_matches_the_hand_computation() -> None:
    # mean 2, sample variance ((1-2)^2 + 0 + (3-2)^2) / 2 = 1, so t = 2 / (1 / sqrt(3)).
    assert one_sided_t_statistic((1.0, 2.0, 3.0)) == pytest.approx(2.0 * 3.0**0.5)
    assert one_sided_t_statistic((-2.0, -2.0, -2.0, -2.0)) is None
    assert one_sided_t_statistic((1.0,)) is None
    assert one_sided_t_statistic(()) is None


# --------------------------------------------------------------------------------------
# Drift and demotion
# --------------------------------------------------------------------------------------


def _ledger_of_drifts(
    path: Path, drifts: list[float], *, expected: float = EXPECTED_EDGE, key: str = ""
) -> IdeaLedger:
    """A ledger holding one settled idea per drift, written and read back through disk.

    Building the entries as JSON rather than by settling a corpus is what lets a statistics
    test state its inputs exactly: the drift series *is* the fixture, and a corpus that
    produced it would be a much larger apparatus asserting the same arithmetic.
    """
    entries = []
    for index, drift in enumerate(drifts):
        as_of = (dt.date(2026, 1, 1) + dt.timedelta(days=index)).isoformat()
        identity = {
            "as_of": as_of,
            "template_id": TEMPLATE,
            "parameter_key": key,
            "underlying": UNDERLYING,
        }
        entries.append(
            {
                "kind": "presented",
                "parameters": {},
                "rank": 1,
                "score": 1.0,
                "expected_edge": expected,
                "granted_lots": LOTS,
                "hold_sessions": 1,
                "legs": [],
                "generated_at": GENERATED_AT,
                "code_version": CODE_VERSION,
                **identity,
            }
        )
        entries.append(
            {
                "kind": "settlement",
                "status": STATUS_SETTLED,
                "exit_as_of": as_of,
                "hold_sessions": 1,
                "capital_base": DEFAULT_CAPITAL_BASE,
                "pnl": (expected + drift) * DEFAULT_CAPITAL_BASE,
                "realised_return": expected + drift,
                "expected_return": expected,
                "legs": [],
                "reason": "fixture",
                "settled_at": "2026-04-30T18:00:00+00:00",
                **identity,
            }
        )
    path.write_text(
        json.dumps({"schema_version": LEDGER_SCHEMA_VERSION, "entries": entries}, indent=2)
    )
    return IdeaLedger.load(path)


#: Eight shortfalls of one step, eight recoveries, and one exactly-on-expectation idea. The
#: sample deviation of this multiset is exactly one step: sixteen deviations of one step each
#: over sixteen degrees of freedom. The CUSUM threshold is therefore exactly three steps, and
#: whether it breaches depends only on how long the shortfalls run without interruption.
_SUSTAINED = [-DRIFT_STEP] * 3 + [DRIFT_STEP] * 3
_SUSTAINED += [-DRIFT_STEP] * 3 + [DRIFT_STEP] * 3
_SUSTAINED += [-DRIFT_STEP] * 2 + [DRIFT_STEP] * 2 + [0.0]

_ALTERNATING = ([-DRIFT_STEP] * 2 + [DRIFT_STEP] * 2) * 4 + [0.0]


def test_a_sustained_run_of_shortfall_breaches_exactly_at_three_sigma(tmp_path: Path) -> None:
    ledger = _ledger_of_drifts(tmp_path / "ledger.json", _SUSTAINED)
    report = ledger.drift(TemplateLibrary(tmp_path / "templates.json"), window=20, min_settled=10)[
        0
    ]

    assert report.n_settled == 17
    assert report.sigma == pytest.approx(DRIFT_STEP)
    assert report.cusum_threshold == pytest.approx(-CUSUM_K * DRIFT_STEP)
    # Three consecutive shortfalls, and the recoveries between the runs never lift the
    # running sum back to zero — so the lowest point is exactly the threshold.
    assert report.cusum == pytest.approx(-3.0 * DRIFT_STEP)
    assert report.cusum <= report.cusum_threshold
    assert report.verdict == VERDICT_CUSUM_BREACH


def test_the_same_shortfalls_alternating_do_not_breach(tmp_path: Path) -> None:
    ledger = _ledger_of_drifts(tmp_path / "ledger.json", _ALTERNATING)
    report = ledger.drift(TemplateLibrary(tmp_path / "templates.json"), window=20, min_settled=10)[
        0
    ]

    assert sorted(_ALTERNATING) == sorted(_SUSTAINED)
    assert report.sigma == pytest.approx(DRIFT_STEP)
    assert report.cusum == pytest.approx(-2.0 * DRIFT_STEP)
    assert report.verdict == VERDICT_WITHIN_TOLERANCE


#: Four realised returns whose mean is exactly one step below zero and whose sample deviation
#: is exactly one step. Over four observations that puts the one-sided t at exactly -2, the
#: boundary the rule names, with no rounding anywhere: every value is a small multiple of a
#: power of two and the variance is an exact square.
_AT_T_OF_MINUS_TWO = [4 * 2.0**-16] + [-12 * 2.0**-16] * 3

#: The same mean with the dispersion widened by a quarter, which puts the t at exactly -1.6.
_INSIDE_T_THRESHOLD = [7 * 2.0**-16] + [-13 * 2.0**-16] * 3


def test_a_realised_mean_below_zero_at_t_of_minus_two_is_named_as_such(tmp_path: Path) -> None:
    expected = 8 * 2.0**-16
    drifts = [value - expected for value in _AT_T_OF_MINUS_TWO]
    ledger = _ledger_of_drifts(tmp_path / "ledger.json", drifts, expected=expected)
    report = ledger.drift(TemplateLibrary(tmp_path / "templates.json"), window=20, min_settled=4)[0]

    assert report.realised_mean == pytest.approx(-(2.0**-13))
    assert report.t_statistic == -2.0
    assert report.realised_hit_rate == pytest.approx(0.25)
    assert report.verdict == VERDICT_NEGATIVE_MEAN_BREACH


def test_just_inside_the_t_threshold_the_cusum_is_what_names_the_breach(tmp_path: Path) -> None:
    """A wider spread around the same losing mean puts the t at -1.6, inside the boundary.

    The demotion still fires, on the CUSUM, and that is not an accident of these numbers: the
    whole window is itself a contiguous run, so its total shortfall is an upper bound on the
    CUSUM, and a mean significant enough to trip the t-rule has always already carried that
    total past three sigma. The t-rule is therefore a naming device rather than an
    independent trigger — it is checked first so that a template which is simply losing money
    is reported as losing money rather than as having drifted.
    """
    expected = 8 * 2.0**-16
    drifts = [value - expected for value in _INSIDE_T_THRESHOLD]
    ledger = _ledger_of_drifts(tmp_path / "ledger.json", drifts, expected=expected)
    report = ledger.drift(TemplateLibrary(tmp_path / "templates.json"), window=20, min_settled=4)[0]

    assert report.realised_mean == pytest.approx(-(2.0**-13))
    assert report.t_statistic == -1.6
    assert report.verdict == VERDICT_CUSUM_BREACH


def test_no_demotion_below_the_minimum_settled_count(tmp_path: Path) -> None:
    """The statistics are reported so the trend is visible; the rule may not act on them."""
    ledger = _ledger_of_drifts(tmp_path / "ledger.json", _SUSTAINED)
    library = TemplateLibrary(tmp_path / "templates.json")
    report = ledger.drift(library, window=20, min_settled=18)[0]

    assert report.n_settled == 17
    assert report.verdict == VERDICT_NOT_ENOUGH_SETTLED
    assert "17 of 18" in report.reason
    assert report.breached is False
    # The numbers are still on the report — an unjudged point is not an unmeasured one.
    assert report.cusum == pytest.approx(-3.0 * DRIFT_STEP)
    assert apply_demotions((report,), library, by="tester") == ()


def test_an_unmarkable_idea_is_counted_but_never_scored(tmp_path: Path) -> None:
    _ledger_of_drifts(tmp_path / "ledger.json", _SUSTAINED)
    document = json.loads((tmp_path / "ledger.json").read_text())
    document["entries"].append(
        {
            "kind": "settlement",
            "as_of": "2026-02-01",
            "template_id": TEMPLATE,
            "parameter_key": "",
            "underlying": UNDERLYING,
            "status": STATUS_UNMARKABLE,
            "exit_as_of": "2026-02-02",
            "hold_sessions": 1,
            "capital_base": DEFAULT_CAPITAL_BASE,
            "pnl": None,
            "realised_return": None,
            "expected_return": EXPECTED_EDGE,
            "legs": [],
            "reason": "fixture",
            "settled_at": "2026-04-30T18:00:00+00:00",
        }
    )
    (tmp_path / "ledger.json").write_text(json.dumps(document, indent=2))
    report = IdeaLedger.load(tmp_path / "ledger.json").drift(
        TemplateLibrary(tmp_path / "templates.json"), window=20, min_settled=10
    )[0]

    assert report.n_settled == 17
    assert report.n_unmarkable == 1
    # Scoring it as a zero return would move the mean; it does not appear in any statistic.
    assert report.cusum == pytest.approx(-3.0 * DRIFT_STEP)


def test_a_ledger_with_no_settled_ideas_reports_the_question_as_unasked(tmp_path: Path) -> None:
    ledger = _ledger_of_drifts(tmp_path / "ledger.json", [])
    assert ledger.drift(TemplateLibrary(tmp_path / "templates.json")) == ()


# --------------------------------------------------------------------------------------
# Integration: a real scan, recorded, settled and reported
# --------------------------------------------------------------------------------------

#: Anchored to the repository so the test carries no hidden precondition on the working
#: directory, exactly as the ranker's own tests anchor it.
DECISION_RECORD = Path(__file__).resolve().parents[1] / "research" / "h1" / "decision.json"

#: The anchor H1 record failed its gate, and `TemplateLibrary.admit` refuses unpassed
#: evidence without a written override. The ledger needs an ADMITTED template to have a scan
#: to record at all.
ADMIT_OVERRIDE = (
    "test fixture: the anchor H1 record failed its gate. The tracking loop is under test "
    "here, and it needs an ADMITTED template for the ranker to propose anything."
)


def test_a_scanned_sheet_is_recorded_settled_and_reported(
    tmp_path: Path, synthetic_store, clock: ManualClock
) -> None:
    """The whole forward loop over one synthetic corpus: scan, record, settle, report.

    Nothing is stubbed between the ranker and the ledger — the sheet the ledger reads is the
    JSON the scan actually wrote, which is the seam a hand-built fixture would not exercise.
    """
    sessions = trading_days(30, ending=dt.date(2026, 4, 24))
    write_corpus(
        synthetic_store.root,
        sessions=sessions,
        spot_for=lambda index: FLAT_SPOT + STEP * (index % 3),
        expiry=sessions[-1] + dt.timedelta(days=14),
    )
    store = synthetic_store()
    library = TemplateLibrary(tmp_path / "templates.json", clock=clock)
    library.admit(
        override_reason=ADMIT_OVERRIDE,
        template=default_registry().get(TEMPLATE),
        decision_path=DECISION_RECORD,
        by="tester",
        reason="exercising the tracking loop against the anchor hypothesis's evidence",
    )
    as_of = sessions[-2]
    sheet = NightlyScan(
        store=store,
        registry=default_registry(),
        library=library,
        as_of=as_of,
        universe=[UNDERLYING],
        top_n=5,
        feature_builder=FeatureBuilder(store, regime_lookback_sessions=10),
        clock=clock,
        code_version=StaticCodeVersion("0" * 40, dirty=False),
    ).run()
    assert sheet.ideas, "the fixture must produce an idea for there to be anything to track"

    sheet_path = tmp_path / "ideas.json"
    sheet_path.write_text(json.dumps(sheet.as_dict(), indent=2, sort_keys=True))

    ledger = IdeaLedger(tmp_path / "ledger.json", clock=clock)
    recorded = ledger.record_sheet(json.loads(sheet_path.read_text()))
    ledger.save()
    assert len(recorded) == len(sheet.ideas)
    assert recorded[0].hold_sessions == sheet.ideas[0].rationale.trade.hold_sessions
    assert recorded[0].granted_lots == sheet.ideas[0].granted_lots

    settled = ledger.settle(as_of_end=sessions[-1], store=store)
    ledger.save()
    assert len(settled) == len(recorded)
    assert ledger.open_ideas() == ()
    marked = [entry for entry in settled if entry.status == STATUS_SETTLED]
    assert marked, "the fixture quotes every leg on both sessions, so nothing is unmarkable"
    for entry in marked:
        assert entry.realised_return == pytest.approx(entry.pnl / DEFAULT_CAPITAL_BASE)
        assert entry.drift == pytest.approx(entry.realised_return - entry.expected_return)

    reports = ledger.drift(library, window=20, min_settled=10)
    assert len(reports) == 1
    report = reports[0]
    # One settled idea is nowhere near enough to judge a template, and the report says so
    # in the words an operator reads rather than by staying silent.
    assert report.verdict == VERDICT_NOT_ENOUGH_SETTLED
    assert f"{report.n_settled} of 10" in report.reason
    assert report.card_mean_return_at_hold is not None
    assert report.realised_mean is not None
    assert apply_demotions(reports, library, by="tester") == ()
    assert {record.template_id for record in library.admitted()} == {TEMPLATE}


def _admitted_library(tmp_path: Path, clock: ManualClock) -> tuple[TemplateLibrary, str]:
    """A library holding one admitted point, and the parameter key that names it."""
    library = TemplateLibrary(tmp_path / "templates.json", clock=clock)
    library.admit(
        override_reason=ADMIT_OVERRIDE,
        template=default_registry().get(TEMPLATE),
        decision_path=DECISION_RECORD,
        by="tester",
        reason="a live admission for the demotion rule to act on",
    )
    admitted = library.admitted()
    assert len(admitted) == 1
    return library, admitted[0].parameter_key


def test_a_breach_demotes_the_admitted_point_with_the_numbers_in_the_reason(
    tmp_path: Path, clock: ManualClock
) -> None:
    """The rule's hand on the lever: a CUSUM breach takes the template off the ranker.

    The ledger is written at the *admitted* parameter key rather than a bare template id.
    A template can be filed at several points and only one of them may be drifting, so a
    demotion that could not name the point would take a healthy trade down with a broken one.
    """
    library, key = _admitted_library(tmp_path, clock)
    ledger = _ledger_of_drifts(tmp_path / "ledger.json", _SUSTAINED, key=key)
    reports = ledger.drift(library, window=20, min_settled=10)

    assert len(reports) == 1
    assert reports[0].parameter_key == key
    assert reports[0].card_mean_return_at_hold is not None
    assert reports[0].verdict == VERDICT_CUSUM_BREACH

    demoted = apply_demotions(reports, library, by="tester")
    assert [report.identity for report in demoted] == [(TEMPLATE, key)]
    assert library.admitted() == ()

    point = dict(library.history(TEMPLATE)[0].parameters)
    current = library.current(TEMPLATE, parameters=point)
    assert current is not None
    assert current.status == AdmissionStatus.DEMOTED
    assert current.admitted_by == "tester"
    # The evidence the point was admitted on is carried forward, not cleared: what the
    # offline loop measured is still true, and the demotion is a statement about now.
    assert current.evidence.mean_return_at_hold == reports[0].card_mean_return_at_hold
    # The reason has to stand on its own in the library, without the ledger beside it.
    assert "CUSUM" in current.reason
    assert f"{CUSUM_K:g} sigma" in current.reason

    # The rule keeps breaching after it has fired; a second pass must not file a second
    # demotion entry on top of the one that mattered.
    assert apply_demotions(ledger.drift(library, window=20, min_settled=10), library, by="x") == ()


def test_the_same_shortfalls_alternating_leave_the_admission_alone(
    tmp_path: Path, clock: ManualClock
) -> None:
    library, key = _admitted_library(tmp_path, clock)
    ledger = _ledger_of_drifts(tmp_path / "ledger.json", _ALTERNATING, key=key)
    reports = ledger.drift(library, window=20, min_settled=10)

    assert reports[0].verdict == VERDICT_WITHIN_TOLERANCE
    assert apply_demotions(reports, library, by="tester") == ()
    assert [record.template_id for record in library.admitted()] == [TEMPLATE]


class _RefusesAnEmptySelector:
    """A library that fails the test if a selector matching every entry reaches it."""

    def current(self, template_id: str, *, parameters):
        assert parameters, "an empty parameter selector reached the library"
        return None


def test_a_settlement_with_no_parameter_key_never_selects_by_an_empty_point(
    tmp_path: Path, clock: ManualClock
) -> None:
    """An empty key matches every entry, so it is treated as naming none.

    ``history({})`` matches everything — ``all([])`` is true — so a hand-built row carrying
    no point would make ``current()`` refuse a template admitted at two points, and the
    refusal would come out of the middle of ``drift()`` and fail the whole nightly run over
    that one row.
    """
    ledger = IdeaLedger(tmp_path / "ledger.json", clock=clock)
    ledger._append(
        Settlement(
            as_of="2026-04-20",
            template_id=TEMPLATE,
            parameter_key="",
            underlying=UNDERLYING,
            status=STATUS_SETTLED,
            exit_as_of="2026-04-21",
            hold_sessions=1,
            capital_base=DEFAULT_CAPITAL_BASE,
            pnl=-100.0,
            realised_return=-0.0001,
            expected_return=0.001,
            legs=(),
            reason="a hand-built row carrying no point",
            settled_at="2026-04-21T00:00:00+00:00",
        )
    )

    reports = ledger.drift(_RefusesAnEmptySelector(), min_settled=1)

    assert [report.parameter_key for report in reports] == [""]
    assert reports[0].card_mean_return_at_hold is None


def _idea_sized(requested: int, granted: int) -> PresentedIdea:
    return PresentedIdea(
        as_of="2026-04-20",
        template_id=TEMPLATE,
        parameters={"hold_sessions": 1.0},
        underlying=UNDERLYING,
        rank=1,
        score=1.0,
        expected_edge=0.001,
        granted_lots=granted,
        hold_sessions=1,
        legs=(),
        generated_at="2026-04-20T18:00:00+00:00",
        code_version="0" * 40,
        requested_lots=requested,
    )


def test_a_capped_idea_is_scored_at_the_size_its_evidence_was_measured_at() -> None:
    """The caps cut the lots, not the expectation, so realised is put back on that size.

    Without this the drift on a capped idea is negative purely from sizing, and for a
    positive expectation that bias points toward demotion — the one direction every other
    bias in this module deliberately does not point.
    """
    assert _idea_sized(requested=4, granted=1).size_scale == 4.0
    assert _idea_sized(requested=1, granted=1).size_scale == 1.0


def test_an_unsized_idea_is_not_given_an_invented_ratio() -> None:
    """Granted nothing, or a sheet that never said what was asked for: no ratio exists."""
    assert _idea_sized(requested=4, granted=0).size_scale == 1.0
    idea = _idea_sized(requested=4, granted=2)
    assert PresentedIdea.from_dict({**idea.as_dict(), "requested_lots": None}).size_scale == 1.0


def test_the_ratio_is_lots_not_notionals_so_a_two_legged_structure_is_not_halved() -> None:
    """A straddle's notional sums both short legs; its lots do not.

    Deriving the ratio from ``target_notional / notional`` would divide every straddle's
    realised return by about two — a correction twice the size of the error it fixes.
    """
    assert _idea_sized(requested=2, granted=2).size_scale == 1.0
