"""Criterion 2, in its strictest reading: an evaluation run *from a notebook* is logged.

The other tests call decorated functions from test code, which is the same code path a
notebook takes but not the same shape. This one executes cell source with ``exec`` into
a fresh namespace, cell by cell, the way IPython does — no import of a test helper, no
entrypoint, no CLI, nothing the researcher had to remember to invoke. The rows still
land, and the count still comes from the log.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from xman_research import ManualClock, StaticCodeVersion, open_session

CELL_1 = """
from datetime import date
from xman_research import DataWindow, HypothesisRecord

h = HypothesisRecord(
    name="H1 - variance risk premium",
    mechanism="Hedgers pay up for index protection, so implied exceeds realised variance.",
    null_hypothesis="The spread has no positive mean once statutory costs are paid.",
    thresholds={"deflated_sharpe": 0.0, "cost_breakeven_multiple": 2.0},
    predictors=["iv_30d", "realised_vol_20d"],
)
window = DataWindow(date(2023, 1, 1), date(2024, 12, 31))
"""

CELL_2 = """
@session.evaluation(h)
def evaluate(data, *, delta):
    return {"sharpe": 0.9 + delta, "cost_breakeven_multiple": 2.1}
"""

CELL_3 = """
results = [evaluate(window, delta=d) for d in (0.10, 0.20, 0.30)]
"""

CELL_4 = """
# The researcher tries a variant that blows up, then moves on.
try:
    evaluate(window, delta="thirty")
except TypeError:
    pass
"""

CELL_5 = """
trials_for_dsr = session.count_family_trials(h)
"""


def test_evaluations_run_from_notebook_cells_are_logged(tmp_path: Path) -> None:
    session = open_session(
        tmp_path / "notebook.db",
        clock=ManualClock(datetime(2026, 8, 12, 10, 0, tzinfo=UTC)),
        code_version=StaticCodeVersion("notebook-sha", dirty=True),
    )
    namespace: dict[str, Any] = {"session": session}
    try:
        for cell in (CELL_1, CELL_2, CELL_3, CELL_4, CELL_5):
            exec(cell, namespace)

        hypothesis = namespace["h"]

        # Four evaluations happened in that notebook: three that returned, one that raised.
        assert namespace["trials_for_dsr"] == 4
        assert session.count_trials(hypothesis) == 4

        logged = session.trials(hypothesis)
        assert [t.params["delta"] for t in logged] == [0.10, 0.20, 0.30, "thirty"]
        assert [str(t.outcome) for t in logged] == ["completed"] * 3 + ["error"]

        # The count the researcher would feed to DSR came from the log, not from them.
        assert namespace["trials_for_dsr"] == len(logged)

        # And the dirty tree is on every row, because it was.
        assert all(t.code_version.dirty for t in logged)
    finally:
        session.log.close()
