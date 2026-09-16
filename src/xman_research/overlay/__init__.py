"""Backtest of the pledge-funded index option overlay (requirements v1.0, sections 3-4).

The package is organised as the requirements are: :mod:`sizing` is the Capital Allocation
Service's calculator, :mod:`strategy` is the Strategy Service, :mod:`context` is the daily
market state its filters read, and :mod:`run` is one arm of the study with section 6.3's
metrics attached. :mod:`greeks`, :mod:`fills` and :mod:`synthetic` are the three places
where this corpus cannot answer the requirement directly and something is modelled instead;
each states what it models and what the error is.
"""

from xman_research.overlay.context import VIX_SUBSTITUTION, DailyContext, load_context
from xman_research.overlay.fills import AbsoluteSlippageFillModel
from xman_research.overlay.sizing import (
    AllocationInputs,
    AllocationRecord,
    CollateralAssumption,
    MarginPerLotModel,
    allocate,
    allocation_sweep,
    worked_example,
)
from xman_research.overlay.strategy import IndexOptionOverlay, OverlayParameters
from xman_research.overlay.synthetic import SYNTHETIC_WING_STAMP, SyntheticWingStore

__all__ = [
    "SYNTHETIC_WING_STAMP",
    "VIX_SUBSTITUTION",
    "AbsoluteSlippageFillModel",
    "AllocationInputs",
    "AllocationRecord",
    "CollateralAssumption",
    "DailyContext",
    "IndexOptionOverlay",
    "MarginPerLotModel",
    "OverlayParameters",
    "SyntheticWingStore",
    "allocate",
    "allocation_sweep",
    "load_context",
    "worked_example",
]
