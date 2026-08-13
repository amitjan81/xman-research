"""The seam: what C6 needs from a run, stated without importing the backtester.

C5 is a separate component on a separate branch. Importing it here would couple the
thing that computes a result to the thing that judges it, and the judgement would then
be untestable without a backtest — which is exactly the shape that makes a validation
layer grade its own homework. So the input is a **narrow value object** a caller fills
in, and the acceptance tests fill it in from synthetic strategies with known truth.

Two facts about a run are needed and one is easy to leave out:

* the **net** return series, and
* the **cost drag** that produced it, per period, in the same units.

The second is not decoration. The headline number of this component is the multiple by
which costs would have to rise before the edge disappears (spec §2.1), and that question
cannot be asked of a series that has already absorbed its costs into a single net number.
:meth:`ReturnSeries.at_cost_multiple` is the whole reason the two travel separately.

**Adapting C5.** Checked against the merged component rather than sketched from its
branch — every name below exists on ``xman_research.backtest.engine.BacktestResult`` as
it stands on ``main``:

.. code-block:: python

    RunEvidence.from_equity_curve(
        result.equity_curve(),                    # tuple[(date, equity), ...]
        label=result.strategy_name,
        capital_base=float(result.config_provenance["starting_cash"]),
        total_cost=result.total_costs.total,      # dated costs are better; see below
        unverified_inputs=result.unverified_inputs,
        feasibility=FeasibilityFacts.from_verdicts(
            result.feasibility_counts(),
            intents_resized=len(result.resized_fills()),
            sessions_with_stale_marks=sum(1 for day in result.daily if day.stale_marks),
            sessions_run=result.sessions_run,
        ),
        peak_margin=result.peak_margin,
        trial_id=result.trial_id,
    )

Three things the obvious version of that gets wrong, all of them silent:

* ``capital_base`` is the **denominator of every return in this component**, so
  ``peak_margin`` is the wrong choice even though it is the more flattering one:
  :attr:`~xman_research.backtest.engine.BacktestResult.peak_margin` is a *derived* number
  that C5 itself documents as approximate, and it moves with the run. Starting cash is
  fixed and is what the equity curve is denominated in. ``peak_margin`` still travels, as
  its own field, for the return-on-capital question C6 does not ask.
* ``sessions_run`` and ``sessions_with_stale_marks`` must actually be passed. Their
  defaults are zero, which makes ``stale_fraction`` zero, which reads as *no session was
  marked stale* rather than *nobody said*. C5 counts stale marks per session precisely so
  this component can refuse; leaving the argument off discards that.
* the infeasible verdict set is C5's enumeration, not this component's — see
  :meth:`FeasibilityFacts.from_verdicts`.

``total_cost`` is the weaker of the two cost inputs: it can only be spread evenly over
the sessions, which is wrong on any day the book did not trade, and the run is stamped
``costs.uniformly_allocated`` when it is used. ``cost_by_date`` — costs bucketed from
``result.fills`` and ``result.settlements`` by date — is the honest input, and it is the
one thing the adapter has to build rather than copy.
"""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from xman_research.trial_log import DataWindow

__all__ = [
    "TRADING_SESSIONS_PER_YEAR",
    "FeasibilityFacts",
    "ReturnSeries",
    "RunEvidence",
    "SeriesError",
]

# NSE trades roughly 250 sessions a year; 252 is the convention every reference in this
# package annualises with, and switching between them moves an annualised Sharpe by 0.4%.
TRADING_SESSIONS_PER_YEAR = 252.0

UNIFORM_COST_STAMP = "costs.uniformly_allocated"


class SeriesError(ValueError):
    """Raised when a return series cannot mean what it claims to."""


@dataclass(frozen=True, slots=True)
class ReturnSeries:
    """Per-session returns on a fixed capital base, net of costs, plus the drag.

    ``net[i]`` is the return realised over the session ending ``dates[i]``, already net
    of ``drag[i]``. ``gross`` is ``net + drag``. Returns are **simple returns on a fixed
    base**, not compounded on running equity: an options book sized to a margin
    requirement does not reinvest its own P&L within a backtest window, and compounding
    a series that was never compounded flatters a rising equity curve and punishes a
    falling one.
    """

    dates: tuple[dt.date, ...]
    net: tuple[float, ...]
    drag: tuple[float, ...]
    label: str = ""
    periods_per_year: float = TRADING_SESSIONS_PER_YEAR

    def __post_init__(self) -> None:
        if len(self.dates) != len(self.net) or len(self.dates) != len(self.drag):
            raise SeriesError(
                f"{self.label or 'series'}: dates, net and drag must be the same length "
                f"({len(self.dates)}, {len(self.net)}, {len(self.drag)})"
            )
        if len(self.dates) < 2:
            raise SeriesError(
                f"{self.label or 'series'}: a return series needs at least 2 observations "
                f"to have a dispersion, got {len(self.dates)}"
            )
        for earlier, later in zip(self.dates, self.dates[1:], strict=False):
            if later <= earlier:
                raise SeriesError(
                    f"{self.label or 'series'}: dates must be strictly increasing, "
                    f"found {earlier} followed by {later}"
                )
        for name, values in (("net", self.net), ("drag", self.drag)):
            for value in values:
                if not math.isfinite(value):
                    raise SeriesError(f"{self.label or 'series'}: non-finite {name} value {value}")
        if any(value < 0.0 for value in self.drag):
            raise SeriesError(
                f"{self.label or 'series'}: a negative cost drag means costs paid the book. "
                "Costs are a subtraction; sign it at the adapter, not here."
            )

    def __len__(self) -> int:
        return len(self.dates)

    @property
    def window(self) -> DataWindow:
        return DataWindow(self.dates[0], self.dates[-1])

    @property
    def gross(self) -> tuple[float, ...]:
        """Returns before costs — ``net + drag``."""
        return tuple(n + d for n, d in zip(self.net, self.drag, strict=True))

    def at_cost_multiple(self, multiple: float) -> ReturnSeries:
        """The same run with every cost multiplied by ``multiple``.

        This is a *counterfactual on the cost model only*. It cannot know that at 4x
        costs the strategy would have traded less, or not at all — a real cost rise
        changes behaviour, and this holds behaviour fixed. That makes the resulting
        breakeven multiple conservative in one direction (a real book would adapt) and
        optimistic in the other (a real book might not be able to). Stated, not hidden.
        """
        if multiple < 0.0:
            raise SeriesError(f"cost multiple must be non-negative, got {multiple}")
        return ReturnSeries(
            dates=self.dates,
            net=tuple(g - multiple * d for g, d in zip(self.gross, self.drag, strict=True)),
            drag=tuple(multiple * d for d in self.drag),
            label=f"{self.label}@{multiple:g}x-costs",
            periods_per_year=self.periods_per_year,
        )

    def restricted_to(self, window: DataWindow) -> ReturnSeries:
        """The sub-series falling inside ``window``, inclusive of both ends."""
        kept = [index for index, day in enumerate(self.dates) if window.start <= day <= window.end]
        if len(kept) < 2:
            raise SeriesError(
                f"{self.label or 'series'}: {window} contains {len(kept)} observations of "
                f"{len(self.dates)}; a sub-series needs at least 2"
            )
        return ReturnSeries(
            dates=tuple(self.dates[i] for i in kept),
            net=tuple(self.net[i] for i in kept),
            drag=tuple(self.drag[i] for i in kept),
            label=f"{self.label}[{window}]",
            periods_per_year=self.periods_per_year,
        )

    @classmethod
    def chained(cls, parts: Iterable[ReturnSeries], *, label: str) -> ReturnSeries:
        """Concatenate disjoint series in date order — the walk-forward OOS series.

        Overlapping dates are refused rather than merged: two folds covering the same
        session would count that session's return twice, which is how an out-of-sample
        series quietly acquires more evidence than the market provided.
        """
        ordered = sorted(parts, key=lambda part: part.dates[0])
        if not ordered:
            raise SeriesError(f"{label}: nothing to chain")
        dates: list[dt.date] = []
        net: list[float] = []
        drag: list[float] = []
        for part in ordered:
            if dates and part.dates[0] <= dates[-1]:
                raise SeriesError(
                    f"{label}: fold starting {part.dates[0]} overlaps the previous fold, "
                    f"which ends {dates[-1]}"
                )
            dates.extend(part.dates)
            net.extend(part.net)
            drag.extend(part.drag)
        return cls(
            dates=tuple(dates),
            net=tuple(net),
            drag=tuple(drag),
            label=label,
            periods_per_year=ordered[0].periods_per_year,
        )


@dataclass(frozen=True, slots=True)
class FeasibilityFacts:
    """How much of the run the market would actually have taken.

    Spec §6's fourth outcome — *not evaluable* — is partly an execution question, so the
    verdict needs these numbers, not a P&L that silently assumes every intent filled.
    """

    intents_attempted: int = 0
    intents_infeasible: int = 0
    intents_resized: int = 0
    sessions_with_stale_marks: int = 0
    sessions_run: int = 0

    def __post_init__(self) -> None:
        for name in (
            "intents_attempted",
            "intents_infeasible",
            "intents_resized",
            "sessions_with_stale_marks",
            "sessions_run",
        ):
            if getattr(self, name) < 0:
                raise SeriesError(f"{name} cannot be negative")
        if self.intents_infeasible > self.intents_attempted:
            raise SeriesError("more intents were infeasible than were attempted")

    @property
    def infeasible_fraction(self) -> float:
        """Share of intents the market could not have taken. 0.0 when nothing was tried."""
        if not self.intents_attempted:
            return 0.0
        return self.intents_infeasible / self.intents_attempted

    @property
    def stale_fraction(self) -> float:
        return 0.0 if not self.sessions_run else self.sessions_with_stale_marks / self.sessions_run

    @classmethod
    def from_verdicts(
        cls,
        verdicts: Mapping[str, int],
        *,
        infeasible_verdicts: Sequence[str] = (
            "no_bar",
            "no_liquidity",
            "capped_to_zero",
            "group_incomplete",
        ),
        not_an_intent: Sequence[str] = ("settled",),
        intents_resized: int = 0,
        sessions_with_stale_marks: int = 0,
        sessions_run: int = 0,
    ) -> FeasibilityFacts:
        """Build from C5's ``BacktestResult.feasibility_counts()``.

        Both verdict sets are parameters because they belong to C5's enumeration, not to
        this component: if a verdict is added there, this adapter should be told about it
        rather than silently treating the new verdict as a fill.

        Two defaults are worth the words, because both were wrong in the direction of
        flattering the run:

        ``group_incomplete`` **is infeasible.** C5 defines it as a leg that was fillable on
        its own and did not trade because a sibling in its ``leg_group`` was not — the
        market did not take the structure, which is exactly what this fraction measures.
        C5's own ``BacktestResult.metrics()`` counts it under ``fills_infeasible``; omitting
        it here made the two components disagree about the same run, with C6 reading the
        lower number.

        ``settled`` **is not an intent.** Cash settlement at expiry is something the
        exchange does *to* the book — C5's own docstring says no participant can fail to
        receive it — so it can never be infeasible, and counting it in the denominator
        dilutes ``infeasible_fraction`` towards zero in proportion to how many expiries the
        run held through. A run whose every intent was refused reads as half-fine if it
        settled as many positions as it attempted.
        """
        excluded = set(not_an_intent)
        attempted = sum(int(value) for name, value in verdicts.items() if name not in excluded)
        infeasible = sum(
            int(verdicts.get(name, 0)) for name in infeasible_verdicts if name not in excluded
        )
        return cls(
            intents_attempted=attempted,
            intents_infeasible=infeasible,
            intents_resized=intents_resized,
            sessions_with_stale_marks=sessions_with_stale_marks,
            sessions_run=sessions_run,
        )


@dataclass(frozen=True, slots=True)
class RunEvidence:
    """One strategy, one window, everything C6 is allowed to judge it on.

    ``unverified_inputs`` travels with the run and is carried into the verdict verbatim.
    Nothing here can decide that a rate is fine; it can only refuse to present a clean
    number computed from one that is not.
    """

    label: str
    returns: ReturnSeries
    feasibility: FeasibilityFacts = field(default_factory=FeasibilityFacts)
    unverified_inputs: tuple[str, ...] = ()
    capital_base: float | None = None
    peak_margin: float | None = None
    trial_id: str | None = None
    run_at: dt.datetime | None = None
    fingerprint: str | None = None

    def __post_init__(self) -> None:
        if not self.label.strip():
            raise SeriesError("a run needs a label; an unlabelled result cannot be argued with")
        if self.run_at is not None and self.run_at.tzinfo is None:
            raise SeriesError(f"run_at must be timezone-aware, got naive {self.run_at!r}")

    @property
    def window(self) -> DataWindow:
        return self.returns.window

    @classmethod
    def from_equity_curve(
        cls,
        points: Sequence[tuple[dt.date, float]],
        *,
        label: str,
        capital_base: float,
        cost_by_date: Mapping[dt.date, float] | None = None,
        total_cost: float | None = None,
        feasibility: FeasibilityFacts | None = None,
        unverified_inputs: Iterable[str] = (),
        peak_margin: float | None = None,
        trial_id: str | None = None,
        run_at: dt.datetime | None = None,
        fingerprint: str | None = None,
        periods_per_year: float = TRADING_SESSIONS_PER_YEAR,
    ) -> RunEvidence:
        """Build from an equity curve and the costs that shaped it — the C5 adapter.

        Exactly one of ``cost_by_date`` and ``total_cost`` is required. Supplying neither
        would produce a series whose cost-breakeven multiple is infinite, which is the
        most flattering possible answer to the question this component exists to ask.
        """
        if (cost_by_date is None) == (total_cost is None):
            raise SeriesError(
                "supply exactly one of cost_by_date= (preferred) or total_cost=. A run "
                "with no cost input has an infinite cost-breakeven multiple, and that is "
                "not a result, it is a missing input."
            )
        if capital_base <= 0.0:
            raise SeriesError(f"capital_base must be positive, got {capital_base}")
        if len(points) < 3:
            raise SeriesError(
                f"an equity curve needs at least 3 points to yield 2 returns, got {len(points)}"
            )
        ordered = sorted(points, key=lambda point: point[0])
        dates = tuple(day for day, _ in ordered[1:])
        net = tuple(
            (ordered[i][1] - ordered[i - 1][1]) / capital_base for i in range(1, len(ordered))
        )
        stamps = list(unverified_inputs)
        if cost_by_date is not None:
            drag = tuple(float(cost_by_date.get(day, 0.0)) / capital_base for day in dates)
        else:
            assert total_cost is not None
            drag = tuple(float(total_cost) / capital_base / len(dates) for _ in dates)
            if UNIFORM_COST_STAMP not in stamps:
                stamps.append(UNIFORM_COST_STAMP)
        return cls(
            label=label,
            returns=ReturnSeries(
                dates=dates,
                net=net,
                drag=drag,
                label=label,
                periods_per_year=periods_per_year,
            ),
            feasibility=feasibility if feasibility is not None else FeasibilityFacts(),
            unverified_inputs=tuple(dict.fromkeys(stamps)),
            capital_base=capital_base,
            peak_margin=peak_margin,
            trial_id=trial_id,
            run_at=run_at,
            fingerprint=fingerprint,
        )
