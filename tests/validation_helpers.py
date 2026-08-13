"""Synthetic strategies with known truth, for the criterion-1 acceptance test.

Two families, built to be as alike as possible except in the one respect that matters:

* **genuine** — every configuration has a real positive drift, and they differ slightly
  from each other. Selecting the best one in sample is selecting a genuinely better
  configuration, so the choice carries information forward.
* **overfit** — every configuration is pure noise with zero drift. Selecting the best one
  in sample is selecting the luckiest one, and the choice carries nothing forward.

Both families are given the same short-option *shape*: a small positive return most days
and an occasional large loss, so the return distributions are negatively skewed and
fat-tailed in both cases. If the separation came from distribution shape rather than from
edge, the test would prove nothing about the gate.

Everything is seeded. Two runs of the same seed produce the same numbers, on any machine.
"""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from xman_research.trial_log import DataWindow
from xman_research.validation.series import FeasibilityFacts, ReturnSeries, RunEvidence
from xman_research.validation.walkforward import FoldResult, Split

DAILY_VOLATILITY = 0.006
SHOCK_PROBABILITY = 0.02
SHOCK_SIZE = 0.020
COST_DRAG = 0.00025
"""Per-session cost drag in return units — roughly 6 bps of the capital base a day."""


def trading_sessions(start: dt.date, length: int) -> tuple[dt.date, ...]:
    """``length`` consecutive weekdays from ``start``. A synthetic calendar, not NSE's."""
    days: list[dt.date] = []
    day = start
    while len(days) < length:
        if day.weekday() < 5:
            days.append(day)
        day += dt.timedelta(days=1)
    return tuple(days)


@dataclass(frozen=True, slots=True)
class Family:
    """A set of configurations that were all tried, over the same sessions."""

    label: str
    dates: tuple[dt.date, ...]
    net: Mapping[str, np.ndarray]

    def series(self, name: str, *, drag: float = COST_DRAG) -> ReturnSeries:
        values = self.net[name]
        return ReturnSeries(
            dates=self.dates,
            net=tuple(float(value) for value in values),
            drag=tuple(drag for _ in values),
            label=f"{self.label}:{name}",
        )

    def restricted(self, name: str, window: DataWindow) -> ReturnSeries:
        return self.series(name).restricted_to(window)

    def best_on(self, window: DataWindow) -> str:
        """The configuration with the highest Sharpe over ``window`` — the fit."""
        mask = np.array([window.start <= day <= window.end for day in self.dates])
        best_name, best_sharpe = "", -np.inf
        for name, values in self.net.items():
            block = values[mask]
            stdev = block.std(ddof=1)
            sharpe = 0.0 if stdev == 0 else float(block.mean() / stdev)
            if sharpe > best_sharpe:
                best_name, best_sharpe = name, sharpe
        return best_name


IDIOSYNCRATIC_WEIGHT = 0.5
"""How much of a configuration's noise is its own rather than the market's.

Variants of one strategy on one underlying are strongly correlated — they trade the same
index on the same days. Without a common factor every configuration is its own
independent lottery, and a configuration that happened to draw few tail shocks looks
persistently good in *every* partition, which is a property of the synthetic rather than
of the strategy and which drags CSCV's PBO well below the 0.5 that pure selection noise
should give. The common factor is what makes the synthetic family behave like a family."""


def _shaped_noise(
    rng: np.random.Generator,
    length: int,
    drift: float,
    common: np.ndarray | None = None,
) -> np.ndarray:
    """Drift plus (common + own) noise, minus an occasional large loss.

    The subtracted shock is the short-option tail: a small premium most days, a large
    loss rarely. It makes both families negatively skewed and fat-tailed, so the gate
    cannot separate them on distribution shape.
    """
    body = rng.normal(0.0, DAILY_VOLATILITY, size=length)
    if common is None:
        mixed = body
    else:
        mixed = math.sqrt(1.0 - IDIOSYNCRATIC_WEIGHT**2) * common + IDIOSYNCRATIC_WEIGHT * body
    shocks = (rng.random(length) < SHOCK_PROBABILITY) * SHOCK_SIZE
    return drift + mixed - shocks


def market_factor(rng: np.random.Generator, length: int) -> np.ndarray:
    """The move every configuration in a family shares."""
    return rng.normal(0.0, DAILY_VOLATILITY, size=length)


def genuine_family(
    dates: Sequence[dt.date],
    *,
    seed: int,
    configurations: int = 12,
    edge: float = 0.00055,
    edge_step: float = 0.00008,
) -> Family:
    """Every configuration has real edge, and some are genuinely better than others.

    The drift runs from ``edge`` to ``edge + 11*edge_step``; the 2%-probability shock
    costs about 0.0004 a session, so realised means run from roughly 0.00015 to 0.00103 —
    a best configuration near a 2.2 annualised Sharpe. Two properties matter and both are
    deliberate: the effect is real (so it survives out-of-sample), and the configurations
    differ (so choosing between them in sample carries information, which is what CSCV
    measures).
    """
    rng = np.random.default_rng(seed)
    dates = tuple(dates)
    common = market_factor(rng, len(dates))
    net = {
        f"cfg{index:02d}": _shaped_noise(rng, len(dates), edge + index * edge_step, common)
        for index in range(configurations)
    }
    return Family(label="genuine", dates=dates, net=net)


def overfit_family(
    dates: Sequence[dt.date],
    *,
    seed: int,
    configurations: int = 200,
) -> Family:
    """Every configuration is noise with zero drift. The winner is the luckiest one."""
    rng = np.random.default_rng(seed)
    dates = tuple(dates)
    common = market_factor(rng, len(dates))
    net = {
        f"cfg{index:03d}": _shaped_noise(rng, len(dates), 0.0, common)
        for index in range(configurations)
    }
    return Family(label="overfit", dates=dates, net=net)


def benchmark_series(
    dates: Sequence[dt.date],
    *,
    seed: int,
    drift: float = 0.0006,
    label: str = "naive always-on benchmark",
) -> ReturnSeries:
    """The always-on naive benchmark: in the market every session, modest drift.

    It is *always on*, which is the whole reason the comparison must be risk-matched — it
    carries more risk and more return than a conditional strategy by construction.
    """
    rng = np.random.default_rng(seed)
    values = _shaped_noise(rng, len(dates), drift)
    return ReturnSeries(
        dates=tuple(dates),
        net=tuple(float(value) for value in values),
        drag=tuple(COST_DRAG for _ in values),
        label=label,
    )


def evidence(
    series: ReturnSeries,
    *,
    label: str | None = None,
    run_at: dt.datetime,
    unverified_inputs: tuple[str, ...] = (),
    feasibility: FeasibilityFacts | None = None,
    trial_id: str | None = None,
) -> RunEvidence:
    return RunEvidence(
        label=label or series.label,
        returns=series,
        feasibility=feasibility
        if feasibility is not None
        else FeasibilityFacts(
            intents_attempted=len(series) * 2,
            intents_infeasible=0,
            sessions_run=len(series),
        ),
        unverified_inputs=unverified_inputs,
        capital_base=1_000_000.0,
        peak_margin=250_000.0,
        trial_id=trial_id,
        run_at=run_at,
    )


def fold_runner(family: Family):
    """A walk-forward fold: fit on the training window, report the test window only."""

    def run(split: Split) -> FoldResult:
        chosen = family.best_on(split.train)
        return FoldResult(
            split=split,
            returns=family.restricted(chosen, split.test),
            parameters={"configuration": chosen},
        )

    return run
