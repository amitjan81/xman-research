"""A dynamic strangle: sell each leg only when the index comes to it.

The static strangle sells both legs at one moment and then hopes the index stays between
them. This sells the call **when NIFTY reaches the top of a range** and the put **when it
reaches the bottom**, so a leg is only ever short after the index has already travelled
towards it.

**Two mechanisms pull in opposite directions, which is why this is worth measuring rather
than arguing about.**

*For it.* A call sold after a rally is sold richer — higher delta, usually higher implied
volatility — so the same strike distance pays more premium. And on a trending session only
one leg ever triggers, which is precisely the session where a static strangle is fully
loaded on the side that is about to run.

*Against it.* The upper bound is where a breakout starts. Selling the call there is selling
into the arrival of momentum, at the worst price, and the days the range fails are the days
the loss is largest. On the days the range holds, only one leg triggers and the credit is
roughly half.

Three ways to draw the range are implemented, because the choice is most of the strategy:

``RangeMethod.OPENING_RANGE``
    The high and low of the session's first minutes. Self-calibrating — a quiet morning
    gives a narrow range and a violent one a wide range — and it uses nothing but spot.

``RangeMethod.PERCENT_FROM_OPEN``
    A fixed percentage either side of the opening print. The simplest possible rule and the
    right control for the other two: if neither beats it, the range is not adding anything.

``RangeMethod.IV_MOVE``
    The market's own expected move, from the at-the-money implied volatility at the entry
    window's start, scaled to the time left in the session. Selling the call at one expected
    move is selling after the index has already done what the option market priced for the
    whole day.
"""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from xman_research.backtest.costs import Side
from xman_research.backtest.engine import BookView, TradeIntent
from xman_research.backtest.market import OptionType, SessionView
from xman_research.intraday.window_stats import WindowStats
from xman_research.overlay.greeks import bs_delta, year_fraction

__all__ = ["DynamicParameters", "DynamicStrangle", "RangeMethod"]


class RangeMethod(StrEnum):
    OPENING_RANGE = "opening_range"
    PERCENT_FROM_OPEN = "percent_from_open"
    IV_MOVE = "iv_move"
    ATR_WINDOW = "atr_window"
    """The mean 10:00-15:00 range of the last N sessions, applied to today's 10:00 print.

    Measured on the *window*, not the session: a whole-day ATR includes the opening gap and
    the closing half hour, and this strategy is exposed to neither."""
    BOLLINGER = "bollinger"
    """Standard deviations of the last N sessions' in-window close-to-open move.

    The Bollinger idea adapted to the scenario: the centre is today's 10:00 print rather than
    a moving average, because the position is opened from there and it is distance from *that*
    price which decides whether a leg is sold."""


@dataclass(frozen=True, slots=True)
class DynamicParameters:
    """The range, the strike, the stop, and the clock."""

    range_method: RangeMethod = RangeMethod.OPENING_RANGE
    opening_range_until: dt.time = dt.time(10, 0)
    """For OPENING_RANGE: the high and low up to this time define the band."""
    range_width_pct: float = 0.004
    """For PERCENT_FROM_OPEN: half-width as a fraction of the opening print."""
    iv_move_multiple: float = 1.0
    """For IV_MOVE: how many expected moves from the open the bound sits at."""
    lookback_sessions: int = 14
    """For ATR_WINDOW and BOLLINGER: how many prior sessions the statistic is taken over."""
    atr_multiple: float = 1.0
    """For ATR_WINDOW: bounds at this multiple of the average in-window range."""
    bollinger_sigma: float = 1.5
    """For BOLLINGER: bounds at this many standard deviations of the in-window move."""

    short_delta_target: float = 0.15
    delta_band: tuple[float, float] = (0.11, 0.19)

    arm_time: dt.time = dt.time(10, 0)
    """Nothing is sold before this: the range has to exist first."""
    last_entry_time: dt.time = dt.time(14, 30)
    """A leg sold later than this has too little time left to decay and too little time to
    be stopped out of sensibly."""

    stop_move_pct: float = 0.0075
    """Per leg, measured from the price at which that leg was sold. A call sold at the upper
    bound is stopped if the index runs a further 0.75%."""
    profit_take_pct: float = 0.90
    exit_time: dt.time = dt.time(15, 15)
    exit_start_time: dt.time = dt.time(15, 0)

    allowed_dte: tuple[int, ...] = (0,)
    target_notional: float = 10_000_000.0
    min_credit_pct_of_spot: float = 0.0001
    one_touch_per_side: bool = True
    """Sell each side at most once a session. Without it a choppy session re-sells the same
    leg every time the index crosses back, which is a different strategy — a mean-reversion
    scalper — and one this study is not testing."""


@dataclass
class _Leg:
    """One sold side, and the facts its exit rules measure against."""

    role: str
    symbol: str
    strike: float
    lots: int
    lot_size: int
    entry_minute: dt.datetime
    entry_spot: float
    credit_per_unit: float
    exit_rule: str | None = None

    @property
    def units(self) -> int:
        return self.lots * self.lot_size


@dataclass
class DynamicStrangle:
    """Sell the call at the top of the range, the put at the bottom, each on its own."""

    params: DynamicParameters = field(default_factory=DynamicParameters)
    window_stats: WindowStats | None = None
    """Required by ATR_WINDOW and BOLLINGER; unused by the other three methods."""

    _session: dt.date | None = field(default=None, init=False, repr=False)
    _bounds: tuple[float, float] | None = field(default=None, init=False, repr=False)
    _legs: dict[str, _Leg] = field(default_factory=dict, init=False, repr=False)
    _sold_today: set[str] = field(default_factory=set, init=False, repr=False)
    _closed: list[dict[str, Any]] = field(default_factory=list, init=False, repr=False)
    _journal: list[dict[str, Any]] = field(default_factory=list, init=False, repr=False)

    @property
    def name(self) -> str:
        return "intraday_dynamic_strangle"

    def parameters(self) -> Mapping[str, Any]:
        params = self.params
        return {
            "range_method": str(params.range_method),
            "opening_range_until": params.opening_range_until.isoformat(),
            "range_width_pct": params.range_width_pct,
            "iv_move_multiple": params.iv_move_multiple,
            "short_delta_target": params.short_delta_target,
            "arm_time": params.arm_time.isoformat(),
            "stop_move_pct": params.stop_move_pct,
            "profit_take_pct": params.profit_take_pct,
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
        self._roll_session(session, minute)
        intents: list[TradeIntent] = []
        intents.extend(self._manage(session, minute, book))
        if not intents:
            intents.extend(self._maybe_sell(session, minute))
        return tuple(intents)

    # ------------------------------------------------------------------ session state

    def _roll_session(self, session: SessionView, minute: dt.datetime) -> None:
        """A new session resets the range and the per-side locks."""
        if self._session == session.session_date:
            return
        self._session = session.session_date
        self._bounds = None
        self._legs = {}
        self._sold_today = set()

    def _range(self, session: SessionView, minute: dt.datetime) -> tuple[float, float] | None:
        """The band, computed once a session and then held."""
        if self._bounds is not None:
            return self._bounds
        params = self.params
        # **The opening range is not complete until its window has closed.** Arming at 10:00
        # while the window runs to 11:00 silently truncated the range at the arm time, so
        # three different cutoffs produced byte-identical results — the tell that caught it.
        armed_from = (
            max(params.arm_time, params.opening_range_until)
            if params.range_method is RangeMethod.OPENING_RANGE
            else params.arm_time
        )
        if minute.time() < armed_from:
            return None
        spot = session.spot_at(minute)
        if spot is None or spot <= 0:
            return None

        if params.range_method is RangeMethod.OPENING_RANGE:
            prints: list[float] = []
            for candidate in session.minutes():
                if candidate.time() > params.opening_range_until:
                    break
                value = session.spot_at(candidate)
                if value:
                    prints.append(value)
            if len(prints) < 5:
                return None
            self._bounds = (min(prints), max(prints))
        elif params.range_method is RangeMethod.PERCENT_FROM_OPEN:
            opening = session.spot_at(session.minutes()[0]) or spot
            self._bounds = (
                opening * (1.0 - params.range_width_pct),
                opening * (1.0 + params.range_width_pct),
            )
        elif params.range_method in (RangeMethod.ATR_WINDOW, RangeMethod.BOLLINGER):
            if self.window_stats is None:
                return None
            bands = self.window_stats.bands_for(
                session.session_date, lookback=params.lookback_sessions
            )
            # **The anchor is the 10:00 print, not the session open.** The position is opened
            # from where the index is when the window starts, so it is distance from there
            # that decides whether a bound is touched.
            if params.range_method is RangeMethod.ATR_WINDOW:
                width = None if bands.atr_pct is None else bands.atr_pct * params.atr_multiple
            else:
                width = (
                    None
                    if bands.sigma_pct is None
                    else bands.sigma_pct * params.bollinger_sigma
                )
            if width is None or width <= 0:
                return None
            self._bounds = (spot * (1.0 - width), spot * (1.0 + width))
            self._log(
                session.session_date,
                rule="range_set",
                outcome="armed",
                detail={
                    "minute": minute.isoformat(),
                    "lower": self._bounds[0],
                    "upper": self._bounds[1],
                    "width_pct": 2 * width,
                    "anchor": spot,
                    "lookback_observations": bands.observations,
                    "atr_pct": bands.atr_pct,
                    "sigma_pct": bands.sigma_pct,
                },
            )
            return self._bounds
        else:  # IV_MOVE
            opening = session.spot_at(session.minutes()[0]) or spot
            implied = self._atm_iv(session, minute)
            if implied is None:
                return None
            # Time left in the session, as a fraction of a trading year.
            closing = dt.datetime.combine(
                session.session_date, dt.time(15, 30), tzinfo=minute.tzinfo
            )
            hours_left = max((closing - minute).total_seconds() / 3600.0, 0.25)
            t_years = hours_left / (6.25 * 252.0)
            move = opening * implied * math.sqrt(t_years) * params.iv_move_multiple
            self._bounds = (opening - move, opening + move)
        self._log(
            session.session_date,
            rule="range_set",
            outcome="armed",
            detail={
                "minute": minute.isoformat(),
                "lower": self._bounds[0],
                "upper": self._bounds[1],
                "width_pct": (self._bounds[1] - self._bounds[0]) / spot,
            },
        )
        return self._bounds

    def _atm_iv(self, session: SessionView, minute: dt.datetime) -> float | None:
        expiry = session.universe.nearest_expiry(session.session_date)
        spot = session.spot_at(minute)
        if expiry is None or not spot:
            return None
        strike = session.universe.atm_strike(spot, expiry)
        if strike is None:
            return None
        values = []
        for option_type in (OptionType.CALL, OptionType.PUT):
            contract = session.universe.get(expiry, strike, option_type)
            if contract is None:
                continue
            bar = session.bar(contract.trading_symbol, minute)
            if bar is not None and bar.iv and bar.iv > 0:
                values.append(bar.iv)
        return sum(values) / len(values) if values else None

    # ------------------------------------------------------------------ management

    def _manage(
        self, session: SessionView, minute: dt.datetime, book: BookView
    ) -> list[TradeIntent]:
        """Each leg is stopped, taken or closed on its own — they were sold on their own."""
        params = self.params
        if not self._legs:
            return []
        spot = session.spot_at(minute)
        intents: list[TradeIntent] = []
        for role, leg in list(self._legs.items()):
            position = book.position(leg.symbol)
            if position is None or abs(position.units) < leg.lot_size:
                self._record(leg, session, minute, leg.exit_rule or "filled_away")
                self._legs.pop(role, None)
                continue

            rule: str | None = None
            if minute.time() >= params.exit_start_time:
                rule = "exit_time"
            elif spot and self._stopped(leg, spot):
                rule = "stop_spot_move"
            else:
                bar = session.bar(leg.symbol, minute)
                if bar is not None:
                    captured = (leg.credit_per_unit - bar.close) / leg.credit_per_unit
                    if captured >= params.profit_take_pct:
                        rule = "profit_take"
            if rule is None:
                continue
            leg.exit_rule = rule
            intents.append(
                TradeIntent(
                    trading_symbol=leg.symbol,
                    side=Side.BUY,
                    lots=abs(position.units) // leg.lot_size,
                    tag=rule,
                    leg_group=f"exit:{role}:{session.session_date.isoformat()}",
                )
            )
        return intents

    def _stopped(self, leg: _Leg, spot: float) -> bool:
        """The index has run further in the direction that hurts this leg."""
        move = (spot - leg.entry_spot) / leg.entry_spot
        return move >= self.params.stop_move_pct if leg.role == "call" else (
            move <= -self.params.stop_move_pct
        )

    def _record(
        self, leg: _Leg, session: SessionView, minute: dt.datetime, rule: str
    ) -> None:
        self._closed.append(
            {
                "session_date": session.session_date.isoformat(),
                "role": leg.role,
                "symbol": leg.symbol,
                "strike": leg.strike,
                "lots": leg.lots,
                "lot_size": leg.lot_size,
                "entry_minute": leg.entry_minute.isoformat(),
                "exit_minute": minute.isoformat(),
                "entry_spot": leg.entry_spot,
                "credit_per_unit": leg.credit_per_unit,
                "credit_rupees": leg.credit_per_unit * leg.units,
                "exit_rule": rule,
            }
        )

    # ------------------------------------------------------------------ entry

    def _maybe_sell(self, session: SessionView, minute: dt.datetime) -> list[TradeIntent]:
        """Sell a side the moment the index reaches its bound."""
        params = self.params
        armed_from = (
            max(params.arm_time, params.opening_range_until)
            if params.range_method is RangeMethod.OPENING_RANGE
            else params.arm_time
        )
        if not (armed_from <= minute.time() <= params.last_entry_time):
            return []
        expiry = session.universe.nearest_expiry(session.session_date)
        if expiry is None:
            return []
        days_to_expiry = (expiry - session.session_date).days
        if days_to_expiry not in params.allowed_dte:
            return []
        bounds = self._range(session, minute)
        if bounds is None:
            return []
        spot = session.spot_at(minute)
        if spot is None or spot <= 0:
            return []

        lower, upper = bounds
        wanted: list[str] = []
        if spot >= upper and "call" not in self._sold_today:
            wanted.append("call")
        if spot <= lower and "put" not in self._sold_today:
            wanted.append("put")
        if not wanted:
            return []

        intents: list[TradeIntent] = []
        for role in wanted:
            option_type = OptionType.CALL if role == "call" else OptionType.PUT
            selected = self._select(session, minute, expiry, spot, days_to_expiry, option_type)
            if selected is None:
                self._log(
                    session.session_date,
                    rule="no_strike_in_delta_band",
                    outcome="declined",
                    detail={"role": role, "minute": minute.isoformat()},
                )
                continue
            symbol, strike, credit, delta, lot_size = selected
            if credit < params.min_credit_pct_of_spot * spot:
                self._log(
                    session.session_date,
                    rule="credit_too_thin",
                    outcome="declined",
                    detail={"role": role, "credit": credit},
                )
                continue
            lots = int(params.target_notional / (spot * lot_size))
            if lots <= 0:
                continue
            intents.append(
                TradeIntent(
                    trading_symbol=symbol,
                    side=Side.SELL,
                    lots=lots,
                    tag=f"sell_{role}",
                    leg_group=f"entry:{role}:{session.session_date.isoformat()}",
                )
            )
            self._legs[role] = _Leg(
                role=role,
                symbol=symbol,
                strike=strike,
                lots=lots,
                lot_size=lot_size,
                entry_minute=minute,
                entry_spot=spot,
                credit_per_unit=credit,
            )
            if params.one_touch_per_side:
                self._sold_today.add(role)
            self._log(
                session.session_date,
                rule=f"sell_{role}",
                outcome="entered",
                detail={
                    "minute": minute.isoformat(),
                    "spot": spot,
                    "bound": upper if role == "call" else lower,
                    "strike": strike,
                    "delta": delta,
                    "credit_per_unit": credit,
                    "credit_pct_of_spot": credit / spot,
                    "dte": days_to_expiry,
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
        option_type: str,
    ) -> tuple[str, float, float, float, int] | None:
        params = self.params
        low, high = params.delta_band
        t_years = year_fraction(
            minute_hour=minute.hour + minute.minute / 60.0, days_to_expiry=days_to_expiry
        )
        direction = 1.0 if option_type == OptionType.CALL else -1.0
        best: tuple[float, str, float, float, int] | None = None
        for strike in session.universe.strikes(expiry):
            if (strike - spot) * direction <= 0:
                continue
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
                best = (distance, contract.trading_symbol, strike, bar.close, contract.lot_size)
        if best is None:
            return None
        _d, symbol, strike, price, lot_size = best
        delta = params.short_delta_target
        return symbol, strike, price, delta, lot_size

    # ------------------------------------------------------------------ journal

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
