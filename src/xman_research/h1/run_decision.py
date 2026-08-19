"""Close the MVP loop: run H1 against the real corpus and land on one of spec §6's four.

The whole loop, in one place, in the order spec §4.3 draws it: register the hypothesis and
its written thresholds, run the backtest through the trial log, adapt the run into evidence,
grade it against thresholds recorded beforehand, and — only if it passed everything else —
read the holdout months once.

Two properties this module exists to hold, both of which are easy to lose:

**The holdout is spent only when it can say something.** ``Validator.grade_holdout`` writes
its touch row *first* and grades second, so a grading that raises leaves the months read and
the log saying so; a retry then sees the earlier touch and refuses. The holdout is therefore
one-shot in the strongest sense — a *failed* holdout grading destroys it as surely as a
successful one. ``decide()`` needs a holdout verdict only when the in-sample verdict PASSED,
so that is the only branch on which this module touches it. A FAILED or NOT_EVALUABLE
in-sample verdict is a complete decision with the holdout still sealed, which is a strictly
better state to leave the research programme in.

**Nothing here types a number that belongs to the evidence.** No trial count (C6 reads it
from the log), no threshold (C6 reads it from the gate file), no run timestamp (the adapter
reads it from the log row). The only inputs are which windows to run and where the
configuration is.

Run: ``uv run python -m xman_research.h1.run_decision``
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from xman_research import DataWindow, HypothesisRecord, ResearchSession, open_session
from xman_research.adapter import evidence_from_result
from xman_research.backtest import BacktestConfig, BacktestResult, ShortAtmStraddle, run_backtest
from xman_research.h1.hypothesis import h1_record
from xman_research.session_store import SessionStore
from xman_research.validation import (
    Decision,
    GateStatus,
    ValidationConfig,
    Validator,
    Verdict,
)

__all__ = ["REPO_CONFIG_PATH", "DecisionRun", "run_h1_decision"]

#: The committed configuration for the real H1 decision.
REPO_CONFIG_PATH = Path(__file__).resolve().parents[3] / "research" / "h1" / "validation.toml"

#: The in-sample window: 2025-12-31 .. 2026-04-30, 80 NIFTY sessions.
#:
#: The start is not a preference. December 2025 sessions carry a lot size their own refdata
#: contradicts — NIFTY traded at 75 through 2025-12-30 while every bundle declares 65 — and
#: C5 refuses a run that touches them rather than guessing which is right. The first session
#: after that refusal is 2025-12-31.
#:
#: The end is ``holdout_first_date - 1 day``, and is derived from configuration below rather
#: than written here, so the two cannot drift.
IN_SAMPLE_START = dt.date(2025, 12, 31)

#: The last captured session. Everything after is a vendor capture outage — the subscription
#: lapsed on 2026-06-14 and roughly 42 sessions are permanently absent, not merely missing.
CORPUS_END = dt.date(2026, 6, 12)


@dataclass(frozen=True, slots=True)
class DecisionRun:
    """Everything the decision rested on, kept so the record can quote it rather than retell it."""

    decision: Decision
    hypothesis: HypothesisRecord
    in_sample_result: BacktestResult
    holdout_result: BacktestResult | None
    trial_rows: tuple[dict[str, Any], ...]
    holdout_spent: bool

    @property
    def trial_count(self) -> int:
        """The family trial count, derived from the rows the log handed back.

        A read-only property and **not** a constructor field. That distinction is not
        cosmetic: ``tests/test_no_caller_supplied_count.py`` refuses any public callable in
        this package that accepts a parameter looking like a trial count, and it refused
        this class when the count arrived alongside the rows. It was right to. A count
        passed next to the evidence it describes is a count that can disagree with it, and
        the one number the researcher must never supply is this one.

        :func:`run_h1_decision` still asks the log's own ``count_family_trials`` and refuses
        a disagreement with these rows, so the authority stays with the log rather than with
        ``len()``.
        """
        return len(self.trial_rows)

    def as_dict(self) -> dict[str, Any]:
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
            "in_sample": _run_summary(self.in_sample_result),
            "holdout": _run_summary(self.holdout_result) if self.holdout_result else None,
        }
        payload["trial_log"] = {
            "family_trial_count_at_decision": self.trial_count,
            "rows": list(self.trial_rows),
        }
        payload["holdout_spent"] = self.holdout_spent
        return payload


def _run_summary(result: BacktestResult) -> dict[str, Any]:
    return {
        "trial_id": result.trial_id,
        "window": f"{result.start.isoformat()}..{result.end.isoformat()}",
        "fingerprint": result.fingerprint(),
        "strategy": result.strategy_name,
        "strategy_parameters": dict(result.strategy_parameters),
        "metrics": result.metrics(),
        "feasibility_counts": result.feasibility_counts(),
        "unverified_inputs": list(result.unverified_inputs),
    }


def _backtest(
    session: ResearchSession,
    hypothesis: HypothesisRecord,
    *,
    store: SessionStore,
    window: DataWindow,
    underlying: str,
    notes: str,
    gap_reason_override: str | None = None,
) -> BacktestResult:
    """One backtest, through the log, over a window the store has confirmed complete.

    ``gap_reason`` is asked of the store rather than assumed either way: a complete range
    must record no reason, and a holey one must record a written one. Both windows here
    resolve complete against the NSE calendar, so both record ``None`` — but the code does
    not know that in advance and must not pretend to.
    """
    resolution = store.resolve(underlying, window.start, window.end)
    # An override is the RESEARCH decision about a known-holey window, and it belongs to
    # the caller: the reason must name the missing dates and say why the window was not
    # narrowed around them, which is knowledge the runner does not have. Left None, the
    # generic reason below applies and behaviour is exactly what it always was.
    generic = (
        None
        if resolution.is_complete
        else (
            "H1 decision run: the range has known holes and the decision is being "
            f"taken anyway. {resolution.summary()}"
        )
    )
    gap_reason = (
        generic if resolution.is_complete or gap_reason_override is None else (gap_reason_override)
    )
    with session.trial(hypothesis, data_window=window, notes=notes) as trial:
        return run_backtest(
            trial,
            store=store,
            strategy=ShortAtmStraddle(),
            config=BacktestConfig(underlying=underlying, gap_reason=gap_reason),
        )


def run_h1_decision(
    config_path: Path | str = REPO_CONFIG_PATH,
    *,
    store: SessionStore | None = None,
    in_sample_start: dt.date = IN_SAMPLE_START,
    holdout_end: dt.date = CORPUS_END,
    hypothesis: HypothesisRecord | None = None,
    gap_reason: str | None = None,
) -> DecisionRun:
    """Run the loop and return the decision, with everything it rested on attached."""
    config = ValidationConfig.from_file(config_path)
    validator = Validator(config)
    record = hypothesis if hypothesis is not None else h1_record()
    resolved_store = store if store is not None else SessionStore()

    in_sample_window = DataWindow(in_sample_start, config.holdout_first_date - dt.timedelta(days=1))
    holdout_window = DataWindow(config.holdout_first_date, holdout_end)

    with open_session(config.trial_log_path) as session:
        in_sample_result = _backtest(
            session,
            record,
            store=resolved_store,
            window=in_sample_window,
            underlying=config.underlying,
            gap_reason_override=gap_reason,
            notes=(
                "H1 in-sample decision run. Unconditional short ATM straddle, one lot, held "
                "to cash settlement. Thresholds pre-registered in research/h1/gate.toml."
            ),
        )
        candidate = evidence_from_result(
            in_sample_result,
            session=session,
            hypothesis_id=record.id,
            label="H1 short ATM straddle (candidate)",
        )
        # The naive always-on benchmark spec §3 C6 requires, under the identical cost model,
        # data and window — because it is the identical RUN. The MVP's expression of H1 is
        # unconditional, and strategies.py names the unconditional short straddle as the
        # naive benchmark. Presenting it twice under two labels is the honest form: it makes
        # the increment's structural zero visible in the verdict instead of manufacturing a
        # different strategy so that the number looks informative.
        benchmark = evidence_from_result(
            in_sample_result,
            session=session,
            hypothesis_id=record.id,
            label="naive always-on short ATM straddle (benchmark, identical run)",
        )

    # walk_forward is not supplied, and that is a decision. Nothing is being fitted — one
    # configuration, no parameters searched — so there is no in-sample fit for an
    # out-of-sample fold to test. Passing a report would shrink the judged series to the
    # out-of-sample folds alone, spending sessions from an already-short sample to answer a
    # question this strategy does not raise. overfitting is not supplied for the same
    # reason: CSCV compares configurations, and there is one.
    in_sample_verdict = validator.grade(candidate, benchmark=benchmark, hypothesis=record)

    holdout_verdict: Verdict | None = None
    holdout_result: BacktestResult | None = None
    if in_sample_verdict.status is GateStatus.PASSED:
        holdout_result, holdout_verdict = _spend_the_holdout(
            validator,
            config,
            record,
            store=resolved_store,
            window=holdout_window,
            gap_reason=gap_reason,
        )

    decision = validator.decide(in_sample_verdict, holdout=holdout_verdict)

    with open_session(config.trial_log_path) as session:
        rows = tuple(_trial_row(row) for row in session.family_trials(record))
        # The log's own counter is the authority; the rows are what the record quotes. They
        # must agree, and a disagreement is refused rather than resolved in either
        # direction — one of the two would then be describing a different family.
        counted = session.count_family_trials(record)
    if counted != len(rows):
        raise RuntimeError(
            f"the log counts {counted} trials in the family of {record.id} but handed back "
            f"{len(rows)} rows. The deflated Sharpe is computed against that count, so the "
            "two cannot be allowed to differ."
        )

    return DecisionRun(
        decision=decision,
        hypothesis=record,
        in_sample_result=in_sample_result,
        holdout_result=holdout_result,
        trial_rows=rows,
        holdout_spent=holdout_verdict is not None,
    )


def _spend_the_holdout(
    validator: Validator,
    config: ValidationConfig,
    record: HypothesisRecord,
    *,
    store: SessionStore,
    window: DataWindow,
    gap_reason: str | None = None,
) -> tuple[BacktestResult, Verdict]:
    """Read the unseen months. Reached only from a PASSED in-sample verdict — see module doc."""
    with open_session(config.trial_log_path) as session:
        result = _backtest(
            session,
            record,
            store=store,
            window=window,
            underlying=config.underlying,
            gap_reason_override=gap_reason,
            notes=(
                "H1 holdout run. The months nothing read until the in-sample verdict was "
                "settled. Graded once, against the holdout thresholds recorded in "
                "research/h1/gate.toml at the same moment as the in-sample ones."
            ),
        )
        candidate = evidence_from_result(
            result,
            session=session,
            hypothesis_id=record.id,
            label="H1 short ATM straddle (holdout)",
        )
        benchmark = evidence_from_result(
            result,
            session=session,
            hypothesis_id=record.id,
            label="naive always-on short ATM straddle (holdout benchmark, identical run)",
        )
    return result, validator.grade_holdout(candidate, benchmark=benchmark, hypothesis=record)


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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(REPO_CONFIG_PATH))
    parser.add_argument("--json-out", default=None, help="write the full decision payload here")
    arguments = parser.parse_args()

    run = run_h1_decision(arguments.config)
    print(run.decision.summary())
    print()
    print(f"family trial count at decision: {run.trial_count}")
    print(f"holdout spent: {run.holdout_spent}")
    if arguments.json_out:
        Path(arguments.json_out).write_text(
            json.dumps(run.as_dict(), indent=2, sort_keys=True, default=str) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
