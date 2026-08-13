"""Probability of backtest overfitting, by combinatorially symmetric cross-validation.

Bailey, D. H., Borwein, J., López de Prado, M. and Zhu, Q. J. (2017). "The Probability of
Backtest Overfitting." *Journal of Computational Finance*, 20(4), 39-69.

The question CSCV asks is not "is this strategy good" but "does picking the in-sample
winner tell me anything about the out-of-sample winner". The procedure:

1. Take the ``T x N`` matrix of per-period returns: ``T`` observations, ``N``
   configurations that were all tried.
2. Cut the rows into ``S`` contiguous partitions of equal size.
3. For **every** way of choosing ``S/2`` partitions as in-sample (there are
   :math:`\\binom{S}{S/2}` of them, and the complement is out-of-sample — this is what
   *symmetric* means, and it is why the result does not depend on where you happened to
   cut the history):

   * find the configuration with the best in-sample performance, :math:`n^*`;
   * take its **rank** among all configurations out-of-sample,
     :math:`\\bar\\omega = \\mathrm{rank}/(N+1)`;
   * take the logit :math:`\\lambda = \\ln\\frac{\\bar\\omega}{1-\\bar\\omega}`.

4. **PBO** is :math:`P(\\lambda \\le 0)` — the share of splits where the in-sample winner
   landed in the bottom half out-of-sample.

A PBO near 0.5 is the signature of selection on noise: knowing which configuration won
in-sample tells you nothing about which wins out-of-sample. A PBO near 0 means the
ranking is stable, which is what a real effect looks like.

The ``(N+1)`` denominator is not cosmetic: with ``rank/N`` the best configuration scores
:math:`\\bar\\omega = 1`, whose logit is :math:`+\\infty`, and a single such split makes
the mean logit meaningless. Ranks run ``1..N``, so ``rank/(N+1)`` is strictly inside
``(0, 1)``.

This module holds no opinion about what PBO is acceptable. That is a threshold, and
thresholds are written down before the run — see :mod:`xman_research.validation.gate`.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import combinations

import numpy as np

from xman_research.validation.series import ReturnSeries, SeriesError

__all__ = [
    "PBOResult",
    "PerformanceMatrix",
    "matrix_from_columns",
    "performance_matrix",
    "probability_of_backtest_overfitting",
]


@dataclass(frozen=True, slots=True)
class PerformanceMatrix:
    """``T x N`` per-period returns for ``N`` configurations over the same ``T`` sessions."""

    labels: tuple[str, ...]
    values: np.ndarray

    def __post_init__(self) -> None:
        if self.values.ndim != 2:
            raise SeriesError(f"a performance matrix is 2-D, got shape {self.values.shape}")
        if self.values.shape[1] != len(self.labels):
            raise SeriesError(f"{self.values.shape[1]} columns but {len(self.labels)} labels")


def performance_matrix(runs: Mapping[str, ReturnSeries]) -> PerformanceMatrix:
    """Assemble the matrix from per-configuration series over identical dates.

    Identical dates are required rather than aligned-with-gaps: CSCV cuts the rows into
    time partitions, so a column whose observations sit on different sessions from its
    neighbours would put different histories in the same partition.
    """
    if len(runs) < 2:
        raise SeriesError(
            f"CSCV compares configurations against each other and needs at least 2, got {len(runs)}"
        )
    labels = tuple(runs)
    reference = runs[labels[0]].dates
    for label in labels[1:]:
        if runs[label].dates != reference:
            raise SeriesError(
                f"configuration {label!r} is not on the same sessions as {labels[0]!r}"
            )
    values = np.column_stack([np.asarray(runs[label].net, dtype=float) for label in labels])
    return PerformanceMatrix(labels=labels, values=values)


@dataclass(frozen=True, slots=True)
class PBOResult:
    """The CSCV outcome, with the parts needed to argue with the number."""

    value: float
    logits: tuple[float, ...]
    partitions: int
    splits_evaluated: int
    configurations: int
    observations_used: int
    observations_dropped: int
    best_labels: tuple[str, ...]

    @property
    def median_logit(self) -> float:
        return float(np.median(np.asarray(self.logits)))

    def as_dict(self) -> dict[str, object]:
        return {
            "pbo": self.value,
            "pbo_median_logit": self.median_logit,
            "pbo_partitions": self.partitions,
            "pbo_splits": self.splits_evaluated,
            "pbo_configurations": self.configurations,
            "pbo_observations_used": self.observations_used,
            "pbo_observations_dropped": self.observations_dropped,
        }


def probability_of_backtest_overfitting(
    performance: PerformanceMatrix | Mapping[str, ReturnSeries],
    *,
    partitions: int = 16,
) -> PBOResult:
    """Run CSCV over every symmetric split and report :math:`P(\\lambda \\le 0)`.

    ``partitions`` must be even — the splits are into halves — and at least 4 to give
    :math:`\\binom{4}{2} = 6` splits; below that the estimate is a handful of draws.
    Observations that do not divide evenly into the partitions are dropped from the
    **end** of the series (the most recent sessions), and the number dropped is reported
    rather than absorbed.

    In-sample performance is the per-period Sharpe of each configuration on the chosen
    partitions. A configuration with zero dispersion over a subset scores 0.0 there: it
    is not the winner and it is not disqualified.
    """
    matrix = (
        performance
        if isinstance(performance, PerformanceMatrix)
        else performance_matrix(performance)
    )
    if partitions < 4 or partitions % 2 != 0:
        raise ValueError(f"CSCV needs an even number of partitions, at least 4, got {partitions}")
    rows, columns = matrix.values.shape
    if columns < 2:
        raise SeriesError("CSCV needs at least 2 configurations to rank against each other")
    if rows < partitions * 2:
        raise SeriesError(
            f"{rows} observations cannot be cut into {partitions} partitions of at least "
            "2 observations each; use fewer partitions or a longer history"
        )
    per_partition = rows // partitions
    used = per_partition * partitions
    values = matrix.values[:used]

    # Per-partition sums and sums of squares. Every split's mean and variance is then a
    # sum over S/2 partitions rather than a pass over the data, which turns C(16,8) x T x N
    # arithmetic into C(16,8) x S x N.
    blocks = values.reshape(partitions, per_partition, columns)
    block_sum = blocks.sum(axis=1)
    block_square_sum = (blocks**2).sum(axis=1)

    half = partitions // 2
    length = per_partition * half
    logits: list[float] = []
    best_labels: list[str] = []
    for chosen in combinations(range(partitions), half):
        in_sample = np.array(chosen)
        out_sample = np.array([index for index in range(partitions) if index not in set(chosen)])
        in_metric = _sharpe_of_blocks(block_sum[in_sample], block_square_sum[in_sample], length)
        out_metric = _sharpe_of_blocks(block_sum[out_sample], block_square_sum[out_sample], length)
        best = int(np.argmax(in_metric))
        best_labels.append(matrix.labels[best])
        # Average rank on ties, so a matrix of identical columns gives a logit of exactly
        # 0 rather than an artefact of column order.
        order = np.argsort(np.argsort(out_metric))
        rank = _average_rank(out_metric, order, best)
        omega = rank / (columns + 1)
        logits.append(math.log(omega / (1.0 - omega)))
    return PBOResult(
        value=sum(1 for value in logits if value <= 0.0) / len(logits),
        logits=tuple(logits),
        partitions=partitions,
        splits_evaluated=len(logits),
        configurations=columns,
        observations_used=used,
        observations_dropped=rows - used,
        best_labels=tuple(best_labels),
    )


def _sharpe_of_blocks(sums: np.ndarray, square_sums: np.ndarray, length: int) -> np.ndarray:
    """Per-column per-period Sharpe over a set of partitions, from their sums."""
    total = sums.sum(axis=0)
    square_total = square_sums.sum(axis=0)
    mean = total / length
    variance = (square_total - length * mean**2) / (length - 1)
    stdev = np.sqrt(np.maximum(variance, 0.0))
    return np.divide(mean, stdev, out=np.zeros_like(mean), where=stdev > 0.0)


def _average_rank(metric: np.ndarray, order: np.ndarray, index: int) -> float:
    """1-based rank of ``index``, averaged across ties."""
    tied = np.flatnonzero(metric == metric[index])
    return float(np.mean(order[tied]) + 1.0)


def matrix_from_columns(
    labels: Sequence[str], columns: Sequence[Sequence[float]]
) -> PerformanceMatrix:
    """Build a matrix from raw columns — for tests and for callers not holding series."""
    return PerformanceMatrix(
        labels=tuple(labels),
        values=np.column_stack([np.asarray(column, dtype=float) for column in columns]),
    )
