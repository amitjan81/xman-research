"""The alpha framework's E2E: the CLI, the real corpus, and a sheet on disk.

Every layer the pull request touches runs here — argument parsing, the session store
reading captured parquet, the feature layer, the library reading the H1 decision record,
the ranker, the rationale and the JSON writer — with nothing mocked. It skips cleanly when
the corpus is absent so the suite still runs on a machine without it, and everything it
reads is read-only.

**Both dates are inside the in-sample window.** ``research/h1/decision.json`` seals
2026-05-01 onward as a holdout, and a scan reads a hundred and forty sessions of trailing
history, so an as-of date after 30 April would put holdout sessions into a feature window.
The window here ends comfortably before it.

**Two dates, because they exercise opposite branches.** 28 April 2026 is an expiry Tuesday:
the front contract dies that evening, the template will not open a position it cannot hold,
and the sheet must say so in words rather than being empty and mute. 24 April 2026 is the
Friday before it, where the same template does fire and the whole rationale has to be
present and populated.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path

import pytest

from xman_research.alpha.cli import main
from xman_research.session_store import DEFAULT_CORPUS_ROOT

CORPUS_ROOT = Path(os.environ.get("XMAN_RESEARCH_CORPUS_ROOT") or DEFAULT_CORPUS_ROOT)
UNDERLYING = "NIFTY"
#: Anchored to the repository, not to the working directory: a test that only passes
#: when pytest happens to be invoked from the repo root is a test with a hidden
#: precondition.
DECISION_RECORD = Path(__file__).resolve().parents[1] / "research" / "h1" / "decision.json"

#: A Friday: the front weekly contract expires the following Tuesday, far enough out for a
#: one-session hold to be opened and closed inside its life.
FIRES = dt.date(2026, 4, 24)

#: The expiry Tuesday itself.
EXPIRY_SESSION = dt.date(2026, 4, 28)

#: The regime tercile's default is a hundred and twenty sessions and each one is a parquet
#: read. Forty still cuts a meaningful tercile and keeps this test to a few seconds; the
#: length is on the sheet, so a reader can see which window the tag describes.
REGIME_LOOKBACK = 40

pytestmark = pytest.mark.skipif(
    not (CORPUS_ROOT / UNDERLYING).is_dir(),
    reason=f"no captured corpus at {CORPUS_ROOT / UNDERLYING}",
)


@pytest.fixture
def seeded_library(tmp_path: Path) -> Path:
    """The H1 decision record, filed and admitted, in a library of this test's own."""
    path = tmp_path / "templates.json"
    exit_code = main(
        [
            "--library",
            str(path),
            "library",
            "seed-from-decision",
            "--template",
            "short_atm_straddle_hold_n",
            "--decision",
            str(DECISION_RECORD),
            "--admit",
            "--by",
            "alpha-framework E2E",
            "--reason",
            "the anchor hypothesis's evidence, so the ranker has something to rank",
        ]
    )
    assert exit_code == 0
    return path


def _scan(library: Path, out: Path, as_of: dt.date) -> int:
    return main(
        [
            "--library",
            str(library),
            "scan",
            "--as-of",
            as_of.isoformat(),
            "--universe",
            UNDERLYING,
            "--top",
            "10",
            "--regime-lookback",
            str(REGIME_LOOKBACK),
            "--out",
            str(out),
        ]
    )


def test_seeding_the_library_reads_the_real_decision_record(seeded_library: Path) -> None:
    payload = json.loads(seeded_library.read_text())
    entry = payload["entries"][0]
    assert entry["template_id"] == "short_atm_straddle_hold_n"
    assert entry["status"] == "admitted"
    assert entry["decision_outcome"] == "fails_threshold"
    assert entry["evidence"]["n_observations"] == 79
    assert entry["evidence"]["gate_status"] == "failed"
    assert entry["trial_ids"]


def test_the_cli_scans_the_real_corpus_and_writes_a_sheet_with_a_full_rationale(
    seeded_library: Path, tmp_path: Path
) -> None:
    out = tmp_path / "ideas.json"
    assert _scan(seeded_library, out, FIRES) == 0

    sheet = json.loads(out.read_text())
    assert sheet["as_of"] == FIRES.isoformat()
    assert sheet["universe"] == [UNDERLYING]
    assert sheet["schema_version"] >= 1
    # The H1 record failed its gate, so a sheet built on it must say so on its face.
    assert sheet["rests_on_unpassed_evidence"] is True

    assert sheet["ideas"] or sheet["no_ideas_reason"]
    assert len(sheet["ideas"]) == 1
    idea = sheet["ideas"][0]
    assert idea["rank"] == 1
    assert idea["template_id"] == "short_atm_straddle_hold_n"
    assert idea["score"] > 0
    assert idea["margin_total"] > 0
    assert idea["granted_lots"] >= 1

    rationale = idea["rationale"]
    assert rationale["thesis"]
    assert rationale["trigger"]["fired"] is True
    assert rationale["evidence"]["annualised_sharpe"] is not None
    assert rationale["evidence"]["cost_stamps"]
    assert rationale["evidence_source"] == str(DECISION_RECORD)
    assert rationale["invalidators"]
    assert rationale["provenance"]

    trade = rationale["trade"]
    assert len(trade["legs"]) == 2
    assert {leg["option_type"] for leg in trade["legs"]} == {"CE", "PE"}
    assert all(leg["side"] == "sell" for leg in trade["legs"])
    assert all(leg["trading_symbol"].startswith(UNDERLYING) for leg in trade["legs"])
    assert trade["margin"]["total"] > 0
    assert trade["hold_sessions"] == 1
    assert trade["entry_rule"] and trade["exit_rule"]


def test_an_expiry_session_produces_an_explicit_reason_rather_than_a_mute_empty_sheet(
    seeded_library: Path, tmp_path: Path
) -> None:
    out = tmp_path / "expiry-day.json"
    assert _scan(seeded_library, out, EXPIRY_SESSION) == 0

    sheet = json.loads(out.read_text())
    assert sheet["ideas"] == []
    assert sheet["no_ideas_reason"]
    assert sheet["skipped"]
    assert sheet["skipped"][0]["reason"] == "no_entry_at_decision_minute"


def test_each_sheet_is_dated_by_the_session_it_read(seeded_library: Path, tmp_path: Path) -> None:
    """Two scans four sessions apart file their results under their own dates.

    This is a provenance check and nothing more. The look-ahead guarantee is held where it
    can actually be tested — ``test_alpha_features.py`` builds one frame from a corpus that
    stops at the as-of session and another from a corpus that continues past it with a
    wildly different price, and requires them to be equal.
    """
    early, late = tmp_path / "early.json", tmp_path / "late.json"
    assert _scan(seeded_library, early, FIRES) == 0
    assert _scan(seeded_library, late, EXPIRY_SESSION) == 0
    assert json.loads(early.read_text())["as_of"] == FIRES.isoformat()
    assert json.loads(late.read_text())["as_of"] == EXPIRY_SESSION.isoformat()


def test_a_scan_of_a_date_the_corpus_has_no_session_for_is_refused(
    seeded_library: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # 25 April 2026 is a Saturday.
    assert _scan(seeded_library, tmp_path / "never.json", dt.date(2026, 4, 25)) == 2
    assert "refused" in capsys.readouterr().err
    assert not (tmp_path / "never.json").exists()


def test_the_cli_refuses_to_admit_against_a_decision_record_that_is_not_there(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(
        [
            "--library",
            str(tmp_path / "templates.json"),
            "library",
            "admit",
            "--template",
            "short_atm_straddle_hold_n",
            "--decision",
            str(tmp_path / "absent.json"),
            "--by",
            "tester",
            "--reason",
            "there is no record to admit against",
        ]
    )
    assert exit_code == 2
    assert "no decision record at" in capsys.readouterr().err


def test_library_list_reports_every_registered_template_and_its_status(
    seeded_library: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--library", str(seeded_library), "library", "list"]) == 0
    out = capsys.readouterr().out
    assert "short_atm_straddle_hold_n: admitted" in out
    assert "short_atm_straddle_iv_rv: unfiled" in out


def test_demoting_through_the_cli_stops_the_ranker_proposing_the_template(
    seeded_library: Path, tmp_path: Path
) -> None:
    assert (
        main(
            [
                "--library",
                str(seeded_library),
                "library",
                "demote",
                "--template",
                "short_atm_straddle_hold_n",
                "--by",
                "tester",
                "--reason",
                "checking a demotion reaches the scan",
            ]
        )
        == 0
    )
    out = tmp_path / "after-demotion.json"
    assert _scan(seeded_library, out, FIRES) == 0
    sheet = json.loads(out.read_text())
    assert sheet["ideas"] == []
    assert "admits no templates" in sheet["no_ideas_reason"]
