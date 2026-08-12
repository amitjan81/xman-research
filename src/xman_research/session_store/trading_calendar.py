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
"""

from __future__ import annotations

import datetime as dt
from functools import cached_property

import pandas as pd
import pandas_market_calendars as mcal

__all__ = ["NSE_CALENDAR", "CalendarCoverageError", "TradingCalendar"]

NSE_CALENDAR = "NSE"


class CalendarCoverageError(RuntimeError):
    """A range extends past the last date the holiday table knows about.

    Raised rather than warned. The failure it prevents is a range of ordinary weekdays
    being reported as complete when the exchange was in fact shut — a wrong answer that
    looks exactly like a right one, which is the class of bug C2 exists to remove.
    """


class TradingCalendar:
    """Exchange sessions for one market, read from ``pandas_market_calendars``."""

    def __init__(self, name: str = NSE_CALENDAR) -> None:
        self._name = name
        self._calendar = mcal.get_calendar(name)

    @property
    def name(self) -> str:
        return self._name

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
        return tuple(ts.date() for ts in schedule.index)
