"""The feature layer, against corpora small enough to compute by hand.

Two synthetic price paths carry most of the arithmetic. A **flat** path pins every
volatility-like feature at zero and every level-like feature at the spot, which catches a
whole class of sign and scaling errors. An **alternating** path gives every feature a
closed form: the log returns are ``+l, -l, +l, ...`` with zero mean, so the sample standard
deviation is ``l * sqrt(n / (n - 1))``, and the true range of a session with no intraday
movement is exactly the gap against the previous close.

The look-ahead guard is held twice over, because it is the one error no downstream number
can reveal: once by showing that bars printed after the decision minute do not move any
feature, and once by showing that a corpus which continues past the as-of session produces
the same frame as one that stops there.
"""

from __future__ import annotations

import datetime as dt
import math

import pytest

from alpha_helpers import (
    DECISION_MINUTE_INDEX,
    FIXTURE_IV,
    FLAT_SPOT,
    STEP,
)
from alpha_helpers import (
    trading_days as _trading_days,
)
from alpha_helpers import (
    write_corpus as _write_corpus,
)
from xman_research.alpha.features import (
    ANNUALISATION_SESSIONS,
    DEFAULT_DECISION_TIME,
    AsOfNotASessionError,
    FeatureBuilder,
    FeatureFrame,
)
from xman_research.session_store import NSE_CALENDAR, SessionStore, TradingCalendar


@pytest.fixture
def flat_corpus(synthetic_store) -> tuple[SessionStore, list[dt.date], dt.date]:
    """Thirty sessions at one unchanging price, and an expiry beyond all of them."""
    sessions = _trading_days(30, ending=dt.date(2026, 4, 24))
    expiry = sessions[-1] + dt.timedelta(days=14)
    _write_corpus(
        synthetic_store.root, sessions=sessions, spot_for=lambda _: FLAT_SPOT, expiry=expiry
    )
    return synthetic_store(), sessions, expiry


@pytest.fixture
def alternating_corpus(synthetic_store) -> tuple[SessionStore, list[dt.date], dt.date]:
    """Thirty sessions alternating between two prices — every feature has a closed form."""
    sessions = _trading_days(30, ending=dt.date(2026, 4, 24))
    expiry = sessions[-1] + dt.timedelta(days=14)
    _write_corpus(
        synthetic_store.root,
        sessions=sessions,
        spot_for=lambda index: FLAT_SPOT + (STEP if index % 2 else 0.0),
        expiry=expiry,
    )
    return synthetic_store(), sessions, expiry


def _build(store: SessionStore, as_of: dt.date, *, regime_lookback: int = 10) -> FeatureFrame:
    return FeatureBuilder(store, regime_lookback_sessions=regime_lookback).build("NIFTY", as_of)


# ------------------------------------------------------------------------ the flat corpus


def test_a_flat_price_path_has_no_realised_volatility_and_no_true_range(
    flat_corpus: tuple[SessionStore, list[dt.date], dt.date],
) -> None:
    store, sessions, _ = flat_corpus
    frame = _build(store, sessions[-1])
    assert frame.value("realised_vol_10") == pytest.approx(0.0)
    assert frame.value("realised_vol_20") == pytest.approx(0.0)
    assert frame.value("atr_14") == pytest.approx(0.0)
    assert frame.value("overnight_gap_return") == pytest.approx(0.0)


def test_an_exponential_average_of_one_repeated_price_is_that_price(
    flat_corpus: tuple[SessionStore, list[dt.date], dt.date],
) -> None:
    store, sessions, _ = flat_corpus
    assert _build(store, sessions[-1]).value("ema_20") == pytest.approx(FLAT_SPOT)


def test_the_z_score_is_absent_rather_than_infinite_when_the_true_range_is_zero(
    flat_corpus: tuple[SessionStore, list[dt.date], dt.date],
) -> None:
    store, sessions, _ = flat_corpus
    feature = _build(store, sessions[-1]).get("ema20_z")
    assert feature is not None
    assert feature.value is None
    assert "not computable" in (feature.reason or "")


def test_implied_minus_realised_is_the_implied_reading_when_realised_is_zero(
    flat_corpus: tuple[SessionStore, list[dt.date], dt.date],
) -> None:
    store, sessions, _ = flat_corpus
    frame = _build(store, sessions[-1])
    assert frame.value("atm_iv") == pytest.approx(FIXTURE_IV)
    assert frame.value("iv_minus_rv_20") == pytest.approx(FIXTURE_IV)
    assert frame.value("iv_minus_rv_10") == pytest.approx(FIXTURE_IV)


def test_sessions_to_expiry_counts_exchange_trading_days_not_calendar_days(
    flat_corpus: tuple[SessionStore, list[dt.date], dt.date],
) -> None:
    store, sessions, expiry = flat_corpus
    as_of = sessions[-1]
    expected = len(TradingCalendar().trading_days(as_of, expiry)) - 1
    assert _build(store, as_of).value("sessions_to_nearest_expiry") == pytest.approx(expected)


def test_every_feature_states_the_lookback_it_was_measured_over(
    flat_corpus: tuple[SessionStore, list[dt.date], dt.date],
) -> None:
    store, sessions, _ = flat_corpus
    frame = _build(store, sessions[-1])
    assert frame.features
    for feature in frame.features.values():
        assert feature.lookback_sessions >= 1
        assert feature.description
        assert (feature.value is None) == bool(feature.reason)


# ----------------------------------------------------------------- the alternating corpus


def test_realised_volatility_matches_its_closed_form_on_an_alternating_path(
    alternating_corpus: tuple[SessionStore, list[dt.date], dt.date],
) -> None:
    store, sessions, _ = alternating_corpus
    frame = _build(store, sessions[-1])
    step = math.log((FLAT_SPOT + STEP) / FLAT_SPOT)
    for name, count in (("realised_vol_10", 10), ("realised_vol_20", 20)):
        expected = step * math.sqrt(count / (count - 1)) * math.sqrt(ANNUALISATION_SESSIONS)
        assert frame.value(name) == pytest.approx(expected)


def test_the_true_range_of_a_gap_only_path_is_the_gap(
    alternating_corpus: tuple[SessionStore, list[dt.date], dt.date],
) -> None:
    store, sessions, _ = alternating_corpus
    assert _build(store, sessions[-1]).value("atr_14") == pytest.approx(STEP)


def test_the_overnight_gap_is_the_move_against_the_previous_session_close(
    alternating_corpus: tuple[SessionStore, list[dt.date], dt.date],
) -> None:
    store, sessions, _ = alternating_corpus
    last, previous = sessions[-1], sessions[-2]
    frame = _build(store, last)
    spot_last = FLAT_SPOT + (STEP if (len(sessions) - 1) % 2 else 0.0)
    spot_previous = FLAT_SPOT + (STEP if (len(sessions) - 2) % 2 else 0.0)
    del previous
    assert frame.value("overnight_gap_return") == pytest.approx(spot_last / spot_previous - 1.0)


def test_the_regime_tag_is_a_tercile_of_the_trailing_spread(
    alternating_corpus: tuple[SessionStore, list[dt.date], dt.date],
) -> None:
    store, sessions, _ = alternating_corpus
    regime = _build(store, sessions[-1], regime_lookback=8).regime
    assert regime.tag in {"iv_rv_low", "iv_rv_mid", "iv_rv_high"}
    assert regime.lookback_sessions == 8
    assert regime.lower_tercile is not None and regime.upper_tercile is not None
    assert regime.lower_tercile <= regime.upper_tercile


def test_a_regime_tercile_over_too_few_observations_is_absent_with_a_reason(
    synthetic_store,
) -> None:
    sessions = _trading_days(22, ending=dt.date(2026, 4, 24))
    expiry = sessions[-1] + dt.timedelta(days=14)
    _write_corpus(
        synthetic_store.root, sessions=sessions, spot_for=lambda _: FLAT_SPOT, expiry=expiry
    )
    # Twenty-two sessions leave one computable twenty-session spread, and a tercile of one
    # observation describes nothing.
    regime = _build(synthetic_store(), sessions[-1], regime_lookback=120).regime
    assert regime.tag is None
    assert "at least three" in (regime.reason or "")


# ------------------------------------------------------------------------- no look-ahead


def test_bars_printed_after_the_decision_minute_move_no_feature(
    synthetic_store,
) -> None:
    """The strongest form of the guard: the future is present in the file and unread."""
    sessions = _trading_days(30, ending=dt.date(2026, 4, 24))
    expiry = sessions[-1] + dt.timedelta(days=14)
    _write_corpus(
        synthetic_store.root, sessions=sessions, spot_for=lambda _: FLAT_SPOT, expiry=expiry
    )
    quiet = _build(synthetic_store(), sessions[-1]).as_dict()

    # Rewrite the as-of session so every minute after 15:20 prints a violent move.
    _write_corpus(
        synthetic_store.root,
        sessions=[sessions[-1]],
        spot_for=lambda _: FLAT_SPOT,
        expiry=expiry,
        spot_by_minute={index: FLAT_SPOT * 1.5 for index in range(DECISION_MINUTE_INDEX + 1, 375)},
        spot_by_minute_on=sessions[-1],
    )
    violent = _build(synthetic_store(), sessions[-1]).as_dict()
    assert violent == quiet


def test_a_corpus_that_continues_past_the_as_of_gives_the_same_frame_as_one_that_stops(
    synthetic_store,
) -> None:
    sessions = _trading_days(33, ending=dt.date(2026, 5, 8))
    as_of = sessions[-4]
    expiry = sessions[-1] + dt.timedelta(days=14)
    _write_corpus(
        synthetic_store.root,
        sessions=sessions[:-3],
        spot_for=lambda index: FLAT_SPOT + (STEP if index % 2 else 0.0),
        expiry=expiry,
    )
    truncated = _build(synthetic_store(), as_of).as_dict()

    _write_corpus(
        synthetic_store.root,
        sessions=sessions[-3:],
        # A wildly different level after the as-of session: if any feature reached forward,
        # this is the change that would show it.
        spot_for=lambda _: FLAT_SPOT * 2,
        expiry=expiry,
    )
    continued = _build(synthetic_store(), as_of).as_dict()
    assert continued == truncated


def test_the_decision_minute_is_the_one_the_builder_was_configured_with(
    flat_corpus: tuple[SessionStore, list[dt.date], dt.date],
) -> None:
    store, sessions, _ = flat_corpus
    frame = _build(store, sessions[-1])
    assert frame.decision_minute is not None
    assert frame.decision_minute.time() == DEFAULT_DECISION_TIME
    assert frame.decision_time == DEFAULT_DECISION_TIME


# --------------------------------------------------------------------------- refusals


def test_an_as_of_the_corpus_has_no_session_for_is_refused_not_rolled_back(
    flat_corpus: tuple[SessionStore, list[dt.date], dt.date],
) -> None:
    """Rolling back would file the scan under a date whose data it never read."""
    store, sessions, _ = flat_corpus
    saturday = sessions[-1] + dt.timedelta(days=1)
    with pytest.raises(AsOfNotASessionError, match="has no session on"):
        _build(store, saturday)


def test_a_regime_lookback_below_three_is_refused(
    flat_corpus: tuple[SessionStore, list[dt.date], dt.date],
) -> None:
    store, _, _ = flat_corpus
    with pytest.raises(ValueError, match="at least 3"):
        FeatureBuilder(store, regime_lookback_sessions=2)


def test_the_implied_reading_is_withheld_on_a_session_that_is_its_own_expiry(
    synthetic_store,
) -> None:
    """Minutes from settlement the at-the-money reading is rounding, not forward variance."""
    sessions = _trading_days(30, ending=dt.date(2026, 4, 24))
    _write_corpus(
        synthetic_store.root,
        sessions=sessions,
        spot_for=lambda _: FLAT_SPOT,
        expiry=sessions[-1],
    )
    frame = _build(synthetic_store(), sessions[-1])
    feature = frame.get("atm_iv")
    assert feature is not None and feature.value is None
    assert "the as-of session itself" in (feature.reason or "")
    assert frame.value("iv_minus_rv_20") is None


def test_the_calendar_used_is_the_exchange_one(
    flat_corpus: tuple[SessionStore, list[dt.date], dt.date],
) -> None:
    del flat_corpus
    assert TradingCalendar().name == NSE_CALENDAR
