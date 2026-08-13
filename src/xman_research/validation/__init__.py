"""MVP component C6 — validation and the decision gate.

The component that decides whether a hypothesis is real. Everything before it produces
evidence; this is where evidence becomes one of spec §6's four outcomes, or where the
process refuses to pretend it can.

What it holds, and why each part exists:

* :mod:`~xman_research.validation.series` — the narrow input. C5 is not imported; a run
  arrives as returns plus the cost drag that shaped them.
* :mod:`~xman_research.validation.statistics` — deflated Sharpe against the log-derived
  trial count, the cost-breakeven **headline**, and the tail metrics a Sharpe hides.
* :mod:`~xman_research.validation.pbo` — probability of backtest overfitting by CSCV.
* :mod:`~xman_research.validation.walkforward` — fit on the past, judge on what came next.
* :mod:`~xman_research.validation.gate` — the three refusals: thresholds recorded before
  the run, epoch boundaries, and the untouched holdout.
* :mod:`~xman_research.validation.decision` — the four outcomes, in precedence order.

The shape of a full run::

    validator = Validator(ValidationConfig.from_file("validation.toml"))
    in_sample = validator.grade(candidate, benchmark=naive, hypothesis=h1,
                                walk_forward=report, overfitting=pbo)
    decision = validator.decide(in_sample, holdout=validator.grade_holdout(
        holdout_run, benchmark=holdout_naive, hypothesis=h1))
    print(decision.summary())

Three properties worth stating once, because they are what the component is *for*:

1. **Nothing here accepts a trial count.** The deflation reads it from the append-only
   log, through :class:`~xman_research.validation.statistics.SelectionUniverse`, and the
   log path is pinned in configuration rather than passed per call.
2. **A number computed from unverified inputs says so, structurally.** The stamps travel
   from the run into the verdict, ``str()`` of the headline always carries them, and
   ``float()`` of it refuses while any remain.
3. **A refusal is not a verdict.** Ungraded-because-the-process-was-not-in-order raises;
   it is never quietly recorded as a property of the strategy.
"""

from xman_research.validation.decision import (
    Decision,
    GateStatus,
    HoldoutRequiredError,
    Outcome,
    ValidationConfig,
    Validator,
    Verdict,
)
from xman_research.validation.gate import (
    EPOCH_BOUNDARIES,
    CrossEpochWindowError,
    DecisionGate,
    Direction,
    EpochAnnotation,
    EpochBoundary,
    GateBindingError,
    HoldoutPolicy,
    HoldoutStatus,
    HoldoutTouchedError,
    NotEvaluableRules,
    Threshold,
    ThresholdResult,
    ThresholdsNotRecordedError,
    epochs_spanned,
    inspect_holdout,
)
from xman_research.validation.pbo import (
    PBOResult,
    PerformanceMatrix,
    performance_matrix,
    probability_of_backtest_overfitting,
)
from xman_research.validation.series import (
    FeasibilityFacts,
    ReturnSeries,
    RunEvidence,
    SeriesError,
)
from xman_research.validation.statistics import (
    BenchmarkMismatchError,
    CostBreakeven,
    DeflatedSharpe,
    DrawdownFacts,
    RiskMatchedIncrement,
    SelectionUniverse,
    TailMetrics,
    UnverifiedInputsError,
    adjusted_sharpe_ratio,
    annualised_sharpe_ratio,
    cost_breakeven,
    deflated_sharpe_ratio,
    drawdown,
    expected_shortfall,
    per_period_sharpe_ratio,
    probabilistic_sharpe_ratio,
    risk_matched_increment,
    tail_metrics,
)
from xman_research.validation.walkforward import (
    FoldResult,
    Split,
    WalkForwardReport,
    walk_forward,
    walk_forward_splits,
)

__all__ = [
    "EPOCH_BOUNDARIES",
    "BenchmarkMismatchError",
    "CostBreakeven",
    "CrossEpochWindowError",
    "Decision",
    "DecisionGate",
    "DeflatedSharpe",
    "Direction",
    "DrawdownFacts",
    "EpochAnnotation",
    "EpochBoundary",
    "FeasibilityFacts",
    "FoldResult",
    "GateBindingError",
    "GateStatus",
    "HoldoutPolicy",
    "HoldoutRequiredError",
    "HoldoutStatus",
    "HoldoutTouchedError",
    "NotEvaluableRules",
    "Outcome",
    "PBOResult",
    "PerformanceMatrix",
    "ReturnSeries",
    "RiskMatchedIncrement",
    "RunEvidence",
    "SelectionUniverse",
    "SeriesError",
    "Split",
    "TailMetrics",
    "Threshold",
    "ThresholdResult",
    "ThresholdsNotRecordedError",
    "UnverifiedInputsError",
    "ValidationConfig",
    "Validator",
    "Verdict",
    "WalkForwardReport",
    "adjusted_sharpe_ratio",
    "annualised_sharpe_ratio",
    "cost_breakeven",
    "deflated_sharpe_ratio",
    "drawdown",
    "epochs_spanned",
    "expected_shortfall",
    "inspect_holdout",
    "per_period_sharpe_ratio",
    "performance_matrix",
    "probabilistic_sharpe_ratio",
    "probability_of_backtest_overfitting",
    "risk_matched_increment",
    "tail_metrics",
    "walk_forward",
    "walk_forward_splits",
]
