"""The set of metrics a decision criterion may name, and how a holdout bar is spelled.

**Why this is its own module and not part of the validator.** Two components need the
same vocabulary at two different moments, and they sit on opposite sides of an import
edge. :mod:`xman_research.hypothesis` checks it when a record is *registered*, so a
criterion nothing can compute is refused at the moment it would otherwise become
immutable; :mod:`xman_research.validation.gate` checks it when a gate file is *read*,
so a typo is reported against the gate rather than against the run. ``validation.gate``
imports ``hypothesis`` — the gate binds to a record — so the vocabulary cannot live in
``validation.gate`` without the reverse import closing a cycle. It lives here, imports
nothing, and both sides read the same names.

**The two checks must stay in step, and sharing the names is only half of that.** The
registration check and :meth:`~xman_research.validation.gate.DecisionGate.check_binding`
also have to agree on *which keys are criteria at all*: binding grades a registered
threshold only when its value is numeric, and resolves a ``holdout.``-prefixed name
against the gate's holdout set. :func:`is_gradeable_metric` is the one predicate both
use, so a key that registration accepts is a key binding can grade, and a criterion
cannot be simultaneously mandatory for a gate to carry and forbidden for it to name.
"""

from __future__ import annotations

__all__ = [
    "HOLDOUT_THRESHOLD_PREFIX",
    "HOLDOUT_UNCOMPUTABLE_METRICS",
    "MEASURED_METRICS",
    "is_gradeable_metric",
]

HOLDOUT_THRESHOLD_PREFIX = "holdout."
"""How a holdout threshold is named in the immutable hypothesis record.

The holdout bar has to be anchored to the content-addressed
:class:`~xman_research.hypothesis.HypothesisRecord` and not only to the gate file, which is
editable and whose ``recorded_at`` is just another editable field: an operator who has seen
the in-sample verdict must not be able to soften the holdout bar and re-read, which is the
move :meth:`~xman_research.validation.gate.DecisionGate.check_binding` exists to stop, on
the one run where it matters most. Registering ``holdout.probabilistic_sharpe`` in the
record's own ``thresholds`` mapping binds it the same way without adding a field to the
record's schema — the schema is content-addressed, so a field added to the hashed content
changes every id ever minted."""

MEASURED_METRICS: frozenset[str] = frozenset(
    {
        "deflated_sharpe",
        "probabilistic_sharpe",
        "cost_breakeven_multiple",
        "max_drawdown",
        "annualised_sharpe",
        "annualised_adjusted_sharpe",
        "expected_shortfall",
        "risk_matched_increment",
        "sharpe_difference",
        "pbo",
    }
)
"""Every metric a threshold may name — the gate's whole vocabulary.

Checked when a hypothesis is registered, so a criterion no component computes is refused
before it is frozen into a content-addressed id; and again when the gate file is *read*,
so a typo or a metric this component does not compute is a refusal about the gate rather
than a grade-time complaint that "the run did not report it" — which accuses the wrong
party and sends the operator to re-run a backtest that was never going to help.
:meth:`~xman_research.validation.decision.Validator._grade` asserts its observed metrics
are exactly this set, which is what stops the two drifting apart.

A criterion a screen applies to itself is not in here and does not belong in a record's
``thresholds`` — it belongs in ``screen_criteria``, which no gate is asked to grade. See
:attr:`~xman_research.hypothesis.HypothesisRecord.screen_criteria`."""


HOLDOUT_UNCOMPUTABLE_METRICS = frozenset({"pbo"})
"""Metrics the single holdout run structurally cannot report.

:meth:`~xman_research.validation.decision.Validator.grade_holdout` passes no CSCV result:
the holdout is one run of one configuration, and probability-of-backtest-overfitting is a
statement about choosing between many. A ``holdout.``-prefixed threshold on one of these is
ungradeable in the same way a metric outside :data:`MEASURED_METRICS` is, and
:func:`is_gradeable_metric` refuses it for the same reason: binding would require a gate to
carry a bar the holdout grade can never produce a number for."""


def is_gradeable_metric(name: str) -> bool:
    """Whether a threshold key names something the validator can measure.

    A ``holdout.``-prefixed name is resolved against the same vocabulary: the prefix says
    *which run* the bar applies to, not which quantity, so ``holdout.max_drawdown`` and
    ``max_drawdown`` name the same measurement. The exception is a metric only the
    many-configuration in-sample run can report — see
    :data:`HOLDOUT_UNCOMPUTABLE_METRICS`.
    """
    if name.startswith(HOLDOUT_THRESHOLD_PREFIX):
        bare = name[len(HOLDOUT_THRESHOLD_PREFIX) :]
        return bare in MEASURED_METRICS and bare not in HOLDOUT_UNCOMPUTABLE_METRICS
    return name in MEASURED_METRICS
