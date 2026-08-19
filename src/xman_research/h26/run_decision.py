"""Run H26 against the real corpus and land on one of spec 6's four outcomes.

Follows ``xman_research.h1.run_decision`` deliberately closely; the differences are the
hypothesis's, not the runner's:

* **The family is seeded first.** H26 amends H1, so H1's record and its trial must be in
  the log before H26 is registered or graded — otherwise the deflation reads a family
  count that is short by one, in the flattering direction. See :mod:`h1_replay`.
* **Candidate and benchmark are two backtests, not one run shown twice.** H1's benchmark
  WAS its candidate, so it cost no trial. H26's arms are genuinely different portfolios,
  each burns its own single-use token, and both are logged in the family. That inflates N
  and makes the verdict harder, which is correct.
* **The engine clock comes from the strategy.** ``BacktestConfig.decision_times`` is taken
  from ``strategy.decision_times`` so the engine's minutes and the strategy's reading of
  them cannot drift apart.

Nothing here types a number belonging to the evidence: no trial count, no threshold, no
run timestamp.

Run: ``uv run python -m xman_research.h26.run_decision``
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
from xman_research.backtest import BacktestConfig, BacktestResult, run_backtest
from xman_research.backtest.strategies import ClockSide, ClockSplitShortStraddle
from xman_research.h26.h1_replay import replay_h1_family
from xman_research.h26.hypothesis import (
    CLOSE_DECISION,
    MIN_CALENDAR_DAYS_TO_EXPIRY,
    OPEN_DECISION,
    _h26_v1_record,
    h26_record,
)
from xman_research.session_store import SessionStore
from xman_research.validation import Decision, GateStatus, ValidationConfig, Validator, Verdict

__all__ = ["CORPUS_END", "IN_SAMPLE_START", "REPO_CONFIG_PATH", "DecisionRun", "run_h26_decision"]

REPO_CONFIG_PATH = Path(__file__).resolve().parents[3] / "research" / "h26" / "validation.toml"

#: 2025-12-31. The first session C5's lot-size guard does not refuse.
IN_SAMPLE_START = dt.date(2025, 12, 31)

#: 2026-08-12, the last captured session after the vendor backfill. Used only as the
#: holdout's end; the in-sample end is derived from ``holdout_first_date``.
#:
#: **This is pinned to the corpus's extent as it stood, and is deliberately left that
#: way.** Sessions after it exist now — capture reached 2026-08-19, and a historical
#: backfill reaches back to 2021-06-01. Widening it would change which sessions H26 is
#: graded over, and that is a research decision and a new trial, not a maintenance edit.
#: So it stays a boundary the owner sets rather than one that follows the data.
CORPUS_END = dt.date(2026, 8, 12)

#: N* for both arms, in rupees of index exposure — M1 §5 via M2 §3, and the same default
#: M1's own runner uses, so the two models are sized alike unless someone says otherwise.
#: M1 §12.1's pre-registration check applies to this value before any validation run.
DEFAULT_TARGET_NOTIONAL = 1_500_000.0


@dataclass(frozen=True, slots=True)
class DecisionRun:
    """Everything the decision rested on, kept so the record can quote it."""

    decision: Decision
    hypothesis: HypothesisRecord
    candidate_result: BacktestResult
    benchmark_result: BacktestResult
    holdout_results: tuple[BacktestResult, ...]
    trial_rows: tuple[dict[str, Any], ...]
    holdout_spent: bool
    h1_rows_replayed: int

    @property
    def trial_count(self) -> int:
        """Derived from the rows the log handed back — never a constructor field.

        ``tests/test_no_caller_supplied_count.py`` refuses any public callable in this
        package taking a parameter shaped like a trial count, and it is right to: a count
        passed alongside the evidence it describes is a count that can disagree with it.
        """
        return len(self.trial_rows)

    def as_dict(self) -> dict[str, Any]:
        payload = self.decision.as_dict()
        payload["hypothesis"] = {
            "id": self.hypothesis.id,
            "parent_id": self.hypothesis.parent_id,
            "name": self.hypothesis.name,
            "mechanism": self.hypothesis.mechanism,
            "null_hypothesis": self.hypothesis.null_hypothesis,
            "thresholds": dict(self.hypothesis.thresholds),
            "predictors": list(self.hypothesis.predictors),
            "entry_rule": dict(self.hypothesis.entry_rule),
            "exit_rule": dict(self.hypothesis.exit_rule),
            "notes": self.hypothesis.notes,
        }
        payload["runs"] = {
            "candidate": _run_summary(self.candidate_result),
            "benchmark": _run_summary(self.benchmark_result),
            "holdout": [_run_summary(result) for result in self.holdout_results],
        }
        payload["trial_log"] = {
            "family_trial_count_at_decision": self.trial_count,
            "h1_rows_replayed": self.h1_rows_replayed,
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
    strategy: ClockSplitShortStraddle,
    notes: str,
) -> BacktestResult:
    """One backtest, through the log, over a window the store has confirmed complete."""
    resolution = store.resolve(underlying, window.start, window.end)
    gap_reason = (
        None
        if resolution.is_complete
        else (
            "H26 decision run: the range has known holes and the decision is being taken "
            f"anyway. {resolution.summary()}"
        )
    )
    with session.trial(hypothesis, data_window=window, notes=notes) as trial:
        return run_backtest(
            trial,
            store=store,
            strategy=strategy,
            config=BacktestConfig(
                underlying=underlying,
                gap_reason=gap_reason,
                decision_times=strategy.decision_times,
            ),
        )


def _arms(
    target_notional: float = DEFAULT_TARGET_NOTIONAL,
) -> tuple[ClockSplitShortStraddle, ClockSplitShortStraddle]:
    """The candidate and its control: one class, one flag, so they cannot drift apart.

    Sized by notional rather than by lots since M2 §3 was brought back into line with
    M1 §5. Both arms take the same number, which is the point: an asymmetry in size
    would be an asymmetry in the comparison H26 exists to make.
    """
    # The minutes come from the RECORD, not from the strategy's defaults. They are
    # id-bearing there, so a change mints a new hypothesis id and breaks the gate binding;
    # taking them from anywhere else would let the graded clock drift from the registered
    # one without anything noticing.
    return (
        ClockSplitShortStraddle(
            hold=ClockSide.GAP,
            target_notional=target_notional,
            open_time=OPEN_DECISION,
            close_time=CLOSE_DECISION,
            min_calendar_days_to_expiry=MIN_CALENDAR_DAYS_TO_EXPIRY,
        ),
        ClockSplitShortStraddle(
            hold=ClockSide.SESSION,
            target_notional=target_notional,
            open_time=OPEN_DECISION,
            close_time=CLOSE_DECISION,
            min_calendar_days_to_expiry=MIN_CALENDAR_DAYS_TO_EXPIRY,
        ),
    )


def run_h26_decision(
    config_path: Path | str = REPO_CONFIG_PATH,
    *,
    store: SessionStore | None = None,
    in_sample_start: dt.date = IN_SAMPLE_START,
    holdout_end: dt.date = CORPUS_END,
    hypothesis: HypothesisRecord | None = None,
) -> DecisionRun:
    """Run the loop and return the decision, with everything it rested on attached."""
    config = ValidationConfig.from_file(config_path)
    validator = Validator(config)
    record = hypothesis if hypothesis is not None else h26_record()
    resolved_store = store if store is not None else SessionStore()
    candidate_arm, benchmark_arm = _arms()

    in_sample_window = DataWindow(in_sample_start, config.holdout_first_date - dt.timedelta(days=1))
    holdout_window = DataWindow(config.holdout_first_date, holdout_end)

    with open_session(config.trial_log_path) as session:
        # H1 first, and its parent link, before H26 is registered at all: an amendment
        # whose parent is unknown to the log cannot be registered, and a family count
        # taken before the replay would be short by one.
        _, h1_rows_replayed = replay_h1_family(session.log)
        # The whole chain, parent-first: an amendment cannot be registered against a
        # parent the log has never seen, and a family count taken before the chain is
        # complete would be short. H1 -> H26 v1 (pre-registered, superseded) -> H26 v2.
        session.register(_h26_v1_record())
        session.register(record)

        candidate_result = _backtest(
            session,
            record,
            store=resolved_store,
            window=in_sample_window,
            underlying=config.underlying,
            strategy=candidate_arm,
            notes=(
                "H26 in-sample CANDIDATE. Short ATM straddle sold at the close decision "
                "and bought back at the next open decision, so it holds only non-trading "
                "time. Thresholds pre-registered in research/h26/gate.toml."
            ),
        )
        benchmark_result = _backtest(
            session,
            record,
            store=resolved_store,
            window=in_sample_window,
            underlying=config.underlying,
            strategy=benchmark_arm,
            notes=(
                "H26 in-sample BENCHMARK. The identical straddle held open-to-close, so "
                "it holds only trading time. A separate backtest and therefore a separate "
                "trial, logged in H26's family: it inflates N and makes the verdict "
                "harder, which is the correct direction."
            ),
        )
        candidate = evidence_from_result(
            candidate_result,
            session=session,
            hypothesis_id=record.id,
            label="H26 gap-held short straddle (candidate)",
        )
        benchmark = evidence_from_result(
            benchmark_result,
            session=session,
            hypothesis_id=record.id,
            label="H26 intraday short straddle (benchmark, trading-time control)",
        )

    # No walk_forward and no overfitting report, for H1's reasons: nothing is fitted, so
    # there is no in-sample fit for a fold to test, and CSCV compares configurations of
    # which there is one.
    in_sample_verdict = validator.grade(candidate, benchmark=benchmark, hypothesis=record)

    holdout_verdict: Verdict | None = None
    holdout_results: tuple[BacktestResult, ...] = ()
    if in_sample_verdict.status is GateStatus.PASSED:
        holdout_results, holdout_verdict = _spend_the_holdout(
            validator, config, record, store=resolved_store, window=holdout_window, arms=_arms()
        )

    decision = validator.decide(in_sample_verdict, holdout=holdout_verdict)

    with open_session(config.trial_log_path) as session:
        rows = tuple(_trial_row(row) for row in session.family_trials(record))
        counted = session.count_family_trials(record)
    if counted != len(rows):
        raise RuntimeError(
            f"the log counts {counted} trials in the family of {record.id} but handed "
            f"back {len(rows)} rows. The deflated Sharpe is computed against that count, "
            "so the two cannot be allowed to differ."
        )

    return DecisionRun(
        decision=decision,
        hypothesis=record,
        candidate_result=candidate_result,
        benchmark_result=benchmark_result,
        holdout_results=holdout_results,
        trial_rows=rows,
        holdout_spent=holdout_verdict is not None,
        h1_rows_replayed=h1_rows_replayed,
    )


def _spend_the_holdout(
    validator: Validator,
    config: ValidationConfig,
    record: HypothesisRecord,
    *,
    store: SessionStore,
    window: DataWindow,
    arms: tuple[ClockSplitShortStraddle, ClockSplitShortStraddle],
) -> tuple[tuple[BacktestResult, ...], Verdict]:
    """Read the sealed months. Reached only from a PASSED in-sample verdict.

    ``grade_holdout`` writes its touch row BEFORE it grades, so a grading that raises
    leaves the months read and the log saying so. The holdout is one-shot in the strongest
    sense — a failed grading destroys it as surely as a successful one — which is why this
    is reached from one branch only.
    """
    candidate_arm, benchmark_arm = arms
    with open_session(config.trial_log_path) as session:
        candidate_result = _backtest(
            session,
            record,
            store=store,
            window=window,
            underlying=config.underlying,
            strategy=candidate_arm,
            notes="H26 holdout CANDIDATE. The months nothing read until the verdict settled.",
        )
        benchmark_result = _backtest(
            session,
            record,
            store=store,
            window=window,
            underlying=config.underlying,
            strategy=benchmark_arm,
            notes="H26 holdout BENCHMARK, the trading-time control over the same months.",
        )
        candidate = evidence_from_result(
            candidate_result,
            session=session,
            hypothesis_id=record.id,
            label="H26 gap-held short straddle (holdout)",
        )
        benchmark = evidence_from_result(
            benchmark_result,
            session=session,
            hypothesis_id=record.id,
            label="H26 intraday short straddle (holdout benchmark)",
        )
    verdict = validator.grade_holdout(candidate, benchmark=benchmark, hypothesis=record)
    return (candidate_result, benchmark_result), verdict


def _trial_row(row: Any) -> dict[str, Any]:
    """One log row, exported in full.

    ``code_sha``, ``code_dirty`` and ``error`` are included, which H1's exporter omitted —
    the omission is why H1's replayed row can never be provenance-faithful. Fixing it here
    means H26's export can actually reconstruct what H1's could not.
    """
    return {
        "trial_id": row.trial_id,
        "hypothesis_id": row.hypothesis_id,
        "created_at": row.created_at.isoformat(),
        "data_window": str(row.data_window),
        "params": dict(row.params),
        "metrics": dict(row.metrics),
        "outcome": str(row.outcome),
        "error": row.error,
        "code_sha": row.code_version.sha,
        "code_dirty": row.code_version.dirty,
        "notes": row.notes,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(REPO_CONFIG_PATH))
    parser.add_argument("--json-out", default=None, help="write the full decision payload here")
    parser.add_argument("--trial-log-out", default=None, help="write the trial log export here")
    arguments = parser.parse_args()

    run = run_h26_decision(arguments.config)
    print(run.decision.summary())
    print()
    print(f"family trial count at decision: {run.trial_count}")
    print(f"H1 rows replayed into the log:  {run.h1_rows_replayed}")
    print(f"holdout spent: {run.holdout_spent}")
    if arguments.json_out:
        Path(arguments.json_out).write_text(
            json.dumps(run.as_dict(), indent=2, sort_keys=True, default=str) + "\n",
            encoding="utf-8",
        )
    if arguments.trial_log_out:
        Path(arguments.trial_log_out).write_text(
            json.dumps(list(run.trial_rows), indent=2, sort_keys=True, default=str) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
