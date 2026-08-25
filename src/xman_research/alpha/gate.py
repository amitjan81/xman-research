"""Stage two: take one screened instance to a pre-registered gate and land on a verdict.

**This module reimplements no statistics.** Every number in the record it writes comes from
:mod:`xman_research.validation` — the deflated Sharpe, the cost-breakeven multiple, the
risk-matched increment, the four-outcome decision. What is added here is the wiring that
stage one leaves open: which instance, at which point, filed against which hypothesis, over
which window.

**The screen's trials are counted, and that is the whole reason the hypothesis is reused.**
:class:`~xman_research.validation.decision.Validator` deflates against
:class:`~xman_research.validation.pbo.SelectionUniverse`, which asks the trial log how many
trials the *family* of the graded hypothesis holds. A screen appends one trial per instance
against its own hypothesis record before reading any number, so a gate run filed against
that same record deflates against every instance the screen tried, not against the one that
survived. Nothing here passes a count: the log is the authority, and the record this module
writes quotes ``trial_log.family_trial_count_at_decision`` back from it.

**The binding is checked before a single trial is spent.** A gate file that does not carry
every numeric threshold the hypothesis registered can never grade it, and discovering that
from inside the grading would leave the log holding runs for a decision that was never
reached. :func:`run_stage_two_gate` reads the gate and the hypothesis first, calls
``check_binding``, and only then runs anything. So does the seal check on the window.

**Two refusals remain that cost trials, and they are named rather than implied.** A gate
whose ``recorded_at`` is not before the run it grades is refused from inside the grading, by
which point the run is logged; the check needs the run's own timestamp, which the log writes
when the trial closes. And a window carrying too few sessions to form a return series is
refused by :func:`~xman_research.adapter.evidence_from_result` after the backtest, which is
where a one-month holdout for a template that enters weekly lands. Both leave logged trials
and no decision record. Neither is reachable without the log already holding the run, so
neither is pre-checkable here; what is available is that they are stated.

**The holdout window is an argument, and it is required.** Where the unseen months end is a
pre-registration, and defaulting it would be choosing the most consequential window in the
loop with the screen's rankings already on the table. It is read only if the in-sample
verdict passes — see :func:`~xman_research.h1.run_decision.run_h1_decision` for why a failed
in-sample verdict is a complete decision with the holdout still sealed.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from xman_research.adapter import evidence_from_result
from xman_research.alpha.features import FeatureBuilder
from xman_research.alpha.holdout import HOLDOUT_FIRST_DATE, require_unsealed
from xman_research.alpha.screen import (
    CandidateInstance,
    ScreenedInstance,
    ScreenSheet,
    feature_pass,
    load_screen_sheet,
)
from xman_research.alpha.templates import (
    StrategyTemplate,
    TemplateRegistry,
    default_registry,
    parameter_key,
)
from xman_research.backtest.engine import BacktestConfig, BacktestResult, run_backtest
from xman_research.evaluation import ResearchSession, open_session
from xman_research.hypothesis import HypothesisRecord
from xman_research.session_store import SessionStore
from xman_research.trial_log import DataWindow
from xman_research.validation import Decision, GateStatus, ValidationConfig, Validator, Verdict

__all__ = ["DECISION_RECORD_NAME", "GateRun", "StageTwoGateError", "run_stage_two_gate"]

#: What the stage-two runner calls its output inside ``--out``. The same basename
#: ``research/h1`` uses, because it is the same shape of document and
#: :meth:`~xman_research.alpha.library.TemplateLibrary.admit` reads either without knowing
#: which runner produced it.
DECISION_RECORD_NAME = "decision.json"


class StageTwoGateError(ValueError):
    """A stage-two run that cannot be made as asked, refused before any trial is appended."""


@dataclass(frozen=True, slots=True)
class GateRun:
    """One stage-two decision and everything it rested on."""

    decision: Decision
    hypothesis: HypothesisRecord
    instance: CandidateInstance
    parameters: dict[str, float]
    sheet: ScreenSheet
    sheet_path: Path
    gate_path: Path
    in_sample_result: BacktestResult
    benchmark_result: BacktestResult
    benchmark_parameters: dict[str, float]
    """The point the sheet's benchmark was built at — it is a template instance too."""
    holdout_result: BacktestResult | None
    trial_rows: tuple[dict[str, Any], ...]
    holdout_spent: bool
    seal_override: str | None = None
    """Why this run was allowed to read past the corpus-wide seal, where it did."""

    @property
    def screen_trials(self) -> int:
        """How many trials the screen spent, read off the sheet's own rows.

        A property and not a field, for the same reason :attr:`trial_count` is one: a count
        accepted beside the evidence it describes is a count that can disagree with it, and
        ``tests/test_no_caller_supplied_count.py`` refuses any public callable in this
        package that takes one.
        """
        return self.sheet.n_trials_logged

    @property
    def trial_count(self) -> int:
        """The family trial count, derived from the rows the log handed back.

        A property and not a field, for the reason ``tests/test_no_caller_supplied_count.py``
        enforces across this package: the one number a researcher must never supply is the
        one the deflation is computed against.
        """
        return len(self.trial_rows)

    def as_dict(self) -> dict[str, Any]:
        """The decision record, in the shape ``research/h1/decision.json`` carries.

        ``runs.in_sample.template_parameters`` is the addition, and it is what lets an
        admission be checked against the trade the record measured rather than against its
        hold alone.
        """
        payload = self.decision.as_dict()
        payload["hypothesis"] = {
            "id": self.hypothesis.id,
            "name": self.hypothesis.name,
            "mechanism": self.hypothesis.mechanism,
            "null_hypothesis": self.hypothesis.null_hypothesis,
            "thresholds": dict(self.hypothesis.thresholds),
            "predictors": list(self.hypothesis.predictors),
        }
        payload["runs"] = {
            "in_sample": _run_summary(self.in_sample_result, parameters=self.parameters),
            "benchmark": _run_summary(self.benchmark_result, parameters=self.benchmark_parameters),
            "holdout": (
                _run_summary(self.holdout_result, parameters=self.parameters)
                if self.holdout_result is not None
                else None
            ),
        }
        payload["trial_log"] = {
            "family_trial_count_at_decision": self.trial_count,
            "rows": list(self.trial_rows),
        }
        payload["holdout_spent"] = self.holdout_spent
        payload["holdout_seal"] = {
            "first_sealed_session": HOLDOUT_FIRST_DATE.isoformat(),
            "override_reason": self.seal_override,
        }
        payload["stage_one"] = {
            "sheet": str(self.sheet_path),
            "instance_id": self.instance.instance_id,
            "template_id": self.instance.template_id,
            "parameters": dict(self.parameters),
            "parameter_key": parameter_key(self.parameters),
            "screen_trials_logged": self.screen_trials,
            "deflation_note": (
                "the deflated Sharpe above is computed against the family trial count this "
                f"record quotes ({self.trial_count}), which includes the "
                f"{self.screen_trials} trial(s) the screen at {self.sheet_path} appended "
                "against this same hypothesis. The screen is therefore paid for here."
            ),
        }
        payload["gate_path"] = str(self.gate_path)
        return payload


def _run_summary(result: BacktestResult, *, parameters: dict[str, float] | None) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "trial_id": result.trial_id,
        "window": f"{result.start.isoformat()}..{result.end.isoformat()}",
        "fingerprint": result.fingerprint(),
        "strategy": result.strategy_name,
        "strategy_parameters": dict(result.strategy_parameters),
        "metrics": result.metrics(),
        "feasibility_counts": result.feasibility_counts(),
        "unverified_inputs": list(result.unverified_inputs),
    }
    if parameters is not None:
        summary["template_parameters"] = dict(parameters)
    return summary


def run_stage_two_gate(
    *,
    sheet_path: Path | str,
    gate_path: Path | str,
    out_dir: Path | str,
    holdout_end: dt.date,
    rank: int = 1,
    store: SessionStore | None = None,
    registry: TemplateRegistry | None = None,
    holdout_first: dt.date | None = None,
    trial_log_path: Path | str | None = None,
    gaps_reason: str | None = None,
    seal_override: str | None = None,
) -> GateRun:
    """Grade one ranked instance from ``sheet_path`` and write its decision record.

    ``holdout_first`` defaults to the session after the screen's window, which is what makes
    the graded window and the sealed one abut without overlapping. ``gaps_reason`` defaults
    to the sheet's own policy, so the gate run accepts exactly the holes the screen did.

    ``seal_override`` is the written reason for a ``holdout_end`` at or past
    :data:`~xman_research.alpha.holdout.HOLDOUT_FIRST_DATE`; without one such a window is
    refused before any trial is spent. Where it is given it is copied into the decision
    record, so the months are answerable for afterwards.
    """
    sheet = load_screen_sheet(sheet_path)
    resolved_registry = registry if registry is not None else default_registry()
    row = _ranked_row(sheet, rank, Path(sheet_path))
    template = resolved_registry.get(row.instance.template_id)
    point = template.resolve(row.instance.params)
    benchmark_point = resolved_registry.get(sheet.benchmark.instance.template_id).resolve(
        sheet.benchmark.instance.params
    )

    log_path = Path(trial_log_path) if trial_log_path is not None else _sheet_log_path(sheet)
    holdout_start = (
        holdout_first if holdout_first is not None else sheet.window.end + dt.timedelta(days=1)
    )
    if holdout_start <= sheet.window.end:
        raise StageTwoGateError(
            f"the holdout begins {holdout_start} and the screened window ends "
            f"{sheet.window.end}. The graded months and the sealed ones would overlap, so "
            "the holdout would not be unseen."
        )
    if holdout_end < holdout_start:
        raise StageTwoGateError(
            f"the holdout window {holdout_start}..{holdout_end} ends before it begins"
        )
    # Before the gate file is even read: a window past the corpus-wide seal is refused here
    # rather than after the screen's window has been re-measured and logged.
    override = require_unsealed(
        holdout_end, what="the gate's holdout window", override_reason=seal_override
    )
    require_unsealed(
        sheet.window.end, what="the screened window this run re-measures", override_reason=override
    )

    config = ValidationConfig(
        trial_log_path=log_path,
        gate_path=Path(gate_path),
        holdout_first_date=holdout_start,
        underlying=sheet.underlying,
    )
    # Everything that can be refused without spending a trial is refused here: the gate file
    # must exist, its recorded_at must parse, and it must carry every numeric threshold the
    # hypothesis was registered with. A GateBindingError raised from inside the grading would
    # arrive with the runs already in the log and no decision to show for them.
    gate = config.gate()
    with open_session(log_path) as session:
        record = _hypothesis_of(session, sheet, Path(sheet_path))
    gate.check_binding(record)

    resolved_store = store if store is not None else SessionStore()
    policy = gaps_reason if gaps_reason is not None else sheet.gaps_reason
    decision_time = _decision_time(sheet)
    builder = FeatureBuilder(resolved_store, decision_time=decision_time)
    validator = Validator(config)

    in_sample_result, benchmark_result, candidate, benchmark = _measure(
        instance=row.instance,
        window=sheet.window,
        sheet=sheet,
        template=template,
        point=point,
        record=record,
        store=resolved_store,
        builder=builder,
        config=config,
        decision_time=decision_time,
        gaps_reason=policy,
        label="in-sample",
        registry=resolved_registry,
    )
    in_sample_verdict = validator.grade(candidate, benchmark=benchmark, hypothesis=record)

    holdout_verdict: Verdict | None = None
    holdout_result: BacktestResult | None = None
    if in_sample_verdict.status is GateStatus.PASSED:
        holdout_window = DataWindow(holdout_start, holdout_end)
        holdout_result, _, holdout_candidate, holdout_benchmark = _measure(
            instance=row.instance,
            window=holdout_window,
            sheet=sheet,
            template=template,
            point=point,
            record=record,
            store=resolved_store,
            builder=builder,
            config=config,
            decision_time=decision_time,
            gaps_reason=policy,
            label="holdout",
            registry=resolved_registry,
        )
        holdout_verdict = validator.grade_holdout(
            holdout_candidate, benchmark=holdout_benchmark, hypothesis=record
        )

    decision = validator.decide(in_sample_verdict, holdout=holdout_verdict)

    with open_session(log_path) as session:
        rows = tuple(_trial_row(entry) for entry in session.family_trials(record))
        counted = session.count_family_trials(record)
    logged = {row["trial_id"] for row in rows}
    missing = [identifier for identifier in sheet.trial_ids if identifier not in logged]
    if missing:
        raise StageTwoGateError(
            f"the family of {record.id} in {log_path} does not hold "
            f"{len(missing)} of the {len(sheet.trial_ids)} trials the sheet at {sheet_path} "
            f"was screened with (first missing: {missing[0]}). The hypothesis record is "
            "content-addressed, so the same spec screened into two logs mints the same id in "
            "both; deflating against a family that holds a different screen's trials would "
            "let this record claim a screen it did not pay for."
        )
    if counted != len(rows):
        raise StageTwoGateError(
            f"the log counts {counted} trials in the family of {record.id} but handed back "
            f"{len(rows)} rows. The deflated Sharpe is computed against that count, so the "
            "two cannot be allowed to differ."
        )

    run = GateRun(
        decision=decision,
        hypothesis=record,
        instance=row.instance,
        parameters=point,
        sheet_path=Path(sheet_path),
        gate_path=Path(gate_path),
        sheet=sheet,
        in_sample_result=in_sample_result,
        benchmark_result=benchmark_result,
        benchmark_parameters=benchmark_point,
        holdout_result=holdout_result,
        trial_rows=rows,
        holdout_spent=holdout_verdict is not None,
        seal_override=override,
    )
    _write(run, Path(out_dir))
    return run


# ---------------------------------------------------------------------------- internals


def _measure(
    *,
    instance: CandidateInstance,
    window: DataWindow,
    sheet: ScreenSheet,
    template: StrategyTemplate,
    point: dict[str, float],
    record: HypothesisRecord,
    store: SessionStore,
    builder: FeatureBuilder,
    config: ValidationConfig,
    decision_time: dt.time,
    gaps_reason: str | None,
    label: str,
    registry: TemplateRegistry,
) -> tuple[BacktestResult, BacktestResult, Any, Any]:
    """Run the candidate and the sheet's benchmark over one window, each in its own trial.

    **The benchmark is re-run rather than borrowed from the sheet.** The risk-matched
    increment is a comparison of two series over the identical sessions under the identical
    cost model, and the screen's benchmark row was measured in a different trial whose result
    object is gone by the time a sheet is read back. Re-running costs one trial, which is
    logged and enters the deflation — the conservative direction.
    """
    series, _, _ = feature_pass(
        store=store,
        features=builder,
        underlying=sheet.underlying,
        window=window,
        gaps_reason=gaps_reason,
    )
    benchmark_instance = sheet.benchmark.instance
    benchmark_template = registry.get(benchmark_instance.template_id)
    engine_config = BacktestConfig(
        underlying=sheet.underlying, decision_time=decision_time, gap_reason=gaps_reason
    )
    with open_session(config.trial_log_path) as session:
        candidate_result = _one_run(
            session,
            record,
            store=store,
            window=window,
            config=engine_config,
            strategy=template.build(point, sheet.underlying, feature_series=series),
            params={
                # The screen's own id for this instance, so a reader joining the gate's rows
                # to the sheet's is joining on one string. Keying the resolved point instead
                # would name the same instance differently in the two sets of rows.
                "instance_id": instance.instance_id,
                "template_id": template.template_id,
                "stage": f"stage 2 {label} candidate",
                **point,
            },
            notes=(
                f"Stage-two gate, {label} run over {window}. {template.template_id} at "
                f"[{parameter_key(point)}], graded against thresholds recorded in "
                f"{config.gate_path}."
            ),
        )
        benchmark_result = _one_run(
            session,
            record,
            store=store,
            window=window,
            config=engine_config,
            strategy=benchmark_template.build(
                benchmark_instance.params, sheet.underlying, feature_series=series
            ),
            params={
                "instance_id": benchmark_instance.instance_id,
                "template_id": benchmark_instance.template_id,
                "stage": f"stage 2 {label} benchmark",
                **dict(benchmark_instance.params),
            },
            notes=(
                f"Stage-two gate, {label} benchmark over {window}. The sheet's own "
                "unconditional benchmark, re-run under the identical cost model and window "
                "so the risk-matched increment compares like with like."
            ),
        )
        candidate = evidence_from_result(
            candidate_result,
            session=session,
            hypothesis_id=record.id,
            label=f"{template.template_id}[{parameter_key(point)}] ({label})",
        )
        benchmark = evidence_from_result(
            benchmark_result,
            session=session,
            hypothesis_id=record.id,
            label=f"{benchmark_instance.instance_id} ({label} benchmark)",
        )
    return candidate_result, benchmark_result, candidate, benchmark


def _one_run(
    session: ResearchSession,
    record: HypothesisRecord,
    *,
    store: SessionStore,
    window: DataWindow,
    config: BacktestConfig,
    strategy: Any,
    params: dict[str, Any],
    notes: str,
) -> BacktestResult:
    with session.trial(record, data_window=window, params=params, notes=notes) as trial:
        return run_backtest(trial, store=store, strategy=strategy, config=config)


def _ranked_row(sheet: ScreenSheet, rank: int, source: Path) -> ScreenedInstance:
    if rank < 1 or rank > len(sheet.instances):
        raise StageTwoGateError(
            f"--rank {rank} names no instance: the sheet at {source} ranks "
            f"{len(sheet.instances)} of them"
        )
    row = sheet.instances[rank - 1]
    if not row.measured:
        raise StageTwoGateError(
            f"rank {rank} of {source} is {row.instance.instance_id}, which the screen could "
            f"not measure ({row.outcome}): {row.reason}. A gate grades a strategy against "
            "thresholds, and there is no series here to grade."
        )
    return row


def _sheet_log_path(sheet: ScreenSheet) -> Path:
    path = sheet.provenance.get("trial_log_path")
    if not isinstance(path, str) or not path.strip():
        raise StageTwoGateError(
            "the sheet names no trial log in its provenance, so there is nowhere to file "
            "this run and no family to deflate against. Pass --trial-log."
        )
    return Path(path)


def _hypothesis_of(session: ResearchSession, sheet: ScreenSheet, source: Path) -> HypothesisRecord:
    """The screen's own hypothesis record, read back out of the log it was registered in.

    Read rather than rebuilt from the spec file: the record is content-addressed, so a spec
    edited since the screen ran would mint a different id, file this run against a family
    that holds none of the screen's trials, and deflate against a count of one.
    """
    hypothesis_id = sheet.provenance.get("hypothesis_id")
    if not isinstance(hypothesis_id, str) or not hypothesis_id.strip():
        raise StageTwoGateError(f"the sheet at {source} names no hypothesis in its provenance")
    try:
        return session.log.get_hypothesis(hypothesis_id)
    except LookupError as error:
        raise StageTwoGateError(
            f"the log at {session.log.db_path} holds no hypothesis {hypothesis_id!r}, which "
            f"the sheet at {source} was screened against. Without it there is no family to "
            f"deflate against: {error}"
        ) from error


def _decision_time(sheet: ScreenSheet) -> dt.time:
    stated = sheet.provenance.get("decision_time")
    if not isinstance(stated, str):
        raise StageTwoGateError(
            "the sheet names no decision time in its provenance. The gate run must act at "
            "the minute the screen acted at, and guessing it would grade a different strategy."
        )
    return dt.time.fromisoformat(stated)


def _trial_row(row: Any) -> dict[str, Any]:
    return {
        "trial_id": row.trial_id,
        "hypothesis_id": row.hypothesis_id,
        "created_at": row.created_at.isoformat(),
        "data_window": str(row.data_window),
        "params": dict(row.params),
        "metrics": dict(row.metrics),
        "outcome": str(row.outcome),
        "notes": row.notes,
    }


def _write(run: GateRun, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / DECISION_RECORD_NAME
    target.write_text(
        json.dumps(run.as_dict(), indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    return target
