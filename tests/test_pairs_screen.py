"""Gate arithmetic of the pair screen, checked on synthetic frames with known answers.

The screen's admission decision is arithmetic on five quantities — OU half-life, Hurst,
the Benjamini-Hochberg step-up, lot quantisation of beta, and the cost scaling. Each is
exercised here against a series whose correct answer is constructed, so a wrong gate
fails a test rather than quietly changing which pairs a screen admits.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest

SCREEN_DIR = Path(__file__).resolve().parents[1] / "research" / "pairs" / "screen_nifty50"
sys.path.insert(0, str(SCREEN_DIR))

from screen import (  # noqa: E402
    benjamini_hochberg,
    half_life_sessions,
    hurst_exponent,
    lot_quantisation,
    mean_crossings,
    min_notional_for_lot_gate,
    round_trip_cost_bps,
)


def ou_path(*, theta: float, sigma: float, n: int, seed: int) -> np.ndarray:
    """Discrete OU: e_t = (1 - theta) e_{t-1} + sigma * shock, mean zero."""
    rng = np.random.default_rng(seed)
    e = np.zeros(n)
    for t in range(1, n):
        e[t] = (1.0 - theta) * e[t - 1] + sigma * rng.standard_normal()
    return e


@pytest.mark.parametrize("target_half_life", [2.0, 5.0, 20.0])
def test_half_life_recovers_the_ou_speed(target_half_life: float) -> None:
    theta = math.log(2.0) / target_half_life
    estimated = half_life_sessions(ou_path(theta=theta, sigma=0.01, n=4000, seed=7))
    assert estimated == pytest.approx(target_half_life, rel=0.15)


def test_half_life_of_a_random_walk_is_not_finite_enough_to_pass_the_gate() -> None:
    rng = np.random.default_rng(11)
    walk = np.cumsum(rng.standard_normal(2000)) * 0.01
    estimated = half_life_sessions(walk)
    assert estimated > 5.0  # infinite when the fitted slope is non-negative


def test_hurst_separates_mean_reversion_from_a_random_walk() -> None:
    reverting = hurst_exponent(ou_path(theta=math.log(2) / 3, sigma=0.01, n=3000, seed=3))
    rng = np.random.default_rng(3)
    walk = np.cumsum(rng.standard_normal(3000)) * 0.01
    assert reverting < 0.5 < hurst_exponent(walk)


def test_mean_crossings_counts_sign_changes_about_the_window_mean() -> None:
    assert mean_crossings(np.array([1.0, -1.0, 1.0, -1.0])) == 3
    assert mean_crossings(np.array([1.0, 2.0, 3.0, 4.0])) == 1


def test_bh_is_a_step_up_not_a_per_hypothesis_comparison() -> None:
    """A p-value above its own bar is still rejected when a later rank clears its bar.

    m = 4, q = 0.10 gives bars 0.025, 0.05, 0.075, 0.10. The second p-value (0.04) sits
    below its bar, so the step-up rejects ranks 1 and 2 — including the first p-value,
    which a naive per-index test would also reject, and the third (0.08), which it must
    not.
    """
    rejected, bars = benjamini_hochberg([0.01, 0.04, 0.08, 0.9], q=0.10)
    assert bars == pytest.approx([0.025, 0.05, 0.075, 0.10])
    assert rejected == [True, True, False, False]


def test_bh_rejects_nothing_when_the_smallest_p_exceeds_the_rank_one_bar() -> None:
    pvalues = [0.03] + [0.5] * 53  # the screen's own shape: m = 54, best p = 0.03
    rejected, bars = benjamini_hochberg(pvalues, q=0.10)
    assert bars[0] == pytest.approx(0.10 / 54)
    assert not any(rejected)


def test_bh_rejects_every_hypothesis_when_all_p_values_are_tiny() -> None:
    rejected, _ = benjamini_hochberg([1e-6] * 10, q=0.10)
    assert all(rejected)


def test_lot_quantisation_is_exact_when_the_notional_is_a_whole_number_of_lots() -> None:
    # Leg A: 1000 * 100 = Rs 1L per lot, 10 lots at N = Rs 10L. Leg B at beta = 1.0:
    # 500 * 200 = Rs 1L per lot, 10 lots. Both land exactly, so beta is realised.
    quant = lot_quantisation(
        price_a=1000.0, price_b=500.0, beta=1.0, lot_a=100, lot_b=200, notional=1_000_000.0
    )
    assert quant["lots_a"] == 10
    assert quant["lots_b"] == 10
    assert quant["beta_effective"] == pytest.approx(1.0)
    assert quant["lot_error"] == pytest.approx(0.0)


def test_lot_quantisation_error_is_large_when_one_lot_overshoots_the_target() -> None:
    # Leg B's lot is Rs 5L while the target leg-B notional is beta * N = Rs 1L, so the
    # floor of one lot realises five times the intended hedge.
    quant = lot_quantisation(
        price_a=1000.0, price_b=1000.0, beta=0.1, lot_a=100, lot_b=500, notional=1_000_000.0
    )
    assert quant["lots_b"] == 1
    assert quant["beta_effective"] == pytest.approx(0.5)
    assert quant["lot_error"] == pytest.approx(4.0)


def test_lot_quantisation_sizes_on_magnitude_and_keeps_the_sign_of_beta() -> None:
    positive = lot_quantisation(
        price_a=1000.0, price_b=500.0, beta=1.0, lot_a=100, lot_b=200, notional=1_000_000.0
    )
    negative = lot_quantisation(
        price_a=1000.0, price_b=500.0, beta=-1.0, lot_a=100, lot_b=200, notional=1_000_000.0
    )
    assert negative["lots_b"] == positive["lots_b"]
    assert negative["beta_effective"] == pytest.approx(-1.0)
    assert negative["lot_error"] == pytest.approx(0.0)


def test_cost_scales_with_the_second_leg_notional() -> None:
    """At beta = 1 both legs carry N and the framework's 12.3 bps applies unscaled."""
    assert round_trip_cost_bps(1.0)["cost_hard_bps"] == pytest.approx(12.3)
    # A half-sized second leg carries three quarters of the two-leg cost.
    assert round_trip_cost_bps(0.5)["cost_hard_bps"] == pytest.approx(12.3 * 0.75)
    # Sign does not change what a leg costs to trade.
    assert round_trip_cost_bps(-1.0)["cost_hard_bps"] == pytest.approx(12.3)


def test_the_two_admission_inequalities_bind_as_specified() -> None:
    """A spread that reverts in 4 sessions with 60 bps sigma passes; 6 sessions fails."""
    fast = ou_path(theta=math.log(2) / 4, sigma=0.004, n=4000, seed=21)
    assert half_life_sessions(fast) <= 5.0
    assert np.std(fast, ddof=1) * 1e4 >= 50.0

    slow = ou_path(theta=math.log(2) / 12, sigma=0.004, n=4000, seed=21)
    assert half_life_sessions(slow) > 5.0


def test_min_notional_for_lot_gate_finds_where_the_size_starts_working() -> None:
    """Beta 0.73 with Rs 6.7L lots cannot be expressed at Rs 10L; a larger size can."""
    kwargs = dict(price_a=3334.0, price_b=6688.0, beta=0.73, lot_a=200, lot_b=100)
    assert lot_quantisation(**kwargs, notional=1_000_000.0)["lot_error"] > 0.10
    threshold = min_notional_for_lot_gate(**kwargs)
    assert threshold > 1_000_000.0
    assert lot_quantisation(**kwargs, notional=threshold)["lot_error"] <= 0.10
