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

What this seam cannot see, stated plainly because the count it produces is consumed as
authoritative:

* **N-in-1 nesting.** One decorated function whose body sweeps 200 parameter values
  internally and returns the best of them is **one** logged trial containing a 200-way
  selection — and 200-way selection is exactly the burden deflated Sharpe is correcting
  for. Nothing here can see inside the body, so nothing here can tell that shape from a
  single honest evaluation. **This is a design constraint on C5, not a caveat:** the
  :class:`TrialContext` token the backtester will demand must be **single-use per
  backtest run** (or the backtester must append a trial per invocation). If one token can
  be handed to 200 backtest calls, the mitigation those calls were supposed to provide is
  not there, and the nesting hole stays open under a token that looks like it closed it.
* **Notebook cell source is not versioned.** :class:`~xman_research.code_version.CodeVersion`
  reports the state of a git tree; a notebook cell is not in one. An evaluation whose
  deciding logic lives in a cell can therefore record ``dirty=False`` against a clean
  repository and still be irreproducible — the sha is true and says nothing about the
  code that ran. Hashing ``inspect.getsource`` of the decorated function into the row
  would narrow this (it does not close it: called helpers still live in other cells), and
  it needs a schema column, so it is recorded here as a known limit rather than
  half-done.
"""

from __future__ import annotations

import functools
import inspect
import traceback
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from types import TracebackType
from typing import Any

from xman_research._canonical import json_safe
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


class TrialContext:
    """A trial that is currently running.

    Handed to the evaluation body so it can attach metrics and an outcome to the row
    that will be written when it returns. It is also the token a future backtester can
    demand, proving its caller is inside a logged trial.

    **The three identity fields are read-only**, and that is load-bearing rather than
    tidy. The row is appended in a ``finally`` from these values, so a body that
    reassigned ``hypothesis_id`` to something unregistered made the append raise and
    the trial vanish — an evaluation that ran, produced a number the researcher kept,
    and left no trace. Not misattribution: a complete un-log, which defeats "a
    researcher cannot un-try a variant by throwing" head-on. ``outcome``, ``error`` and
    ``notes`` stay writable — :meth:`~ResearchSession.trial` assigns them itself, and
    every value they can take still lands a row and still increments the count.

    Params and metrics are made JSON-safe **as they are recorded**, not at append time.
    That moves any serialisation trouble into the body, at the call site that caused
    it, where the ``finally`` still logs the trial — instead of into the ``finally``,
    where it costs the row.
    """

    __slots__ = (
        "_data_window",
        "_hypothesis_id",
        "_trial_id",
        "error",
        "metrics",
        "notes",
        "outcome",
        "params",
    )

    def __init__(
        self,
        trial_id: str,
        hypothesis_id: str,
        data_window: DataWindow,
        params: Mapping[str, Any] | None = None,
        metrics: Mapping[str, Any] | None = None,
        outcome: TrialOutcome = TrialOutcome.COMPLETED,
        error: str | None = None,
        notes: str | None = None,
    ) -> None:
        self._trial_id = trial_id
        self._hypothesis_id = hypothesis_id
        self._data_window = data_window
        self.params: dict[str, Any] = json_safe(dict(params)) if params else {}
        self.metrics: dict[str, Any] = json_safe(dict(metrics)) if metrics else {}
        self.outcome = outcome
        self.error = error
        self.notes = notes

    @property
    def trial_id(self) -> str:
        """This trial's identity. Read-only — see the class docstring."""
        return self._trial_id

    @property
    def hypothesis_id(self) -> str:
        """The hypothesis this trial is filed against. Read-only."""
        return self._hypothesis_id

    @property
    def data_window(self) -> DataWindow:
        """The span this trial was run over. Read-only."""
        return self._data_window

    def __repr__(self) -> str:
        return (
            f"TrialContext(trial_id={self._trial_id!r}, "
            f"hypothesis_id={self._hypothesis_id!r}, outcome={self.outcome!r})"
        )

    def record_metrics(self, metrics: Mapping[str, Any] | None = None, **kwargs: Any) -> None:
        """Merge metrics into what will be logged. Callable more than once."""
        if metrics:
            self.metrics.update(json_safe(dict(metrics)))
        if kwargs:
            self.metrics.update(json_safe(kwargs))

    def record_params(self, params: Mapping[str, Any] | None = None, **kwargs: Any) -> None:
        """Merge extra params into what will be logged — resolved defaults, say."""
        if params:
            self.params.update(json_safe(dict(params)))
        if kwargs:
            self.params.update(json_safe(kwargs))

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

    def close(self) -> None:
        """Close the underlying log's connection."""
        self._log.close()

    def __enter__(self) -> ResearchSession:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

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

        Everything that can legitimately refuse a trial is checked **before the block
        runs**: an unregistered hypothesis, a ``data_window`` that is not one. After the
        yield there is no failure mode left that could cost the row — a refusal raised
        at that point would be indistinguishable from an evaluation that never happened,
        except that it did.
        """
        if not isinstance(data_window, DataWindow):
            raise TypeError(
                f"data_window must be a DataWindow, got {type(data_window).__name__}. "
                "Checked here, before the block runs: the same check inside the append "
                "would abort a trial that had already produced a result."
            )
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
            context.error = _describe(exc)
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
            _refuse_deferred_body(function)
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

    **``db_path`` is the count's weakest joint.** Nothing binds an evaluation to a
    canonical log: 200 trials against ``scratch.db``, then the winner against
    ``research.db``, leaves the second file honestly reporting a count of one. No check
    inside this package can tell a legitimate second database from that, because they
    are the same operation. C6 should therefore pin the database path in configuration
    and not accept it per call — the researcher choosing which log to write to, while
    looking at a result, is the decision that has to be taken off the table.
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
    found = [(name, value) for name, value in arguments.items() if isinstance(value, DataWindow)]
    if len(found) > 1:
        # Walk-forward evaluations take a train window and a test window. Picking the
        # first and dropping the rest would file the trial under a window it was not
        # judged on, which is worse than refusing: the row would look comparable to
        # other rows and would not be.
        raise ValueError(
            "an evaluation was given more than one DataWindow argument "
            f"({', '.join(name for name, _ in found)}), and which one the trial should "
            "be filed under is ambiguous. Pass exactly one, or state it explicitly with "
            "data_window= on the decorator and keep the others out of the signature "
            "(a walk-forward split can travel as one window plus params)."
        )
    if found:
        return found[0][1]
    if default is not None:
        return default
    raise ValueError(
        "an evaluation needs a data window: pass a DataWindow argument, or give "
        "data_window= to the decorator. A trial whose window is unknown cannot be "
        "compared with any other trial."
    )


def _refuse_deferred_body(function: Callable[..., Any]) -> None:
    """Refuse bodies that return without running: coroutines, generators.

    Decorating ``async def`` looks like it works and does the opposite of the job. The
    wrapper's ``with`` block ends when the coroutine object is *constructed*, so the
    trial is logged ``COMPLETED`` before a single line of the evaluation has run — and
    the real run, when something awaits it, is logged nowhere. IPython's top-level
    ``await`` makes this an ordinary notebook shape, not an exotic one. The same holds
    for a generator body, whose work happens on iteration.
    """
    kind = None
    if inspect.iscoroutinefunction(function):
        kind = "an async def"
    elif inspect.isasyncgenfunction(function):
        kind = "an async generator"
    elif inspect.isgeneratorfunction(function):
        kind = "a generator"
    if kind is None:
        return
    raise TypeError(
        f"{getattr(function, '__qualname__', function)!r} is {kind} function and cannot "
        "be an evaluation: calling it returns immediately, so the trial would be logged "
        "as completed before any of its code ran, and the actual run would not be logged "
        "at all. Wrap the body in a synchronous function (run the coroutine inside it, "
        "or materialise the generator) and decorate that."
    )


def _describe(exc: BaseException) -> str:
    """``Type: message``, plus the frame it came from where one is available.

    The type and message alone routinely fail to identify *which* of several similar
    calls in a long body failed, and the traceback object is gone by the time anyone
    reads the row.
    """
    described = f"{type(exc).__name__}: {exc}"
    try:
        frames = traceback.extract_tb(exc.__traceback__)
    except Exception:  # pragma: no cover - defensive; extract_tb does not normally raise
        return described
    if not frames:
        return described
    last = frames[-1]
    return f"{described} (at {last.filename}:{last.lineno} in {last.name})"
