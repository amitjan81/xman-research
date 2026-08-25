"""The decision: four outcomes, in a fixed order of precedence, and never a boolean.

Spec §6 says the MVP is done when it has produced one decision on H1 and the operator can
say **which of four things happened**. So the terminal type here is a four-valued
:class:`Outcome`, not a pass/fail — a boolean cannot express "passed in sample and failed
the holdout", which the spec calls the most valuable outcome, nor "not evaluable", which
is a statement about execution rather than about the edge.

**Precedence, and it matters.** *Not evaluable* is decided before pass/fail. A run where a
tenth of the intents could not have been filled, or which is only profitable if the
unverified cost rates are generous, has not failed a threshold — it was never measured.
Reporting that as ``FAILS_THRESHOLD`` would send the operator to the next hypothesis when
the actual next step is to resolve the quote-data question.

**A refusal is not an outcome.** Thresholds that were not recorded beforehand, a
cross-epoch window with no justification, a holdout that has already been read: each
raises out of :mod:`xman_research.validation.gate`. None of them is ``NOT_EVALUABLE``.
They are failures of the process to be in a state where grading means anything, and
turning them into a fourth outcome would let a broken process be filed as a property of
the strategy.

**The database is pinned in configuration and is not an argument.** C4 documents its own
sharpest hole: nothing binds an evaluation to a canonical log, so 200 trials against
``scratch.db`` followed by the winner against ``research.db`` leaves the second file
honestly reporting a count of one. C6 cannot close that hole, but it can decline to be
the place where it is opened — :class:`Validator` reads its log path from
:class:`ValidationConfig`, so which log the deflation counts is not a decision anyone
makes while looking at a result.
"""

from __future__ import annotations

import datetime as dt
import tomllib
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import Any

from xman_research.clock import Clock, SystemClock, require_aware
from xman_research.evaluation import ResearchSession, open_session
from xman_research.hypothesis import HypothesisRecord
from xman_research.validation.gate import (
    EPOCH_PROVENANCE_STAMP,
    MEASURED_METRICS,
    DecisionGate,
    EpochAnnotation,
    HoldoutPolicy,
    HoldoutStatus,
    HoldoutTouchedError,
    ThresholdResult,
    ThresholdsNotRecordedError,
    epochs_spanned,
    inspect_holdout,
)
from xman_research.validation.pbo import PBOResult
from xman_research.validation.series import ReturnSeries, RunEvidence
from xman_research.validation.statistics import (
    CostBreakeven,
    DeflatedSharpe,
    RiskMatchedIncrement,
    SelectionUniverse,
    TailMetrics,
    cost_breakeven,
    deflated_sharpe_ratio,
    probabilistic_sharpe_ratio,
    risk_matched_increment,
    tail_metrics,
)
from xman_research.validation.walkforward import WalkForwardReport

__all__ = [
    "MEASURED_METRICS",
    "Decision",
    "GateStatus",
    "GateVocabularyError",
    "HoldoutRequiredError",
    "HypothesisMismatchError",
    "JudgedSeriesMismatchError",
    "MetricNotReportedError",
    "Outcome",
    "ValidationConfig",
    "Validator",
    "Verdict",
]


class HoldoutRequiredError(RuntimeError):
    """Raised when a decision is asked for on a passing run whose holdout has not run."""


class HypothesisMismatchError(RuntimeError):
    """Raised when a decision pairs verdicts on two different hypotheses."""


class JudgedSeriesMismatchError(RuntimeError):
    """Raised when the walk-forward report is not a report on the candidate being graded.

    The walk-forward out-of-sample series *replaces* the candidate's own returns as the
    thing every statistic is computed on, and nothing downstream re-derived its window.
    Left unchecked that made three refusals bypassable at once by handing in a report
    built on other sessions: :meth:`Validator.grade` checked the *candidate's* window
    against the holdout boundary, :func:`~xman_research.validation.gate.epochs_spanned`
    annotated the *candidate's* window, and the verdict reported the *candidate's*
    window — while the deflated Sharpe, the breakeven, the tails, the increment and the
    PSR all came from months the candidate never covered. A report whose sessions ran 18
    months past the holdout boundary graded as an innocent in-sample run, and passed.

    Containment closes all three at once: an out-of-sample window inside the candidate's
    window cannot reach the holdout when the candidate's does not, and cannot cross an
    epoch boundary the candidate's does not.
    """


class GateVocabularyError(RuntimeError):
    """Raised when a gate names a metric this component does not compute.

    Caught at gate load, not at grade time. A threshold on a metric nobody measures used
    to survive until :class:`MetricNotReportedError` reported that *the run* did not
    report it — which is the wrong accusation and sends the operator to re-run a backtest
    that was never going to help.
    """


class MetricNotReportedError(RuntimeError):
    """Raised when the run did not measure something the pre-recorded gate requires.

    A refusal, not the fourth outcome. Spec §6 defines *not evaluable* as surviving only
    at optimistic costs or being dominated by feasibility failures — both statements about
    the strategy and its execution. "Nobody ran the cross-validation" is neither: it is a
    gap in the evidence, and the next step is to run it, not to go and resolve the
    quote-data question. Filing it as ``NOT_EVALUABLE`` would attach that wrong advice to
    it.
    """


class GateStatus(StrEnum):
    """What one graded run did against its pre-recorded thresholds."""

    PASSED = "passed"
    FAILED = "failed"
    NOT_EVALUABLE = "not_evaluable"


class Outcome(StrEnum):
    """The four things spec §6 says the operator must be able to choose between."""

    PASSES_SURVIVES_HOLDOUT = "passes_survives_holdout"
    FAILS_THRESHOLD = "fails_threshold"
    PASSES_FAILS_HOLDOUT = "passes_fails_holdout"
    NOT_EVALUABLE = "not_evaluable"

    @property
    def next_step(self) -> str:
        return _NEXT_STEP[self]


_NEXT_STEP = {
    Outcome.PASSES_SURVIVES_HOLDOUT: (
        "Forward test — where the cost model starts calibrating against real fills."
    ),
    Outcome.FAILS_THRESHOLD: "Next hypothesis. The loop works.",
    Outcome.PASSES_FAILS_HOLDOUT: (
        "The most valuable outcome: the in-sample machinery was insufficient and the "
        "holdout caught it. Tighten before spending more research."
    ),
    Outcome.NOT_EVALUABLE: (
        "The answer is about execution — resolve the quote-data question before continuing."
    ),
}


@dataclass(frozen=True, slots=True)
class Verdict:
    """One graded run: every statistic, every threshold, and why it landed where it did."""

    label: str
    hypothesis_id: str
    status: GateStatus
    window: str
    """The window of the series that was actually judged, not the run's own window.

    With a walk-forward report those differ — the first training block is never scored —
    and reporting the run's window beside statistics computed on the folds is a mismatch
    a reader cannot see. The run's own window is kept as :attr:`candidate_window`."""

    candidate_window: str
    """The window the run itself covered. Equal to :attr:`window` without a walk-forward."""

    judged_series: str
    """Which series every statistic below was computed on.

    Not decoration: with a walk-forward report the statistics are computed on the
    concatenated out-of-sample folds, and without one they are computed on the whole
    window. An out-of-sample deflated Sharpe printed beside an in-sample cost-breakeven
    is a mismatch a reader cannot see, so the verdict names the series once and every
    number in it comes from that series."""

    graded_at: dt.datetime
    headline: CostBreakeven
    deflated: DeflatedSharpe
    tails: TailMetrics
    increment: RiskMatchedIncrement
    probabilistic_sharpe: float
    epochs: EpochAnnotation
    threshold_results: tuple[ThresholdResult, ...]
    unverified_inputs: tuple[str, ...]
    not_evaluable_reasons: tuple[str, ...] = ()
    overfitting: PBOResult | None = None
    walk_forward: WalkForwardReport | None = None
    holdout: HoldoutStatus | None = None
    trial_id: str | None = None

    @property
    def failed_thresholds(self) -> tuple[ThresholdResult, ...]:
        return tuple(result for result in self.threshold_results if not result.passed)

    def metrics(self) -> dict[str, Any]:
        """The shape that goes into a trial log row.

        Mostly scalars, and deliberately not only scalars: ``unverified_inputs`` and
        ``epochs`` are lists because collapsing them to a count or a joined string is how
        a caveat stops being readable. The log stores JSON, so a list costs nothing there.
        """
        collected: dict[str, Any] = {
            "gate_status": str(self.status),
            "selection_size": self.deflated.selection_size,
            "probabilistic_sharpe": self.probabilistic_sharpe,
            **self.headline.as_dict(),
            **self.deflated.as_dict(),
            **self.tails.as_dict(),
            **self.increment.as_dict(),
        }
        if self.overfitting is not None:
            collected.update(self.overfitting.as_dict())
        if self.walk_forward is not None:
            collected["walk_forward_folds"] = len(self.walk_forward.folds)
        collected["unverified_inputs"] = list(self.unverified_inputs)
        collected["epochs"] = list(self.epochs.regimes)
        return collected

    def summary(self) -> str:
        """The line an operator reads. It always carries the unverified stamps."""
        lines = [
            f"{self.label} [{self.window}] — {str(self.status).upper()}",
            f"  run window: {self.candidate_window}",
            f"  judged on: {self.judged_series}",
            f"  headline: {self.headline}",
            f"  deflated Sharpe {self.deflated.value:.3f} "
            f"(observed {self.deflated.observed_sharpe:.4f}/period, "
            f"deflated against {self.deflated.selection_size} logged trials, "
            f"SR* {self.deflated.expected_max_sharpe:.4f})",
            f"  annualised Sharpe {self.tails.annualised_sharpe:.2f}, "
            f"adjusted {self.tails.annualised_adjusted_sharpe:.2f}, "
            f"max drawdown {self.tails.max_drawdown:.1%}, "
            f"5% shortfall {self.tails.expected_shortfall:.4%}",
            f"  risk-matched increment {self.increment.annualised_increment:+.2%}/yr "
            f"(benchmark scaled {self.increment.benchmark_scale:.2f}x)",
        ]
        if self.overfitting is not None:
            lines.append(f"  {self.overfitting}")
        for result in self.threshold_results:
            lines.append(f"  {result}")
        for reason in self.not_evaluable_reasons:
            lines.append(f"  not evaluable: {reason}")
        if self.epochs.crosses_boundary:
            names = ", ".join(boundary.name for boundary in self.epochs.boundaries_crossed)
            lines.append(f"  window crosses epochs: {names} (justified in the gate file)")
        lines.append(f"  epochs spanned: {', '.join(self.epochs.regimes)}")
        if self.unverified_inputs:
            lines.append(f"  UNVERIFIED INPUTS: {', '.join(self.unverified_inputs)}")
        return "\n".join(lines)

    def as_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "hypothesis_id": self.hypothesis_id,
            "status": str(self.status),
            "window": self.window,
            "candidate_window": self.candidate_window,
            "judged_series": self.judged_series,
            "graded_at": self.graded_at.isoformat(),
            "trial_id": self.trial_id,
            "metrics": self.metrics(),
            "thresholds": [result.as_dict() for result in self.threshold_results],
            "not_evaluable_reasons": list(self.not_evaluable_reasons),
            "epochs": self.epochs.as_dict(),
            "holdout": self.holdout.as_dict() if self.holdout else None,
            "walk_forward": self.walk_forward.as_dict() if self.walk_forward else None,
        }


@dataclass(frozen=True, slots=True)
class Decision:
    """The terminal answer on a hypothesis: one of four, with the evidence attached."""

    outcome: Outcome
    hypothesis_id: str
    in_sample: Verdict
    holdout: Verdict | None = None

    @property
    def next_step(self) -> str:
        return self.outcome.next_step

    def summary(self) -> str:
        parts = [
            f"DECISION on {self.hypothesis_id}: {str(self.outcome).upper()}",
            f"  next: {self.next_step}",
            self.in_sample.summary(),
        ]
        if self.holdout is not None:
            parts.append("  --- holdout ---")
            parts.append(self.holdout.summary())
        return "\n".join(parts)

    def as_dict(self) -> dict[str, Any]:
        return {
            "outcome": str(self.outcome),
            "next_step": self.next_step,
            "hypothesis_id": self.hypothesis_id,
            "in_sample": self.in_sample.as_dict(),
            "holdout": self.holdout.as_dict() if self.holdout else None,
        }


@dataclass(frozen=True, slots=True)
class ValidationConfig:
    """Where the canonical log is, where the thresholds are, and where the holdout starts.

    All three are *configuration*, not call arguments, and that is the point: each is a
    decision that must not be taken while looking at a result.
    """

    trial_log_path: Path
    gate_path: Path
    holdout_first_date: dt.date
    underlying: str = "NIFTY"

    @classmethod
    def from_file(cls, path: Path | str) -> ValidationConfig:
        """Read TOML::

            trial_log_path = "research.db"
            gate_path = "thresholds/h1.toml"
            holdout_first_date = 2026-03-01
            underlying = "NIFTY"

        Relative paths resolve against the config file's own directory, so a config that
        is committed alongside its gate file keeps working from any working directory.
        """
        path = Path(path)
        with path.open("rb") as handle:
            document = tomllib.load(handle)
        root = path.parent
        missing = [
            key
            for key in ("trial_log_path", "gate_path", "holdout_first_date")
            if key not in document
        ]
        if missing:
            raise ValueError(f"{path} is missing {', '.join(missing)}")
        holdout = document["holdout_first_date"]
        if isinstance(holdout, dt.datetime):
            holdout = holdout.date()
        if not isinstance(holdout, dt.date):
            raise ValueError(f"{path}: holdout_first_date must be a date, got {holdout!r}")
        return cls(
            trial_log_path=_resolve(root, document["trial_log_path"]),
            gate_path=_resolve(root, document["gate_path"]),
            holdout_first_date=holdout,
            underlying=str(document.get("underlying", "NIFTY")),
        )

    @property
    def holdout_policy(self) -> HoldoutPolicy:
        return HoldoutPolicy(first_date=self.holdout_first_date)

    def gate(self) -> DecisionGate:
        return DecisionGate.from_file(self.gate_path)


def _resolve(root: Path, value: str) -> Path:
    candidate = Path(value)
    return candidate if candidate.is_absolute() else (root / candidate)


class Validator:
    """Grades runs against pre-recorded thresholds and lands on one of four outcomes.

    Construct it from a :class:`ValidationConfig`; it opens the canonical trial log itself
    for every count it needs, and closes it again. Nothing it exposes accepts a log path,
    a trial count, or a threshold.
    """

    def __init__(self, config: ValidationConfig, *, clock: Clock | None = None) -> None:
        self._config = config
        self._clock = clock if clock is not None else SystemClock()

    @property
    def config(self) -> ValidationConfig:
        return self._config

    def open_log(self) -> ResearchSession:
        """Open the canonical log named in configuration. The only path this class knows."""
        return open_session(self._config.trial_log_path, clock=self._clock)

    def grade(
        self,
        candidate: RunEvidence,
        *,
        benchmark: RunEvidence,
        hypothesis: HypothesisRecord | str,
        overfitting: PBOResult | None = None,
        walk_forward: WalkForwardReport | None = None,
    ) -> Verdict:
        """Grade an **in-sample** run. Refuses a window that reaches into the holdout."""
        policy = self._config.holdout_policy
        if policy.contains(candidate.window):
            raise HoldoutTouchedError(
                f"the run {candidate.label!r} covers {candidate.window}, which reaches into "
                f"the holdout that begins {policy.first_date}. In-sample grading may not "
                "read those months; they exist to be looked at once, at the end."
            )
        return self._grade(
            candidate,
            benchmark=benchmark,
            hypothesis=hypothesis,
            overfitting=overfitting,
            walk_forward=walk_forward,
            holdout=None,
        )

    def grade_holdout(
        self,
        candidate: RunEvidence,
        *,
        benchmark: RunEvidence,
        hypothesis: HypothesisRecord | str,
    ) -> Verdict:
        """Grade the one run against the holdout months, after checking they are untouched.

        The check is the discipline made answerable: :func:`inspect_holdout` asks the log
        which evaluations already read past the boundary, and refuses if any did.

        **The read is recorded before it happens.** Grading the holdout *is* the touch, and
        it used to leave no trace at all: the same holdout could be graded twice and both
        passed, so the single most consequential read in the system was both invisible and
        repeatable. The touch row goes in first, as this method's first act after checking
        the run is shaped like a holdout run — writing it afterwards would mean a crash
        between the read and the write leaves the months read and the log saying otherwise.

        The row is then exempted from the check it enables, along with the trial that
        produced the evidence being graded; see :func:`inspect_holdout` for why the second
        exemption is what makes the honest workflow possible at all.

        One consequence, stated rather than hidden: the touch is a trial in the family, so
        it enters the deflation's selection count. That makes the holdout verdict very
        slightly *more* conservative than the in-sample one, which is the right direction
        for the number to move if it has to move.
        """
        policy = self._config.holdout_policy
        # Before anything is written: a run that is not a holdout run must not leave a
        # touch record for a read that never happened.
        if candidate.window.start < policy.first_date:
            raise HoldoutTouchedError(
                f"a holdout run must lie inside the holdout: {candidate.window} starts "
                f"before {policy.first_date}, so it mixes seen and unseen months."
            )
        hypothesis_id = (
            hypothesis.id if isinstance(hypothesis, HypothesisRecord) else str(hypothesis)
        )
        with self.open_log() as session:
            touch = session.log.append_trial(
                hypothesis_id=hypothesis_id,
                params={"holdout_first_date": policy.first_date.isoformat()},
                data_window=candidate.window,
                # No Sharpe key: this row records a read, not a result, and a Sharpe here
                # would enter the cross-trial variance the deflation is computed against.
                metrics={
                    "holdout_touch": True,
                    "holdout_label": policy.label,
                    "graded_run_label": candidate.label,
                    "graded_run_trial_id": candidate.trial_id,
                },
                notes=(
                    f"holdout read: {candidate.label!r} graded against the months from "
                    f"{policy.first_date}. Written before the grading, so the read is on "
                    "the record whether or not the grading completed."
                ),
            )
            status = inspect_holdout(
                session,
                hypothesis,
                policy=policy,
                exempt_trial_ids=tuple(
                    identifier
                    for identifier in (touch.trial_id, candidate.trial_id)
                    if identifier is not None
                ),
            )
        status.require_untouched()
        return self._grade(
            candidate,
            benchmark=benchmark,
            hypothesis=hypothesis,
            overfitting=None,
            walk_forward=None,
            holdout=status,
        )

    def decide(
        self,
        in_sample: Verdict,
        *,
        holdout: Verdict | None = None,
    ) -> Decision:
        """Land on one of spec §6's four outcomes.

        A passing in-sample verdict with no holdout verdict is **not** a decision, and
        this refuses to invent one: the holdout is the last step of the loop, and a
        candidate that has passed everything else is exactly the case where skipping it
        is most tempting and most expensive.
        """
        hypothesis_id = in_sample.hypothesis_id
        if holdout is not None and holdout.hypothesis_id != hypothesis_id:
            raise HypothesisMismatchError(
                f"the in-sample verdict is filed under {hypothesis_id!r} and the holdout "
                f"verdict under {holdout.hypothesis_id!r}. A decision is a statement about "
                "one hypothesis; pairing two would attach one idea's holdout evidence to "
                "another idea's in-sample case, which is the strongest possible form of "
                "the mistake this component exists to prevent."
            )
        # A holdout verdict alongside a FAILED or NOT_EVALUABLE in-sample verdict is kept
        # rather than refused — it is evidence, and discarding evidence is worse than
        # carrying it — but it did not enter the outcome below, and the record should not
        # let a reader think it did.
        if in_sample.status is GateStatus.NOT_EVALUABLE:
            return Decision(Outcome.NOT_EVALUABLE, hypothesis_id, in_sample, holdout)
        if in_sample.status is GateStatus.FAILED:
            return Decision(Outcome.FAILS_THRESHOLD, hypothesis_id, in_sample, holdout)
        if holdout is None:
            raise HoldoutRequiredError(
                f"{in_sample.label!r} passed every in-sample threshold, so the decision "
                "depends on the holdout months and nothing else. Run grade_holdout() and "
                "pass the result; there is no decision without it."
            )
        if holdout.status is GateStatus.NOT_EVALUABLE:
            return Decision(Outcome.NOT_EVALUABLE, hypothesis_id, in_sample, holdout)
        if holdout.status is GateStatus.PASSED:
            return Decision(Outcome.PASSES_SURVIVES_HOLDOUT, hypothesis_id, in_sample, holdout)
        return Decision(Outcome.PASSES_FAILS_HOLDOUT, hypothesis_id, in_sample, holdout)

    # ----------------------------------------------------------------- internals

    def _grade(
        self,
        candidate: RunEvidence,
        *,
        benchmark: RunEvidence,
        hypothesis: HypothesisRecord | str,
        overfitting: PBOResult | None,
        walk_forward: WalkForwardReport | None,
        holdout: HoldoutStatus | None,
    ) -> Verdict:
        gate = self._config.gate()
        with self.open_log() as session:
            universe = SelectionUniverse(session, hypothesis)
            record = (
                hypothesis
                if isinstance(hypothesis, HypothesisRecord)
                else session.log.get_hypothesis(universe.hypothesis_id)
            )
            logged_at = _logged_created_at(session, universe.hypothesis_id, candidate.trial_id)
        gate.check_binding(record)
        # A run that came through the log has an authoritative timestamp there; run_at is
        # a free field the caller typed. Prefer the log, and refuse a disagreement rather
        # than silently taking either side — see _reconcile_run_timestamp.
        run_at = _reconcile_run_timestamp(candidate, logged_at)
        gate.require_recorded_before(run_at, what=f"the run {candidate.label!r}")

        # Every statistic is computed on ONE series. With a walk-forward report that is
        # the concatenated out-of-sample folds — including the cost-breakeven headline and
        # the benchmark increment, which would otherwise be in-sample numbers printed
        # beside an out-of-sample Sharpe. The benchmark is cut to the same span so the
        # comparison stays like-for-like; if it cannot be, the increment refuses.
        if walk_forward is not None:
            judged = walk_forward.out_of_sample
            # The report has to be a report *on this candidate*. Nothing below re-derives
            # the judged window from the candidate, so without this the walk-forward
            # series can carry the grading anywhere — including past the holdout boundary
            # that grade() just checked the candidate's own window against. See
            # JudgedSeriesMismatchError.
            if not (
                candidate.window.start <= judged.window.start
                and judged.window.end <= candidate.window.end
            ):
                raise JudgedSeriesMismatchError(
                    f"the walk-forward out-of-sample series covers {judged.window}, which is "
                    f"not inside the run {candidate.label!r}'s own window "
                    f"{candidate.window}. Every statistic in the verdict is computed on the "
                    "out-of-sample series, so a report built on other sessions would be "
                    "graded under this run's name — and would bypass the holdout and epoch "
                    "checks, which are made against the run's window."
                )
            judged_run = replace(candidate, returns=judged)
            judged_benchmark = replace(
                benchmark, returns=benchmark.returns.restricted_to(judged.window)
            )
            judged_series = (
                f"walk-forward out-of-sample, {len(walk_forward.folds)} folds, "
                f"{len(judged)} sessions [{judged.window}]"
            )
        else:
            judged = candidate.returns
            judged_run = candidate
            judged_benchmark = benchmark
            judged_series = f"the whole window, {len(judged)} sessions, no walk-forward"
        # Annotated from the judged series, which is the object every statistic describes.
        # Containment above means this can only ever be a SUBSET of the candidate's
        # epochs, and that cuts both ways: the annotation is the honest one, and the
        # refusal is weaker than it was. A run whose window spans a break but whose
        # out-of-sample folds all land inside one regime no longer needs a recorded
        # cross_epoch_justification. That is correct — nothing pooled two regimes, so
        # there is nothing to justify — but it is a relaxation, and it is stated rather
        # than left for someone to discover.
        annotation = epochs_spanned(judged.window, justification=gate.cross_epoch_justification)
        annotation.require_justification()

        deflated = deflated_sharpe_ratio(judged, universe=universe)
        breakeven = cost_breakeven(judged_run)
        tails = tail_metrics(judged)
        increment = risk_matched_increment(judged_run, benchmark=judged_benchmark)
        # Spec §3 requires the benchmark under the *identical* cost model, so a caveat on
        # the benchmark is as verdict-relevant as one on the candidate: the risk-matched
        # increment is judged against it. Prefixed, because whose caveat it is matters.
        benchmark_stamps = tuple(f"benchmark:{stamp}" for stamp in benchmark.unverified_inputs)
        stamps = tuple(
            dict.fromkeys(
                (
                    *candidate.unverified_inputs,
                    *_feasibility_stamps(candidate),
                    *benchmark_stamps,
                    *deflated.unverified_inputs,
                    *_pbo_stamps(overfitting),
                    *_periodicity_stamps(judged, judged_benchmark),
                    EPOCH_PROVENANCE_STAMP,
                )
            )
        )
        psr = probabilistic_sharpe_ratio(judged)
        observed: dict[str, float | None] = {
            "deflated_sharpe": deflated.value,
            "probabilistic_sharpe": psr,
            "cost_breakeven_multiple": breakeven.multiple,
            "max_drawdown": tails.max_drawdown,
            "annualised_sharpe": tails.annualised_sharpe,
            # Named for what it is. TailMetrics carries a per-period `adjusted_sharpe`
            # too, and the two differ by sqrt(252) — a factor of 15.9 under one name.
            "annualised_adjusted_sharpe": tails.annualised_adjusted_sharpe,
            "expected_shortfall": tails.expected_shortfall,
            "risk_matched_increment": increment.annualised_increment,
            "sharpe_difference": increment.sharpe_difference,
            "pbo": overfitting.value if overfitting is not None else None,
        }
        # The gate validates threshold names against MEASURED_METRICS at load; this is the
        # other half of that promise, and it fails loudly in tests rather than at a user.
        assert set(observed) == set(MEASURED_METRICS), (
            "the gate's threshold vocabulary and the metrics actually computed have "
            f"drifted: {set(observed) ^ set(MEASURED_METRICS)}"
        )
        results = tuple(
            threshold.check(observed.get(threshold.metric))
            for threshold in gate.thresholds_in_force(holdout=holdout is not None)
        )
        unmeasured = sorted(result.threshold.metric for result in results if result.missing)
        if unmeasured:
            raise MetricNotReportedError(
                f"the gate in {gate.source} requires {', '.join(unmeasured)}, and the run "
                f"{candidate.label!r} did not report it. Refusing to grade: an unmeasured "
                "criterion is neither a pass nor a fail, and recording it as either would "
                "be a statement about the strategy rather than about the evidence."
            )
        reasons = _not_evaluable_reasons(
            candidate=candidate,
            breakeven=breakeven,
            gate=gate,
        )
        if reasons:
            status = GateStatus.NOT_EVALUABLE
        elif all(result.passed for result in results):
            status = GateStatus.PASSED
        else:
            status = GateStatus.FAILED
        return Verdict(
            label=candidate.label,
            hypothesis_id=universe.hypothesis_id,
            status=status,
            window=str(judged.window),
            candidate_window=str(candidate.window),
            judged_series=judged_series,
            graded_at=require_aware(self._clock.now(), "clock.now()"),
            headline=breakeven,
            deflated=deflated,
            tails=tails,
            increment=increment,
            probabilistic_sharpe=psr,
            epochs=annotation,
            threshold_results=results,
            unverified_inputs=stamps,
            not_evaluable_reasons=reasons,
            overfitting=overfitting,
            walk_forward=walk_forward,
            holdout=holdout,
            trial_id=candidate.trial_id,
        )


FEASIBILITY_NOT_REPORTED_STAMP = "feasibility.not_reported"
LOW_POWER_PBO_STAMP = "pbo.few_configurations"
PERIODICITY_MISMATCH_STAMP = "increment.periods_per_year_mismatch"


def _logged_created_at(
    session: ResearchSession, hypothesis_id: str, trial_id: str | None
) -> dt.datetime | None:
    """The log's own ``created_at`` for ``trial_id``, or refuse.

    ``None`` means the run carries no ``trial_id``, which is legitimate — the caller's
    ``run_at`` is then all there is and the gate decides whether that is enough.

    An id that is supplied and does not resolve raises. It used to fall back to
    ``run_at``, which made a mistyped or foreign id look exactly like no id at all: the
    thresholds-predate-the-run check reverted to trusting a caller-typed timestamp,
    which is the thing resolving ``trial_id`` was added to stop. Which database is
    canonical is still C4's question, but it is answered for this call by
    ``ValidationConfig.trial_log_path`` — so "not in the configured log" is now a
    statement this component can make and refuse on.
    """
    if trial_id is None:
        return None
    return session.log.require_family_trial(hypothesis_id, trial_id).created_at


def _reconcile_run_timestamp(
    candidate: RunEvidence, logged_at: dt.datetime | None
) -> dt.datetime | None:
    """Prefer the log's timestamp over the caller-typed one, and refuse a disagreement.

    ``RunEvidence.run_at`` is a free field: a caller who wants the thresholds to look like
    they predate the run can type any moment into it. When ``trial_id`` names a row in the
    canonical log, that row's ``created_at`` was written by the log's own clock and is the
    thing the docstring of
    :meth:`~xman_research.validation.gate.DecisionGate.require_recorded_before` already
    points at. A disagreement is not resolved silently in either direction — one of the
    two is wrong, and which one is not this component's to decide.
    """
    if logged_at is None:
        return candidate.run_at
    if candidate.run_at is not None and candidate.run_at != logged_at:
        raise ThresholdsNotRecordedError(
            f"the run {candidate.label!r} reports run_at {candidate.run_at.isoformat()}, but "
            f"the trial log records trial {candidate.trial_id} as created at "
            f"{logged_at.isoformat()}. run_at is a field the caller fills in and created_at "
            "is written by the log's own clock; a disagreement between them means the "
            "evidence about when this run happened is not consistent, and the "
            "thresholds-predate-the-run check rests on exactly that."
        )
    return logged_at


def _feasibility_stamps(candidate: RunEvidence) -> tuple[str, ...]:
    """Say so when a run supplied no feasibility facts at all.

    :class:`~xman_research.validation.series.FeasibilityFacts` defaults to all zeros, and
    zero attempted intents makes ``infeasible_fraction`` and ``stale_fraction`` both 0.0 —
    so a run that reported nothing reads as a run where nothing went wrong, and the *not
    evaluable* rules can never fire on it. Contrast the cost input, where absence is
    refused outright. Silence is not verification, so it is stamped.
    """
    facts = candidate.feasibility
    if facts.intents_attempted == 0 and facts.sessions_run == 0:
        return (FEASIBILITY_NOT_REPORTED_STAMP,)
    return ()


def _pbo_stamps(overfitting: PBOResult | None) -> tuple[str, ...]:
    """Carry PBO's own low-power caveat into the verdict when it has one."""
    if overfitting is not None and overfitting.low_power:
        return (LOW_POWER_PBO_STAMP,)
    return ()


def _periodicity_stamps(judged: ReturnSeries, benchmark: RunEvidence) -> tuple[str, ...]:
    """The risk-matched increment annualises both sides by the candidate's periodicity."""
    if judged.periods_per_year != benchmark.returns.periods_per_year:
        return (PERIODICITY_MISMATCH_STAMP,)
    return ()


def _not_evaluable_reasons(
    *,
    candidate: RunEvidence,
    breakeven: CostBreakeven,
    gate: DecisionGate,
) -> tuple[str, ...]:
    """Spec §6's fourth outcome, decided before pass/fail. See the module docstring."""
    reasons: list[str] = []
    feasibility = candidate.feasibility
    if feasibility.infeasible_fraction > gate.rules.max_infeasible_fraction:
        reasons.append(
            f"{feasibility.infeasible_fraction:.1%} of {feasibility.intents_attempted} "
            f"intents could not have been filled (limit "
            f"{gate.rules.max_infeasible_fraction:.1%}); the P&L describes trades the "
            "market would not have taken"
        )
    if feasibility.stale_fraction > gate.rules.max_stale_fraction:
        reasons.append(
            f"{feasibility.stale_fraction:.1%} of sessions carried a position at a stale "
            f"mark (limit {gate.rules.max_stale_fraction:.1%}); the equity curve is partly "
            "an estimate"
        )
    # Only when the *gross* edge is positive. A strategy that loses before costs does not
    # "survive only at optimistic costs" — no cost assumption saves it, so it is a plain
    # failure and calling it unevaluable would send the operator to fix the wrong thing.
    if (
        candidate.unverified_inputs
        and breakeven.mean_gross > 0.0
        and breakeven.multiple <= gate.rules.optimistic_costs_below
    ):
        reasons.append(
            f"the edge survives only at optimistic costs (breakeven "
            f"{breakeven.multiple:.2f}x, at or below "
            f"{gate.rules.optimistic_costs_below:.2f}x) while the cost inputs are "
            f"unverified ({', '.join(candidate.unverified_inputs)})"
        )
    return tuple(reasons)
