"""Systematic alpha exploration: two loops, on two clocks.

**The offline discovery loop** runs on a research clock and is the rest of ``xman_research``: a
:class:`~xman_research.hypothesis.HypothesisRecord`, trials counted in an append-only
:class:`~xman_research.trial_log.TrialLog`, a pre-registered gate, a sealed holdout, and a
decision record at the end. Its output for this subpackage is an **admitted strategy
template** together with the evidence that admitted it.

**The nightly ranker** runs on a market clock and never invents a strategy. After the close
it instantiates every admitted template on every product in the universe, computes the
session's features, decides which templates fire and how strongly, attaches the expected
edge the admission record measured, applies participation and margin feasibility, and ranks
by expected edge per unit of margin at risk. Its output is an :class:`IdeaSheet`, and every
idea on it carries a :class:`Rationale` — mechanism, trigger, evidence, trade, invalidators
— with each number naming its source.

**The trade this design makes, stated rather than hidden.** Templates are Python code
registered explicitly, so adding one is a pull request and no strategy can appear overnight
that nobody reviewed. What is bought is statistical honesty: the scan cannot search, so it
cannot mine the corpus, so the trial count the deflated Sharpe corrects for stays true. What
is given up is overnight novelty — a genuinely new trade shape has to go round the offline
loop first, which takes days rather than hours.

Adding a template is four steps: write the trade shape as a
:class:`~xman_research.alpha.templates.StrategyTemplate` with a thesis, register it in
:func:`~xman_research.alpha.templates.default_registry`, run it through the offline loop to
produce a decision record, then admit it with
``python -m xman_research.alpha.cli library admit``.
"""

from xman_research.alpha.explain import (
    RATIONALE_SCHEMA_VERSION,
    Invalidator,
    Rationale,
    TradeLeg,
    TradeSpec,
    TriggerExplanation,
    invalidators_for,
)
from xman_research.alpha.features import (
    DEFAULT_DECISION_TIME,
    DEFAULT_REGIME_LOOKBACK_SESSIONS,
    AsOfNotASessionError,
    FeatureBuilder,
    FeatureFrame,
    FeatureValue,
    InsufficientHistoryError,
    RegimeTag,
    SessionSummary,
)
from xman_research.alpha.library import (
    DEFAULT_LIBRARY_PATH,
    LIBRARY_SCHEMA_VERSION,
    AdmissionRecord,
    AdmissionStatus,
    AppendOnlyLibraryError,
    DecisionRecordError,
    EvidenceCard,
    TemplateLibrary,
)
from xman_research.alpha.ranker import (
    IDEA_SHEET_SCHEMA_VERSION,
    Idea,
    IdeaSheet,
    NightlyScan,
    SkippedCandidate,
)
from xman_research.alpha.templates import (
    HOLD_SESSIONS,
    MAX_HOLD_SESSIONS,
    MIN_HOLD_SESSIONS,
    Comparator,
    ConditionerSpec,
    HoldNIronCondor,
    HoldNShortStraddle,
    HoldNShortStrangle,
    HoldNSpread,
    LegRule,
    ParameterRange,
    StrategyTemplate,
    StrengthShape,
    TemplateRegistry,
    UnknownTemplateError,
    default_registry,
    shipped_templates,
)

__all__ = [
    "DEFAULT_DECISION_TIME",
    "DEFAULT_LIBRARY_PATH",
    "DEFAULT_REGIME_LOOKBACK_SESSIONS",
    "HOLD_SESSIONS",
    "IDEA_SHEET_SCHEMA_VERSION",
    "LIBRARY_SCHEMA_VERSION",
    "MAX_HOLD_SESSIONS",
    "MIN_HOLD_SESSIONS",
    "RATIONALE_SCHEMA_VERSION",
    "AdmissionRecord",
    "AdmissionStatus",
    "AppendOnlyLibraryError",
    "AsOfNotASessionError",
    "Comparator",
    "ConditionerSpec",
    "DecisionRecordError",
    "EvidenceCard",
    "FeatureBuilder",
    "FeatureFrame",
    "FeatureValue",
    "HoldNIronCondor",
    "HoldNShortStraddle",
    "HoldNShortStrangle",
    "HoldNSpread",
    "Idea",
    "IdeaSheet",
    "InsufficientHistoryError",
    "Invalidator",
    "LegRule",
    "NightlyScan",
    "ParameterRange",
    "Rationale",
    "RegimeTag",
    "SessionSummary",
    "SkippedCandidate",
    "StrategyTemplate",
    "StrengthShape",
    "TemplateLibrary",
    "TemplateRegistry",
    "TradeLeg",
    "TradeSpec",
    "TriggerExplanation",
    "UnknownTemplateError",
    "default_registry",
    "invalidators_for",
    "shipped_templates",
]
