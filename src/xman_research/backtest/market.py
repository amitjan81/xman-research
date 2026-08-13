"""One session, as the backtest sees it: bars indexed by minute, contracts from refdata.

Two rules from the sibling trading repository are enforced here rather than assumed,
because they are the ones a research codebase breaks first.

**The engine never constructs a refdata-owned value.** Trading symbols, strikes, lot
sizes, tick sizes and expiry dates come out of the ``.refdata`` bundle verbatim. Nothing
here parses ``NIFTY-16Jun2026-22600-CE`` to learn that it expires on 16 June, even though
it plainly does — a composed or parsed symbol drifts from the exchange's own format in
ways the engine cannot know, and the sibling repo deleted a whole module for exactly this
mistake. The symbol is an opaque key into the bar frame; every attribute is looked up.

**Time is IST, and it is derived once.** ``minute_ts`` is epoch microseconds UTC. Every
comparison against a wall-clock time of day — the 15:00 settlement window, an entry
minute — happens in ``Asia/Kolkata``, because that is the timezone the rules are written
in. Doing the conversion per comparison is how a backtest ends up half an hour out on
exactly the sessions that matter.

The class is built once per session and then read many times, so the per-minute index is
materialised up front. A session is roughly 16,000 rows; the dictionary costs a few
milliseconds and removes a DataFrame filter from the inner loop.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

if TYPE_CHECKING:  # pragma: no cover - import cost is paid only by type checkers
    import pandas as pd

    from xman_research.session_store import RefData

__all__ = [
    "IST",
    "Bar",
    "Contract",
    "ContractUniverse",
    "OptionType",
    "SessionView",
]

#: The exchange's timezone. Every time-of-day rule in this package is expressed in it.
IST = ZoneInfo("Asia/Kolkata")

_REFDATA_EXPIRY_FORMAT = "%d/%m/%Y"


class OptionType:
    """The two option types, as the refdata spells them. Not an enum: these are the
    producer's strings and comparing against the producer's spelling is the point."""

    CALL = "CE"
    PUT = "PE"


@dataclass(frozen=True, slots=True)
class Bar:
    """One minute of one instrument, as captured.

    ``volume_units`` and ``open_interest_units`` are in **units** (shares), not lots or
    contracts. That is verified rather than assumed — every non-null value in the real
    corpus divides exactly by the lot size, and a test asserts it, so a future backfill
    that switches the vendor's convention to contracts fails loudly instead of inflating
    every participation cap by a factor of the lot size.
    """

    symbol: str
    minute: dt.datetime
    open: float
    high: float
    low: float
    close: float
    volume_units: float
    open_interest_units: float
    iv: float | None
    spot: float | None

    @property
    def has_traded(self) -> bool:
        """Whether anything changed hands in this minute — the liquidity precondition."""
        return self.volume_units > 0


@dataclass(frozen=True, slots=True)
class Contract:
    """One listed option, exactly as the instrument master defines it."""

    trading_symbol: str
    underlying: str
    expiry: dt.date
    strike: float
    option_type: str
    lot_size: int
    tick_size: float

    @property
    def is_call(self) -> bool:
        return self.option_type == OptionType.CALL

    def intrinsic(self, settlement_value: float) -> float:
        """Per-unit intrinsic value at ``settlement_value``. Zero when out of the money."""
        if self.is_call:
            return max(0.0, settlement_value - self.strike)
        return max(0.0, self.strike - settlement_value)


class ContractUniverse:
    """The options listed for one underlying on one session.

    Built from the refdata bundle, filtered to option rows for the requested underlying.
    Every lookup is deterministic and ordered; nothing iterates a set.
    """

    def __init__(self, underlying: str, contracts: Sequence[Contract]) -> None:
        self._underlying = underlying
        self._contracts = tuple(
            sorted(contracts, key=lambda c: (c.expiry, c.strike, c.option_type))
        )
        self._by_key = {(c.expiry, c.strike, c.option_type): c for c in self._contracts}
        self._by_symbol = {c.trading_symbol: c for c in self._contracts}

    @classmethod
    def from_refdata(cls, refdata: RefData, underlying: str) -> ContractUniverse:
        contracts: list[Contract] = []
        for row in refdata.nfo_instruments:
            if row.get("LookupName") != underlying:
                continue
            option_type = row.get("OptionType")
            if option_type not in (OptionType.CALL, OptionType.PUT):
                continue
            contracts.append(
                Contract(
                    trading_symbol=str(row["TradingSymbol"]),
                    underlying=underlying,
                    expiry=_parse_refdata_date(str(row["ExpiryDate"])),
                    strike=float(row["StrikePrice"]),
                    option_type=str(option_type),
                    lot_size=int(row["LotSize"]),
                    tick_size=float(row["TickSize"]),
                )
            )
        return cls(underlying, contracts)

    @property
    def underlying(self) -> str:
        return self._underlying

    def __len__(self) -> int:
        return len(self._contracts)

    def __iter__(self) -> Iterator[Contract]:
        return iter(self._contracts)

    def expiries(self) -> tuple[dt.date, ...]:
        """Listed expiries, ascending."""
        seen: dict[dt.date, None] = {}
        for contract in self._contracts:
            seen.setdefault(contract.expiry, None)
        return tuple(seen)

    def nearest_expiry(self, on: dt.date) -> dt.date | None:
        """The first expiry on or after ``on``, or ``None`` if the chain has run out.

        ``on`` itself counts: an option expiring today is tradable today, and excluding
        it would silently move every zero-DTE decision to the next week.
        """
        for expiry in self.expiries():
            if expiry >= on:
                return expiry
        return None

    def strikes(self, expiry: dt.date) -> tuple[float, ...]:
        seen: dict[float, None] = {}
        for contract in self._contracts:
            if contract.expiry == expiry:
                seen.setdefault(contract.strike, None)
        return tuple(sorted(seen))

    def atm_strike(self, spot: float, expiry: dt.date) -> float | None:
        """The listed strike nearest ``spot``.

        **Ties break to the lower strike.** Spot landing exactly midway between two
        strikes is not hypothetical — NIFTY strikes are 50 or 100 apart and the index
        prints round numbers — and "nearest" with no tie-break is a coin flip that
        depends on iteration order. Lower is chosen arbitrarily; what matters is that it
        is written down, tested, and never changed silently.
        """
        strikes = self.strikes(expiry)
        if not strikes:
            return None
        return min(strikes, key=lambda strike: (abs(strike - spot), strike))

    def get(self, expiry: dt.date, strike: float, option_type: str) -> Contract | None:
        return self._by_key.get((expiry, strike, option_type))

    def by_symbol(self, trading_symbol: str) -> Contract | None:
        return self._by_symbol.get(trading_symbol)


class SessionView:
    """One session's bars, indexed for lookup by (symbol, minute).

    **Bars are the producer's, untouched.** The session store hands back the frame
    exactly as captured, and this class only indexes it — no forward fill, no
    interpolation, no synthetic bar for a minute that did not trade. A missing bar is a
    fact about liquidity, and manufacturing one is how a backtest fills an order that
    could not have been filled. :class:`~xman_research.backtest.execution.Feasibility`
    is where that fact gets its verdict.
    """

    def __init__(
        self,
        session_date: dt.date,
        underlying: str,
        bars: Mapping[tuple[str, dt.datetime], Bar],
        universe: ContractUniverse,
    ) -> None:
        self._session_date = session_date
        self._underlying = underlying
        self._bars = dict(bars)
        self._universe = universe
        self._minutes = tuple(sorted({minute for _, minute in self._bars}))
        self._symbols = frozenset(symbol for symbol, _ in self._bars)
        self._underlying_bars = tuple(
            self._bars[(underlying, minute)]
            for minute in self._minutes
            if (underlying, minute) in self._bars
        )

    @classmethod
    def from_frame(
        cls,
        session_date: dt.date,
        underlying: str,
        frame: pd.DataFrame,
        refdata: RefData,
    ) -> SessionView:
        universe = ContractUniverse.from_refdata(refdata, underlying)
        bars: dict[tuple[str, dt.datetime], Bar] = {}
        columns = frame.columns
        has_iv = "iv" in columns
        has_spot = "spot" in columns
        for row in frame.itertuples(index=False):
            minute = _to_ist(int(row.minute_ts))
            symbol = str(row.symbol)
            bars[(symbol, minute)] = Bar(
                symbol=symbol,
                minute=minute,
                open=float(row.open),
                high=float(row.high),
                low=float(row.low),
                close=float(row.close),
                volume_units=_finite(row.volume),
                open_interest_units=_finite(row.oi),
                iv=_optional(row.iv) if has_iv else None,
                spot=_optional(row.spot) if has_spot else None,
            )
        return cls(session_date, underlying, bars, universe)

    @property
    def session_date(self) -> dt.date:
        return self._session_date

    @property
    def underlying(self) -> str:
        return self._underlying

    @property
    def universe(self) -> ContractUniverse:
        return self._universe

    def minutes(self) -> tuple[dt.datetime, ...]:
        """Every minute with at least one bar, ascending, timezone-aware IST."""
        return self._minutes

    def bar(self, symbol: str, minute: dt.datetime) -> Bar | None:
        return self._bars.get((symbol, minute))

    def has_bars_for(self, symbol: str) -> bool:
        """Whether the symbol traded at all this session.

        The corpus carries bars only for the front expiry even though refdata lists the
        whole ladder, so a contract can be perfectly listed and have no data. That is a
        capture-scope fact (spec §3 C1), not a market fact, and the backtester must be
        able to tell the difference before it decides a leg was unfillable.
        """
        return symbol in self._symbols

    def underlying_bars(self) -> tuple[Bar, ...]:
        """The index's own bars, ascending by minute."""
        return self._underlying_bars

    def spot_at(self, minute: dt.datetime) -> float | None:
        bar = self.bar(self._underlying, minute)
        return bar.close if bar is not None else None

    def through(self, minute: dt.datetime) -> SessionView:
        """This session as it was knowable at ``minute`` — no bar after it exists.

        **The strategy is handed one of these, never the whole session.** A full-day view
        contains every bar to 15:29, including the 15:00-15:30 settlement window, and one
        ``session.bar(symbol, later_minute)`` inside a ``decide()`` is a backtest that
        trades on prices it could not have seen. That error is invisible in every number a
        run produces — the equity curve looks better and nothing else changes — so it
        cannot be caught downstream and has to be made unrepresentable here.

        The shipped :class:`~xman_research.backtest.strategies.ShortAtmStraddle` does not
        do this. The point is the seam: :class:`~xman_research.backtest.engine.Strategy`
        is a Protocol, every future variant plugs into it, and the guarantee should be a
        property of the engine rather than of each author's discipline.

        Costs one dictionary rebuild per session (~16,000 rows, a few milliseconds), paid
        once per session rather than per lookup.
        """
        return SessionView(
            self._session_date,
            self._underlying,
            {key: bar for key, bar in self._bars.items() if key[1] <= minute},
            self._universe,
        )

    def minute_at_or_after(self, time_of_day: dt.time) -> dt.datetime | None:
        """The first minute at or after ``time_of_day`` IST.

        Used so a decision time of 09:20 still resolves on a session whose first bars are
        late — returning ``None`` only when the session ends before the requested time,
        which is a real "could not act" and is reported as one.
        """
        for minute in self._minutes:
            if minute.timetz().replace(tzinfo=None) >= time_of_day:
                return minute
        return None


def _parse_refdata_date(value: str) -> dt.date:
    return dt.datetime.strptime(value, _REFDATA_EXPIRY_FORMAT).date()


def _to_ist(minute_ts: int) -> dt.datetime:
    return dt.datetime.fromtimestamp(minute_ts / 1_000_000, tz=dt.UTC).astimezone(IST)


def _finite(value: Any) -> float:
    """``NaN`` becomes ``0.0`` for volume and open interest.

    The producer widens both columns to float because the index's own rows carry no
    volume. For an option row a NaN would mean "not reported", and treating that as zero
    liquidity is the conservative reading: it fails the participation cap rather than
    passing it on an unknown.
    """
    number = float(value)
    return 0.0 if number != number else number


def _optional(value: Any) -> float | None:
    number = float(value)
    return None if number != number else number
