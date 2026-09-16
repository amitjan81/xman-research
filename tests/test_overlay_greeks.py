"""Black-Scholes, the wing extrapolation, and the one check the corpus itself can give.

The unit tests here hold properties (parity, monotonicity, the calibration clamp). The
last test is different in kind: it compares this module's delta against the **vendor's
own** delta column, which :class:`~xman_research.backtest.market.Bar` does not expose and
which nothing in the strategy reads. It is the only independent check available that the
greeks the strike selection runs on are the greeks the market was actually pricing.
"""

from __future__ import annotations

import datetime as dt
import math
import os
from pathlib import Path

import pytest

from xman_research.overlay.greeks import (
    ObservedQuote,
    bs_delta,
    bs_price,
    extrapolated_wing_price,
    flat_iv_beyond_band,
    year_fraction,
)
from xman_research.session_store import DEFAULT_CORPUS_ROOT

CORPUS_ROOT = Path(os.environ.get("XMAN_RESEARCH_CORPUS_ROOT") or DEFAULT_CORPUS_ROOT)


def test_put_call_parity_holds_for_the_prices() -> None:
    spot, strike, t_years, iv = 23_500.0, 23_800.0, 6.0 / 365.0, 0.13

    call = bs_price(option_type="CE", spot=spot, strike=strike, t_years=t_years, iv=iv)
    put = bs_price(option_type="PE", spot=spot, strike=strike, t_years=t_years, iv=iv)

    # Zero rate, zero dividend: C - P = S - K.
    assert call - put == pytest.approx(spot - strike, abs=1e-6)


def test_call_and_put_deltas_differ_by_one() -> None:
    kwargs = {"spot": 23_500.0, "strike": 24_000.0, "t_years": 6.0 / 365.0, "iv": 0.13}

    assert bs_delta(option_type="CE", **kwargs) - bs_delta(option_type="PE", **kwargs) == (
        pytest.approx(1.0, abs=1e-9)
    )


def test_delta_falls_as_the_strike_moves_out_of_the_money() -> None:
    deltas = [
        bs_delta(option_type="CE", spot=23_500.0, strike=strike, t_years=6 / 365, iv=0.13)
        for strike in (23_600.0, 23_800.0, 24_000.0, 24_400.0)
    ]

    assert deltas == sorted(deltas, reverse=True)


def test_expired_options_degenerate_to_intrinsic_and_indicator_delta() -> None:
    assert bs_price(option_type="CE", spot=100.0, strike=90.0, t_years=0.0, iv=0.2) == 10.0
    assert bs_delta(option_type="CE", spot=100.0, strike=90.0, t_years=0.0, iv=0.2) == 1.0
    assert bs_delta(option_type="PE", spot=80.0, strike=90.0, t_years=0.0, iv=0.2) == -1.0


def test_year_fraction_counts_to_settlement_not_to_midnight() -> None:
    same_day = year_fraction(minute_hour=9.5, days_to_expiry=0)
    next_day = year_fraction(minute_hour=9.5, days_to_expiry=1)

    assert same_day > 0.0
    assert next_day - same_day == pytest.approx(1.0 / 365.0, abs=1e-9)


def test_the_wing_is_calibrated_to_the_edge_strikes_printed_price() -> None:
    """A wing priced off an edge whose model value is half its print doubles with it."""
    spot, t_years, iv = 23_500.0, 6.0 / 365.0, 0.13
    edge_strike = 24_000.0
    model = bs_price(option_type="CE", spot=spot, strike=edge_strike, t_years=t_years, iv=iv)
    observed = [
        ObservedQuote(
            strike=edge_strike, iv=iv, close=2.0 * model, volume_units=1.0, open_interest_units=1.0
        )
    ]

    priced = extrapolated_wing_price(
        option_type="CE", spot=spot, strike=24_350.0, t_years=t_years, observed=observed
    )

    assert priced is not None
    raw = bs_price(option_type="CE", spot=spot, strike=24_350.0, t_years=t_years, iv=iv)
    assert priced[0] == pytest.approx(2.0 * raw)


def test_a_wild_calibration_ratio_is_clamped_rather_than_propagated() -> None:
    spot, t_years, iv = 23_500.0, 6.0 / 365.0, 0.13
    edge_strike = 24_000.0
    model = bs_price(option_type="CE", spot=spot, strike=edge_strike, t_years=t_years, iv=iv)
    observed = [
        ObservedQuote(
            strike=edge_strike, iv=iv, close=50.0 * model, volume_units=1.0, open_interest_units=1.0
        )
    ]

    priced = extrapolated_wing_price(
        option_type="CE", spot=spot, strike=24_350.0, t_years=t_years, observed=observed
    )

    assert priced is not None
    raw = bs_price(option_type="CE", spot=spot, strike=24_350.0, t_years=t_years, iv=iv)
    assert priced[0] == pytest.approx(2.0 * raw)  # ratio clamped at 2, not 50


def test_an_empty_side_cannot_be_extrapolated_from() -> None:
    assert (
        extrapolated_wing_price(
            option_type="PE", spot=23_500.0, strike=22_000.0, t_years=0.01, observed=[]
        )
        is None
    )
    assert flat_iv_beyond_band(observed=[], strike=22_000.0, spot=23_500.0) is None


def test_implied_volatility_is_held_flat_outside_the_observed_band() -> None:
    observed = [(23_000.0, 0.15), (23_500.0, 0.13), (24_000.0, 0.12)]

    assert flat_iv_beyond_band(observed=observed, strike=22_000.0, spot=23_500.0) == 0.15
    assert flat_iv_beyond_band(observed=observed, strike=25_000.0, spot=23_500.0) == 0.12
    middle = flat_iv_beyond_band(observed=observed, strike=23_750.0, spot=23_500.0)
    assert 0.12 < middle < 0.13


@pytest.mark.skipif(
    not (CORPUS_ROOT / "NIFTY").is_dir(), reason=f"real corpus not present at {CORPUS_ROOT}"
)
def test_the_computed_delta_agrees_with_the_vendors_own() -> None:
    """The check nothing else can make: our greeks against the producer's.

    The corpus carries a ``delta`` column the engine never surfaces. Agreement to a few
    thousandths means the strike ST-6 selects is the strike the market's own pricing would
    have selected, and disagreement would mean every entry in the study is at the wrong
    strike.
    """
    import pandas as pd
    import pyarrow.parquet as pq

    path = sorted((CORPUS_ROOT / "NIFTY").glob("2026-09-*.parquet"))[-1]
    frame = pq.read_table(path).to_pandas().dropna(subset=["iv", "delta", "spot"])
    options = frame[frame.symbol.str.contains("-", regex=False)]
    parts = options.symbol.str.split("-", expand=True)
    options = options.assign(expiry=parts[1], strike=parts[2].astype(float), option_type=parts[3])
    session_date = dt.date.fromisoformat(path.stem)
    expiry = dt.datetime.strptime(options.expiry.iloc[0], "%d%b%Y").date()

    errors = []
    for row in options.sample(300, random_state=1).itertuples(index=False):
        moment = dt.datetime.fromtimestamp(row.minute_ts / 1e6, dt.UTC) + dt.timedelta(
            hours=5, minutes=30
        )
        t_years = year_fraction(
            minute_hour=moment.hour + moment.minute / 60.0,
            days_to_expiry=(expiry - session_date).days,
        )
        mine = bs_delta(
            option_type=row.option_type,
            spot=row.spot,
            strike=row.strike,
            t_years=t_years,
            iv=row.iv,
        )
        errors.append(abs(mine - row.delta))

    assert pd.Series(errors).median() < 0.005
    assert pd.Series(errors).quantile(0.95) < 0.02
    assert not any(math.isnan(value) for value in errors)
