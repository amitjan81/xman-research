"""Intraday option-selling studies on the NIFTY weekly chain.

Flat by the close, every session. The distinction from
:mod:`xman_research.overlay` is not the structure but the holding period: nothing here
carries an overnight gap, which removes the risk H26 found the premium actually living in —
and is therefore the harder case to make money in, not the easier one.
"""

from xman_research.intraday.dynamic import DynamicParameters, DynamicStrangle, RangeMethod
from xman_research.intraday.run import (
    DynamicRunConfig,
    StrangleRun,
    StrangleRunConfig,
    decision_grid,
    run_dynamic,
    run_strangle,
    strangle_metrics,
)
from xman_research.intraday.strangle import IntradayStrangle, SpotStop, StrangleParameters
from xman_research.intraday.window_stats import WindowStats, load_window_stats

__all__ = [
    "DynamicParameters",
    "DynamicRunConfig",
    "DynamicStrangle",
    "IntradayStrangle",
    "RangeMethod",
    "SpotStop",
    "StrangleParameters",
    "StrangleRun",
    "StrangleRunConfig",
    "WindowStats",
    "decision_grid",
    "load_window_stats",
    "run_dynamic",
    "run_strangle",
    "strangle_metrics",
]
