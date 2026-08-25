"""The per-epoch breakdown: DESCRIPTIVE, UNGRADED, and incapable of changing an outcome.

Pre-registered in ``research/m1/gate.toml`` and ``research/m2/gate.toml`` before any of it
was computed, for the reason those files give: a FAILS_THRESHOLD pooled verdict sitting
beside one attractive regime reads, in prose, as a pass.

**Why it is not graded.** Grading six sub-windows would burn six trials against a family
already carrying five, deflate all six Sharpes accordingly, and hand the researcher a
post-hoc choice of which regime to believe. The pooled verdict is the graded one and the
gate files say so.

Nothing here re-runs a backtest. The partitions are slices of the SAME return series the
pooled verdict was computed on, so no partition can disagree with the pooled number about
what happened on a session — only about which sessions it is averaging.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from xman_research.validation.gate import EPOCH_BOUNDARIES, EpochBoundary
from xman_research.validation.series import ReturnSeries
from xman_research.validation.statistics import (
    annualised_sharpe_ratio,
    drawdown,
    tail_metrics,
)

__all__ = ["EpochSlice", "epoch_breakdown"]


@dataclass(frozen=True, slots=True)
class EpochSlice:
    """One regime's slice of the graded return series."""

    name: str
    start: dt.date
    end: dt.date
    sessions: int
    net_return: float
    mean_net: float
    annualised_sharpe: float | None
    max_drawdown: float | None
    skew: float | None
    kurtosis: float | None

    def as_dict(self) -> dict[str, object]:
        return {
            "epoch": self.name,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "sessions": self.sessions,
            "net_return_on_capital": self.net_return,
            "mean_net_per_session": self.mean_net,
            "annualised_sharpe": self.annualised_sharpe,
            "max_drawdown": self.max_drawdown,
            "skew": self.skew,
            "kurtosis": self.kurtosis,
        }


def _regime_name(day: dt.date, boundaries: tuple[EpochBoundary, ...]) -> str:
    """The epoch in force on ``day``: the latest boundary at or before it."""
    name = "pre_" + boundaries[0].name
    for boundary in boundaries:
        if day >= boundary.effective_from:
            name = boundary.name
    return name


def epoch_breakdown(
    returns: ReturnSeries,
    *,
    boundaries: tuple[EpochBoundary, ...] = EPOCH_BOUNDARIES,
) -> tuple[EpochSlice, ...]:
    """Partition ``returns`` by the epoch in force on each session.

    Slices with fewer than two observations report ``None`` for every dispersion
    statistic rather than a number: a Sharpe on one observation is not a small sample, it
    is not a statistic. The session count and the net return are still reported, because
    those are sums and a sum of one is a sum.
    """
    buckets: dict[str, list[tuple[dt.date, float, float]]] = {}
    for day, net, drag in zip(returns.dates, returns.net, returns.drag, strict=True):
        buckets.setdefault(_regime_name(day, boundaries), []).append((day, net, drag))

    ordered = sorted(buckets.items(), key=lambda item: item[1][0][0])
    slices: list[EpochSlice] = []
    for name, rows in ordered:
        days = tuple(row[0] for row in rows)
        nets = tuple(row[1] for row in rows)
        sharpe: float | None = None
        max_dd: float | None = None
        skew: float | None = None
        kurt: float | None = None
        # Zero dispersion is not a small sample, it is an undefined statistic, and it
        # happens for a real reason: an epoch slice in which the book never had a
        # position prints an unbroken run of identical (zero) returns. _math.sharpe
        # raises on it, correctly. Reporting None here is the honest answer; catching
        # the raise further out would have discarded the whole breakdown.
        dispersed = len({round(value, 15) for value in nets}) > 1
        if len(rows) >= 2 and dispersed:
            sliced = ReturnSeries(
                dates=days,
                net=nets,
                drag=tuple(row[2] for row in rows),
                label=f"{returns.label}:{name}",
                periods_per_year=returns.periods_per_year,
            )
            sharpe = annualised_sharpe_ratio(sliced)
            max_dd = drawdown(sliced).max_drawdown
            tails = tail_metrics(sliced)
            skew = tails.skew
            kurt = tails.kurtosis
        slices.append(
            EpochSlice(
                name=name,
                start=days[0],
                end=days[-1],
                sessions=len(rows),
                net_return=sum(nets),
                mean_net=sum(nets) / len(nets),
                annualised_sharpe=sharpe,
                max_drawdown=max_dd,
                skew=skew,
                kurtosis=kurt,
            )
        )
    return tuple(slices)
