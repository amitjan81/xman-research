"""Calibrate H26's deflated-Sharpe bars on SYNTHETIC series, before any real run.

Same instrument as ``xman_research.h1.calibrate_thresholds`` and for the same reason: a
threshold is a pre-registration only if the number can be defended without reference to
the result it grades. Nothing here can read the session store even in principle.

**Why H26 cannot inherit H1's bars.** Two inputs moved. The judged series is 79 return
observations either way, but the *trial count* is not 1 — H26's decision run appends a
candidate trial and a separate benchmark trial to a family that already contains H1's
replayed row, so the deflation has three tries to correct for rather than one. And the
holdout is no longer 29 sessions: the vendor backfill of 2026-06-13..2026-08-12 enlarged
it to 71. A bar copied across that change would be a number, not a pre-registration.

Run: ``uv run python -m xman_research.h26.calibrate_thresholds``
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

#: (return observations, logged family trials).
#:
#: ``(79, 3)`` is the in-sample case exactly as it will be graded: the in-sample window
#: holds 80 sessions and therefore 79 returns, and the family holds H1's replayed row plus
#: H26's candidate and benchmark trials.
#:
#: ``(70, 6)`` is the holdout case: 71 sessions, and a family that by then also carries
#: the holdout touch row and the holdout's own two runs. ``(70, 3)`` brackets it from
#: below in case the touch row lands differently than projected.
CASES = ((79, 1), (79, 3), (79, 4), (79, 6), (70, 3), (70, 6))


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
    """A throwaway log holding ``trials`` rows. Private for the reason H1's twin is."""
    log = TrialLog(
        Path(tempfile.mkdtemp(prefix="h26_calibration_")) / "calibration.db",
        clock=ManualClock(dt.datetime(2026, 1, 1, tzinfo=dt.UTC)),
        code_version=StaticCodeVersion("0" * 40, dirty=False),
    )
    record = HypothesisRecord(
        name="H26 threshold calibration, synthetic only",
        mechanism="Not a hypothesis about markets: a fixture giving the deflation a trial "
        "count to read, since SelectionUniverse accepts no count from a caller.",
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
    for observations, trials in CASES:
        universe = _universe_of_size(trials)
        print(f"--- n={observations} returns, N={universe.size} logged trials")
        for sharpe in TRUE_SHARPES:
            values = sorted(
                deflated_sharpe_ratio(
                    synthetic(observations, sharpe, seed=seed), universe=universe
                ).value
                for seed in range(SEEDS)
            )
            print(
                f"   true annualised Sharpe {sharpe:4.1f}: "
                f"median DSR {values[len(values) // 2]:.3f}   p25 {values[len(values) // 4]:.3f}"
            )


if __name__ == "__main__":
    main()
