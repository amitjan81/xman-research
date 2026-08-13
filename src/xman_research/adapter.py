"""The C5 -> C6 seam: a finished backtest, restated as evidence C6 is allowed to judge.

This module exists because neither component may import the other.
:mod:`xman_research.validation.series` says so explicitly — a judge that imports the thing
it judges cannot be tested without it, which is the shape that lets a validation layer
grade its own homework. So the seam lives above both, in one place, tested on its own.

**What it has to get right, and what each one silently costs if it does not.** Every item
below was found by comparing what the obvious adapter produces against what C5 itself
reports about the same run, and every one of them errs in the flattering direction:

1. ``capital_base`` is ``config_provenance["starting_cash"]``, never ``peak_margin``.
   The capital base is the denominator of every return in C6, so choosing the smaller,
   more flattering number inflates every return, every Sharpe and the drawdown alike.
   ``peak_margin`` is additionally *derived* — C5 documents it as an approximation, and it
   moves with the run, so a "return" denominated in it is not comparable between runs.
   It still travels, in its own field, for the return-on-capital question C6 does not ask.

2. ``group_incomplete`` is an **infeasible** verdict. C5's own ``metrics()`` counts it
   under ``fills_infeasible``; leaving it out of C6's set made the two components report
   different infeasibility for the same run, with C6 reading the lower one.

3. ``settled`` is **not an intent**. Cash settlement is something the exchange does to the
   book, so it can never be infeasible; counting it in the denominator dilutes the
   infeasible fraction in proportion to how many expiries the run held through.

4. Costs are **bucketed by date**, from the fill and settlement records. ``DailyRecord``
   carries no cost field, so the only alternative is C5's single ``total_costs.total``
   spread evenly across sessions — which is wrong on every session the book did not trade,
   and which stamps the run ``costs.uniformly_allocated``. The cost-breakeven multiple is
   the headline number of the whole MVP (spec §2.1); it deserves the real allocation.

5. ``run_at`` comes from the **trial log's** ``created_at``, not from the wall clock. The
   gate refuses to grade a run it cannot show post-dates the thresholds, and a timestamp
   the caller types is exactly the field an operator would adjust. C6 reconciles the two
   and refuses a disagreement, so the adapter reads the same row the validator will.

The last one is why :func:`evidence_from_result` takes the session: it is not decoration,
it is the only authoritative answer to *when did this run happen*.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict

from xman_research.backtest.engine import BacktestResult
from xman_research.evaluation import ResearchSession
from xman_research.trial_log import TrialLog
from xman_research.validation.series import (
    TRADING_SESSIONS_PER_YEAR,
    FeasibilityFacts,
    RunEvidence,
)

__all__ = ["costs_by_date", "evidence_from_result", "feasibility_from_result", "logged_run_at"]


def costs_by_date(result: BacktestResult) -> dict[dt.date, float]:
    """Every rupee of cost the run paid, bucketed on the session that paid it.

    Both sources are included and both are needed. Entry costs land on fills; the STT on
    exercise — the single largest component for a short-option book held to expiry — lands
    on settlements, and a bucket built from fills alone would omit it entirely and report a
    cost-breakeven multiple several times too generous.

    Sessions with no trading simply do not appear; :meth:`RunEvidence.from_equity_curve`
    reads a missing date as zero cost, which is what it means.
    """
    buckets: defaultdict[dt.date, float] = defaultdict(float)
    for fill in result.fills:
        buckets[fill.session_date] += fill.costs.total
    for settlement in result.settlements:
        buckets[settlement.session_date] += settlement.costs.total
    return dict(buckets)


def feasibility_from_result(result: BacktestResult) -> FeasibilityFacts:
    """C5's verdict counts as C6's feasibility facts, with nothing defaulted away.

    ``sessions_run`` and ``sessions_with_stale_marks`` must both be passed: their defaults
    are zero, and a zero stale fraction reads as *no session was marked stale* rather than
    *nobody said*. C5 counts stale marks per session precisely so C6 can refuse.

    The infeasible verdict set is left at C6's default, which already includes
    ``group_incomplete`` and already excludes ``settled`` — the two corrections above. It
    is spelled out here rather than passed, so that a verdict added to C5 shows up as a
    disagreement between this adapter's tests and C5's enumeration rather than as silence.
    """
    return FeasibilityFacts.from_verdicts(
        result.feasibility_counts(),
        intents_resized=len(result.resized_fills()),
        sessions_with_stale_marks=sum(1 for day in result.daily if day.stale_marks),
        sessions_run=result.sessions_run,
    )


def logged_run_at(
    source: ResearchSession | TrialLog, hypothesis_id: str, trial_id: str
) -> dt.datetime | None:
    """When the log says this trial happened. ``None`` when the row cannot be found.

    ``None`` is returned rather than raised because C6 handles it: a run with no logged
    timestamp falls back to ``RunEvidence.run_at``, and a run with neither is refused by
    the gate. Inventing a timestamp here would defeat that refusal.
    """
    log = source.log if isinstance(source, ResearchSession) else source
    for record in log.family_trials(hypothesis_id):
        if record.trial_id == trial_id:
            return record.created_at
    return None


def evidence_from_result(
    result: BacktestResult,
    *,
    session: ResearchSession | TrialLog,
    hypothesis_id: str,
    label: str | None = None,
    periods_per_year: float = TRADING_SESSIONS_PER_YEAR,
) -> RunEvidence:
    """Restate a finished C5 run as C6's :class:`RunEvidence`.

    ``label`` defaults to C5's strategy name. It is worth overriding when the same run is
    presented twice — once as the candidate and once as the naive benchmark, which is the
    honest shape when the candidate *is* unconditional — so the verdict names which is
    which.
    """
    return RunEvidence.from_equity_curve(
        result.equity_curve(),
        label=label if label is not None else result.strategy_name,
        capital_base=float(result.config_provenance["starting_cash"]),
        cost_by_date=costs_by_date(result),
        feasibility=feasibility_from_result(result),
        unverified_inputs=result.unverified_inputs,
        peak_margin=result.peak_margin,
        trial_id=result.trial_id,
        run_at=logged_run_at(session, hypothesis_id, result.trial_id),
        fingerprint=result.fingerprint(),
        periods_per_year=periods_per_year,
    )
