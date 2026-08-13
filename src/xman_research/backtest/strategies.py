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
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from xman_research.backtest.costs import Side
from xman_research.backtest.engine import BookView, TradeIntent
from xman_research.backtest.market import Contract, OptionType, SessionView

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

    **Size is an exposure, not a contract count — see :attr:`target_notional`.** This
    class used to take ``lots``, and that made every headline statistic a function of the
    exchange's contract multiplier. It is the one thing about a research verdict that
    must not be true.
    """

    target_notional: float = 1_500_000.0
    """Rupees of underlying index exposure the straddle aims at, per open.

    **Why the size is stated in money.** "Does selling index variance earn a premium" is a
    question about an economic effect. The lot size is an execution-layer rounding
    constraint — NSE has set NIFTY's at 25, 50, 75 and 65 within living memory, and it
    will move again. Sizing in *lots* silently makes the position, and therefore the P&L,
    the margin and the drawdown, proportional to whichever multiplier happened to be in
    force. A Sharpe survived that (it is scale-free), but the maximum drawdown did not:
    :func:`~xman_research.validation.statistics.drawdown` runs on returns denominated in a
    fixed capital base, so a 75/65 change moved it by 15% — and H1's gate bars drawdown at
    10%. The verdict could flip on an exchange circular about contract size.

    Sizing at a notional target removes it by construction. P&L, margin and every
    percentage-based statutory cost scale together with the position, so the Sharpe, the
    deflated Sharpe, the return on margin, the drawdown and the cost-breakeven *ratio* are
    all invariant to the multiplier. What remains is stated rather than hidden, in
    :meth:`lots_for`.

    Scale-freeness in *capital* is the caller's to preserve: this number and
    :attr:`~xman_research.backtest.engine.BacktestConfig.starting_cash` are the numerator
    and denominator of every return C6 computes, so they must be moved together. Their
    ratio is the run's leverage and is a research decision; their common scale is not.
    """

    min_days_to_expiry: int = 1

    def __post_init__(self) -> None:
        if self.target_notional <= 0:
            raise ValueError(f"target_notional must be positive, got {self.target_notional}")
        if self.min_days_to_expiry < 0:
            raise ValueError("min_days_to_expiry must be non-negative")

    @property
    def name(self) -> str:
        return "short_atm_straddle"

    def parameters(self) -> Mapping[str, Any]:
        return {
            "target_notional": self.target_notional,
            "min_days_to_expiry": self.min_days_to_expiry,
        }

    def lots_for(self, *, spot: float, lot_size: int) -> int:
        """Whole contracts closest to :attr:`target_notional` of exposure at ``spot``.

        **This rounding is the entire residual of the invariance, so it is worth being
        precise about.** The target is a real number of index units,
        ``target_notional / spot``; the exchange trades whole contracts. Rounding to
        nearest leaves a size error of at most half a lot, so the realised exposure differs
        from the target by at most ``lot_size / (2 * target_units)`` — 3% at 15 contracts,
        0.5% at 100, and **50% at one**. Two runs at different multipliers therefore agree
        on every scale-free statistic to about twice that bound, and no better.

        There is no way around it and pretending otherwise would be the error: a book that
        can only trade one contract *is* sized by the lot, and its drawdown genuinely does
        move when the lot moves. The property this class provides is that the sizing rule
        no longer *introduces* the dependence — it survives only where the market's own
        granularity puts it, and it shrinks as the book grows.

        Nearest, not floor: floor is biased small by half a lot on average, which would
        make the realised exposure depend on the multiplier in the *mean* as well as in the
        residual. ``floor(x + 0.5)`` rather than :func:`round`, because :func:`round` is
        banker's rounding and would break the tie by parity — a rule nobody reading a
        position size expects, and one that makes the residual depend on the parity of a
        quotient.

        Returns ``0`` when the target is under half a contract. The caller trades nothing
        rather than rounding up to one, which would silently take a position larger than
        the exposure that was asked for.
        """
        if spot <= 0 or lot_size <= 0:
            return 0
        return math.floor((self.target_notional / spot) / lot_size + 0.5)

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
        # legs also share one size, taken from the CALL's lot size and applied to both:
        # a straddle whose two legs were sized independently would not be a straddle if
        # the chain ever listed them at different multipliers.
        # listing guard below is necessary and not sufficient: it establishes that both
        # legs *exist*, while the group establishes that both legs *traded*. A straddle
        # whose PE came back NO_LIQUIDITY used to leave a naked short call.
        group = f"straddle:{expiry.isoformat()}:{strike:g}"
        legs: list[Contract] = []
        for option_type in (OptionType.CALL, OptionType.PUT):
            contract = session.universe.get(expiry, strike, option_type)
            if contract is None:
                # A chain missing one side of the ATM strike is not a straddle. Returning
                # the leg that exists would open a naked directional position under a
                # market-neutral hypothesis's name.
                return ()
            legs.append(contract)

        lots = self.lots_for(spot=spot, lot_size=legs[0].lot_size)
        if lots <= 0:
            # The targeted exposure is under half a contract. Nothing is traded, and the
            # session simply carries no position — see lots_for for why not one lot.
            return ()
        return tuple(
            TradeIntent(
                trading_symbol=contract.trading_symbol,
                side=Side.SELL,
                lots=lots,
                tag="entry",
                leg_group=group,
            )
            for contract in legs
        )


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
