"""Put H1's trial back in the log, so H26's family count is read rather than asserted.

**Why this module has to exist.** H26 is an amendment of H1, so the deflated Sharpe must
deflate against a family count that includes H1's trial. That count is read from the
canonical trial log — and H1's canonical log does not exist. ``*.db`` is gitignored
repo-wide and the worktree that held it is gone. ``research/h1/DECISION.md`` names
``research/h1/trial_log_export.json`` as the committed substitute, and that file was never
committed either. The only surviving copy of H1's trial row is inside
``research/h1/decision.json``.

The alternative to this module is to type "N is 3" somewhere, which is the one number the
researcher must never supply. So the row is replayed into the log and the count is read
back out of it, exactly as it would have been.

**What the hash check does and does not prove.** :func:`replay_h1_family` recomputes H1's
record from source and refuses unless it content-addresses to the id in the export. That
validates the *hypothesis record* — it proves the text of H1 has not drifted. It proves
nothing about the trial row, whose fidelity rests entirely on ``decision.json``'s say-so.

**Three fields are unrecoverable and the replayed row is wrong about all three.**
``created_at`` is stamped by the log's own clock and ``code_sha``/``code_dirty`` by its
code-version provider, neither of which ``append_trial`` lets a caller override — so the
row carries H26-era provenance for an H1-era run. And the H1 export never carried
``code_sha`` or ``error`` at all, so full-fidelity reconstruction is impossible even in
principle. The replayed row is a **count-preserving stub**, not H1's trial; every one of
those defects is written into the row's own ``notes`` so it cannot be mistaken for the
real thing downstream. ``research/h1/decision.json`` remains the authoritative record.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

from xman_research import DataWindow, HypothesisRecord, TrialLog
from xman_research.h1.hypothesis import h1_record

__all__ = ["H1_DECISION_PATH", "H1RecordDriftError", "replay_h1_family"]

H1_DECISION_PATH = Path(__file__).resolve().parents[3] / "research" / "h1" / "decision.json"


class H1RecordDriftError(RuntimeError):
    """H1's record no longer content-addresses to the id its own decision recorded.

    Raised rather than warned, and the run must stop. Proceeding would log H26 against a
    family that is not H1's, silently reducing the trial count — the flattering direction,
    and exactly the failure the family link exists to prevent.
    """


def _payload(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def replay_h1_family(
    log: TrialLog, *, decision_path: Path = H1_DECISION_PATH
) -> tuple[HypothesisRecord, int]:
    """Register H1 and re-append its logged trials. Returns the record and rows added.

    Idempotent: a trial id already present is left alone, so re-running a decision does not
    inflate the family with duplicate H1 rows.
    """
    payload = _payload(decision_path)
    recorded_id = str(payload["hypothesis_id"])
    record = h1_record()
    if record.id != recorded_id:
        raise H1RecordDriftError(
            f"h1_record() content-addresses to {record.id}, but "
            f"{decision_path} recorded {recorded_id}. H1's text has drifted, so the "
            "family H26 would amend is not the family H1 was decided under. Stop: "
            "running anyway would deflate against a smaller trial count, which is the "
            "flattering direction."
        )
    log.register_hypothesis(record)

    existing = {row.trial_id for row in log.trials(record.id)}
    added = 0
    for row in payload["trial_log"]["rows"]:
        trial_id = str(row["trial_id"])
        if trial_id in existing:
            continue
        start, end = (dt.date.fromisoformat(part) for part in str(row["data_window"]).split(".."))
        log.append_trial(
            hypothesis_id=record.id,
            trial_id=trial_id,
            params=dict(row.get("params") or {}),
            data_window=DataWindow(start, end),
            metrics=dict(row.get("metrics") or {}),
            outcome=str(row.get("outcome") or "completed"),
            notes=(
                f"REPLAYED from {decision_path.name} because H1's canonical log was lost "
                "(gitignored, worktree gone) and its cited trial_log_export.json was never "
                "committed. This row preserves H1's trial COUNT and identity, not its "
                f"provenance: original created_at was {row.get('created_at')!r}; this "
                "row's created_at, code_sha and code_dirty are stamped by the replaying "
                "process and are wrong for H1; the export carried no code_sha or error "
                "field to restore. research/h1/decision.json is authoritative. Original "
                f"notes: {row.get('notes')!r}"
            ),
        )
        added += 1
    return record, added
