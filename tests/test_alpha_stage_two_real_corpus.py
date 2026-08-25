"""The whole loop on the real corpus: screen, seed, gate, admit, scan.

Every layer runs with nothing mocked — the TOML spec reader, the session store reading
captured parquet, the feature layer, the backtest engine, the trial log, the validation
gate, the decision record writer, the library's admission guard, and the nightly ranker.
It skips cleanly when the corpus is absent, and everything it reads from the corpus is
read-only.

**The screened window ends 2026-03-31 and the holdout ends 2026-04-30.**
``research/h1/decision.json`` seals 2026-05-01 onward, and a screen reads trailing history
behind every session it runs, so neither window comes near the seal.

**The property this test exists to hold is the parameter point.** The screen runs at a
three-session hold; the gate re-runs that same point and writes it onto the decision record;
the admission carries it and the guard checks it against what the record measured; the scan
builds the template *there* rather than at its declared default. A break anywhere in that
chain shows up here as a hold-1 trade wearing hold-3 numbers.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path

import pytest

from xman_research.alpha.cli import main
from xman_research.alpha.library import AdmissionStatus, TemplateLibrary
from xman_research.alpha.screen import load_screen_sheet
from xman_research.alpha.templates import default_registry, parameter_key
from xman_research.session_store import DEFAULT_CORPUS_ROOT

CORPUS_ROOT = Path(os.environ.get("XMAN_RESEARCH_CORPUS_ROOT") or DEFAULT_CORPUS_ROOT)
UNDERLYING = "NIFTY"
HOLD = 3
SCAN_AS_OF = "2026-04-24"

pytestmark = pytest.mark.skipif(
    not (CORPUS_ROOT / UNDERLYING).is_dir(),
    reason=f"no captured corpus at {CORPUS_ROOT / UNDERLYING}",
)

#: The screen. Two candidates at one hold, against the unconditional straddle at the same
#: hold — small on purpose: the point is that every layer connects over real data.
#:
#: ``[hypothesis.thresholds]`` names the four metrics the stage-two gate grades, because a
#: :class:`~xman_research.hypothesis.HypothesisRecord` is immutable and
#: ``DecisionGate.check_binding`` requires the gate file to carry every numeric threshold it
#: registered. A screen whose hypothesis registered a number outside the gate's measured
#: vocabulary could never be gated at all. The screen's own advancement rule is recorded as
#: text beside them, which is what keeps it out of that reconciliation.
SPEC = """
underlying = "NIFTY"
trial_log = "__TRIAL_LOG__"
decision_time = "14:50"
gaps_reason = \"\"\"
Screening stage 1 over 2025-10-01..2026-03-31, and the stage-two gate over the same window.
The range is taken as the corpus holds it: a session absent from the population is absent
from every instance equally, so a hole cannot move the ordering, and the graded run is the
same population the screen ranked.
\"\"\"

[window]
start = 2025-10-01
end = 2026-03-31

[hypothesis]
name = "Screening: does a conditioner or a wider structure beat the hold-3 straddle"
mechanism = \"\"\"
Indian index-option implied variance sits above subsequently realised variance because index
hedgers and structured-product desks buy convexity with price insensitivity and somebody must
warehouse it. Whether that premium is best collected at the money, across a band of strikes,
or only on sessions where implied sits far above realised, is an empirical question about
this corpus rather than about the mechanism.
\"\"\"
null_hypothesis = \"\"\"
No screened structure or conditioner produces a positive spread over the unconditional short
at-the-money straddle held for the same number of sessions.
\"\"\"

[hypothesis.thresholds]
deflated_sharpe = 0.90
cost_breakeven_multiple = 2.0
max_drawdown = 0.10
risk_matched_increment = 0.0
alpha_to_advance = "0.5 annualised Sharpe of the spread, applied by the reader"

[benchmark]
template = "short_atm_straddle_hold_n"
grid = {hold_sessions = [3]}

[[candidates]]
template = "short_atm_straddle_iv_rv"
grid = {hold_sessions = [3], iv_rv_threshold = [0.03]}

[[candidates]]
template = "short_atm_strangle_hold_n"
grid = {hold_sessions = [3], atr_multiple = [0.5]}
"""

#: The stage-two gate. The thresholds are ``research/m1/gate.toml``'s, transcribed rather
#: than imported: a gate is a file recorded before the run it grades, and one that reached
#: into another decision's file would make two decisions share a threshold that could then
#: be edited for either.
GATE = """
hypothesis_id = "__HYPOTHESIS_ID__"
recorded_at = 2026-04-01T00:00:00Z

[thresholds]
deflated_sharpe = {{ at_least = 0.90 }}
cost_breakeven_multiple = {{ at_least = 2.0 }}
max_drawdown = {{ at_most = 0.10 }}
risk_matched_increment = {{ at_least = 0.0 }}

[holdout_thresholds]
deflated_sharpe = {{ at_least = 0.50 }}
"""


def test_the_whole_loop_screens_gates_admits_and_ranks_at_the_screened_point(
    tmp_path: Path,
) -> None:
    log_path = tmp_path / "screen.db"
    spec_path = tmp_path / "screen.toml"
    spec_path.write_text(SPEC.replace("__TRIAL_LOG__", log_path.as_posix()))
    sheet_path = tmp_path / "sheet.json"
    library_path = tmp_path / "library.json"
    corpus = ["--corpus-root", str(CORPUS_ROOT)]

    # ---------------------------------------------------------------- stage one
    assert main(["screen", "--spec", str(spec_path), "--out", str(sheet_path), *corpus]) == 0
    sheet = load_screen_sheet(sheet_path)
    assert sheet.n_trials_logged == 3
    top = sheet.instances[0]
    assert top.measured, f"rank 1 is unmeasurable: {top.reason}"
    assert top.instance.hold_sessions == HOLD
    template = default_registry().get(top.instance.template_id)
    point = template.resolve(top.instance.params)
    print(f"\nsheet rank 1: {top.instance.instance_id} alpha={top.alpha} n={top.n_observations}")

    # ---------------------------------------------------------------- the candidate handoff
    assert (
        main(
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
        == 0
    )
    seeded = TemplateLibrary.load(library_path).entries()[-1]
    assert seeded.status is AdmissionStatus.CANDIDATE
    assert seeded.parameter_key == parameter_key(point)
    assert seeded.evidence.hold_sessions == HOLD

    # ---------------------------------------------------------------- stage two
    gate_path = tmp_path / "gate.toml"
    gate_path.write_text(
        GATE.format().replace("__HYPOTHESIS_ID__", sheet.provenance["hypothesis_id"])
    )
    out_dir = tmp_path / "decision"
    assert (
        main(
            [
                "gate",
                "--sheet",
                str(sheet_path),
                "--rank",
                "1",
                "--gate",
                str(gate_path),
                "--out",
                str(out_dir),
                "--holdout-end",
                "2026-04-30",
                *corpus,
            ]
        )
        == 0
    )
    record = json.loads((out_dir / "decision.json").read_text())
    metrics = record["in_sample"]["metrics"]
    print(
        f"gate verdict: {record['outcome']} gate_status={metrics['gate_status']} "
        f"deflated_sharpe={metrics['deflated_sharpe']} n={metrics['sample_length']} "
        f"family_trials={record['trial_log']['family_trial_count_at_decision']}"
    )

    # The record is in the H1 shape, and it names the point it measured.
    assert record["hypothesis_id"] == sheet.provenance["hypothesis_id"]
    assert record["runs"]["in_sample"]["template_parameters"] == pytest.approx(point)
    assert record["runs"]["in_sample"]["strategy_parameters"]["hold_sessions"] == HOLD
    assert record["holdout_spent"] is False, "a failed in-sample verdict must leave it sealed"

    # **Deflation counted the screen.** The family the gate deflated against holds the
    # screen's trials as well as this run's, which is the whole reason stage two reuses the
    # screen's hypothesis record rather than minting one of its own.
    counted = record["trial_log"]["family_trial_count_at_decision"]
    assert counted > sheet.n_trials_logged
    assert counted == len(record["trial_log"]["rows"])
    assert set(sheet.trial_ids) <= {row["trial_id"] for row in record["trial_log"]["rows"]}

    # ---------------------------------------------------------------- the admission
    assert (
        main(
            [
                "--library",
                str(library_path),
                "library",
                "admit",
                "--template",
                top.instance.template_id,
                "--decision",
                str(out_dir / "decision.json"),
                "--by",
                "e2e",
                "--reason",
                "closing the loop end to end on the real corpus",
                "--override-reason",
                (
                    f"E2E: {record['outcome']} at n={metrics['sample_length']} with a "
                    f"deflated Sharpe of {metrics['deflated_sharpe']}"
                ),
            ]
        )
        == 0
    )
    admission = TemplateLibrary.load(library_path).admitted()[0]
    assert admission.parameter_key == parameter_key(point)
    assert admission.evidence.parameters == pytest.approx(point)
    assert admission.evidence.hold_sessions == HOLD
    assert admission.override_reason

    # ---------------------------------------------------------------- the nightly scan
    ideas_path = tmp_path / "ideas.json"
    assert (
        main(
            [
                "--library",
                str(library_path),
                "scan",
                "--as-of",
                SCAN_AS_OF,
                "--universe",
                UNDERLYING,
                "--out",
                str(ideas_path),
                "--decision-time",
                "14:50",
                *corpus,
            ]
        )
        == 0
    )
    ideas = json.loads(ideas_path.read_text())
    considered = [*ideas["ideas"], *ideas["skipped"]]
    # The scan considered exactly the admitted point, whatever it decided about it. An idea
    # or a skip carrying the template's declared default instead would be the failure this
    # whole chain exists to prevent.
    assert considered, ideas["no_ideas_reason"]
    assert all(row["parameter_key"] == parameter_key(point) for row in considered)

    if ideas["ideas"]:
        idea = ideas["ideas"][0]
        assert idea["rationale"]["trade"]["hold_sessions"] == HOLD
        assert f"{HOLD} session(s)" in idea["rationale"]["trade"]["exit_rule"]
        assert idea["rationale"]["evidence_source"] == str(out_dir / "decision.json")
        assert idea["rationale"]["parameters"] == pytest.approx(point)
        assert ideas["rests_on_unpassed_evidence"] is True
        print(f"idea: {idea['template_id']}[{idea['parameter_key']}] score={idea['score']}")
    else:
        print(f"no idea on {SCAN_AS_OF}: {ideas['skipped'][0]['reason']}")


def test_the_gate_refuses_a_rank_the_sheet_does_not_rank(tmp_path: Path) -> None:
    """A refusal is the interesting outcome of this tool and carries its own exit code."""
    log_path = tmp_path / "screen.db"
    spec_path = tmp_path / "screen.toml"
    spec_path.write_text(SPEC.replace("__TRIAL_LOG__", log_path.as_posix()))
    sheet_path = tmp_path / "sheet.json"
    assert (
        main(
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
        == 0
    )
    gate_path = tmp_path / "gate.toml"
    sheet = load_screen_sheet(sheet_path)
    gate_path.write_text(
        GATE.format().replace("__HYPOTHESIS_ID__", sheet.provenance["hypothesis_id"])
    )
    assert (
        main(
            [
                "gate",
                "--sheet",
                str(sheet_path),
                "--rank",
                "99",
                "--gate",
                str(gate_path),
                "--out",
                str(tmp_path / "nowhere"),
                "--holdout-end",
                "2026-04-30",
                "--corpus-root",
                str(CORPUS_ROOT),
            ]
        )
        == 2
    )
    assert not (tmp_path / "nowhere" / "decision.json").exists()


def test_the_holdout_may_not_overlap_the_screened_window(tmp_path: Path) -> None:
    """The graded months and the sealed ones abut; an overlap is refused before any run."""
    from xman_research.alpha.gate import StageTwoGateError, run_stage_two_gate

    log_path = tmp_path / "screen.db"
    spec_path = tmp_path / "screen.toml"
    spec_path.write_text(SPEC.replace("__TRIAL_LOG__", log_path.as_posix()))
    sheet_path = tmp_path / "sheet.json"
    assert (
        main(
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
        == 0
    )
    with pytest.raises(StageTwoGateError, match="would not be unseen"):
        run_stage_two_gate(
            sheet_path=sheet_path,
            gate_path=tmp_path / "absent.toml",
            out_dir=tmp_path / "nowhere",
            holdout_first=dt.date(2026, 3, 1),
            holdout_end=dt.date(2026, 4, 30),
        )
