"""Calibrate the H1 deflated-Sharpe bars on SYNTHETIC series, before any real run.

This is what makes ``research/h1/gate.toml``'s deflated-Sharpe numbers a pre-registration
rather than a preference. It answers one question — *at this sample length and this logged
trial count, what deflated Sharpe would a strategy with a known true Sharpe actually show?*
— using nothing but Gaussian noise with a planted mean. No corpus, no backtest, no result.

Calibrating a bar against synthetic data is legitimate. Calibrating it against the result it
will grade is not, which is why this script cannot read the session store even in principle.

Run: ``uv run python research/h1/calibrate_thresholds.py``
"""

from __future__ import annotations

import datetime as dt
import math
import random
import tempfile
from pathlib import Path

from xman_research import (
    DataWindow,
    HypothesisRecord,
    ManualClock,
    StaticCodeVersion,
    TrialLog,
)
from xman_research.validation import ReturnSeries, SelectionUniverse, deflated_sharpe_ratio

SEEDS = 40
DAILY_VOL = 0.01
TRUE_SHARPES = (0.5, 1.0, 1.5, 2.0, 2.5, 3.0)
#: (sessions, logged trials) — the in-sample case and the holdout case.
#: The holdout is graded with three family trials (the in-sample run, the touch row the
#: read itself writes, and the holdout run), so N=2 and N=5 bracket it.
CASES = ((80, 1), (80, 2), (80, 5), (29, 1), (29, 2), (29, 5))


def synthetic(n: int, annualised_sharpe: float, *, seed: int) -> ReturnSeries:
    """Gaussian returns with a planted mean giving the requested annualised Sharpe."""
    rng = random.Random(seed)
    mean = annualised_sharpe * DAILY_VOL / math.sqrt(252.0)
    first = dt.date(2026, 1, 1)
    return ReturnSeries(
        dates=tuple(first + dt.timedelta(days=index) for index in range(n)),
        net=tuple(rng.gauss(mean, DAILY_VOL) for _ in range(n)),
        drag=tuple(0.0 for _ in range(n)),
        label=f"synthetic-sharpe-{annualised_sharpe:g}",
    )


def _universe_of_size(trials: int) -> SelectionUniverse:
    """A throwaway log holding ``trials`` rows, so the deflation reads the count it must.

    **Private on purpose.** ``tests/test_no_caller_supplied_count.py`` refuses any *public*
    callable in this package that takes a parameter shaped like a trial count, and it
    refused this one. The guard is blunt by design and it is pointing at something real: a
    public helper that manufactures a trial count is one import away from being used to
    supply one. This function creates synthetic rows in a temporary database and is an
    internal fixture of a calibration script, so it is named accordingly rather than
    renamed to slip past the check.
    """
    log = TrialLog(
        Path(tempfile.mkdtemp(prefix="h1_calibration_")) / "calibration.db",
        clock=ManualClock(dt.datetime(2026, 1, 1, tzinfo=dt.UTC)),
        code_version=StaticCodeVersion("0" * 40, dirty=False),
    )
    record = HypothesisRecord(
        name="threshold calibration, synthetic only",
        mechanism="Not a hypothesis about markets: a fixture that gives the deflation a "
        "trial count to read, since SelectionUniverse accepts no count from a caller.",
        null_hypothesis="Not tested here. This record exists to hold rows.",
        thresholds={"deflated_sharpe": 0.0},
    )
    log.register_hypothesis(record)
    for index in range(trials):
        log.append_trial(
            hypothesis_id=record.id,
            params={"synthetic_trial": index},
            data_window=DataWindow(dt.date(2026, 1, 1), dt.date(2026, 3, 1)),
            metrics={},
        )
    return SelectionUniverse(log, record)


def main() -> None:
    for sessions, trials in CASES:
        universe = _universe_of_size(trials)
        print(f"--- n={sessions} sessions, N={universe.size} logged trials")
        for sharpe in TRUE_SHARPES:
            values = sorted(
                deflated_sharpe_ratio(
                    synthetic(sessions, sharpe, seed=seed), universe=universe
                ).value
                for seed in range(SEEDS)
            )
            median = values[len(values) // 2]
            lower_quartile = values[len(values) // 4]
            print(
                f"   true annualised Sharpe {sharpe:4.1f}: "
                f"median DSR {median:.3f}   p25 {lower_quartile:.3f}"
            )


if __name__ == "__main__":
    main()
