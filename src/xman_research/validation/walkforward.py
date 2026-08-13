"""Walk-forward evaluation: fit on the past, judge on what came after, repeatedly.

Spec §7 defers combinatorial cross-validation until in-sample rigour is the binding
constraint, so this is the plain rolling form — and the plain form is what makes the
overfit/genuine separation visible in the first place. A strategy whose parameters were
chosen by looking at the whole history has no out-of-sample; a strategy re-fitted on each
training block and judged only on the block after it has nothing else.

**Only the out-of-sample halves are judged.** :attr:`WalkForwardReport.out_of_sample` is
the concatenation of every test fold, in date order, with overlaps refused — that series
is what the rest of C6 computes its statistics on. The in-sample fits are kept for
inspection (which parameters the fit chose, fold by fold, is the clearest single view of
whether a strategy is stable or is chasing noise) and are never scored.

The fold callable is the seam to C5: given a :class:`Split`, run the fit on
``split.train`` and the backtest on ``split.test``, and hand back a
:class:`~xman_research.validation.series.ReturnSeries` for the test window only. The
acceptance tests pass a synthetic implementation; the C5 adapter passes one that calls
``run_backtest`` twice.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

from xman_research.trial_log import DataWindow
from xman_research.validation.series import ReturnSeries, SeriesError

__all__ = [
    "FoldResult",
    "Split",
    "WalkForwardReport",
    "walk_forward",
    "walk_forward_splits",
]


@dataclass(frozen=True, slots=True)
class Split:
    """One fit window and the window judged on it, which never overlap."""

    train: DataWindow
    test: DataWindow

    def __post_init__(self) -> None:
        if self.test.start <= self.train.end:
            raise SeriesError(
                f"the test window {self.test} starts on or before the training window "
                f"{self.train} ends. A fold whose test data was in its own fit is not "
                "out-of-sample."
            )

    def __str__(self) -> str:
        return f"fit {self.train} -> test {self.test}"


def walk_forward_splits(
    sessions: Sequence[dt.date],
    *,
    train_length: int,
    test_length: int,
    step: int | None = None,
    anchored: bool = False,
) -> tuple[Split, ...]:
    """Cut a list of session dates into rolling fit/test folds.

    Lengths are in **sessions, not calendar days**, so a fold is the same amount of
    evidence wherever it lands — calendar-length folds would silently shrink across
    holiday-heavy stretches, and the Indian calendar is holiday-heavy.

    ``step`` defaults to ``test_length``, which makes the test folds exactly partition the
    evaluable history: no session is judged twice, and none is skipped. A smaller step
    overlaps the test folds, which inflates the apparent sample; it is allowed, and
    :func:`walk_forward` refuses to chain overlapping folds into one series.

    ``anchored=True`` grows the training window from the start instead of rolling it,
    which is the right shape when the effect is believed stationary and more history is
    better. Rolling is the default because a market with the epoch breaks this one has is
    not stationary across years.
    """
    if train_length < 2 or test_length < 1:
        raise SeriesError(
            f"train_length must be at least 2 and test_length at least 1, got "
            f"{train_length} and {test_length}"
        )
    ordered = sorted(sessions)
    if len(set(ordered)) != len(ordered):
        raise SeriesError("session dates contain duplicates")
    stride = test_length if step is None else step
    if stride < 1:
        raise SeriesError(f"step must be at least 1, got {stride}")
    splits: list[Split] = []
    start = 0
    while start + train_length + test_length <= len(ordered):
        train_start = 0 if anchored else start
        train_end = start + train_length - 1
        test_start = train_end + 1
        test_end = test_start + test_length - 1
        splits.append(
            Split(
                train=DataWindow(ordered[train_start], ordered[train_end]),
                test=DataWindow(ordered[test_start], ordered[test_end]),
            )
        )
        start += stride
    if not splits:
        raise SeriesError(
            f"{len(ordered)} sessions cannot hold a {train_length}-session fit plus a "
            f"{test_length}-session test"
        )
    return tuple(splits)


@dataclass(frozen=True, slots=True)
class FoldResult:
    """What one fold produced: the parameters the fit chose, and the test returns."""

    split: Split
    returns: ReturnSeries
    parameters: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        first, last = self.returns.dates[0], self.returns.dates[-1]
        if first < self.split.test.start or last > self.split.test.end:
            raise SeriesError(
                f"fold returned {first}..{last}, which is outside its test window "
                f"{self.split.test}. A fold that reports returns from outside its own "
                "test window is reporting in-sample performance as out-of-sample."
            )


@dataclass(frozen=True, slots=True)
class WalkForwardReport:
    """Every fold, and the single out-of-sample series they concatenate to."""

    folds: tuple[FoldResult, ...]
    out_of_sample: ReturnSeries

    @property
    def parameters_by_fold(self) -> tuple[Mapping[str, object], ...]:
        """The fit's choice per fold — instability here is overfitting in plain sight."""
        return tuple(fold.parameters for fold in self.folds)

    def as_dict(self) -> dict[str, object]:
        return {
            "folds": len(self.folds),
            "out_of_sample_periods": len(self.out_of_sample),
            "out_of_sample_window": str(self.out_of_sample.window),
            "parameters_by_fold": [dict(item) for item in self.parameters_by_fold],
        }


def walk_forward(
    sessions: Sequence[dt.date],
    *,
    run: Callable[[Split], FoldResult],
    train_length: int,
    test_length: int,
    step: int | None = None,
    anchored: bool = False,
    label: str = "walk-forward out-of-sample",
) -> WalkForwardReport:
    """Run ``run`` over every fold and chain the test returns into one series.

    ``run`` is called once per fold, in date order, and must fit on ``split.train`` and
    report returns for ``split.test`` only — :class:`FoldResult` refuses returns that fall
    outside the test window, which is the mistake that turns a walk-forward into an
    in-sample run wearing its name.
    """
    splits = walk_forward_splits(
        sessions,
        train_length=train_length,
        test_length=test_length,
        step=step,
        anchored=anchored,
    )
    folds = tuple(run(split) for split in splits)
    return WalkForwardReport(
        folds=folds,
        out_of_sample=ReturnSeries.chained((fold.returns for fold in folds), label=label),
    )
