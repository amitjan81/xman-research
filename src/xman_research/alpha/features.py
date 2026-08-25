"""What the market looked like on one session, computed from that session and earlier ones.

**Every feature here is a number an operator could have known at the decision minute, and
that is the property the module exists to enforce rather than to assume.** A scan is run
after the close and is trivially able to read the rest of the day, the next session, or the
settlement print — and a feature that does so improves every downstream statistic while
changing nothing else, so no result can catch it. The three mechanisms that prevent it:

* The corpus window resolved for a build **ends at the as-of session**, so no later file is
  ever opened.
* The as-of session is read through
  :meth:`~xman_research.backtest.market.SessionView.through`, so bars after the decision
  minute do not exist in the view the features are computed from.
* Every trailing session contributes at the **same decision minute**, so a trailing series
  is a series of comparable observations rather than a mixture of intraday snapshots and
  full-day closes.

**Each feature records its lookback**, in sessions, because a rationale that says "implied
volatility is above realised" is not actionable and one that says "above the trailing
twenty-session realised, by 4.1 volatility points" is. A feature that cannot be computed is
``None`` with a written reason, never a zero or a carried-forward value: an operator
declining to trade because a number is unavailable is a correct outcome, and a fabricated
number is not.

**Warm-up lengths are fixed rather than "whatever was loaded".** An exponential average
seeded at the start of whatever window happened to be resolved would give a different
answer for the same session depending on how much history the caller asked for, which would
make a nightly scan non-reproducible against its own corpus.
"""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise
from typing import Any

from xman_research.alpha.templates import ATM_IV_MINUS_RV20
from xman_research.backtest.market import OptionType, SessionView
from xman_research.session_store import CalendarCoverageError, SessionStore, TradingCalendar
from xman_research.session_store.store import SessionRef

__all__ = [
    "ANNUALISATION_SESSIONS",
    "DEFAULT_DECISION_TIME",
    "DEFAULT_REGIME_LOOKBACK_SESSIONS",
    "AsOfNotASessionError",
    "FeatureBuilder",
    "FeatureFrame",
    "FeatureValue",
    "InsufficientHistoryError",
    "RegimeTag",
    "SessionSummary",
]

#: NSE trades roughly 250 sessions a year; 252 is the convention every published Sharpe in
#: this repository is quoted against, and volatility must be annualised on the same one or
#: an implied-minus-realised spread is a comparison between two different years.
ANNUALISATION_SESSIONS = 252

#: The minute a nightly scan evaluates. Late enough that the session's information is in
#: the price, early enough to sit outside the 15:00-15:30 settlement window, whose prints
#: are an artefact of the closing auction rather than a tradable quote.
DEFAULT_DECISION_TIME = dt.time(15, 20)

#: How many trailing sessions the volatility-regime tercile is measured over. Long enough
#: to span more than one volatility episode, short enough that the tercile still describes
#: the current market rather than the last two years of it.
DEFAULT_REGIME_LOOKBACK_SESSIONS = 120

#: Sessions of history the exponential average is warmed up over before the value is read.
#: Fixed so the same as-of session always produces the same average.
_EMA_WARMUP_SESSIONS = 60

_EMA_SPAN = 20
_ATR_SESSIONS = 14
_RV_SHORT_SESSIONS = 10
_RV_LONG_SESSIONS = 20

#: Calendar days assumed per trading session when sizing the corpus window to resolve.
#: Generous on purpose: resolving too wide a window costs a directory listing, resolving too
#: narrow a one silently shortens a trailing average.
_CALENDAR_DAYS_PER_SESSION = 1.75


class AsOfNotASessionError(ValueError):
    """The requested as-of date is not a session the corpus holds."""


class InsufficientHistoryError(ValueError):
    """The corpus holds fewer sessions before the as-of date than a feature needs."""


@dataclass(frozen=True, slots=True)
class FeatureValue:
    """One computed number, with everything a rationale needs to state it.

    ``value`` is ``None`` exactly when the feature could not be computed, and ``reason``
    then says why. The pair is the whole contract: a consumer that reads ``value`` without
    reading ``reason`` gets ``None`` and cannot mistake it for a measurement.
    """

    name: str
    value: float | None
    lookback_sessions: int
    unit: str
    description: str
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "value": self.value,
            "lookback_sessions": self.lookback_sessions,
            "unit": self.unit,
            "description": self.description,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class RegimeTag:
    """Which tercile of its own trailing distribution the implied-realised spread sits in.

    **Descriptive only in this scan.** The tag travels into every rationale so a reader can
    see what kind of market the idea was generated in, and it scales an expected edge only
    where an admission record carries a per-regime table measured over the same partition.
    None does today, so nothing is scaled — see
    :meth:`~xman_research.alpha.library.EvidenceCard.regime_factor`.
    """

    tag: str | None
    lookback_sessions: int
    observations: int
    lower_tercile: float | None
    upper_tercile: float | None
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "tag": self.tag,
            "lookback_sessions": self.lookback_sessions,
            "observations": self.observations,
            "lower_tercile": self.lower_tercile,
            "upper_tercile": self.upper_tercile,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class SessionSummary:
    """One session reduced to what the trailing features need.

    Built from bars at or before the decision minute, so the as-of session's summary is
    what was knowable then rather than what the full day turned out to be.
    """

    session_date: dt.date
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    atm_iv: float | None
    nearest_expiry: dt.date | None


@dataclass(frozen=True, slots=True)
class FeatureFrame:
    """Every feature for one underlying on one as-of session."""

    underlying: str
    as_of: dt.date
    decision_time: dt.time
    decision_minute: dt.datetime | None
    features: Mapping[str, FeatureValue]
    regime: RegimeTag
    sessions_loaded: int
    sessions_missing: int

    def get(self, name: str) -> FeatureValue | None:
        return self.features.get(name)

    def value(self, name: str) -> float | None:
        feature = self.features.get(name)
        return feature.value if feature is not None else None

    def as_dict(self) -> dict[str, Any]:
        return {
            "underlying": self.underlying,
            "as_of": self.as_of.isoformat(),
            "decision_time": self.decision_time.isoformat(),
            "decision_minute": (self.decision_minute.isoformat() if self.decision_minute else None),
            "features": {
                name: feature.as_dict() for name, feature in sorted(self.features.items())
            },
            "regime": self.regime.as_dict(),
            "sessions_loaded": self.sessions_loaded,
            "sessions_missing": self.sessions_missing,
        }


class FeatureBuilder:
    """Computes a :class:`FeatureFrame` for an underlying from the session store.

    One builder may be reused across as-of dates; session summaries are cached by
    ``(underlying, session_date)`` so a scan over several products, or a conditioner series
    over several dates, pays each parquet read once. The cache holds only summaries — a few
    floats per session — so it does not grow with the size of a session.
    """

    def __init__(
        self,
        store: SessionStore,
        *,
        decision_time: dt.time = DEFAULT_DECISION_TIME,
        regime_lookback_sessions: int = DEFAULT_REGIME_LOOKBACK_SESSIONS,
        calendar: TradingCalendar | None = None,
    ) -> None:
        if regime_lookback_sessions < 3:
            raise ValueError(
                "regime_lookback_sessions must be at least 3; a tercile of fewer than "
                "three observations describes nothing"
            )
        self._store = store
        self._decision_time = decision_time
        self._regime_lookback = regime_lookback_sessions
        self._calendar = calendar if calendar is not None else TradingCalendar()
        self._summaries: dict[tuple[str, dt.date], SessionSummary] = {}
        # One session at a time. A frame build reads the as-of session for its summary and
        # the ranker reads it again to size an entry, and a session is ~16,000 rows; a
        # single-entry cache removes that second parquet read without holding a window of
        # sessions in memory.
        self._view_cache: tuple[tuple[str, dt.date], SessionView | None] | None = None

    @property
    def decision_time(self) -> dt.time:
        return self._decision_time

    @property
    def regime_lookback_sessions(self) -> int:
        return self._regime_lookback

    def build(self, underlying: str, as_of: dt.date) -> FeatureFrame:
        """Features for ``underlying`` on ``as_of``, from sessions at or before it."""
        refs, missing = self._window(underlying, as_of)
        if refs[-1].session_date != as_of:
            raise AsOfNotASessionError(
                f"{underlying} has no session on {as_of}; the corpus's last session at or "
                f"before it is {refs[-1].session_date}. A scan is dated by the session it "
                "reads, and silently rolling back to the previous one would file the "
                "result under a date whose data it never saw."
            )
        summaries = [self._summary(underlying, ref) for ref in refs]
        as_of_view = self._view(underlying, refs[-1])
        minute = as_of_view.minute_at_or_after(self._decision_time) if as_of_view else None

        features = _compute(summaries, calendar=self._calendar, as_of=as_of)
        regime = self._regime(summaries)
        return FeatureFrame(
            underlying=underlying,
            as_of=as_of,
            decision_time=self._decision_time,
            decision_minute=minute,
            features=features,
            regime=regime,
            sessions_loaded=len(summaries),
            sessions_missing=missing,
        )

    def session_view(self, underlying: str, as_of: dt.date) -> SessionView | None:
        """The as-of session truncated at the decision minute, or ``None`` if unreadable.

        Handed to the ranker, which needs the same truncated view the features were
        computed from in order to size and price an entry against bars that existed then.
        """
        refs, _ = self._window(underlying, as_of, sessions=1)
        if not refs or refs[-1].session_date != as_of:
            return None
        return self._view(underlying, refs[-1])

    def signal_series(
        self, underlying: str, sessions: Sequence[dt.date], feature: str = ATM_IV_MINUS_RV20
    ) -> dict[dt.date, float]:
        """``{session_date: feature value}`` for a conditioner, one entry per computable date.

        A date whose feature is ``None`` is **absent** rather than present with a filler, so
        a conditioned strategy reading this series declines to enter on it — which is the
        behaviour :class:`~xman_research.alpha.templates.ConditionedShortStraddle` documents.
        """
        series: dict[dt.date, float] = {}
        for session_date in sessions:
            value = self.build(underlying, session_date).value(feature)
            if value is not None:
                series[session_date] = value
        return series

    # ------------------------------------------------------------------ internals

    def _window(
        self, underlying: str, as_of: dt.date, *, sessions: int | None = None
    ) -> tuple[tuple[SessionRef, ...], int]:
        """Resolved sessions ending at ``as_of``, newest last, plus the count of gaps.

        The store refuses a range with holes, and a nightly scan cannot stop for one: a
        vendor outage three months back removes observations from a trailing average and
        that is a fact to report, not a reason to produce no ideas at all. The reason is
        written down here rather than passed by the caller, because it is a property of what
        a feature window is, not of who asked for one.
        """
        needed = sessions if sessions is not None else self._max_lookback()
        span = int(needed * _CALENDAR_DAYS_PER_SESSION) + 15
        start = as_of - dt.timedelta(days=span)
        resolution = self._store.resolve(underlying, start, as_of)
        refs = resolution.accept_gaps(
            "a feature window reads whatever the corpus holds at or before the as-of "
            "session; a gap shortens a trailing average and is reported on the frame "
            "rather than turned into a refusal to scan"
        )
        kept = tuple(ref for ref in refs if ref.session_date <= as_of)
        if not kept:
            raise InsufficientHistoryError(
                f"{underlying} has no session at or before {as_of} in {start}..{as_of}"
            )
        return kept[-needed:], resolution.missing_count

    def _max_lookback(self) -> int:
        """Sessions to load: the longest trailing window, plus what it needs to warm up."""
        return max(self._regime_lookback + _RV_LONG_SESSIONS + 1, _EMA_WARMUP_SESSIONS + 1)

    def _view(self, underlying: str, ref: SessionRef) -> SessionView | None:
        key = (underlying, ref.session_date)
        if self._view_cache is not None and self._view_cache[0] == key:
            return self._view_cache[1]
        view = self._read_view(underlying, ref)
        self._view_cache = (key, view)
        return view

    def _read_view(self, underlying: str, ref: SessionRef) -> SessionView | None:
        if not ref.has_refdata:
            return None
        frame = self._store.load_session(ref)
        refdata = self._store.load_refdata(ref)
        view = SessionView.from_frame(ref.session_date, underlying, frame, refdata)
        minute = view.minute_at_or_after(self._decision_time)
        # `through` is the look-ahead guard, not an optimisation: without it the view holds
        # the settlement window's prints and every feature below could read them.
        return view.through(minute) if minute is not None else view

    def _summary(self, underlying: str, ref: SessionRef) -> SessionSummary:
        key = (underlying, ref.session_date)
        cached = self._summaries.get(key)
        if cached is not None:
            return cached
        view = self._view(underlying, ref)
        summary = (
            _summarise(view)
            if view is not None
            else SessionSummary(ref.session_date, None, None, None, None, None, None)
        )
        self._summaries[key] = summary
        return summary

    def _regime(self, summaries: Sequence[SessionSummary]) -> RegimeTag:
        spreads: list[float] = []
        for index in range(len(summaries)):
            window = summaries[: index + 1]
            spread = _iv_minus_rv(window, _RV_LONG_SESSIONS)
            if spread is not None:
                spreads.append(spread)
        trailing = spreads[-self._regime_lookback :]
        if len(trailing) < 3 or trailing[-1] != spreads[-1]:
            return RegimeTag(
                tag=None,
                lookback_sessions=self._regime_lookback,
                observations=len(trailing),
                lower_tercile=None,
                upper_tercile=None,
                reason=(
                    f"{len(trailing)} computable implied-minus-realised observations in the "
                    f"trailing {self._regime_lookback} sessions, and a tercile needs at "
                    "least three including the as-of session"
                ),
            )
        ordered = sorted(trailing)
        lower = _quantile(ordered, 1 / 3)
        upper = _quantile(ordered, 2 / 3)
        current = trailing[-1]
        tag = (
            "iv_rv_low" if current <= lower else ("iv_rv_high" if current >= upper else "iv_rv_mid")
        )
        return RegimeTag(
            tag=tag,
            lookback_sessions=self._regime_lookback,
            observations=len(trailing),
            lower_tercile=lower,
            upper_tercile=upper,
        )


# ------------------------------------------------------------------- feature arithmetic


def _summarise(view: SessionView) -> SessionSummary:
    bars = view.underlying_bars()
    if not bars:
        return SessionSummary(view.session_date, None, None, None, None, None, None)
    expiry = view.universe.nearest_expiry(view.session_date)
    close = bars[-1].close
    return SessionSummary(
        session_date=view.session_date,
        open=bars[0].open,
        high=max(bar.high for bar in bars),
        low=min(bar.low for bar in bars),
        close=close,
        atm_iv=_atm_iv(view, bars[-1].minute, close, expiry),
        nearest_expiry=expiry,
    )


def _atm_iv(
    view: SessionView, minute: dt.datetime, spot: float, expiry: dt.date | None
) -> float | None:
    """The mean of the ATM call's and put's implied volatility at ``minute``.

    Both legs are required. One leg alone is a directional volatility reading — the call
    and put of the same strike carry different skew — and averaging whichever happened to
    print would make the series' meaning depend on liquidity.

    **A contract expiring on the session itself is not read.** Minutes before its own
    settlement an at-the-money option's time value has decayed to the tick, and the implied
    volatility backed out of that price is dominated by rounding rather than by the market's
    view of forward variance — on this corpus the two legs of the expiring at-the-money
    straddle print 10% and 1.6% on the same strike in the same minute. Including it would
    put one incomparable observation per week into the trailing distribution the regime
    tercile is cut from. The corpus carries bars only for the front expiry, so no later
    contract can stand in; the feature is therefore ``None`` on expiry sessions, which is
    also the population the templates decline to enter.
    """
    if expiry is None or spot <= 0:
        return None
    if expiry == view.session_date:
        return None
    strike = view.universe.atm_strike(spot, expiry)
    if strike is None:
        return None
    values: list[float] = []
    for option_type in (OptionType.CALL, OptionType.PUT):
        contract = view.universe.get(expiry, strike, option_type)
        if contract is None:
            return None
        bar = view.bar(contract.trading_symbol, minute)
        if bar is None or bar.iv is None or bar.iv <= 0:
            return None
        values.append(bar.iv)
    return sum(values) / len(values)


def _closes(summaries: Sequence[SessionSummary]) -> list[float]:
    return [s.close for s in summaries if s.close is not None and s.close > 0]


def _realised_vol(summaries: Sequence[SessionSummary], sessions: int) -> float | None:
    """Annualised close-to-close volatility over the last ``sessions`` returns.

    Sample standard deviation, so the estimator is unbiased for the variance of the
    returns; ``sessions`` returns require ``sessions + 1`` closes and fewer than that
    returns ``None`` rather than a shorter-window figure wearing the long window's label.
    """
    closes = _closes(summaries)
    if len(closes) < sessions + 1:
        return None
    window = closes[-(sessions + 1) :]
    returns = [math.log(b / a) for a, b in pairwise(window)]
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    return math.sqrt(variance) * math.sqrt(ANNUALISATION_SESSIONS)


def _iv_minus_rv(summaries: Sequence[SessionSummary], sessions: int) -> float | None:
    if not summaries or summaries[-1].atm_iv is None:
        return None
    realised = _realised_vol(summaries, sessions)
    if realised is None:
        return None
    return summaries[-1].atm_iv - realised


def _atr(summaries: Sequence[SessionSummary], sessions: int) -> float | None:
    """Mean true range over the last ``sessions`` sessions, in index points.

    True range is the widest of the session's own range and the two gaps against the
    previous close, so it counts an overnight move the high-minus-low would miss entirely.
    """
    usable = [
        s for s in summaries if s.high is not None and s.low is not None and s.close is not None
    ]
    if len(usable) < sessions + 1:
        return None
    window = usable[-(sessions + 1) :]
    ranges: list[float] = []
    for previous, current in pairwise(window):
        high, low, prior_close = current.high, current.low, previous.close
        if high is None or low is None or prior_close is None:
            return None
        ranges.append(max(high - low, abs(high - prior_close), abs(prior_close - low)))
    return sum(ranges) / len(ranges)


def _ema(summaries: Sequence[SessionSummary], span: int) -> float | None:
    """Exponential moving average of closes, seeded on a fixed warm-up.

    The seed is the simple average of the ``span`` closes that begin a fixed warm-up window
    ending at the as-of session, so the answer depends on the as-of date and the span, and
    not on how much history the caller happened to resolve.
    """
    closes = _closes(summaries)
    if len(closes) < span:
        return None
    window = closes[-_EMA_WARMUP_SESSIONS:]
    if len(window) < span:
        return None
    average = sum(window[:span]) / span
    weight = 2.0 / (span + 1)
    for close in window[span:]:
        average = weight * close + (1 - weight) * average
    return average


def _quantile(ordered: Sequence[float], fraction: float) -> float:
    """Linear-interpolated quantile of an already-sorted sequence."""
    if len(ordered) == 1:
        return ordered[0]
    position = fraction * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _sessions_to_expiry(
    calendar: TradingCalendar, as_of: dt.date, expiry: dt.date | None
) -> float | None:
    """Trading days from ``as_of`` to ``expiry``, the as-of session excluded.

    Counted against the exchange calendar rather than against the corpus. A calendar is a
    published schedule, not a measurement of the future, so reading it forward is not
    look-ahead — and counting corpus files forward would be, since the corpus only knows a
    future session exists once it has happened.
    """
    if expiry is None or expiry < as_of:
        return None
    try:
        days = calendar.trading_days(as_of, expiry)
    except CalendarCoverageError:
        # The published holiday table ends before the expiry. That is a fact about the
        # calendar's coverage, not about the market, and it is reported as an
        # uncomputable feature rather than as a guessed session count.
        return None
    return float(max(0, len(days) - 1))


def _compute(
    summaries: Sequence[SessionSummary], *, calendar: TradingCalendar, as_of: dt.date
) -> dict[str, FeatureValue]:
    latest = summaries[-1]
    previous = summaries[-2] if len(summaries) > 1 else None

    atr = _atr(summaries, _ATR_SESSIONS)
    ema = _ema(summaries, _EMA_SPAN)
    rv_short = _realised_vol(summaries, _RV_SHORT_SESSIONS)
    rv_long = _realised_vol(summaries, _RV_LONG_SESSIONS)

    gap: float | None = None
    if previous is not None and previous.close and latest.open is not None:
        gap = latest.open / previous.close - 1.0

    z: float | None = None
    if latest.close is not None and ema is not None and atr is not None and atr > 0:
        z = (latest.close - ema) / (2.0 * atr)

    values: list[FeatureValue] = [
        FeatureValue(
            name="atm_iv",
            value=latest.atm_iv,
            lookback_sessions=1,
            unit="annualised volatility",
            description=(
                "Mean of the at-the-money call and put implied volatility of the nearest "
                "listed expiry, at the decision minute."
            ),
            reason=_atm_iv_reason(latest, as_of),
        ),
        FeatureValue(
            name="realised_vol_10",
            value=rv_short,
            lookback_sessions=_RV_SHORT_SESSIONS,
            unit="annualised volatility",
            description=(
                "Annualised sample standard deviation of the last ten close-to-close log "
                "returns of the index, measured at the decision minute of each session."
            ),
            reason=None
            if rv_short is not None
            else _missing(f"{_RV_SHORT_SESSIONS + 1} session closes"),
        ),
        FeatureValue(
            name="realised_vol_20",
            value=rv_long,
            lookback_sessions=_RV_LONG_SESSIONS,
            unit="annualised volatility",
            description=(
                "Annualised sample standard deviation of the last twenty close-to-close log "
                "returns of the index, measured at the decision minute of each session."
            ),
            reason=None
            if rv_long is not None
            else _missing(f"{_RV_LONG_SESSIONS + 1} session closes"),
        ),
        FeatureValue(
            name="iv_minus_rv_10",
            value=None if latest.atm_iv is None or rv_short is None else latest.atm_iv - rv_short,
            lookback_sessions=_RV_SHORT_SESSIONS,
            unit="annualised volatility",
            description="ATM implied volatility minus ten-session realised volatility.",
            reason=(
                None
                if latest.atm_iv is not None and rv_short is not None
                else _missing("both ATM implied volatility and ten-session realised volatility")
            ),
        ),
        FeatureValue(
            name=ATM_IV_MINUS_RV20,
            value=None if latest.atm_iv is None or rv_long is None else latest.atm_iv - rv_long,
            lookback_sessions=_RV_LONG_SESSIONS,
            unit="annualised volatility",
            description=(
                "ATM implied volatility minus twenty-session realised volatility — the "
                "observable proxy for what a variance seller is currently being paid."
            ),
            reason=(
                None
                if latest.atm_iv is not None and rv_long is not None
                else _missing("both ATM implied volatility and twenty-session realised volatility")
            ),
        ),
        FeatureValue(
            name="atr_14",
            value=atr,
            lookback_sessions=_ATR_SESSIONS,
            unit="index points",
            description=(
                "Mean true range over fourteen sessions, counting overnight gaps against "
                "the previous close as well as each session's own range."
            ),
            reason=None if atr is not None else _missing(f"{_ATR_SESSIONS + 1} session ranges"),
        ),
        FeatureValue(
            name="ema_20",
            value=ema,
            lookback_sessions=_EMA_WARMUP_SESSIONS,
            unit="index points",
            description=(
                "Twenty-session exponential moving average of the index, warmed up over a "
                "fixed sixty-session window so the value depends only on the as-of date."
            ),
            reason=None if ema is not None else _missing(f"{_EMA_SPAN} session closes"),
        ),
        FeatureValue(
            name="ema20_z",
            value=z,
            lookback_sessions=_EMA_WARMUP_SESSIONS,
            unit="ATR multiples",
            description=(
                "Distance of the index from its twenty-session exponential average, in "
                "units of twice the fourteen-session average true range."
            ),
            reason=None
            if z is not None
            else _missing("a close, an exponential average and a positive average true range"),
        ),
        FeatureValue(
            name="overnight_gap_return",
            value=gap,
            lookback_sessions=2,
            unit="fraction",
            description=(
                "The as-of session's opening print against the previous session's close at "
                "the decision minute."
            ),
            reason=None
            if gap is not None
            else _missing("an opening print and a previous session close"),
        ),
        FeatureValue(
            name="sessions_to_nearest_expiry",
            value=_sessions_to_expiry(calendar, as_of, latest.nearest_expiry),
            lookback_sessions=1,
            unit="sessions",
            description=(
                "Exchange trading days from the as-of session to the nearest listed expiry, "
                "the as-of session excluded."
            ),
            reason=(
                None
                if latest.nearest_expiry is not None
                else _missing("a listed expiry at or after the as-of session")
            ),
        ),
    ]
    return {feature.name: feature for feature in values}


def _missing(what: str) -> str:
    return f"not computable: the window does not provide {what}"


def _atm_iv_reason(latest: SessionSummary, as_of: dt.date) -> str | None:
    """Why the surface reading is absent, distinguishing the two reasons it can be."""
    if latest.atm_iv is not None:
        return None
    if latest.nearest_expiry == as_of:
        return (
            "not read: the nearest listed expiry is the as-of session itself, and an "
            "at-the-money option minutes from settlement carries no comparable implied "
            "volatility; the corpus holds bars only for the front expiry, so no later "
            "contract can supply the reading either"
        )
    return _missing("both ATM legs at the decision minute")
