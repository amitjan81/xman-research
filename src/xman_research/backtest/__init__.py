"""MVP component C5 — the backtester.

The narrowest thing that can produce an honest verdict on H1, the index variance risk
premium. It runs one strategy over a range of captured sessions and reports what the
positions would have cost, whether they could have been filled, and what the exchange
would have paid at expiry.

Five properties, one per acceptance criterion in spec §3 C5:

* **Statutory costs at date-effective rates** — :mod:`xman_research.backtest.costs`. Not a
  model and not pluggable: a dated table with a source and a confidence per rate.
* **European cash settlement** against a stored, dated formula —
  :mod:`xman_research.backtest.settlement`.
* **Participation caps** against both volume and open interest, with the resize recorded —
  :mod:`xman_research.backtest.execution`.
* **A feasibility verdict on every entry and exit**, separate from what it cost — same
  module. *Could this have been filled* is not a discount applied to a price.
* **Reproducibility** — :meth:`~xman_research.backtest.engine.BacktestResult.fingerprint`.

Plus a simplified margin approximation (:mod:`xman_research.backtest.margin`), because a
Sharpe ratio computed on unlevered notional is meaningless for short options.

Usage, from the notebook shape C4 already established::

    session = open_session("research.db")
    store = SessionStore()

    with session.trial(h1, data_window=DataWindow(date(2026, 1, 1), date(2026, 3, 31))) as t:
        result = run_backtest(t, store=store, strategy=ShortAtmStraddle())

    result.metrics()["net_pnl"]

The trial token is required and single-use. See :mod:`xman_research.backtest.engine` for
why, at length — it is the mitigation C4's own review asked this component to provide.
"""

from xman_research.backtest.costs import (
    ChargeableTrade,
    Confidence,
    CostBreakdown,
    FlatPerOrderBrokerage,
    RateNotInForceError,
    RateSchedule,
    Side,
    StatutoryCostStack,
    StatutoryRate,
    TradeKind,
)
from xman_research.backtest.engine import (
    BacktestConfig,
    BacktestResult,
    BookView,
    DailyRecord,
    FillRecord,
    SettlementRecord,
    Strategy,
    TokenAlreadyUsedError,
    TradeIntent,
    run_backtest,
)
from xman_research.backtest.execution import (
    BarCloseFillModel,
    Feasibility,
    FeasibilityVerdict,
    FillModel,
    ParticipationLimits,
    apply_participation_caps,
)
from xman_research.backtest.lot_size import (
    NIFTY_LOT_SIZE_EPOCHS,
    LotSizeAudit,
    LotSizeEpoch,
    audit_lot_size,
    epoch_for,
)
from xman_research.backtest.margin import (
    MarginRequirement,
    ShortLeg,
    SimplifiedMarginModel,
)
from xman_research.backtest.market import (
    Bar,
    Contract,
    ContractUniverse,
    OptionType,
    SessionView,
)
from xman_research.backtest.settlement import (
    SETTLEMENT_RULES,
    SettlementRule,
    SettlementValue,
    SettlementWindowError,
    settlement_rule_for,
    settlement_value,
)
from xman_research.backtest.strategies import ShortAtmStraddle

__all__ = [
    "NIFTY_LOT_SIZE_EPOCHS",
    "SETTLEMENT_RULES",
    "BacktestConfig",
    "BacktestResult",
    "Bar",
    "BarCloseFillModel",
    "BookView",
    "ChargeableTrade",
    "Confidence",
    "Contract",
    "ContractUniverse",
    "CostBreakdown",
    "DailyRecord",
    "Feasibility",
    "FeasibilityVerdict",
    "FillModel",
    "FillRecord",
    "FlatPerOrderBrokerage",
    "LotSizeAudit",
    "LotSizeEpoch",
    "MarginRequirement",
    "OptionType",
    "ParticipationLimits",
    "RateNotInForceError",
    "RateSchedule",
    "SessionView",
    "SettlementRecord",
    "SettlementRule",
    "SettlementValue",
    "SettlementWindowError",
    "ShortAtmStraddle",
    "ShortLeg",
    "Side",
    "SimplifiedMarginModel",
    "StatutoryCostStack",
    "StatutoryRate",
    "Strategy",
    "TokenAlreadyUsedError",
    "TradeIntent",
    "TradeKind",
    "apply_participation_caps",
    "audit_lot_size",
    "epoch_for",
    "run_backtest",
    "settlement_rule_for",
    "settlement_value",
]
