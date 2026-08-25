"""The screening harness's E2E: the CLI, a spec on disk, the real corpus, a sheet, a seed.

Every layer the screening work touches runs here with nothing mocked — argument parsing,
the TOML spec reader, the session store reading captured parquet, the feature layer, the
backtest engine, the trial log, the statistics layer, the JSON writer, and the library
handoff that files the top-ranked instance as a candidate. It skips cleanly when the corpus
is absent, and everything it reads from the corpus is read-only.

**The window ends on 2026-03-31, well inside the in-sample period.**
``research/h1/decision.json`` seals 2026-05-01 onward as a holdout, and a screen reads
trailing history behind every session it runs, so a window reaching later would pull sealed
sessions into a feature average. This one does not come near it.

**The trial log is a temporary file, and that is the point of the last assertion.** A screen
appends one trial per instance, and the sheet's own count must equal what the log holds —
the property a stage-two gate depends on when it deflates against the family.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from xman_research.alpha.cli import main
from xman_research.alpha.library import AdmissionStatus, TemplateLibrary
from xman_research.alpha.screen import load_screen_sheet
from xman_research.evaluation import open_session
from xman_research.session_store import DEFAULT_CORPUS_ROOT

CORPUS_ROOT = Path(os.environ.get("XMAN_RESEARCH_CORPUS_ROOT") or DEFAULT_CORPUS_ROOT)
UNDERLYING = "NIFTY"

pytestmark = pytest.mark.skipif(
    not (CORPUS_ROOT / UNDERLYING).is_dir(),
    reason=f"no captured corpus at {CORPUS_ROOT / UNDERLYING}",
)

#: A small screen: one benchmark and three candidates. Deliberately small — the point of
#: this test is that every layer connects over real data, and a wide grid would buy no
#: additional coverage at several times the wall-clock cost.
SPEC = """
underlying = "NIFTY"
trial_log = "__TRIAL_LOG__"
decision_time = "14:50"
gaps_reason = \"\"\"
Screening stage 1 over 2025-10-01..2026-03-31. The range is taken as the corpus holds it: a
screen ranks instances against each other over one identical population of sessions, and a
session absent from that population is absent from every instance equally, so a hole cannot
move the ordering. It would move a stage-two verdict, which is why the gate reads its own
window and not this one.
\"\"\"

[window]
start = 2025-10-01
end = 2026-03-31

[hypothesis]
name = "Screening: does a wider short-variance structure or a conditioner beat the straddle"
mechanism = \"\"\"
Indian index-option implied variance sits above subsequently realised variance because
index hedgers and structured-product desks buy convexity with price insensitivity and
somebody must warehouse it. Whether that premium is best collected at the money, across a
band of strikes, or only on sessions where implied sits far above realised, is an empirical
question about this corpus rather than about the mechanism.
\"\"\"
null_hypothesis = \"\"\"
No screened structure or conditioner produces a positive spread over the unconditional
short at-the-money straddle held for the same number of sessions.
\"\"\"
thresholds = {alpha_to_advance = 0.5}

[benchmark]
template = "short_atm_straddle_hold_n"
grid = {hold_sessions = [3]}

[[candidates]]
template = "short_atm_strangle_hold_n"
grid = {hold_sessions = [3], atr_multiple = [0.5, 1.0]}

[[candidates]]
template = "short_atm_straddle_iv_rv"
grid = {hold_sessions = [3], iv_rv_threshold = [0.03]}
"""


@pytest.fixture
def spec_path(tmp_path: Path) -> Path:
    path = tmp_path / "screen.toml"
    path.write_text(SPEC.replace("__TRIAL_LOG__", (tmp_path / "screen.db").as_posix()))
    return path


def test_the_cli_screens_the_real_corpus_ranks_it_and_seeds_a_candidate(
    spec_path: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sheet_path = tmp_path / "sheet.json"
    exit_code = main(
        [
            "screen",
            "--spec",
            str(spec_path),
            "--out",
            str(sheet_path),
            "--corpus-root",
            str(CORPUS_ROOT),
        ]
    )
    assert exit_code == 0
    printed = capsys.readouterr().out
    assert str(sheet_path) in printed

    document = json.loads(sheet_path.read_text())
    sheet = load_screen_sheet(sheet_path)

    # Three candidate instances plus the benchmark, every one of them a logged trial.
    assert len(sheet.instances) == 3
    assert sheet.n_trials_logged == 4
    assert len(set(sheet.trial_ids)) == 4
    research = open_session(tmp_path / "screen.db")
    try:
        rows = research.family_trials(document["provenance"]["hypothesis_id"])
    finally:
        research.close()
    assert {row.trial_id for row in rows} == set(sheet.trial_ids)

    # Every instance either measured a population or says in words why it did not.
    for row in (sheet.benchmark, *sheet.instances):
        assert (row.n_observations or 0) > 0 or row.reason, row.instance.instance_id
        assert row.instance.hold_sessions == 3

    # The ranking is by alpha descending, ties by the shallower drawdown, unmeasured last.
    measured = [row for row in sheet.instances if row.measured]
    assert measured, "no instance on the real corpus produced a measurable spread"
    assert [row.alpha for row in measured] == sorted((row.alpha for row in measured), reverse=True)
    assert all(not row.measured for row in sheet.instances[len(measured) :])

    # The handoff: the top-ranked instance becomes a CANDIDATE and never an admission.
    library_path = tmp_path / "library.json"
    seed_code = main(
        [
            "--library",
            str(library_path),
            "library",
            "seed-from-screen",
            "--sheet",
            str(sheet_path),
            "--rank",
            "1",
            "--by",
            "e2e",
            "--reason",
            "the screen's top-ranked instance",
        ]
    )
    assert seed_code == 0
    library = TemplateLibrary.load(library_path)
    entry = library.entries()[-1]
    assert entry.status is AdmissionStatus.CANDIDATE
    assert library.admitted() == ()
    assert entry.decision_path == str(sheet_path)
    assert entry.evidence.gate_status is None
    assert entry.template_id == sheet.instances[0].instance.template_id


def test_the_cli_refuses_a_spec_that_names_no_candidates(tmp_path: Path) -> None:
    """A refusal is the interesting outcome of this tool and carries its own exit code."""
    path = tmp_path / "empty.toml"
    path.write_text(
        SPEC.replace("__TRIAL_LOG__", (tmp_path / "unused.db").as_posix()).split("[[candidates]]")[
            0
        ]
    )
    assert main(["screen", "--spec", str(path), "--out", str(tmp_path / "out.json")]) == 2
    assert not (tmp_path / "out.json").exists()
