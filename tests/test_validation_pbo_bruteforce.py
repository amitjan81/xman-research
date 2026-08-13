"""An independent brute-force CSCV, checked against the optimised implementation.

The C6 report claimed PBO had been "cross-checked against an independent brute-force
implementation (identical to 4 dp)". It had not: no second implementation existed
anywhere in the tree. In a component whose whole premise is that an evidence claim must
be verifiable, that is the worst possible claim to have got wrong, so this file is the
thing the report described.

**Independent means independent.** :func:`brute_force_pbo` below re-slices the actual
rows for every split and takes a plain ``mean/std`` per column, where
:mod:`xman_research.validation.pbo` precomputes per-partition sums and reconstructs each
split's variance from them. Same estimator, deliberately different arithmetic: the
optimised route is the one that could be subtly wrong, and a cross-check that shared its
algebra would agree with it for the wrong reason. Ranking is done by
``numpy.argsort``-free comparison counting rather than by the double-argsort the
implementation uses.

Three conventions have to be replicated or the comparison fails for a reason that is not
a bug: leftover observations are dropped from the **end** before partitioning, a
zero-dispersion column scores 0.0 rather than being disqualified, and ties take the
**average** 1-based rank.
"""

from __future__ import annotations

import math
from itertools import combinations

import numpy as np

from xman_research.validation.pbo import (
    matrix_from_columns,
    probability_of_backtest_overfitting,
)


def _sharpe(block: np.ndarray) -> float:
    """Per-period Sharpe of one column over one set of rows, by the plainest route.

    Constancy is tested by ``max == min``, which is exact, rather than by whether the
    computed standard deviation came out as zero — which is not. A two-pass variance does
    not cancel the way the implementation's sums-of-squares route does, but it does not
    give a hard zero either: subtracting a mean that is one ulp off leaves a variance
    around 1e-38 and a standard deviation around 1e-19, which turns a flat column into a
    Sharpe of 4e16 and hands it every split. Both routes needed telling that a column
    which never moves has no dispersion; neither could infer it from its own arithmetic.
    """
    if float(np.max(block)) == float(np.min(block)):
        return 0.0
    count = len(block)
    mean = float(np.mean(block))
    variance = float(sum((float(value) - mean) ** 2 for value in block) / (count - 1))
    stdev = math.sqrt(variance)
    return 0.0 if stdev <= 0.0 else mean / stdev


def _average_rank(metrics: list[float], index: int) -> float:
    """1-based rank of ``index`` among ``metrics``, averaging over ties.

    Counted directly — how many are strictly smaller, how many are tied — rather than by
    sorting, so this shares no code path with the implementation's double ``argsort``.
    """
    value = metrics[index]
    below = sum(1 for other in metrics if other < value)
    tied = sum(1 for other in metrics if other == value)
    # Ranks below+1 .. below+tied are shared by the tied group; their mean is the rank.
    return below + (tied + 1) / 2.0


def brute_force_pbo(values: np.ndarray, *, partitions: int) -> tuple[float, list[float]]:
    """CSCV over every C(S, S/2) split, slicing the rows each time. No shortcuts."""
    rows, columns = values.shape
    per_partition = rows // partitions
    used = per_partition * partitions
    trimmed = values[:used]  # leftovers dropped from the END, as the implementation does
    blocks = [
        trimmed[index * per_partition : (index + 1) * per_partition] for index in range(partitions)
    ]

    half = partitions // 2
    logits: list[float] = []
    for chosen in combinations(range(partitions), half):
        rest = [index for index in range(partitions) if index not in chosen]
        in_rows = np.concatenate([blocks[index] for index in chosen])
        out_rows = np.concatenate([blocks[index] for index in rest])
        in_metric = [_sharpe(in_rows[:, column]) for column in range(columns)]
        out_metric = [_sharpe(out_rows[:, column]) for column in range(columns)]
        best = max(range(columns), key=lambda column: (in_metric[column], -column))
        omega = _average_rank(out_metric, best) / (columns + 1)
        logits.append(math.log(omega / (1.0 - omega)))
    return sum(1 for value in logits if value <= 0.0) / len(logits), logits


def _matrix(seed: int, rows: int, columns: int, *, drift: float = 0.0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.normal(drift, 0.006, size=(rows, columns))


def test_the_brute_force_and_the_optimised_cscv_agree() -> None:
    """The claim the previous report made, now actually executed.

    Three shapes: pure noise (where PBO should sit near 0.5), a drifting family, and a
    row count that does not divide evenly into the partitions so the drop-from-the-end
    convention is exercised on both sides.
    """
    cases = [
        ("noise, exact fit", _matrix(101, 480, 8), 8),
        ("drift", _matrix(202, 480, 6, drift=0.0004), 8),
        ("leftover rows dropped", _matrix(303, 487, 5), 6),
        ("wider family", _matrix(404, 320, 12), 4),
    ]
    for label, values, partitions in cases:
        columns = [list(values[:, index]) for index in range(values.shape[1])]
        matrix = matrix_from_columns(
            [f"cfg{index:02d}" for index in range(values.shape[1])], columns
        )
        optimised = probability_of_backtest_overfitting(matrix, partitions=partitions)
        expected, expected_logits = brute_force_pbo(values, partitions=partitions)

        assert round(optimised.value, 4) == round(expected, 4), label
        assert optimised.splits_evaluated == len(expected_logits), label
        deviation = max(
            abs(left - right) for left, right in zip(optimised.logits, expected_logits, strict=True)
        )
        # Not a tolerance chosen to make this pass: the two routes differ only in
        # floating-point association, so the observed deviation is at the 1e-12 level.
        # If this ever loosens, the estimators have diverged, not the arithmetic.
        assert deviation < 1e-9, f"{label}: max logit deviation {deviation:.3e}"


def test_the_zero_dispersion_convention_is_shared() -> None:
    """A flat column scores 0.0 — not disqualified, not infinite. Pinned separately.

    It is kept out of the cross-check above because a matrix of constant columns makes
    every split a tie, which would let two implementations agree without either ranking
    anything.
    """
    values = _matrix(505, 200, 3)
    values[:, 2] = 0.004  # a configuration with no dispersion at all
    columns = [list(values[:, index]) for index in range(3)]
    matrix = matrix_from_columns(("a", "b", "flat"), columns)
    optimised = probability_of_backtest_overfitting(matrix, partitions=4)
    expected, _ = brute_force_pbo(values, partitions=4)
    assert round(optimised.value, 4) == round(expected, 4)
    # "Not the winner and not disqualified" is the convention, and it is the second half
    # that is easy to get wrong: a flat column scores 0.0, so it legitimately wins a split
    # where every other configuration was negative in sample, and legitimately loses one
    # where any was positive. Both happen here. What must not happen — and did, before the
    # cancellation guard — is the flat column winning *every* split on a Sharpe of 1e7.
    assert set(optimised.best_labels) == {"a", "b", "flat"}
    assert optimised.best_labels.count("flat") == 1


def test_identical_columns_give_a_logit_of_exactly_zero() -> None:
    """The average-rank tie convention, on both implementations."""
    column = list(_matrix(606, 160, 1)[:, 0])
    matrix = matrix_from_columns(("a", "b", "c", "d"), [column] * 4)
    optimised = probability_of_backtest_overfitting(matrix, partitions=4)
    assert all(abs(value) < 1e-12 for value in optimised.logits)
    assert optimised.value == 1.0  # every logit is <= 0, which is the definition
    values = np.column_stack([np.asarray(column)] * 4)
    expected, expected_logits = brute_force_pbo(values, partitions=4)
    assert expected == optimised.value
    assert all(abs(value) < 1e-12 for value in expected_logits)
