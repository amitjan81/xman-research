"""Run M1 and M2 against the backfilled corpus. Thin, because the runners already exist.

``xman_research.h1.run_decision`` and ``xman_research.h26.run_decision`` already take
``config_path``, ``hypothesis``, ``in_sample_start`` and ``holdout_end``, so M1 and M2 are
those loops pointed at new records and new gate files. Nothing is forked. The only thing
this module adds that the runners did not already have is ``gap_reason``, and that was
added to the runners themselves rather than copied around them — the reason for accepting
a holey window is a research decision that belongs to the caller, and the runner has no
way to know it.

**Order is load-bearing and is pre-registered.** M1 runs first and appends one trial; M2
runs second and appends two. Both bars were calibrated against those counts. Running them
in the other order would grade each against a bar sized for the other.

Run: ``uv run python -m xman_research.models.run_models --model m1``
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Any

from xman_research import open_session
from xman_research.adapter import evidence_from_result
from xman_research.h1.run_decision import run_h1_decision
from xman_research.h26.h1_replay import replay_h1_family
from xman_research.h26.run_decision import run_h26_decision
from xman_research.models.epochs import epoch_breakdown
from xman_research.models.m1 import m1_record
from xman_research.models.m2 import m2_record
from xman_research.validation import ValidationConfig

__all__ = ["GAP_REASON", "IN_SAMPLE_START", "M1_HOLDOUT_END", "run_model"]

_REPO = Path(__file__).resolve().parents[3]

#: M1 §13's securities-transaction-tax floor. Before this date the STT rates are not in
#: force and the cost stack raises rather than guessing, so no session before it is
#: costable at all. Not a preference, and not adjustable to taste.
IN_SAMPLE_START = dt.date(2024, 10, 1)

#: M1 §13's ceiling: NSE's Closing Auction Session settlement rule, carried
#: implemented=false and refusing to settle. Used for BOTH models so the two are graded
#: over the identical population of sessions — see research/m2/gate.toml.
M1_HOLDOUT_END = dt.date(2026, 8, 3)

#: The gap policy, decided and written down rather than generated. It names all three
#: missing dates, because a reason that says "three sessions are missing" is not a reason.
GAP_REASON = (
    "M1/M2 decision run over 2024-10-01..2026-04-30. Three sessions the NSE calendar "
    "expects are absent from the corpus: 2024-11-20, 2025-04-30 and 2025-05-08. The "
    "decision is taken over the 385 sessions that exist. The window is NOT narrowed to "
    "avoid them: narrowing to a hole-free sub-range would either fragment one "
    "pre-registered trial into three, or discard roughly 140 sessions including the "
    "2024-11-20 regime change the per-epoch analysis exists to look at. "
    "2024-11-20 is itself an epoch boundary (SEBI weekly-expiry cull, contract size "
    "increase, expiry-day ELM), and losing it costs little for a reason worth stating: "
    "it was a Wednesday, and pre-Tuesday-change expiries fell on Thursdays, so no "
    "settlement is lost. The boundary merely lacks its first day's marks, which biases "
    "neither side of it. 2025-04-30 and 2025-05-08 are interior single-session holes in "
    "the intraday_position_limits_2025 regime with no structural significance."
)


def _epochs_payload(
    result: Any, *, config: ValidationConfig, hypothesis_id: str, label: str
) -> list[dict[str, object]]:
    """The ungraded per-epoch slice of the run's own return series."""
    with open_session(config.trial_log_path) as session:
        evidence = evidence_from_result(
            result, session=session, hypothesis_id=hypothesis_id, label=label
        )
    return [slice_.as_dict() for slice_ in epoch_breakdown(evidence.returns)]


def run_model(model: str, *, json_out: Path | None = None) -> dict[str, Any]:
    """Run one model end to end and return its full decision payload."""
    if model == "m1":
        config_path = _REPO / "research" / "m1" / "validation.toml"
        record = m1_record()
        # SEED THE FAMILY FIRST. M1 amends H1, and the log refuses to register an
        # amendment whose parent it has never seen — correctly, because a count taken
        # before the parent exists is short by one, in the flattering direction. H26's
        # runner does this for the same reason; H1's does not, because H1 has no parent.
        # The replay is idempotent and is gated on H1's record still hashing to the id it
        # was decided under, so a drift in H1's text stops the run rather than quietly
        # deflating against a smaller family.
        with open_session(ValidationConfig.from_file(config_path).trial_log_path) as bootstrap:
            replay_h1_family(bootstrap.log)
        run = run_h1_decision(
            config_path,
            in_sample_start=IN_SAMPLE_START,
            holdout_end=M1_HOLDOUT_END,
            hypothesis=record,
            gap_reason=GAP_REASON,
        )
        primary = run.in_sample_result
        label = "M1 short ATM straddle (candidate)"
    elif model == "m2":
        config_path = _REPO / "research" / "m2" / "validation.toml"
        record = m2_record()
        run = run_h26_decision(
            config_path,
            in_sample_start=IN_SAMPLE_START,
            holdout_end=M1_HOLDOUT_END,
            hypothesis=record,
            gap_reason=GAP_REASON,
        )
        primary = run.candidate_result
        label = "M2 overnight arm (candidate)"
    else:
        raise ValueError(f"model must be 'm1' or 'm2', got {model!r}")

    payload = run.as_dict()
    config = ValidationConfig.from_file(config_path)
    payload["epoch_breakdown"] = {
        "status": (
            "DESCRIPTIVE, UNGRADED. Pre-registered in the gate file before it was "
            "computed. No threshold reads it and it cannot change the outcome."
        ),
        "slices": _epochs_payload(primary, config=config, hypothesis_id=record.id, label=label),
    }
    payload["gap_policy"] = GAP_REASON
    if json_out is not None:
        json_out.write_text(
            json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
        )
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, choices=("m1", "m2"))
    parser.add_argument("--json-out", default=None)
    arguments = parser.parse_args()
    payload = run_model(
        arguments.model, json_out=Path(arguments.json_out) if arguments.json_out else None
    )
    print(payload.get("summary") or json.dumps(payload["outcome"], default=str))
    print(
        f"family trial count at decision: {payload['trial_log']['family_trial_count_at_decision']}"
    )
    print(f"holdout spent: {payload['holdout_spent']}")


if __name__ == "__main__":
    main()
