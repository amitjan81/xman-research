"""An intraday short strangle on NIFTY weeklies, flat by the close every session.

**The prior this is written against is negative.** H26 measured the same premium
intraday and overnight on the same corpus and found the intraday leg losing 10.5% a year
while the overnight leg made 5.79% — the variance premium in that study accrued in the gap,
not in the session. Three things here differ from what H26 tested, and each is a reason the
answer might not carry over: the strikes are out of the money rather than at it, there is a
hard stop, and the entry time is a parameter rather than the open. The negative result is
the null this has to beat, not an excuse to skip the test.

**The stop is on the underlying, not on the option.** That is the owner's design decision
and it is the right one for a reason worth writing down: a short strangle's loss is driven by
the index moving, and the option's own price is the least reliable place to observe that. A
far-out-of-the-money weekly can print a wide, thin, jumpy quote — a single aggressive order
moves it several per cent — so a stop keyed to option premium fires on noise in the leg it is
supposed to protect. Spot is the cleanest signal available and this corpus carries it on
every bar.

Two stop shapes are implemented, because they answer different questions:

``SpotStop.MOVE_FROM_ENTRY``
    Close when the index has moved more than a fixed percentage from where it was at entry,
    in either direction. Symmetric, simple, and independent of where the strikes sit.

``SpotStop.STRIKE_BREACH``
    Close when the index comes within a fixed fraction of the tested short strike. This
    adapts to the strike distance: a 0.10-delta strangle gets a wider berth than a 0.25-delta
    one, which is what an operator would actually do.

Both close the **whole** position rather than the tested leg. A strangle with one leg left is
a naked directional short, which is a different trade with a different risk, and closing into
a move is already the expensive moment without adding a second decision to it.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from xman_research.backtest.costs import Side
from xman_research.backtest.engine import BookView, TradeIntent
from xman_research.backtest.market import OptionType, SessionView
from xman_research.overlay.greeks import bs_delta, year_fraction

__all__ = ["IntradayStrangle", "SpotStop", "StrangleParameters"]


class SpotStop(StrEnum):
    """How the stop reads the underlying."""

    MOVE_FROM_ENTRY = "move_from_entry"
    STRIKE_BREACH = "strike_breach"


@dataclass(frozen=True, slots=True)
class StrangleParameters:
    """The four things the owner asked to tune, plus what they depend on."""

    # 1. Which strike to sell.
    short_delta_target: float = 0.15
    delta_band: tuple[float, float] = (0.10, 0.22)

    # 2. The stop, on the index.
    stop: SpotStop = SpotStop.MOVE_FROM_ENTRY
    stop_move_pct: float = 0.005
    """For MOVE_FROM_ENTRY: adverse index move from the entry print that closes the trade."""
    stop_strike_buffer: float = 0.25
    """For STRIKE_BREACH: close when the index has covered this fraction of the distance
    from the entry spot to the tested short strike. 0.25 is an early stop, 1.0 waits for the
    strike itself to be touched."""

    # 3. When to enter.
    entry_time: dt.time = dt.time(9, 45)
    entry_deadline: dt.time = dt.time(14, 0)
    """If the entry minute has no fillable chain, keep trying until this time, then give up."""

    # 4. When to book.
    profit_take_pct: float = 0.50
    """Close when the position has kept this fraction of the credit received."""
    exit_time: dt.time = dt.time(15, 15)
    """The hard flat-by-the-close deadline. Nothing is meant to be carried overnight."""
    exit_start_time: dt.time = dt.time(15, 0)
    """When closing attempts begin.

    Measured, not guessed: a 0.15-delta weekly six days from expiry stops printing into the
    close. On 2025-01-03 the 24550 call had no bar at 15:15, 15:20 or 15:25, the atomic leg
    group blocked the liquid put with it, and the position carried overnight — which is the
    one thing an intraday strategy must not do. Starting at 15:00 gives the group four
    attempts inside the deadline instead of one at its edge."""

    # What the above depend on.
    allowed_dte: tuple[int, ...] = (0, 1, 2, 3, 4, 5, 6)
    """Days to expiry of the near-week contract the session carries. Expiry day (0) is a
    materially different trade from four days out and the study separates them."""
    target_notional: float = 10_000_000.0
    """Sizing basis, in rupees of index exposure per short leg. Held constant across the
    parameter search so a comparison between parameters is not a comparison of sizes."""
    min_credit_pct_of_spot: float = 0.0002
    """Below this the trade is not worth its own brokerage; the session is skipped."""


@dataclass
class _OpenPosition:
    """The live strangle, and the entry facts the exit rules measure against."""

    session_date: dt.date
    expiry: dt.date
    entry_minute: dt.datetime
    entry_spot: float
    lots: int
    lot_size: int
    legs: dict[str, str]
    strikes: dict[str, float]
    credit_per_unit: float
    exit_rule: str | None = None
    exit_estimate: float | None = None
    exit_minute: dt.datetime | None = None

    @property
    def units(self) -> int:
        return self.lots * self.lot_size

    @property
    def credit_rupees(self) -> float:
        return self.credit_per_unit * self.units


@dataclass
class IntradayStrangle:
    """Sell one out-of-the-money call and one put each session; be flat by the close."""

    params: StrangleParameters = field(default_factory=StrangleParameters)

    _position: _OpenPosition | None = field(default=None, init=False, repr=False)
    _traded_today: dt.date | None = field(default=None, init=False, repr=False)
    _closed: list[dict[str, Any]] = field(default_factory=list, init=False, repr=False)
    _journal: list[dict[str, Any]] = field(default_factory=list, init=False, repr=False)

    @property
    def name(self) -> str:
        return "intraday_short_strangle"

    def parameters(self) -> Mapping[str, Any]:
        params = self.params
        return {
            "short_delta_target": params.short_delta_target,
            "delta_band": list(params.delta_band),
            "stop": str(params.stop),
            "stop_move_pct": params.stop_move_pct,
            "stop_strike_buffer": params.stop_strike_buffer,
            "entry_time": params.entry_time.isoformat(),
            "profit_take_pct": params.profit_take_pct,
            "exit_time": params.exit_time.isoformat(),
            "allowed_dte": list(params.allowed_dte),
            "target_notional": params.target_notional,
        }

    @property
    def journal(self) -> tuple[dict[str, Any], ...]:
        return tuple(self._journal)

    @property
    def completed_cycles(self) -> tuple[dict[str, Any], ...]:
        return tuple(self._closed)

    def decide(
        self, *, session: SessionView, minute: dt.datetime, book: BookView
    ) -> Sequence[TradeIntent]:
        self._reconcile(book)
        if self._position is not None:
            return self._manage(session, minute, book)
        return self._maybe_enter(session, minute)

    # ------------------------------------------------------------------ bookkeeping

    def _reconcile(self, book: BookView) -> None:
        position = self._position
        if position is None or book.positions():
            return
        self._closed.append(
            {
                "session_date": position.session_date.isoformat(),
                "expiry": position.expiry.isoformat(),
                "dte": (position.expiry - position.session_date).days,
                "entry_minute": position.entry_minute.isoformat(),
                "exit_minute": (position.exit_minute.isoformat() if position.exit_minute else None),
                "entry_spot": position.entry_spot,
                "lots": position.lots,
                "lot_size": position.lot_size,
                "strikes": dict(position.strikes),
                "credit_per_unit": position.credit_per_unit,
                "credit_rupees": position.credit_rupees,
                "exit_rule": position.exit_rule,
                "estimated_pnl": position.exit_estimate or 0.0,
            }
        )
        self._position = None

    # ------------------------------------------------------------------ management

    def _manage(
        self, session: SessionView, minute: dt.datetime, book: BookView
    ) -> Sequence[TradeIntent]:
        position = self._position
        assert position is not None
        params = self.params

        spot = session.spot_at(minute)
        marks = self._marks(session, minute, position)
        pnl = None if marks is None else self._unrealised(position, marks)

        # The flat-by-the-close rule outranks everything: this strategy exists to avoid the
        # overnight gap, so a session that ends holding is not a worse trade, it is a
        # different strategy. Attempted from the deadline and again at every remaining
        # decision minute — one attempt is not a close, and a leg group that misses its only
        # minute carries the position into a session whose chain may not even list it.
        if minute.time() >= params.exit_start_time or session.session_date > position.session_date:
            rule = (
                "exit_time"
                if session.session_date == position.session_date
                else "carried_overnight_forced_close"
            )
            # **Legs close independently once the deadline window opens.** A strangle closed
            # on one side is a naked short, which is normally the wrong shape — but the
            # alternative here is not "both legs closed", it is "both legs carried", because
            # the leg that blocks the group is the one nobody is trading. Closing what can be
            # closed strictly reduces what is carried.
            return self._close(position, rule, pnl, book, minute, session=session, split_legs=True)

        if spot is not None and spot > 0:
            breached, distance = self._stop_breached(position, spot)
            if breached:
                return self._close(
                    position,
                    f"stop_{params.stop}",
                    pnl,
                    book,
                    minute,
                    detail={"spot": spot, "move_pct": distance},
                    session=session,
                )

        if pnl is not None and pnl >= params.profit_take_pct * position.credit_rupees:
            return self._close(position, "profit_take", pnl, book, minute, session=session)
        return ()

    def _stop_breached(self, position: _OpenPosition, spot: float) -> tuple[bool, float]:
        """Has the index moved far enough to close the trade? Returns the test and the move."""
        params = self.params
        move = (spot - position.entry_spot) / position.entry_spot
        if params.stop is SpotStop.MOVE_FROM_ENTRY:
            return abs(move) >= params.stop_move_pct, move
        # STRIKE_BREACH: measure progress towards whichever short strike the move is heading
        # at, as a fraction of the distance that was there at entry.
        if move >= 0:
            strike = position.strikes["short_call"]
            room = strike - position.entry_spot
            covered = (spot - position.entry_spot) / room if room > 0 else 1.0
        else:
            strike = position.strikes["short_put"]
            room = position.entry_spot - strike
            covered = (position.entry_spot - spot) / room if room > 0 else 1.0
        return covered >= params.stop_strike_buffer, move

    def _marks(
        self, session: SessionView, minute: dt.datetime, position: _OpenPosition
    ) -> dict[str, float] | None:
        marks: dict[str, float] = {}
        for role, symbol in position.legs.items():
            bar = session.bar(symbol, minute)
            if bar is None:
                return None
            marks[role] = bar.close
        return marks

    def _unrealised(self, position: _OpenPosition, marks: Mapping[str, float]) -> float:
        cost_to_close = marks["short_call"] + marks["short_put"]
        return (position.credit_per_unit - cost_to_close) * position.units

    def _close(
        self,
        position: _OpenPosition,
        rule: str,
        pnl: float | None,
        book: BookView,
        minute: dt.datetime,
        detail: dict[str, Any] | None = None,
        session: SessionView | None = None,
        split_legs: bool = False,
    ) -> Sequence[TradeIntent]:
        """Flatten the book, offering only legs this session's chain still lists.

        The guard is needed because the capture is a band around spot that moves with it: a
        strike sold yesterday can be absent from today's instrument master entirely, and the
        engine refuses — correctly — to trade an instrument that was never listed. Without
        the filter one unlisted leg raises and takes the whole run down. With it, the
        closable legs close and the rest is recorded as stranded, which is a data fact about
        this corpus rather than a decision the strategy made."""
        position.exit_rule = rule
        position.exit_minute = minute
        if pnl is not None:
            position.exit_estimate = pnl
        group = f"exit:{position.session_date.isoformat()}"
        closable, stranded = [], []
        for held in book.positions():
            if abs(held.units) < held.contract.lot_size:
                continue
            listed = (
                session.universe.by_symbol(held.contract.trading_symbol) is not None
                if session is not None
                else True
            )
            (closable if listed else stranded).append(held)
        if stranded:
            self._log(
                position.session_date,
                rule="leg_unlisted_today",
                outcome="declined",
                detail={
                    "minute": minute.isoformat(),
                    "symbols": [h.contract.trading_symbol for h in stranded],
                },
            )
        intents = [
            TradeIntent(
                trading_symbol=held.contract.trading_symbol,
                side=Side.BUY if held.units < 0 else Side.SELL,
                lots=abs(held.units) // held.contract.lot_size,
                tag=rule,
                leg_group=(f"{group}:{held.contract.trading_symbol}" if split_legs else group),
            )
            for held in closable
        ]
        if not intents and book.positions():
            # Something is held that cannot be closed — a leg whose remaining size is under
            # one lot. Recorded rather than retried silently.
            self._log(
                position.session_date,
                rule="unclosable_residual",
                outcome="declined",
                detail={"minute": minute.isoformat()},
            )
        self._log(
            position.session_date,
            rule=rule,
            outcome="exit_requested",
            detail={"minute": minute.isoformat(), "estimated_pnl": pnl, **(detail or {})},
        )
        return tuple(intents)

    # ------------------------------------------------------------------ entry

    def _maybe_enter(self, session: SessionView, minute: dt.datetime) -> Sequence[TradeIntent]:
        params = self.params
        session_date = session.session_date
        if self._traded_today == session_date:
            return ()
        if not (params.entry_time <= minute.time() <= params.entry_deadline):
            return ()

        expiry = session.universe.nearest_expiry(session_date)
        if expiry is None:
            return ()
        days_to_expiry = (expiry - session_date).days
        if days_to_expiry not in params.allowed_dte:
            return ()

        spot = session.spot_at(minute)
        if spot is None or spot <= 0:
            return ()

        structure = self._select(session, minute, expiry, spot, days_to_expiry)
        if isinstance(structure, str):
            return self._decline(session_date, structure, {})

        credit = structure["credit_per_unit"]
        if credit < params.min_credit_pct_of_spot * spot:
            return self._decline(
                session_date,
                "credit_too_thin",
                {"credit_per_unit": credit, "required": params.min_credit_pct_of_spot * spot},
            )

        lot_size = structure["lot_size"]
        lots = int(params.target_notional / (spot * lot_size))
        if lots <= 0:
            return self._decline(session_date, "size_below_one_lot", {})

        group = f"entry:{session_date.isoformat()}"
        intents = tuple(
            TradeIntent(
                trading_symbol=structure["symbols"][role],
                side=Side.SELL,
                lots=lots,
                tag="entry",
                leg_group=group,
            )
            for role in ("short_call", "short_put")
        )
        self._position = _OpenPosition(
            session_date=session_date,
            expiry=expiry,
            entry_minute=minute,
            entry_spot=spot,
            lots=lots,
            lot_size=lot_size,
            legs=dict(structure["symbols"]),
            strikes=dict(structure["strikes"]),
            credit_per_unit=credit,
        )
        self._traded_today = session_date
        self._log(
            session_date,
            rule="entry",
            outcome="entered",
            detail={
                "minute": minute.isoformat(),
                "dte": days_to_expiry,
                "spot": spot,
                "lots": lots,
                "credit_per_unit": credit,
                "credit_pct_of_spot": credit / spot,
                "strikes": structure["strikes"],
                "deltas": structure["deltas"],
            },
        )
        return intents

    def _select(
        self,
        session: SessionView,
        minute: dt.datetime,
        expiry: dt.date,
        spot: float,
        days_to_expiry: int,
    ) -> dict[str, Any] | str:
        """The strike on each side whose delta is nearest the target and inside the band."""
        params = self.params
        low, high = params.delta_band
        t_years = year_fraction(
            minute_hour=minute.hour + minute.minute / 60.0, days_to_expiry=days_to_expiry
        )
        chosen: dict[str, Any] = {"symbols": {}, "strikes": {}, "deltas": {}}
        prices: dict[str, float] = {}
        lot_size = 0
        for role, option_type, direction in (
            ("short_call", OptionType.CALL, 1.0),
            ("short_put", OptionType.PUT, -1.0),
        ):
            best: tuple[float, float, str, float] | None = None
            for strike in session.universe.strikes(expiry):
                if (strike - spot) * direction <= 0:
                    continue  # out of the money only
                contract = session.universe.get(expiry, strike, option_type)
                if contract is None:
                    continue
                bar = session.bar(contract.trading_symbol, minute)
                if bar is None or not bar.iv or bar.iv <= 0 or bar.close <= 0:
                    continue
                delta = abs(
                    bs_delta(
                        option_type=option_type,
                        spot=spot,
                        strike=strike,
                        t_years=t_years,
                        iv=bar.iv,
                    )
                )
                if not (low <= delta <= high):
                    continue
                distance = abs(delta - params.short_delta_target)
                if best is None or distance < best[0]:
                    best = (distance, strike, contract.trading_symbol, delta)
                    lot_size = contract.lot_size
            if best is None:
                return "no_strike_in_delta_band"
            _d, strike, symbol, delta = best
            chosen["symbols"][role] = symbol
            chosen["strikes"][role] = strike
            chosen["deltas"][role] = delta
            bar = session.bar(symbol, minute)
            prices[role] = bar.close  # type: ignore[union-attr]

        chosen["credit_per_unit"] = prices["short_call"] + prices["short_put"]
        chosen["lot_size"] = lot_size
        return chosen

    # ------------------------------------------------------------------ journal

    def _decline(
        self, session_date: dt.date, rule: str, detail: dict[str, Any]
    ) -> tuple[TradeIntent, ...]:
        self._log(session_date, rule=rule, outcome="declined", detail=detail)
        return ()

    def _log(
        self, session_date: dt.date, *, rule: str, outcome: str, detail: dict[str, Any]
    ) -> None:
        self._journal.append(
            {
                "session_date": session_date.isoformat(),
                "rule": rule,
                "outcome": outcome,
                "detail": detail,
            }
        )
