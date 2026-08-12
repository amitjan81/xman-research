"""Which days the exchange was open.

The single question this module answers: *given a date range, which dates should a
complete corpus contain?* Everything about C2's headline guarantee rests on it — a
weekend reported as a capture gap makes the gap report noise, and a genuine gap
reported as a weekend makes it a lie.

**The calendar is not written here, and must never be.** NSE holidays move with the
lunar calendar, with state elections, and with exchange circulars issued weeks ahead;
a list transcribed into source is correct on the day it is written and silently wrong
afterwards. This project has already paid for that lesson once — an engine that
composed its own expiry rules mis-mapped contracts at the broker. So the holiday table
comes from ``pandas_market_calendars`` and the only code here is the adapter.

That dependency has an edge, and it is guarded rather than hoped about: the shipped
holiday table ends on a fixed date (2026-12-25 in pandas-market-calendars 5.4.0).
Past it the schedule keeps producing weekdays with no holidays subtracted, so every
2027 NSE holiday would be reported as a capture gap — criterion 1 exactly inverted,
and inverted *quietly*. :meth:`TradingCalendar.trading_days` refuses instead.

**The errata layer, and what it is not.** ``pandas_market_calendars`` is still the
source of truth; :data:`NSE_ERRATA` is a narrow, individually-cited list of dates it
gets *wrong*, subtracted on top of it. It is not a holiday list, not a weekday rule,
and not a place to put a date somebody remembers — every entry carries the reason the
exchange was shut and the source that says so, so the next reader can check it rather
than trust it. Each entry is a bug report waiting to be filed: report it upstream to
pandas_market_calendars and delete the entry when the release carrying the fix lands.

The opposite direction — pmc missing a session the exchange *did* hold, as with a
Muhurat trading day on a Diwali the table calls a holiday — is deliberately **not**
guessed at here. That case surfaces as
:attr:`~xman_research.session_store.store.Resolution.unexpected`: a file on disk for a
day the calendar calls closed is reported as a producer/calendar disagreement rather
than silently excluded. Inventing sessions requires the same citation as removing
them, and until one exists the honest answer is the disagreement itself.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass
from functools import cached_property

import pandas as pd
import pandas_market_calendars as mcal

__all__ = [
    "NSE_CALENDAR",
    "NSE_ERRATA",
    "CalendarCoverageError",
    "CalendarErratum",
    "TradingCalendar",
]

NSE_CALENDAR = "NSE"


@dataclass(frozen=True, slots=True)
class CalendarErratum:
    """One date the holiday table gets wrong, with the evidence for saying so.

    ``source`` is mandatory and is the whole point: a correction nobody can check is
    indistinguishable from the hand-written holiday list this module exists to refuse.
    """

    session_date: dt.date
    reason: str
    source: str


#: Dates ``pandas_market_calendars`` lists as NSE sessions on which the exchange was in
#: fact shut. Subtracted from the schedule; see the module docstring for the rules.
NSE_ERRATA: tuple[CalendarErratum, ...] = (
    CalendarErratum(
        session_date=dt.date(2026, 1, 15),
        reason="NSE closed — Maharashtra municipal corporation elections",
        source=(
            "Market-data press reports for the week of 2026-01-12 (secondary sources, "
            "consistent across providers): trading on 14 Jan, closed 15 Jan, reopened "
            "16 Jan. Corroborated by the capture corpus itself, which holds 119 "
            "consecutive sessions with neither a parquet file nor a producer manifest "
            "row for 2026-01-15 while every neighbouring session has both. NOT yet "
            "checked against the primary NSE circular, and not yet reported upstream "
            "to pandas_market_calendars — do both, then delete this entry when a "
            "release carries the fix."
        ),
    ),
)

_ERRATA_BY_CALENDAR: dict[str, tuple[CalendarErratum, ...]] = {NSE_CALENDAR: NSE_ERRATA}


class CalendarCoverageError(RuntimeError):
    """A range extends past the last date the holiday table knows about.

    Raised rather than warned. The failure it prevents is a range of ordinary weekdays
    being reported as complete when the exchange was in fact shut — a wrong answer that
    looks exactly like a right one, which is the class of bug C2 exists to remove.
    """


class TradingCalendar:
    """Exchange sessions for one market, read from ``pandas_market_calendars``."""

    def __init__(
        self, name: str = NSE_CALENDAR, *, errata: Sequence[CalendarErratum] | None = None
    ) -> None:
        self._name = name
        self._calendar = mcal.get_calendar(name)
        self._errata = tuple(errata) if errata is not None else _ERRATA_BY_CALENDAR.get(name, ())
        self._errata_dates = frozenset(entry.session_date for entry in self._errata)

    @property
    def name(self) -> str:
        return self._name

    @property
    def errata(self) -> tuple[CalendarErratum, ...]:
        """The corrections applied on top of the packaged holiday table."""
        return self._errata

    @cached_property
    def coverage_end(self) -> dt.date:
        """The last date the underlying holiday table accounts for.

        Beyond this the adapter can still *produce* days, but it cannot subtract
        holidays it has not been told about, so it declines to answer.
        """
        holidays = [d for d in self._calendar.holidays().holidays if d is not None]
        return max(pd.Timestamp(d).date() for d in holidays)

    def trading_days(self, start: dt.date, end: dt.date) -> tuple[dt.date, ...]:
        """Return the exchange sessions in ``[start, end]``, inclusive, in date order.

        An empty tuple is a legitimate answer — a range covering only a weekend has no
        sessions in it, and that is not the same fact as a range whose sessions are
        missing from disk. The caller (:class:`~xman_research.session_store.store.Resolution`)
        keeps those two apart.

        :data:`NSE_ERRATA`-style corrections are subtracted last, so a date the packaged
        table wrongly calls a session never reaches the gap report.
        """
        if start > end:
            raise ValueError(f"start {start} is after end {end}")
        if end > self.coverage_end:
            raise CalendarCoverageError(
                f"{self._name} holiday data ends {self.coverage_end}; a range ending "
                f"{end} would treat unlisted holidays as capture gaps. Upgrade "
                f"pandas-market-calendars or narrow the range."
            )
        schedule = self._calendar.schedule(start_date=start, end_date=end)
        days = tuple(ts.date() for ts in schedule.index)
        if not self._errata_dates:
            return days
        return tuple(day for day in days if day not in self._errata_dates)
