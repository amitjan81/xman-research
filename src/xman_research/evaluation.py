"""The automatic-logging seam.

Criterion: *every* evaluation appears in the log, including one run from a notebook.
That rules out logging inside a blessed CLI entrypoint — a notebook does not go through
one. So the logging lives at the point where an evaluation *is a function call*: a
decorator and a context manager, both of which append a trial by construction.

The natural notebook shape is therefore already the logged shape::

    session = open_session("research.db")

    @session.evaluation(h1)
    def evaluate(window: DataWindow, *, delta: float) -> dict[str, float]:
        ...
        return {"sharpe": 1.1, "cost_breakeven_multiple": 2.4}

    evaluate(DataWindow(date(2023, 1, 1), date(2024, 12, 31)), delta=0.30)

Nothing else has to be remembered, and there is no un-logged variant of the same call
that is more convenient. That is the whole design: the honest path is the easy path.

Two behaviours worth stating because they are the parts people get wrong:

* **A raising evaluation is still logged**, with ``outcome=error``, and the exception is
  re-raised unchanged. If failures went unlogged, a variant could be un-tried by making
  it throw.
* **The trial id is minted when the trial starts**, before the body runs, and handed to
  the body as a :class:`TrialContext`. That is deliberate forward-shaping: when C5's
  backtester arrives, its entrypoint can *require* a ``TrialContext`` argument, at which
  point running a backtest outside a logged trial stops being merely unusual and becomes
  impossible to express.
"""

from __future__ import annotations

import functools
import inspect
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from xman_research.clock import Clock, SystemClock
from xman_research.code_version import CodeVersionProvider, GitCodeVersion
from xman_research.hypothesis import HypothesisRecord
from xman_research.trial_log import (
    DataWindow,
    TrialLog,
    TrialOutcome,
    TrialRecord,
    new_trial_id,
)

__all__ = ["ResearchSession", "TrialContext", "open_session"]


@dataclass
class TrialContext:
    """A trial that is currently running.

    Handed to the evaluation body so it can attach metrics and an outcome to the row
    that will be written when it returns. It is also the token a future backtester can
    demand, proving its caller is inside a logged trial.
    """

    trial_id: str
    hypothesis_id: str
    data_window: DataWindow
    params: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    outcome: TrialOutcome = TrialOutcome.COMPLETED
    error: str | None = None
    notes: str | None = None

    def record_metrics(self, metrics: Mapping[str, Any] | None = None, **kwargs: Any) -> None:
        """Merge metrics into what will be logged. Callable more than once."""
        if metrics:
            self.metrics.update(metrics)
        if kwargs:
            self.metrics.update(kwargs)

    def record_params(self, params: Mapping[str, Any] | None = None, **kwargs: Any) -> None:
        """Merge extra params into what will be logged — resolved defaults, say."""
        if params:
            self.params.update(params)
        if kwargs:
            self.params.update(kwargs)

    def mark_not_evaluable(self, reason: str) -> None:
        """Record that the run produced no judgeable answer (spec §6's fourth outcome)."""
        self.outcome = TrialOutcome.NOT_EVALUABLE
        self.add_note(reason)

    def add_note(self, note: str) -> None:
        self.notes = note if not self.notes else f"{self.notes}; {note}"


class ResearchSession:
    """The public research API: register a hypothesis, run evaluations, read counts.

    Every route through this object that runs an evaluation also logs it. There is no
    route that runs one without logging, and no route that lets a caller state how many
    trials there have been — :meth:`count_trials` and :meth:`count_family_trials` read
    the log and take no count argument.
    """

    def __init__(self, log: TrialLog) -> None:
        self._log = log

    @property
    def log(self) -> TrialLog:
        return self._log

    def register(self, record: HypothesisRecord) -> HypothesisRecord:
        """Persist a hypothesis. Idempotent; called for you by :meth:`trial`."""
        return self._log.register_hypothesis(record)

    @contextmanager
    def trial(
        self,
        hypothesis: HypothesisRecord | str,
        *,
        data_window: DataWindow,
        params: Mapping[str, Any] | None = None,
        notes: str | None = None,
    ) -> Iterator[TrialContext]:
        """Run a block as one logged trial.

        The row is appended in a ``finally``, so it lands whether the block returns or
        raises. It cannot be written up front and updated afterwards — the append-only
        triggers forbid the update, which is the point.
        """
        hypothesis_id = self._resolve_hypothesis(hypothesis)
        context = TrialContext(
            trial_id=new_trial_id(),
            hypothesis_id=hypothesis_id,
            data_window=data_window,
            params=dict(params or {}),
            notes=notes,
        )
        try:
            yield context
        except BaseException as exc:
            context.outcome = TrialOutcome.ERROR
            context.error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            self._append(context)

    def evaluation(
        self,
        hypothesis: HypothesisRecord | str,
        *,
        data_window: DataWindow | None = None,
        notes: str | None = None,
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Decorate an evaluation function so that calling it appends a trial.

        Params are taken from the call's bound arguments, the data window from a
        :class:`DataWindow` argument (or the one given here), and metrics from the
        return value when it is a mapping. If the function declares a parameter
        annotated :class:`TrialContext`, the running trial is injected into it.
        """

        def decorate(function: Callable[..., Any]) -> Callable[..., Any]:
            signature = inspect.signature(function)
            context_param = _context_parameter(signature)

            @functools.wraps(function)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                supplied = signature.bind_partial(*args, **kwargs).arguments
                bound = signature.bind_partial(*args, **kwargs)
                bound.apply_defaults()
                window = _window_from(bound.arguments, data_window)
                params = {
                    name: value
                    for name, value in bound.arguments.items()
                    if name != context_param and not isinstance(value, DataWindow)
                }
                with self.trial(
                    hypothesis, data_window=window, params=params, notes=notes
                ) as context:
                    call_kwargs = dict(kwargs)
                    if context_param is not None and context_param not in supplied:
                        call_kwargs[context_param] = context
                    result = function(*args, **call_kwargs)
                    if isinstance(result, Mapping):
                        context.record_metrics(result)
                    elif result is not None:
                        context.add_note(
                            f"returned {type(result).__name__}, not a metrics mapping: "
                            "no metrics recorded for this trial"
                        )
                    return result

            return wrapper

        return decorate

    def count_trials(self, hypothesis: HypothesisRecord | str) -> int:
        """Trials against exactly this hypothesis, read from the log."""
        return self._log.count_trials(self._id_of(hypothesis))

    def count_family_trials(self, hypothesis: HypothesisRecord | str) -> int:
        """Trials against this hypothesis's whole amendment family, read from the log."""
        return self._log.count_family_trials(self._id_of(hypothesis))

    def trials(self, hypothesis: HypothesisRecord | str) -> tuple[TrialRecord, ...]:
        return self._log.trials(self._id_of(hypothesis))

    def family_trials(self, hypothesis: HypothesisRecord | str) -> tuple[TrialRecord, ...]:
        return self._log.family_trials(self._id_of(hypothesis))

    # ----------------------------------------------------------------- internals

    def _append(self, context: TrialContext) -> TrialRecord:
        return self._log.append_trial(
            hypothesis_id=context.hypothesis_id,
            params=context.params,
            data_window=context.data_window,
            metrics=context.metrics,
            outcome=context.outcome,
            error=context.error,
            notes=context.notes,
            trial_id=context.trial_id,
        )

    def _resolve_hypothesis(self, hypothesis: HypothesisRecord | str) -> str:
        if isinstance(hypothesis, HypothesisRecord):
            self._log.register_hypothesis(hypothesis)
            return hypothesis.id
        return self._id_of(hypothesis)

    def _id_of(self, hypothesis: HypothesisRecord | str) -> str:
        if isinstance(hypothesis, HypothesisRecord):
            return hypothesis.id
        if isinstance(hypothesis, str):
            return hypothesis
        raise TypeError(f"expected a HypothesisRecord or an id, got {type(hypothesis).__name__}")


def open_session(
    db_path: Path | str,
    *,
    clock: Clock | None = None,
    code_version: CodeVersionProvider | None = None,
    repo_root: Path | str | None = None,
) -> ResearchSession:
    """Open a research session against ``db_path`` — the notebook's first line.

    This is the wiring boundary, and the only place a :class:`SystemClock` and a git
    version provider are constructed by default. Business logic below it never reaches
    for the wall clock; tests pass a :class:`~xman_research.clock.ManualClock` here.
    """
    return ResearchSession(
        TrialLog(
            db_path,
            clock=clock if clock is not None else SystemClock(),
            code_version=code_version if code_version is not None else GitCodeVersion(repo_root),
        )
    )


def _context_parameter(signature: inspect.Signature) -> str | None:
    for name, parameter in signature.parameters.items():
        annotation = parameter.annotation
        if annotation is TrialContext or (
            isinstance(annotation, str) and annotation.split(".")[-1] == "TrialContext"
        ):
            return name
    return None


def _window_from(arguments: Mapping[str, Any], default: DataWindow | None) -> DataWindow:
    for value in arguments.values():
        if isinstance(value, DataWindow):
            return value
    if default is not None:
        return default
    raise ValueError(
        "an evaluation needs a data window: pass a DataWindow argument, or give "
        "data_window= to the decorator. A trial whose window is unknown cannot be "
        "compared with any other trial."
    )
