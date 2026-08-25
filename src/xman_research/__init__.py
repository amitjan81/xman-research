"""xman-research — MVP component C4: the hypothesis record and the trial log.

The one property everything here serves: **the trial count is read from an append-only
log that the evaluation path writes automatically, and can never be supplied by the
caller.** Deflated Sharpe needs the true number of trials; a number the researcher types
in is worthless, because the researcher is the party with an incentive to understate it.

Typical use, from a notebook::

    from datetime import date
    from xman_research import DataWindow, HypothesisRecord, open_session

    h1 = HypothesisRecord(
        name="H1 — index variance risk premium",
        mechanism="Hedgers pay up for index protection, so implied variance sits above "
                  "subsequent realised variance; a short-variance position collects that "
                  "premium as compensation for bearing crash risk.",
        null_hypothesis="Implied minus realised variance has no positive mean after "
                        "statutory costs, and the strategy does not beat the naive "
                        "always-on benchmark on a risk-matched basis.",
        thresholds={"deflated_sharpe": 0.0, "cost_breakeven_multiple": 2.0},
        predictors=["iv_30d", "realised_vol_20d"],
    )

    session = open_session("research.db")

    @session.evaluation(h1)
    def evaluate(window: DataWindow, *, delta: float) -> dict[str, float]:
        ...
        return {"sharpe": 1.1, "cost_breakeven_multiple": 2.4}

    evaluate(DataWindow(date(2023, 1, 1), date(2024, 12, 31)), delta=0.30)
    session.count_family_trials(h1)   # read from the log, not from you
"""

from xman_research.clock import Clock, ManualClock, SystemClock
from xman_research.code_version import (
    CodeVersion,
    CodeVersionProvider,
    GitCodeVersion,
    StaticCodeVersion,
)
from xman_research.evaluation import ResearchSession, TrialContext, open_session
from xman_research.hypothesis import HypothesisRecord, HypothesisValidationError
from xman_research.trial_log import (
    AppendOnlyViolation,
    DataWindow,
    LogIntegrityError,
    SchemaVersionError,
    TrialLog,
    TrialOutcome,
    TrialRecord,
    UnknownHypothesisError,
    UnknownTrialError,
)

__all__ = [
    "AppendOnlyViolation",
    "Clock",
    "CodeVersion",
    "CodeVersionProvider",
    "DataWindow",
    "GitCodeVersion",
    "HypothesisRecord",
    "HypothesisValidationError",
    "LogIntegrityError",
    "ManualClock",
    "ResearchSession",
    "SchemaVersionError",
    "StaticCodeVersion",
    "SystemClock",
    "TrialContext",
    "TrialLog",
    "TrialOutcome",
    "TrialRecord",
    "UnknownHypothesisError",
    "UnknownTrialError",
    "open_session",
]

__version__ = "0.1.0"
