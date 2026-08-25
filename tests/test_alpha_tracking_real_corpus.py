"""The tracking loop's E2E: the CLI, the real corpus, a sheet, a ledger, a report.

Every layer runs with nothing mocked — argument parsing, the session store reading captured
parquet, the feature layer, the ranker, the JSON the scan writes, the ledger's reader, the
settlement mark against real option prints, and the drift report. It skips cleanly when the
corpus is absent, and everything it reads from the corpus is read-only.

**Nothing dated 2026-05-01 or later is read.** ``research/h1/decision.json`` seals that date
onward as a holdout. The scan is dated 2026-04-24 and the settlement runs through 2026-04-30,
so the whole run sits inside the in-sample period; the assertion on the exit date is what
keeps it there if the hold length or the calendar ever changes underneath this test.

**The library is built in ``tmp_path``, not the repository's.** A test that admitted a
template into ``research/library/templates.json`` would leave a decision on disk that nobody
made, and the ledger it wrote would be committed alongside it.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
from pathlib import Path

import pytest

from xman_research.alpha.cli import main
from xman_research.alpha.library import TemplateLibrary
from xman_research.alpha.templates import default_registry
from xman_research.alpha.tracking import STATUS_SETTLED, IdeaLedger
from xman_research.session_store import DEFAULT_CORPUS_ROOT

CORPUS_ROOT = Path(os.environ.get("XMAN_RESEARCH_CORPUS_ROOT") or DEFAULT_CORPUS_ROOT)
UNDERLYING = "NIFTY"
TEMPLATE = "short_atm_straddle_hold_n"

AS_OF = "2026-04-24"
THROUGH = "2026-04-30"
HOLDOUT_FIRST = dt.date(2026, 5, 1)

pytestmark = pytest.mark.skipif(
    not (CORPUS_ROOT / UNDERLYING).is_dir(),
    reason=f"no captured corpus at {CORPUS_ROOT / UNDERLYING}",
)

DECISION_RECORD = Path(__file__).resolve().parents[1] / "research" / "h1" / "decision.json"

#: The anchor H1 record failed its gate, and admission on unpassed evidence demands a written
#: override. The ranker needs an ADMITTED template to propose anything, and this test is about
#: what happens to a proposal afterwards.
ADMIT_OVERRIDE = (
    "test fixture: the anchor H1 record failed its gate. This test exercises the tracking "
    "loop end to end, which requires the ranker to produce an idea to track."
)


@pytest.fixture
def library_path(tmp_path: Path) -> Path:
    library = TemplateLibrary(tmp_path / "templates.json")
    library.admit(
        override_reason=ADMIT_OVERRIDE,
        template=default_registry().get(TEMPLATE),
        decision_path=DECISION_RECORD,
        by="tester",
        reason="exercising the tracking loop end to end over the captured corpus",
    )
    return library.save()


def test_scan_record_settle_report_over_the_captured_corpus(
    tmp_path: Path, library_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sheet_path = tmp_path / "ideas.json"
    ledger_path = tmp_path / "ledger.json"
    corpus = ["--corpus-root", str(CORPUS_ROOT)]

    assert (
        main(
            [
                "--library",
                str(library_path),
                "scan",
                "--as-of",
                AS_OF,
                "--universe",
                UNDERLYING,
                "--top",
                "3",
                "--out",
                str(sheet_path),
                *corpus,
            ]
        )
        == 0
    )
    sheet = json.loads(sheet_path.read_text())
    assert sheet["ideas"], f"the scan proposed nothing on {AS_OF}: {sheet['no_ideas_reason']}"

    assert main(["track", "--ledger", str(ledger_path), "record", "--sheet", str(sheet_path)]) == 0
    assert len(IdeaLedger.load(ledger_path).presented()) == len(sheet["ideas"])

    assert (
        main(
            [
                "--library",
                str(library_path),
                "track",
                "--ledger",
                str(ledger_path),
                "settle",
                "--through",
                THROUGH,
                *corpus,
            ]
        )
        == 0
    )

    ledger = IdeaLedger.load(ledger_path)
    assert ledger.open_ideas() == (), "every idea's hold elapses inside the settlement range"
    settled = [entry for entry in ledger.settlements() if entry.status == STATUS_SETTLED]
    assert settled, "the captured ladder quotes an at-the-money straddle on both sessions"

    for entry in settled:
        assert entry.as_of == AS_OF
        assert entry.realised_return is not None
        assert entry.pnl is not None
        assert entry.realised_return == pytest.approx(entry.pnl / entry.capital_base)
        assert entry.drift == pytest.approx(entry.realised_return - entry.expected_return)
        # The sealed holdout is the reason this test names its dates rather than deriving
        # them: an exit past this line would be a settlement computed on unseen months.
        exit_date = dt.date.fromisoformat(entry.exit_as_of)
        assert dt.date.fromisoformat(AS_OF) < exit_date <= dt.date.fromisoformat(THROUGH)
        assert exit_date < HOLDOUT_FIRST
        assert all(leg.entry_price is not None and leg.exit_price is not None for leg in entry.legs)

    capsys.readouterr()
    assert (
        main(
            [
                "--library",
                str(library_path),
                "track",
                "--ledger",
                str(ledger_path),
                "report",
            ]
        )
        == 0
    )
    printed = capsys.readouterr().out
    assert TEMPLATE in printed
    # One settled idea cannot judge a template, and the report is required to say so in the
    # words an operator reads rather than by printing nothing.
    assert "not enough settled ideas to judge" in printed
    assert f"{len(settled)} of 10" in printed
    # The card was found. Asserting only that the word "realised" appears would pass just as
    # happily against a report that could not find the admission — which is what a broken
    # ledger-to-library identity looks like, and the only symptom it has.
    assert re.search(r"admitted mean return at hold: [+-]", printed)
    report = IdeaLedger.load(ledger_path).drift(TemplateLibrary.load(library_path))[0]
    assert report.card_mean_return_at_hold is not None
    # This admission rests on a decision record whose run reports no per-position figure, so
    # there is nothing to rescale the promised edge onto. The comparison stays on the
    # per-session-scaled base at a scale of exactly one, and the report says which base it
    # used rather than leaving a reader to assume the corrected one.
    assert report.card_mean_return_per_round_trip is None
    assert report.expected_scale == 1.0
    assert "per-session" in report.reason or "unscaled" in report.reason


def test_settling_before_the_hold_elapses_leaves_the_idea_open(
    tmp_path: Path, library_path: Path
) -> None:
    """A settlement through the entry session itself marks nothing and loses nothing."""
    sheet_path = tmp_path / "ideas.json"
    ledger_path = tmp_path / "ledger.json"
    corpus = ["--corpus-root", str(CORPUS_ROOT)]

    main(
        [
            "--library",
            str(library_path),
            "scan",
            "--as-of",
            AS_OF,
            "--universe",
            UNDERLYING,
            "--top",
            "1",
            "--out",
            str(sheet_path),
            *corpus,
        ]
    )
    main(["track", "--ledger", str(ledger_path), "record", "--sheet", str(sheet_path)])
    assert (
        main(
            [
                "--library",
                str(library_path),
                "track",
                "--ledger",
                str(ledger_path),
                "settle",
                "--through",
                AS_OF,
                *corpus,
            ]
        )
        == 0
    )
    ledger = IdeaLedger.load(ledger_path)
    assert ledger.settlements() == ()
    assert len(ledger.open_ideas()) == len(ledger.presented())


def test_a_ledger_path_that_names_nothing_reports_rather_than_crashes(
    tmp_path: Path, library_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """An empty ledger is a real state on the first night, not an error."""
    assert (
        main(
            [
                "--library",
                str(library_path),
                "track",
                "--ledger",
                str(tmp_path / "absent.json"),
                "report",
            ]
        )
        == 0
    )
    assert "no settled ideas to report on" in capsys.readouterr().out
