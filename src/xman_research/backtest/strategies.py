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
from enum import StrEnum
from typing import Any

from xman_research.backtest.costs import Side
from xman_research.backtest.engine import BookView, TradeIntent
from xman_research.backtest.market import OptionType, SessionView

__all__ = ["ClockSide", "ClockSplitShortStraddle", "ShortAtmStraddle"]


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

        # Both legs share one group, so the engine fills them together or not at all. The
        # listing guard below is necessary and not sufficient: it establishes that both
        # legs *exist*, while the group establishes that both legs *traded*. A straddle
        # whose PE came back NO_LIQUIDITY used to leave a naked short call.
        group = f"straddle:{expiry.isoformat()}:{strike:g}"
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
                    leg_group=group,
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


class ClockSide(StrEnum):
    """Which side of the clock a position is held over."""

    GAP = "gap"
    """Sold at the session close, bought back at the next session's open.

    Holds only *non-trading* time: the underlying provably cannot move, and calendar
    decay accrues anyway. The exposure H26 claims is paid a premium."""

    SESSION = "session"
    """Sold at the session open, bought back at the same session's close.

    Holds only *trading* time: the mirror image, and the control."""


@dataclass(frozen=True, slots=True)
class ClockSplitShortStraddle:
    """H26 expressed as positions: one short ATM straddle, held over exactly one clock side.

    **The two arms are one class with a flag, and that is the whole design.** H26's claim
    is a *difference* between two holding windows, so the comparison is only worth
    anything if the two arms are otherwise identical — same instrument, same strike rule,
    same size, same eligibility, same number of round trips, same cost model. Written as
    two classes they would be free to drift apart in some detail nobody re-checked, and
    the drift would present as a premium. Written as one class parameterised by
    :class:`ClockSide`, every line below is shared and the *only* asymmetry that can exist
    is which decision minute opens and which closes. That is exactly the asymmetry under
    test.

    **Eligibility is deliberately identical for both arms, and it costs the control
    something.** A straddle can only be held overnight if its contract survives the night,
    so the GAP arm cannot trade on an expiry session. The SESSION arm *could* — nothing
    stops an intraday round trip on expiry day — but it is barred too, because a control
    that trades a population the candidate cannot reach is measuring a different thing.
    On this corpus that removes every Tuesday (see the class of gap this leaves
    unobservable in ``research/h26/DECISION.md``), and the corpus carries only the front
    weekly expiry, so rolling to the next contract is not available as an alternative:
    those bars were never captured (spec §3 C1). The exclusion is a capture-scope
    limitation, not a market fact, and it must not be read as one.

    ``entry_time``/``exit_time`` are the strategy's own, and :attr:`decision_times` is
    what the runner hands to :class:`~xman_research.backtest.engine.BacktestConfig`, so
    the engine's clock and the strategy's reading of it come from one source and cannot
    disagree. Configuring them separately is how an arm silently stops trading.
    """

    hold: ClockSide = ClockSide.GAP
    lots: int = 1
    open_time: dt.time = dt.time(9, 20)
    close_time: dt.time = dt.time(15, 29)

    def __post_init__(self) -> None:
        if self.lots <= 0:
            raise ValueError(f"lots must be positive, got {self.lots}")
        if self.open_time >= self.close_time:
            raise ValueError(
                f"open_time {self.open_time} must be strictly before close_time "
                f"{self.close_time}; with the two reversed a 'gap' would be an intraday "
                "hold and the arms would silently swap."
            )

    @property
    def name(self) -> str:
        return f"clock_split_short_straddle:{self.hold.value}"

    @property
    def decision_times(self) -> tuple[dt.time, ...]:
        """The engine clock this strategy needs. Pass straight to ``BacktestConfig``."""
        return (self.open_time, self.close_time)

    def parameters(self) -> Mapping[str, Any]:
        return {
            "hold": self.hold.value,
            "lots": self.lots,
            "open_time": self.open_time.isoformat(),
            "close_time": self.close_time.isoformat(),
        }

    def decide(
        self, *, session: SessionView, minute: dt.datetime, book: BookView
    ) -> Sequence[TradeIntent]:
        at_close = minute.timetz().replace(tzinfo=None) >= self.close_time
        opens_here = at_close if self.hold is ClockSide.GAP else not at_close
        if opens_here:
            return self._entry(session, minute) if book.is_flat else ()
        return self._exit(book)

    def _entry(self, session: SessionView, minute: dt.datetime) -> Sequence[TradeIntent]:
        expiry = session.universe.nearest_expiry(session.session_date)
        if expiry is None or expiry <= session.session_date:
            # Expiry today (or no listed expiry): the contract does not survive the night.
            # Both arms decline — see the class docstring on identical eligibility.
            return ()
        spot = session.spot_at(minute)
        if spot is None:
            return ()
        strike = session.universe.atm_strike(spot, expiry)
        if strike is None:
            return ()
        group = f"clocksplit:{self.hold.value}:{expiry.isoformat()}:{strike:g}"
        intents: list[TradeIntent] = []
        for option_type in (OptionType.CALL, OptionType.PUT):
            contract = session.universe.get(expiry, strike, option_type)
            if contract is None:
                return ()
            intents.append(
                TradeIntent(
                    trading_symbol=contract.trading_symbol,
                    side=Side.SELL,
                    lots=self.lots,
                    tag="entry",
                    leg_group=group,
                )
            )
        return tuple(intents)

    def _exit(self, book: BookView) -> Sequence[TradeIntent]:
        """Buy back everything, as one group.

        **Grouped, like the entry, and for a reason that cuts the other way.** If one leg
        cannot be bought back, closing only the other would leave a naked short — a
        directional position held under a market-neutral hypothesis's name, which is the
        failure ``leg_group`` exists to prevent. The cost of grouping is the opposite
        failure: neither leg closes, and the straddle is carried into a *further* session,
        so that observation stops being a pure gap (or a pure session) and quietly
        measures both. Neither outcome is acceptable silently, so the engine records the
        refusal as ``GROUP_INCOMPLETE`` and ``research/h26/DECISION.md`` reports how often
        it happened rather than assuming it never did.
        """
        intents: list[TradeIntent] = []
        group = f"clocksplit-exit:{self.hold.value}"
        for position in book.positions:
            if not position.is_short:
                continue
            lots = abs(position.units) // position.contract.lot_size
            if lots <= 0:
                continue
            intents.append(
                TradeIntent(
                    trading_symbol=position.contract.trading_symbol,
                    side=Side.BUY,
                    lots=lots,
                    tag="exit",
                    leg_group=group,
                )
            )
        return tuple(intents)
