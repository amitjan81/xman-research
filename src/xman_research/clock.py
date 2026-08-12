"""Injected time.

Reproducibility is this platform's defining property, so nothing in business logic
may call ``datetime.now()`` / ``time.time()`` directly. Every component that needs the
current time takes a :class:`Clock` as a constructor argument. The only place a
:class:`SystemClock` is constructed is at a wiring boundary (see
:func:`xman_research.evaluation.open_session`) or in a test.

This mirrors the ``EngineTime`` discipline in the sibling ``xman`` repository; that
module is not importable here, so this is the minimal local equivalent.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol, runtime_checkable

__all__ = ["Clock", "ManualClock", "SystemClock", "require_aware"]


@runtime_checkable
class Clock(Protocol):
    """Source of the current time. Always returns a timezone-aware datetime."""

    def now(self) -> datetime:
        """Return the current time as a timezone-aware datetime."""
        ...


class SystemClock:
    """Wall-clock time in UTC. Construct only at a wiring boundary."""

    def now(self) -> datetime:
        return datetime.now(UTC)


class ManualClock:
    """A clock the caller drives. Intended for tests and for replaying history."""

    def __init__(self, start: datetime, *, step: timedelta = timedelta(0)) -> None:
        self._current = require_aware(start, "start")
        self._step = step

    def now(self) -> datetime:
        current = self._current
        self._current = current + self._step
        return current

    def advance(self, delta: timedelta) -> datetime:
        """Move the clock forward and return the new time."""
        self._current = self._current + delta
        return self._current

    def set(self, moment: datetime) -> None:
        """Pin the clock to an exact moment."""
        self._current = require_aware(moment, "moment")


def require_aware(moment: datetime, label: str = "datetime") -> datetime:
    """Return ``moment`` if it is timezone-aware, else raise.

    Naive timestamps are refused rather than coerced: a trial log row whose timezone
    is a guess is not evidence of when anything ran.
    """
    if moment.tzinfo is None or moment.tzinfo.utcoffset(moment) is None:
        raise ValueError(f"{label} must be timezone-aware, got naive {moment!r}")
    return moment
