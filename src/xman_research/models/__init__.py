"""The owner-approved model specifications, and the checks their specs mandate.

``research/models/M1_short_atm_straddle.md`` and ``M2_overnight_vs_intraday.md`` are the
contract. This package holds only what those specs require to be *executed* — the M1 §12.1
sizing-floor gate, the threshold calibration at the realised sample shape, and the two
hypothesis records that carry the recalibrated bars into content-addressed form.

Nothing here forks ``xman_research.h1.run_decision`` or ``xman_research.h26.run_decision``.
Both runners already take ``hypothesis=``, ``config_path=`` and ``in_sample_start=``, so
M1 and M2 are those runners pointed at new records and new gate files.
"""

from xman_research.models.sizing_floor import (
    SessionSizing,
    SizingFloorReport,
    check_sizing_floor,
)

__all__ = ["SessionSizing", "SizingFloorReport", "check_sizing_floor"]
