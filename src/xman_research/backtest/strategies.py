"""One strategy: the short ATM straddle, which is H1 expressed as positions.

**Why exactly one.** The membership test in spec §1.1 admits a thing if the loop does not
close without it or if deferring it loses it permanently. A strategy DSL fails both. What
the loop needs is a single honest expression of the anchor hypothesis — the index variance
risk premium — so the machinery around it can be judged end to end, and that is a short
straddle held to cash settlement: implied variance is sold at entry, realised variance is
paid at expiry, and the difference is the premium the hypothesis claims exists.

**What this deliberately does not do.** No conditioning on a signal, no delta hedging, no
strike selection beyond at-the-money, no roll logic, no stop. Every one of those is a
research decision that belongs to a *variant* — and a variant is a trial, logged and
counted. Building them into the strategy would let one backtest quietly contain several,
which is the same hole the single-use trial token closes from the other end.

The naive always-on benchmark spec §3 C6 requires is this same class: an unconditional
short straddle *is* the benchmark a conditional short-variance signal must beat. That is
convenient and it is not an accident — it is why H1 was chosen as the anchor.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from xman_research.backtest.costs import Side
from xman_research.backtest.engine import BookView, TradeIntent
from xman_research.backtest.market import OptionType, SessionView

__all__ = ["ShortAtmStraddle"]


@dataclass(frozen=True, slots=True)
class ShortAtmStraddle:
    """Sell an at-the-money call and put of the nearest expiry, hold to settlement.

    Entry happens only when the book is flat, so the position is opened once per expiry
    cycle rather than added to daily. Exit is by cash settlement — the engine settles any
    position whose contract expires that session — so there is no exit rule here at all,
    which is the honest shape for a hypothesis about the premium earned over a *full*
    variance cycle.

    ``min_days_to_expiry`` refuses to open a straddle that settles the same session. That
    is a real research decision, not hygiene: a zero-DTE straddle is a different
    hypothesis with a different risk profile, and letting the strategy silently become one
    on expiry Tuesdays would mix two populations inside one trial.
    """

    lots: int = 1
    min_days_to_expiry: int = 1

    def __post_init__(self) -> None:
        if self.lots <= 0:
            raise ValueError(f"lots must be positive, got {self.lots}")
        if self.min_days_to_expiry < 0:
            raise ValueError("min_days_to_expiry must be non-negative")

    @property
    def name(self) -> str:
        return "short_atm_straddle"

    def parameters(self) -> Mapping[str, Any]:
        return {"lots": self.lots, "min_days_to_expiry": self.min_days_to_expiry}

    def decide(
        self, *, session: SessionView, minute: dt.datetime, book: BookView
    ) -> Sequence[TradeIntent]:
        if not book.is_flat:
            return ()
        expiry = session.universe.nearest_expiry(session.session_date)
        if expiry is None:
            return ()
        if (expiry - session.session_date).days < self.min_days_to_expiry:
            expiry = _next_expiry_after(session, expiry)
            if expiry is None:
                return ()
        spot = session.spot_at(minute)
        if spot is None:
            return ()
        strike = session.universe.atm_strike(spot, expiry)
        if strike is None:
            return ()

        intents: list[TradeIntent] = []
        for option_type in (OptionType.CALL, OptionType.PUT):
            contract = session.universe.get(expiry, strike, option_type)
            if contract is None:
                # A chain missing one side of the ATM strike is not a straddle. Returning
                # the leg that exists would open a naked directional position under a
                # market-neutral hypothesis's name.
                return ()
            intents.append(
                TradeIntent(
                    trading_symbol=contract.trading_symbol,
                    side=Side.SELL,
                    lots=self.lots,
                    tag="entry",
                )
            )
        return tuple(intents)


def _next_expiry_after(session: SessionView, expiry: dt.date) -> dt.date | None:
    """The expiry after ``expiry``, or ``None``.

    Usually returns ``None`` against the current corpus, and that is a data fact worth
    stating: capture ran with the expiry ladder hardcoded to the front contract, so the
    instrument master lists later expiries while the bar file carries none of them. The
    engine's feasibility verdicts would report ``NO_BAR`` on every leg — correctly, but
    for a capture-scope reason rather than a market one. Spec §3 C1 is the fix.
    """
    for candidate in session.universe.expiries():
        if candidate > expiry:
            return candidate
    return None
