"""Section 4 of the requirements, as a strategy the engine can run.

Every rule carries its requirement ID in the code that implements it, and every decision —
including the ones that decline to trade — is appended to :attr:`IndexOptionOverlay.journal`
with that ID, because ST-9 and AC-3 both ask for the *outcome* of a filter to be recorded
whether or not an entry followed. The journal is what the report's filter table is built
from; nothing in it is reconstructed after the fact.

**What is implemented, what is substituted, and what is absent** — the report repeats this
list, and it is kept here so the code and the report cannot drift:

* ST-3 entry window, ST-4 exit deadline, ST-5..ST-8 structure and credit test, ST-10..ST-13
  filters, ST-17..ST-21 management, ST-32/ST-33 risk budget: implemented.
* ST-10's VIX limb is substituted by an IV-percentile computed from the corpus itself; see
  :mod:`xman_research.overlay.context`.
* ST-14..ST-16 event calendar: the mechanism is implemented and takes a calendar, but no
  event source exists in this corpus, so the default calendar is empty and every week is
  treated as a normal week. The document's own fallback (missing calendar -> HALF) is not
  applied, because halving every week of a five-year run would be a different strategy
  rather than a conservative version of this one. Runs are stamped accordingly.
* ST-24..ST-27 tail hedge: absent. The corpus carries only the nearest weekly expiry and a
  +/-2.3% strike band, so a 9%-out-of-the-money monthly put cannot be priced at all. The
  overlay is therefore reported unhedged, with the hedge's drag sized separately.
* ST-30/ST-31 intraday margin monitoring and shortfall reduction: absent. Both are driven
  by broker-reported blocked margin and collateral value, neither of which exists
  historically. Their effect would be to *reduce* positions in stressed weeks, so their
  absence flatters a drawdown and is stated rather than modelled.

**Why this class is mutable.** A condor is a five-session commitment whose management rules
read the credit received at entry, and :class:`~xman_research.backtest.engine.Position`
records only units and the last mark — the entry price is not recoverable from the book. The
cycle state therefore lives here. The engine calls :meth:`decide` once per decision minute in
chronological order and nothing else touches the instance, so the run stays deterministic.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Any

from xman_research.backtest.costs import Side
from xman_research.backtest.engine import BookView, TradeIntent
from xman_research.backtest.market import OptionType, SessionView
from xman_research.overlay.context import DailyContext
from xman_research.overlay.greeks import bs_delta, year_fraction
from xman_research.overlay.sizing import (
    AllocationInputs,
    CollateralAssumption,
    MarginPerLotModel,
    allocate,
)

__all__ = ["CycleState", "IndexOptionOverlay", "OverlayParameters"]

#: Order matters: ST-38 requires the long legs to be filled before or together with their
#: shorts. The engine fills a leg group atomically, so "together" already holds, and the
#: order below makes "before" true of the sequence as well — which is what an execution
#: trace has to show to be auditable against the rule.
_LEG_ROLES = ("long_call", "long_put", "short_call", "short_put")


@dataclass(frozen=True, slots=True)
class OverlayParameters:
    """Section 9's register, with the document's defaults.

    ``min_credit_ratio`` leads at the allowed floor rather than at the 0.20% default: the
    0.12-delta structure's achievable net credit is measured at 0.12-0.17% of notional, so
    the default gate refuses almost every week. The run sweeps the range and the report
    shows what each level costs.
    """

    short_delta_target: float = 0.12
    delta_band: tuple[float, float] = (0.10, 0.14)
    wing_width: float = 350.0
    wing_width_band: tuple[float, float] = (300.0, 400.0)
    min_credit_ratio: float = 0.0010
    entry_dte: tuple[int, ...] = (5, 6)
    entry_window: tuple[dt.time, dt.time] = (dt.time(9, 20), dt.time(14, 30))
    gap_delay_until: dt.time = dt.time(11, 0)
    exit_time: dt.time = dt.time(15, 15)
    """ST-4's deadline: fully closed no later than this, on the session before expiry."""
    exit_attempt_from: dt.time = dt.time(14, 0)
    """When the closing attempts begin.

    ST-4 says "no later than 15:15", and a single attempt at 15:15 is not the same thing
    as meeting that deadline: a four-leg group needs every leg to print in the same minute,
    and a far-out wing does not always oblige. Attempting from 14:30 gives the group
    several minutes inside the rule rather than one minute at its edge. The first E2E run
    over 2026 Q1 carried a position into expiry morning for exactly this reason, and a
    2022 session then failed to settle at all because its 15:00-15:30 window was one bar
    short — a fixed rule broken by an execution detail, twice over."""
    ivp_floor: float = 30.0
    trend_band: float = 0.04
    gap_limit: float = 0.01
    profit_take: float = 0.60
    stop_multiple: float = 1.5
    roll_trigger_delta: float = 0.28
    weekly_loss_cap: float = 0.02
    monthly_loss_cap: float = 0.04
    dd_half_trigger: float = 0.08
    dd_stop_trigger: float = 0.12
    half_period_weeks: int = 8
    max_lots_absolute: int = 50


@dataclass
class CycleState:
    """One Core Position, from entry to the rule that closed it."""

    expiry: dt.date
    entry_date: dt.date
    entry_minute: dt.datetime
    lots: int
    lot_size: int
    legs: dict[str, str]
    strikes: dict[str, float]
    entry_credit_per_unit: float
    """The credit received at entry, per unit. **Fixed for the life of the cycle.**

    ST-17 and ST-19 are both stated as multiples of "net credit received", which is an
    entry-time quantity. Folding a roll's cash flow into it — the first shape this took —
    made the stop threshold move with the adjustment, and a roll that cost more than the
    credit flipped the threshold's sign and closed the position on its next evaluation.
    Adjustments are accounted in :attr:`adjustment_cost_per_unit` instead, where they
    belong: in the P&L, not in the specification's basis."""
    entry_spot: float
    wing_width: float
    half_reason: str | None
    adjustment_cost_per_unit: float = 0.0
    rolled: bool = False
    exit_requested: bool = False
    exit_rule: str | None = None
    exit_estimate: float | None = None

    @property
    def units(self) -> int:
        return self.lots * self.lot_size

    @property
    def credit_rupees(self) -> float:
        """The entry credit in rupees — the basis ST-17 and ST-19 are stated against."""
        return self.entry_credit_per_unit * self.units


@dataclass
class IndexOptionOverlay:
    """The Strategy Service, section 4, for one underlying."""

    context: DailyContext
    params: OverlayParameters = field(default_factory=OverlayParameters)
    collateral: CollateralAssumption = field(default_factory=CollateralAssumption)
    margin_model: MarginPerLotModel = field(default_factory=MarginPerLotModel)
    wing_policy: str = "observed"
    """How the long wings are chosen.

    ``"spec"`` takes :attr:`OverlayParameters.wing_width` unconditionally and relies on the
    session frame carrying a bar for it, modelled where the capture printed none (see
    :mod:`xman_research.overlay.synthetic`).

    ``"observed"`` takes the widest wing inside the allowed band that **actually printed**
    at the entry minute — a bar carrying an implied volatility, which modelled bars do not.
    The entry structure is then priced end to end from real trades.

    *Both* policies read modelled bars after entry, and that is not a softening of the
    distinction but a consequence of the corpus: the captured strike band follows spot, so
    a wing bought on Monday can be outside the band by Wednesday and have neither a price
    nor even an instrument-master row that day. A run without the modelled extension
    therefore cannot close its own positions — measured, not assumed: the fully observed
    five-year arm failed on 2022-11-02 with the exit leg unlisted, and the position ran to
    cash settlement. What "observed" can honestly mean for a five-session hold is that
    every price the *decision* rested on was printed."""
    event_calendar: Mapping[dt.date, str] = field(default_factory=dict)
    min_wing_width: float = 100.0
    """Below this the structure stops being the document's condor; the week is skipped and
    counted. Only consulted under ``wing_policy="observed"``."""

    _cycle: CycleState | None = field(default=None, init=False, repr=False)
    _traded: set[dt.date] = field(default_factory=set, init=False, repr=False)
    _closed: list[dict[str, Any]] = field(default_factory=list, init=False, repr=False)
    _journal: list[dict[str, Any]] = field(default_factory=list, init=False, repr=False)
    _halved_until: dt.date | None = field(default=None, init=False, repr=False)
    _peak_equity: float = field(default=0.0, init=False, repr=False)
    _running_pnl: float = field(default=0.0, init=False, repr=False)
    _halted: bool = field(default=False, init=False, repr=False)

    # ------------------------------------------------------------------ engine surface

    @property
    def name(self) -> str:
        return "index_option_overlay"

    def parameters(self) -> Mapping[str, Any]:
        params = self.params
        return {
            "short_delta_target": params.short_delta_target,
            "delta_band": list(params.delta_band),
            "wing_width": params.wing_width,
            "wing_policy": self.wing_policy,
            "min_credit_ratio": params.min_credit_ratio,
            "entry_dte": list(params.entry_dte),
            "profit_take": params.profit_take,
            "stop_multiple": params.stop_multiple,
            "roll_trigger_delta": params.roll_trigger_delta,
            "ivp_floor": params.ivp_floor,
            "trend_band": params.trend_band,
            "gap_limit": params.gap_limit,
            "weekly_loss_cap": params.weekly_loss_cap,
            "monthly_loss_cap": params.monthly_loss_cap,
            "dd_half_trigger": params.dd_half_trigger,
            "dd_stop_trigger": params.dd_stop_trigger,
            "portfolio_capital": self.collateral.portfolio_capital,
            "margin_assumptions": self.margin_model.assumptions,
            "event_calendar_entries": len(self.event_calendar),
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
        self._reconcile(book, session, minute)
        if self._cycle is not None:
            return self._manage(session, minute, book)
        if self._halted:
            return ()
        return self._maybe_enter(session, minute)

    # ------------------------------------------------------------------ book reconciliation

    def _reconcile(self, book: BookView, session: SessionView, minute: dt.datetime) -> None:
        """Notice that the engine closed what this strategy asked it to close.

        The engine never reports fills back to a strategy, so the book is the only evidence
        available. A cycle is closed when the book is **empty** — not when the book stops
        carrying the four legs the cycle currently names. The difference is a bug that
        reached the five-year run: a half-filled roll leaves the *old* legs in the book
        while the cycle names the *new* ones, the cycle looked closed, and the residual was
        never offered for sale again. It then ran into cash settlement in September 2022
        and took the whole arm down with it. One strategy instance holds one structure, so
        "the book is empty" is the honest test.

        The P&L recorded here is this strategy's own mark-based estimate and is used only
        for the risk budget (ST-32/ST-33); every rupee in the report comes from the engine's
        fills instead.
        """
        cycle = self._cycle
        if cycle is None:
            return
        if book.positions():
            return
        if not cycle.exit_requested:
            # The book never held this cycle at all: the entry group was unfillable. It is
            # recorded so the count of entries and the count of positions can disagree
            # visibly rather than silently.
            cycle.exit_rule = "ST-39_entry_never_filled"
            cycle.exit_estimate = 0.0
        estimate = cycle.exit_estimate
        if estimate is None:
            estimate = 0.0
        self._running_pnl += estimate
        self._peak_equity = max(self._peak_equity, self._running_pnl)
        self._closed.append(
            {
                "expiry": cycle.expiry.isoformat(),
                "entry_date": cycle.entry_date.isoformat(),
                "exit_date": session.session_date.isoformat(),
                "exit_minute": minute.isoformat(),
                "lots": cycle.lots,
                "lot_size": cycle.lot_size,
                "wing_width": cycle.wing_width,
                "strikes": dict(cycle.strikes),
                "entry_credit_per_unit": cycle.entry_credit_per_unit,
                "adjustment_cost_per_unit": cycle.adjustment_cost_per_unit,
                "credit_rupees": cycle.credit_rupees,
                "exit_rule": cycle.exit_rule,
                "estimated_pnl": estimate,
                "rolled": cycle.rolled,
                "half_reason": cycle.half_reason,
            }
        )
        self._cycle = None

    # ------------------------------------------------------------------ management

    def _manage(
        self, session: SessionView, minute: dt.datetime, book: BookView
    ) -> Sequence[TradeIntent]:
        cycle = self._cycle
        assert cycle is not None
        params = self.params
        days_left = (cycle.expiry - session.session_date).days

        # ST-22, enforced against reality rather than intent: if the book is not the four
        # legs this cycle describes — a half-filled roll is how that happens — the position
        # is no longer the structure the requirements define, and the only rule that can
        # honestly be applied to it is "close it".
        held = {position.contract.trading_symbol for position in book.positions()}
        if held and held != set(cycle.legs.values()):
            return self._close(cycle, "ST-22_structure_mismatch_unwind", None, book)
        marks = self._marks(session, minute, cycle)
        pnl = None if marks is None else self._unrealised(cycle, marks)

        # ST-4 is fixed and outranks every other rule: a Core Position may not be carried
        # into expiry day. The comparison is >= so that a session whose 15:15 print is
        # missing still exits at the next decision minute that has one.
        if days_left <= 0 or (days_left == 1 and minute.time() >= params.exit_attempt_from):
            rule = "ST-4_time_exit"
            if days_left <= 0:
                # The deadline has already passed: the close was attempted on the prior
                # session and did not complete. Recorded as a breach of a fixed rule
                # rather than absorbed, because that is what it is.
                rule = "ST-4_deadline_missed"
            return self._close(cycle, rule, pnl, book, split_groups=days_left <= 0)

        if pnl is not None:
            if pnl <= -params.stop_multiple * cycle.credit_rupees:
                return self._close(cycle, "ST-19_weekly_stop", pnl, book)
            if pnl >= params.profit_take * cycle.credit_rupees:
                return self._close(cycle, "ST-17_profit_target", pnl, book)
            breach = self._risk_budget_breach(session.session_date, pnl)
            if breach is not None:
                return self._close(cycle, breach, pnl, book)

        # ST-20/ST-21: the tested side is the one whose short delta has run. A first touch
        # rolls, a second closes. The roll is emitted as one group with the untested side's
        # move, so the book never sits half-rolled.
        touched = self._tested_side(session, minute, cycle)
        if touched is not None:
            if cycle.rolled:
                return self._close(cycle, "ST-21_second_touch", pnl, book)
            rolled = self._roll(session, minute, cycle, touched, book)
            if rolled:
                return rolled
        return ()

    def _marks(
        self, session: SessionView, minute: dt.datetime, cycle: CycleState
    ) -> dict[str, float] | None:
        marks: dict[str, float] = {}
        for role, symbol in cycle.legs.items():
            bar = session.bar(symbol, minute)
            if bar is None:
                return None
            marks[role] = bar.close
        return marks

    def _unrealised(self, cycle: CycleState, marks: Mapping[str, float]) -> float:
        """Realised-plus-unrealised P&L per ST-19, in rupees, before statutory costs.

        ``adjustment_cost_per_unit`` carries whatever a roll cost, so a rolled position's
        stop measures the loss the *cycle* is carrying rather than the loss its current
        legs happen to show."""
        cost_to_close = (
            marks["short_call"] + marks["short_put"] - marks["long_call"] - marks["long_put"]
        )
        net = cycle.entry_credit_per_unit - cycle.adjustment_cost_per_unit - cost_to_close
        return net * cycle.units

    def _tested_side(
        self, session: SessionView, minute: dt.datetime, cycle: CycleState
    ) -> str | None:
        days_left = (cycle.expiry - session.session_date).days
        spot = session.spot_at(minute)
        if spot is None or spot <= 0:
            return None
        t_years = year_fraction(
            minute_hour=minute.hour + minute.minute / 60.0, days_to_expiry=days_left
        )
        worst: tuple[float, str] | None = None
        for role, option_type in (("short_call", OptionType.CALL), ("short_put", OptionType.PUT)):
            bar = session.bar(cycle.legs[role], minute)
            if bar is None or bar.iv is None or bar.iv <= 0:
                continue
            delta = abs(
                bs_delta(
                    option_type=option_type,
                    spot=spot,
                    strike=cycle.strikes[role],
                    t_years=t_years,
                    iv=bar.iv,
                )
            )
            if delta >= self.params.roll_trigger_delta and (worst is None or delta > worst[0]):
                worst = (delta, role)
        return None if worst is None else worst[1]

    def _close(
        self,
        cycle: CycleState,
        rule: str,
        pnl: float | None,
        book: BookView,
        *,
        split_groups: bool = False,
    ) -> Sequence[TradeIntent]:
        """Ask the engine to flatten the cycle.

        ``split_groups`` is the expiry-morning path, and it exists because a four-leg group
        is all-or-nothing: one leg that cannot fill — a quiet minute, a participation cap,
        a wing the capture never printed — blocks the other three, and the position then
        runs into cash settlement, which is the outcome ST-4 exists to prevent. On expiry
        day the shorts are therefore offered as their own group and the wings as another.
        Closing the shorts alone can only *reduce* risk: what is left is long options,
        already paid for. Closing the wings alone could leave a naked short, so the shorts
        go first and the wings follow in the same minute."""
        cycle.exit_requested = True
        cycle.exit_rule = rule
        if pnl is not None:
            cycle.exit_estimate = pnl
        expiry = cycle.expiry.isoformat()
        group = f"exit:{expiry}"
        intents: list[TradeIntent] = []
        # **Every open position, not only the four this cycle believes it holds.** A roll is
        # an eight-leg group and the participation caps resize a group to its smallest
        # fillable leg, so a roll can half-execute: part of the old structure closed, part
        # of the new one opened, and the remainder left in the book under no role at all.
        # In September 2022 that remainder was never offered for sale again and ran into
        # cash settlement — the ST-4 breach that took a whole five-year run down with it.
        # Closing what the *book* holds cannot have that failure mode.
        #
        # Shorts first, because they are the legs that carry risk; on the expiry-morning
        # path they are also their own group, so they can close even when a wing cannot.
        shorts = [position for position in book.positions() if position.units < 0]
        longs = [position for position in book.positions() if position.units > 0]
        for position in shorts + longs:
            lots = abs(position.units) // position.contract.lot_size
            if lots <= 0:
                continue
            side = Side.BUY if position.units < 0 else Side.SELL
            leg_group = group
            if split_groups:
                leg_group = f"{group}:{'short' if position.units < 0 else 'long'}"
            intents.append(
                TradeIntent(
                    trading_symbol=position.contract.trading_symbol,
                    side=side,
                    lots=lots,
                    tag=rule,
                    leg_group=leg_group,
                )
            )
        self._log(
            cycle.entry_date,
            rule=rule,
            outcome="exit_requested",
            detail={"expiry": cycle.expiry.isoformat(), "estimated_pnl": pnl},
        )
        return tuple(intents)

    def _roll(
        self,
        session: SessionView,
        minute: dt.datetime,
        cycle: CycleState,
        tested: str,
        book: BookView,
    ) -> Sequence[TradeIntent]:
        """ST-20: move the tested vertical out, the untested one in, in one atomic group.

        The replacement legs must both print at this minute; if either does not, nothing is
        rolled and the rule is re-evaluated at the next decision minute. That is the honest
        behaviour for a corpus with no quotes: a roll that cannot be priced did not happen.
        """
        is_call = tested == "short_call"
        step = cycle.wing_width
        call_roles = ("short_call", "long_call")
        put_roles = ("short_put", "long_put")
        short_role, long_role = call_roles if is_call else put_roles
        other_short, other_long = put_roles if is_call else call_roles
        direction = 1.0 if is_call else -1.0
        strikes = session.universe.strikes(cycle.expiry)
        if not strikes:
            return ()
        spacing = _strike_spacing(strikes)

        new_short = cycle.strikes[short_role] + direction * step
        new_long = new_short + direction * step
        other_new_short = cycle.strikes[other_short] + direction * spacing
        other_new_long = other_new_short - direction * step

        legs: dict[str, tuple[float, str, Side]] = {
            short_role: (new_short, OptionType.CALL if is_call else OptionType.PUT, Side.SELL),
            long_role: (new_long, OptionType.CALL if is_call else OptionType.PUT, Side.BUY),
            other_short: (
                other_new_short,
                OptionType.PUT if is_call else OptionType.CALL,
                Side.SELL,
            ),
            other_long: (
                other_new_long,
                OptionType.PUT if is_call else OptionType.CALL,
                Side.BUY,
            ),
        }
        symbols: dict[str, str] = {}
        for role, (strike, option_type, _side) in legs.items():
            contract = session.universe.get(cycle.expiry, strike, option_type)
            if contract is None:
                return ()
            bar = session.bar(contract.trading_symbol, minute)
            if bar is None:
                return ()
            symbols[role] = contract.trading_symbol

        group = f"roll:{cycle.expiry.isoformat()}"
        intents: list[TradeIntent] = []
        for symbol in cycle.legs.values():
            position = book.position(symbol)
            if position is None:
                return ()
            side = Side.BUY if position.units < 0 else Side.SELL
            intents.append(
                TradeIntent(
                    trading_symbol=symbol,
                    side=side,
                    lots=abs(position.units) // cycle.lot_size,
                    tag="ST-20_roll_close",
                    leg_group=group,
                )
            )
        for role in _LEG_ROLES:
            if role not in legs:
                continue
            intents.append(
                TradeIntent(
                    trading_symbol=symbols[role],
                    side=legs[role][2],
                    lots=cycle.lots,
                    tag="ST-20_roll_open",
                    leg_group=group,
                )
            )

        # What the roll costs is booked against the cycle, not against the basis ST-17 and
        # ST-19 are stated in. Closing the old structure costs the net premium it is worth
        # now; opening the new one receives its net credit.
        closing_cost = sum(
            session.bar(symbol, minute).close  # type: ignore[union-attr]
            * (1 if role.startswith("short") else -1)
            for role, symbol in cycle.legs.items()
        )
        opening_credit = sum(
            session.bar(symbols[role], minute).close  # type: ignore[union-attr]
            * (1 if role.startswith("short") else -1)
            for role in legs
        )
        cycle.adjustment_cost_per_unit += closing_cost - opening_credit
        cycle.legs = symbols
        cycle.strikes = {role: legs[role][0] for role in legs}
        cycle.rolled = True
        self._log(
            session.session_date,
            rule="ST-20_tested_side_roll",
            outcome="rolled",
            detail={"expiry": cycle.expiry.isoformat(), "tested": tested, "strikes": cycle.strikes},
        )
        return tuple(intents)

    # ------------------------------------------------------------------ entry

    def _maybe_enter(self, session: SessionView, minute: dt.datetime) -> Sequence[TradeIntent]:
        params = self.params
        session_date = session.session_date
        expiry = session.universe.nearest_expiry(session_date)
        if expiry is None:
            return ()
        days_to_expiry = (expiry - session_date).days
        if days_to_expiry not in params.entry_dte or expiry in self._traded:
            return ()
        window_start, window_end = params.entry_window
        if not (window_start <= minute.time() <= window_end):
            return ()

        inputs = self.context.inputs_for(session_date)
        spot = session.spot_at(minute)
        if spot is None or spot <= 0:
            return ()

        lot_fraction = 1.0
        half_reason: str | None = None

        # ST-14/ST-16 event calendar. Empty by default; see the module docstring.
        event = self.event_calendar.get(session_date) or self.event_calendar.get(expiry)
        if event == "SKIP":
            return self._decline(session_date, expiry, "ST-14_event_skip", {"event": event})
        if event == "HALF":
            lot_fraction, half_reason = 0.5, "ST-14_event_half"

        # ST-13 gap filter: a wide opening gap delays entry to 11:00 and, if the gap is
        # still outside the band then, cancels the week.
        if inputs.gap_pct is not None and abs(inputs.gap_pct) > params.gap_limit:
            if minute.time() < params.gap_delay_until:
                return ()
            open_now = inputs.previous_close
            if open_now and abs(spot - open_now) / open_now > params.gap_limit:
                return self._decline(
                    session_date, expiry, "ST-13_gap_filter", {"gap_pct": inputs.gap_pct}
                )

        # ST-12 trend filter.
        if inputs.sma_20 and inputs.previous_close:
            deviation = abs(inputs.previous_close - inputs.sma_20) / inputs.sma_20
            if deviation > params.trend_band:
                return self._decline(
                    session_date, expiry, "ST-12_trend_filter", {"deviation": deviation}
                )

        # ST-10 volatility filter (IV-percentile limb only — see context module).
        if inputs.iv_percentile is not None and inputs.iv_percentile < params.ivp_floor:
            lot_fraction *= 0.5
            half_reason = half_reason or "ST-10_low_iv_percentile"

        atm_iv = self._atm_iv(session, minute, expiry, spot)
        # ST-11 variance-risk-premium filter: five-day realised must not exceed the implied
        # being sold. Without an ATM implied for this minute the test cannot be evaluated,
        # and an unevaluable filter is a decline, not a pass.
        if atm_iv is None:
            return self._decline(session_date, expiry, "ST-11_no_atm_iv", {})
        if inputs.realised_vol_5d is not None and inputs.realised_vol_5d > atm_iv:
            return self._decline(
                session_date,
                expiry,
                "ST-11_vrp_filter",
                {"realised_vol_5d": inputs.realised_vol_5d, "atm_iv": atm_iv},
            )

        # ST-33 drawdown scaling, ST-32 period caps.
        scaling = self._drawdown_scaling(session_date)
        if scaling == 0.0:
            return self._decline(session_date, expiry, "ST-33_drawdown_stop", {})
        lot_fraction *= scaling
        if scaling < 1.0:
            half_reason = half_reason or "ST-33_drawdown_half"
        breach = self._period_cap_state(session_date)
        if breach is not None:
            return self._decline(session_date, expiry, breach, {})

        structure = self._select_structure(session, minute, expiry, spot, days_to_expiry)
        if isinstance(structure, str):
            return self._decline(session_date, expiry, structure, {})

        credit_per_unit = structure["credit_per_unit"]
        lot_size = structure["lot_size"]
        notional_per_unit = spot
        if credit_per_unit <= 0 or credit_per_unit < params.min_credit_ratio * notional_per_unit:
            return self._decline(
                session_date,
                expiry,
                "ST-8_minimum_credit",
                {
                    "credit_per_unit": credit_per_unit,
                    "required": params.min_credit_ratio * notional_per_unit,
                },
            )

        record = allocate(
            AllocationInputs(
                spot=spot,
                lot_size=lot_size,
                wing_width=structure["wing_width"],
                collateral=self.collateral,
                margin_model=self.margin_model,
                max_lots_absolute=params.max_lots_absolute,
            )
        )
        lots = int(record.allocated_lots * lot_fraction)
        if lots <= 0:
            return self._decline(
                session_date, expiry, "CA-15_zero_allocation", {"allocation": record.as_dict()}
            )

        group = f"entry:{expiry.isoformat()}"
        intents = tuple(
            TradeIntent(
                trading_symbol=structure["symbols"][role],
                side=Side.SELL if role.startswith("short") else Side.BUY,
                lots=lots,
                tag="ST-5_entry",
                leg_group=group,
            )
            for role in _LEG_ROLES
        )
        self._cycle = CycleState(
            expiry=expiry,
            entry_date=session_date,
            entry_minute=minute,
            lots=lots,
            lot_size=lot_size,
            legs=dict(structure["symbols"]),
            strikes=dict(structure["strikes"]),
            entry_credit_per_unit=credit_per_unit,
            entry_spot=spot,
            wing_width=structure["wing_width"],
            half_reason=half_reason,
        )
        self._traded.add(expiry)
        self._log(
            session_date,
            rule="ST-5_entry",
            outcome="entered",
            detail={
                "expiry": expiry.isoformat(),
                "minute": minute.isoformat(),
                "lots": lots,
                "lot_fraction": lot_fraction,
                "credit_per_unit": credit_per_unit,
                "credit_ratio": credit_per_unit / notional_per_unit,
                "strikes": structure["strikes"],
                "deltas": structure["deltas"],
                "wing_widths": structure["wing_widths"],
                "allocation": record.as_dict(),
                "half_reason": half_reason,
            },
        )
        return intents

    def _atm_iv(
        self, session: SessionView, minute: dt.datetime, expiry: dt.date, spot: float
    ) -> float | None:
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

    def _select_structure(
        self,
        session: SessionView,
        minute: dt.datetime,
        expiry: dt.date,
        spot: float,
        days_to_expiry: int,
    ) -> dict[str, Any] | str:
        """ST-6 and ST-7: the two short strikes by delta, then the wings.

        Returns the structure, or the requirement ID that stopped it — all four legs must
        be listed and printing at this minute, and the journal records *which* of the two
        rules could not be satisfied rather than a single undifferentiated refusal.
        """
        params = self.params
        low, high = params.delta_band
        t_years = year_fraction(
            minute_hour=minute.hour + minute.minute / 60.0, days_to_expiry=days_to_expiry
        )
        strikes = session.universe.strikes(expiry)
        if not strikes:
            return "ST-1_no_listed_strikes"

        chosen: dict[str, Any] = {"symbols": {}, "strikes": {}, "deltas": {}}
        prices: dict[str, float] = {}
        lot_size = 0
        for role, option_type in (("short_call", OptionType.CALL), ("short_put", OptionType.PUT)):
            best: tuple[float, float, str, float] | None = None
            for strike in strikes:
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
                return "ST-6_no_strike_in_delta_band"
            _distance, strike, symbol, delta = best
            chosen["symbols"][role] = symbol
            chosen["strikes"][role] = strike
            chosen["deltas"][role] = delta
            prices[role] = session.bar(symbol, minute).close  # type: ignore[union-attr]

        spacing = _strike_spacing(strikes)
        widths: dict[str, float] = {}
        for short_role, long_role, option_type, direction in (
            ("short_call", "long_call", OptionType.CALL, 1.0),
            ("short_put", "long_put", OptionType.PUT, -1.0),
        ):
            width = self._wing_width(
                session,
                minute,
                expiry,
                short_strike=chosen["strikes"][short_role],
                option_type=option_type,
                direction=direction,
                spacing=spacing,
            )
            if width is None:
                return "ST-7_no_wing_available"
            strike = chosen["strikes"][short_role] + direction * width
            contract = session.universe.get(expiry, strike, option_type)
            bar = None if contract is None else session.bar(contract.trading_symbol, minute)
            if contract is None or bar is None or bar.close <= 0:
                return "ST-7_no_wing_available"
            chosen["symbols"][long_role] = contract.trading_symbol
            chosen["strikes"][long_role] = strike
            prices[long_role] = bar.close
            widths[short_role] = width

        credit = (
            prices["short_call"] + prices["short_put"] - prices["long_call"] - prices["long_put"]
        )
        chosen["credit_per_unit"] = credit
        chosen["wing_widths"] = widths
        # Defined risk is the worse side's, so that is the width the margin model is asked
        # about. Under ``spec`` both sides are the configured width and this is that width.
        chosen["wing_width"] = max(widths.values())
        chosen["lot_size"] = lot_size
        return chosen

    def _wing_width(
        self,
        session: SessionView,
        minute: dt.datetime,
        expiry: dt.date,
        *,
        short_strike: float,
        option_type: str,
        direction: float,
        spacing: float,
    ) -> float | None:
        """The wing distance this side can actually support at this minute.

        ``spec`` returns the configured width unconditionally — the synthetic-bar store is
        what makes it priceable. ``observed`` walks inwards from the allowed band's top and
        takes the widest distance at which the wing prints.

        **The two sides are measured independently, and that is a deviation from ST-7**,
        which names one Wing Width for the structure. It is made because the put skew puts
        the 0.12-delta put at or near the captured band's lower edge: requiring one common
        width leaves only 97 of 295 entry windows tradeable, against 143 when each side
        takes what it has. The structure stays defined-risk on both sides; what changes is
        that the two sides' maximum losses differ, and the report carries the width
        distribution so the asymmetry is visible rather than implied.
        """
        params = self.params
        if self.wing_policy == "spec":
            return params.wing_width
        width = params.wing_width_band[1]
        while width >= self.min_wing_width:
            strike = short_strike + direction * width
            contract = session.universe.get(expiry, strike, option_type)
            if contract is not None:
                bar = session.bar(contract.trading_symbol, minute)
                # `bar.iv` is the tell: modelled bars carry none, so requiring it here is
                # what keeps an "observed" entry observed.
                if bar is not None and bar.close > 0 and bar.iv:
                    return width
            width -= spacing
        return None

    # ------------------------------------------------------------------ risk budget

    def _risk_budget_breach(self, session_date: dt.date, unrealised: float) -> str | None:
        params = self.params
        capital = self.collateral.portfolio_capital
        week_loss = self._period_pnl(session_date, "week") + min(unrealised, 0.0)
        if week_loss <= -params.weekly_loss_cap * capital:
            return "ST-32_weekly_cap"
        month_loss = self._period_pnl(session_date, "month") + min(unrealised, 0.0)
        if month_loss <= -params.monthly_loss_cap * capital:
            return "ST-32_monthly_cap"
        return None

    def _period_cap_state(self, session_date: dt.date) -> str | None:
        params = self.params
        capital = self.collateral.portfolio_capital
        if self._period_pnl(session_date, "week") <= -params.weekly_loss_cap * capital:
            return "ST-32_weekly_cap_active"
        if self._period_pnl(session_date, "month") <= -params.monthly_loss_cap * capital:
            return "ST-32_monthly_cap_active"
        return None

    def _period_pnl(self, session_date: dt.date, period: str) -> float:
        total = 0.0
        for closed in self._closed:
            exit_date = dt.date.fromisoformat(closed["exit_date"])
            if period == "week":
                same = exit_date.isocalendar()[:2] == session_date.isocalendar()[:2]
            else:
                same = (exit_date.year, exit_date.month) == (session_date.year, session_date.month)
            if same:
                total += closed["estimated_pnl"]
        return total

    def _drawdown_scaling(self, session_date: dt.date) -> float:
        params = self.params
        capital = self.collateral.portfolio_capital
        drawdown = self._peak_equity - self._running_pnl
        if drawdown >= params.dd_stop_trigger * capital:
            self._halted = True
            return 0.0
        if drawdown >= params.dd_half_trigger * capital:
            self._halved_until = session_date + dt.timedelta(weeks=params.half_period_weeks)
            return 0.5
        if self._halved_until is not None and session_date <= self._halved_until:
            return 0.5
        return 1.0

    # ------------------------------------------------------------------ journal

    def _decline(
        self, session_date: dt.date, expiry: dt.date, rule: str, detail: dict[str, Any]
    ) -> tuple[TradeIntent, ...]:
        self._log(
            session_date,
            rule=rule,
            outcome="declined",
            detail={"expiry": expiry.isoformat(), **detail},
        )
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


def _strike_spacing(strikes: Sequence[float]) -> float:
    """The listed strike step, as the chain itself states it."""
    if len(strikes) < 2:
        return 50.0
    gaps = sorted({round(b - a, 4) for a, b in pairwise(strikes) if b > a})
    return gaps[0] if gaps else 50.0
