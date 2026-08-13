"""CSCV against constructions whose answer is known before the code runs.

The three that pin the direction and the arithmetic:

* a column that is better in **every** block — the in-sample winner is always the
  out-of-sample winner, so every logit is positive and PBO is exactly 0. With two columns
  the winner's out-of-sample rank is 2 of 2, so :math:`\\bar\\omega = 2/3` and every logit
  is exactly :math:`\\ln 2` — a hand-computable value, not an approximate one;
* **identical** columns — selection carries no information, every rank ties at the
  median, every logit is exactly 0, and PBO is 1 under the paper's
  :math:`P(\\lambda \\le 0)` convention;
* **independent noise** — averaged over seeds, PBO sits near 0.5. Per seed it does not:
  the spread across twenty seeds runs from roughly 0.1 to 0.7 at twenty configurations,
  which is a fact about the estimator worth knowing before a single PBO number is used to
  decide anything.
"""

from __future__ import annotations

import datetime as dt
import math

import numpy as np
import pytest

from xman_research.validation.pbo import (
    matrix_from_columns,
    performance_matrix,
    probability_of_backtest_overfitting,
)
from xman_research.validation.series import ReturnSeries, SeriesError


def columns(*values: list[float]) -> list[list[float]]:
    return list(values)


def test_a_uniformly_better_column_gives_pbo_zero_and_logit_ln_two() -> None:
    """Column A beats column B in every block, so the choice always generalises."""
    length = 40
    good = [0.01 + (0.001 if index % 2 else -0.001) for index in range(length)]
    bad = [-0.01 + (0.001 if index % 2 else -0.001) for index in range(length)]
    result = probability_of_backtest_overfitting(
        matrix_from_columns(["good", "bad"], columns(good, bad)), partitions=4
    )
    assert result.value == 0.0
    assert result.splits_evaluated == 6  # C(4, 2)
    for logit in result.logits:
        assert logit == pytest.approx(math.log(2.0))
    assert set(result.best_labels) == {"good"}


def test_identical_columns_tie_at_the_median() -> None:
    """No information in the choice: every logit is exactly 0, and 0 counts as overfit."""
    values = [0.01, -0.02, 0.03, 0.0] * 10
    result = probability_of_backtest_overfitting(
        matrix_from_columns(["a", "b", "c"], columns(values, list(values), list(values))),
        partitions=4,
    )
    assert result.logits == pytest.approx((0.0,) * 6)
    assert result.value == 1.0


def test_independent_noise_averages_near_one_half_and_varies_widely() -> None:
    """The estimator's own sampling behaviour, measured rather than assumed."""
    values = []
    for seed in range(20):
        rng = np.random.default_rng(1000 + seed)
        data = rng.normal(0.0, 1.0, size=(400, 20))
        values.append(
            probability_of_backtest_overfitting(
                matrix_from_columns([f"c{i}" for i in range(20)], list(data.T)), partitions=8
            ).value
        )
    assert 0.35 < float(np.mean(values)) < 0.65
    # The spread is the point: a single PBO number is weak evidence at this width.
    assert max(values) - min(values) > 0.2


def test_a_dominant_column_among_many_is_recognised() -> None:
    rng = np.random.default_rng(4242)
    data = rng.normal(0.0, 1.0, size=(800, 20))
    data[:, 7] += 0.5
    result = probability_of_backtest_overfitting(
        matrix_from_columns([f"c{i}" for i in range(20)], list(data.T)), partitions=8
    )
    assert result.value == 0.0
    assert set(result.best_labels) == {"c7"}


def test_the_split_count_is_the_full_symmetric_set() -> None:
    rng = np.random.default_rng(5)
    data = rng.normal(0.0, 1.0, size=(320, 4))
    result = probability_of_backtest_overfitting(
        matrix_from_columns(list("abcd"), list(data.T)), partitions=10
    )
    assert result.splits_evaluated == math.comb(10, 5) == 252
    assert result.partitions == 10


def test_leftover_observations_are_dropped_and_reported() -> None:
    rng = np.random.default_rng(6)
    data = rng.normal(0.0, 1.0, size=(103, 3))
    result = probability_of_backtest_overfitting(
        matrix_from_columns(list("abc"), list(data.T)), partitions=4
    )
    assert result.observations_used == 100
    assert result.observations_dropped == 3


def test_odd_or_tiny_partition_counts_are_refused() -> None:
    rng = np.random.default_rng(7)
    matrix = matrix_from_columns(list("ab"), list(rng.normal(0, 1, size=(100, 2)).T))
    with pytest.raises(ValueError, match="even number of partitions"):
        probability_of_backtest_overfitting(matrix, partitions=7)
    with pytest.raises(ValueError, match="even number of partitions"):
        probability_of_backtest_overfitting(matrix, partitions=2)


def test_one_configuration_cannot_be_cross_validated() -> None:
    rng = np.random.default_rng(8)
    with pytest.raises(SeriesError, match="at least 2"):
        probability_of_backtest_overfitting(
            matrix_from_columns(["only"], list(rng.normal(0, 1, size=(100, 1)).T)), partitions=4
        )


def test_too_short_a_history_is_refused_rather_than_partitioned_into_singletons() -> None:
    rng = np.random.default_rng(9)
    with pytest.raises(SeriesError, match="cannot be cut"):
        probability_of_backtest_overfitting(
            matrix_from_columns(list("ab"), list(rng.normal(0, 1, size=(10, 2)).T)), partitions=8
        )


def test_series_on_different_sessions_cannot_be_pooled() -> None:
    first = ReturnSeries(
        dates=tuple(dt.date(2025, 1, 6) + dt.timedelta(days=i) for i in range(20)),
        net=tuple(0.001 * i for i in range(20)),
        drag=(0.0,) * 20,
        label="a",
    )
    second = ReturnSeries(
        dates=tuple(dt.date(2025, 2, 6) + dt.timedelta(days=i) for i in range(20)),
        net=tuple(0.001 * i for i in range(20)),
        drag=(0.0,) * 20,
        label="b",
    )
    with pytest.raises(SeriesError, match="not on the same sessions"):
        performance_matrix({"a": first, "b": second})
