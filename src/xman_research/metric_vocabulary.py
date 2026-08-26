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
    "MEASURED_METRICS",
    "is_gradeable_metric",
]

HOLDOUT_THRESHOLD_PREFIX = "holdout."
"""How a holdout threshold is named in the immutable hypothesis record.

The in-sample bar is anchored to the content-addressed
:class:`~xman_research.hypothesis.HypothesisRecord`; without this, the holdout bar lived
only in the editable gate file, with ``recorded_at`` just another editable field. An
operator who did not like the holdout verdict could soften the holdout bar and re-read —
the exact move :meth:`~xman_research.validation.gate.DecisionGate.check_binding` exists
to prevent, left open on the one run that matters most. Registering
``holdout.probabilistic_sharpe`` in the record's own ``thresholds`` mapping binds it the
same way, without changing the record's schema (which is content-addressed: a field
added to the hashed content would change every id ever minted)."""

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


def is_gradeable_metric(name: str) -> bool:
    """Whether a threshold key names something the validator can measure.

    A ``holdout.``-prefixed name is resolved against the same vocabulary: the prefix
    says *which run* the bar applies to, not which quantity, so ``holdout.max_drawdown``
    and ``max_drawdown`` name the same measurement.
    """
    bare = (
        name[len(HOLDOUT_THRESHOLD_PREFIX) :] if name.startswith(HOLDOUT_THRESHOLD_PREFIX) else name
    )
    return bare in MEASURED_METRICS
