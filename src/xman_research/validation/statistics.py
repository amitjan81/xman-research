"""The statistics a verdict is made of, and the one number that is the headline.

Everything in here takes a :class:`~xman_research.validation.series.ReturnSeries` or a
:class:`~xman_research.validation.series.RunEvidence` and returns a value object. Nothing
in here decides anything — the thresholds live in :mod:`xman_research.validation.gate`
and the grading in :mod:`xman_research.validation.decision`, because a statistic that
grades itself is not evidence.

**The trial count enters through exactly one door.** :class:`SelectionUniverse` reads it
from the append-only log and nothing else can state it. The parameterised expected-maximum
formula lives in the private :mod:`xman_research.validation._math`, and is reached through
the module object rather than re-exported, so the package-wide guard against
caller-supplied counts keeps holding.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass

from xman_research.evaluation import ResearchSession
from xman_research.hypothesis import HypothesisRecord
from xman_research.trial_log import TrialLog
from xman_research.validation import _math
from xman_research.validation.series import ReturnSeries, RunEvidence

__all__ = [
    "BenchmarkMismatchError",
    "CostBreakeven",
    "DeflatedSharpe",
    "DrawdownFacts",
    "RiskMatchedIncrement",
    "SelectionUniverse",
    "TailMetrics",
    "UnverifiedInputsError",
    "adjusted_sharpe_ratio",
    "annualised_sharpe_ratio",
    "cost_breakeven",
    "deflated_sharpe_ratio",
    "drawdown",
    "per_period_sharpe_ratio",
    "probabilistic_sharpe_ratio",
    "risk_matched_increment",
    "tail_metrics",
]

# Metric keys a logged trial may carry its own Sharpe under. The per-period form is
# preferred because it needs no unit conversion; the annualised form is usable only when
# the trial also recorded what it annualised by.
SHARPE_PER_PERIOD_KEY = "sharpe_per_period"
SHARPE_KEY = "sharpe"
SHARPE_PERIODICITY_KEY = "sharpe_periods_per_year"

ASSUMED_VARIANCE_STAMP = "dsr.sharpe_variance_assumed"
UNDECLARED_PERIODICITY_STAMP = "dsr.trial_sharpes_lack_declared_periodicity"
PARTIAL_PERIODICITY_STAMP = "dsr.some_trial_sharpes_lack_declared_periodicity"


class UnverifiedInputsError(RuntimeError):
    """Raised when a number computed from unverified inputs is asked for unqualified."""


class BenchmarkMismatchError(ValueError):
    """Raised when a benchmark was not run on the same window as the candidate."""


class SelectionUniverse:
    """How many ways this result could have been selected, read from the trial log.

    Deflating a Sharpe requires the size of the search that produced it, and the
    researcher is the one party who must not supply that number. So this object takes a
    log and a hypothesis and reads it — there is no argument by which a caller can assert
    it, and :attr:`size` is a read-only property.

    **The number is a lower bound, twice over, and both holes are C4's, not this
    component's.** A researcher who re-registers a reworded hypothesis instead of amending
    it mints a fresh family whose count is zero, and only configuration pins which
    database is read (see :class:`~xman_research.validation.decision.ValidationConfig`,
    which is why C6 does not accept a path per call). Neither is detectable from inside.
    A deflated Sharpe is therefore an *upper* bound on how good the result is: the true
    selection burden can only be larger than the logged one.
    """

    __slots__ = (
        "_hypothesis_id",
        "_log_path",
        "_sharpe_variance",
        "_size",
        "_size_excluding_no_result",
        "_undeclared_periodicity",
        "_variance_basis",
    )

    def __init__(
        self,
        source: ResearchSession | TrialLog,
        hypothesis: HypothesisRecord | str,
    ) -> None:
        log = source.log if isinstance(source, ResearchSession) else source
        hypothesis_id = hypothesis.id if isinstance(hypothesis, HypothesisRecord) else hypothesis
        self._hypothesis_id = hypothesis_id
        self._log_path = log.db_path
        # The family, not the single record: 200 variants of H1 are 200 ways this result
        # could have been chosen, however many records they were written as.
        self._size = log.count_family_trials(hypothesis_id)
        records = log.family_trials(hypothesis_id)
        # Both numbers come from the log. The second is not a smaller count of trials —
        # every row is still there and still undeletable — it is the same family read
        # with the rows that produced no number to judge set aside, so the operator can
        # see how much of the deflation those rows are responsible for.
        self._size_excluding_no_result = sum(
            1 for record in records if not record.recorded_no_result
        )
        variance, basis, undeclared = _observed_sharpe_variance(records)
        self._sharpe_variance = variance
        self._variance_basis = basis
        self._undeclared_periodicity = undeclared

    @property
    def size(self) -> int:
        """Logged trials in this hypothesis's family. Read from the log; a lower bound."""
        return self._size

    @property
    def size_excluding_no_result(self) -> int:
        """The same family, counting only rows that recorded a result.

        A row is set aside when it raised *and* carries no metrics — two facts already
        in the row, with no judgement about *why* the run died. See
        :attr:`~xman_research.trial_log.TrialRecord.recorded_no_result`.

        **This is the optimistic number and it does not govern anything.** Requiring
        empty metrics makes the exclusion narrow, so it under-excludes rather than over-
        excludes; and because a researcher controls both whether a run throws and
        whether it records metrics, it is a channel that can be driven deliberately.
        That is survivable only because :attr:`size` is still what the verdict is graded
        on. Reported beside it, never instead of it.
        """
        return self._size_excluding_no_result

    @property
    def hypothesis_id(self) -> str:
        return self._hypothesis_id

    @property
    def log_path(self) -> str:
        return str(self._log_path)

    @property
    def sharpe_variance(self) -> float | None:
        """Cross-trial variance of the logged per-period Sharpes, or ``None``.

        ``None`` means the log could not supply it — fewer than two trials recorded a
        Sharpe, or they recorded one without saying what they annualised by. The deflation
        then falls back to the null sampling variance and stamps itself.
        """
        return self._sharpe_variance

    @property
    def variance_basis(self) -> str:
        """``observed`` when read from logged trial metrics, else why it was not."""
        return self._variance_basis

    @property
    def undeclared_periodicity_trials(self) -> int:
        """Trials that recorded a Sharpe without saying what they annualised by.

        These are excluded from :attr:`sharpe_variance`. Non-zero alongside an
        ``observed`` basis means the variance was computed from a *minority* of the
        family, which the verdict is told about rather than left to infer."""
        return self._undeclared_periodicity

    def __repr__(self) -> str:
        return (
            f"SelectionUniverse(hypothesis_id={self._hypothesis_id!r}, size={self._size}, "
            f"variance_basis={self._variance_basis!r})"
        )


def _observed_sharpe_variance(records: tuple) -> tuple[float | None, str, int]:
    """Variance of the per-period Sharpes the trials themselves recorded.

    Returns the variance, why it is what it is, and **how many trials were skipped** for
    recording a Sharpe without saying what they annualised by. That third number used to
    be invisible whenever two usable Sharpes survived: a family where 2 of 200 trials
    declared their periodicity produced a confident-looking ``observed`` variance from
    two draws, with the other 198 silently dropped and nothing saying so.
    """
    observed: list[float] = []
    undeclared = 0
    for record in records:
        metrics = record.metrics
        value = metrics.get(SHARPE_PER_PERIOD_KEY)
        if isinstance(value, int | float) and math.isfinite(value):
            observed.append(float(value))
            continue
        annualised = metrics.get(SHARPE_KEY)
        periodicity = metrics.get(SHARPE_PERIODICITY_KEY)
        if isinstance(annualised, int | float) and math.isfinite(annualised):
            if isinstance(periodicity, int | float) and periodicity > 0:
                observed.append(float(annualised) / math.sqrt(float(periodicity)))
            else:
                # A Sharpe of unknown periodicity is not a small error: annualised by 252
                # it is 15.9x the per-period figure, and the deflation would be computed
                # against a variance 252 times too large — which makes every result pass.
                undeclared += 1
    if len(observed) >= 2:
        _, stdev, _, _ = _math.moments(tuple(observed))
        return stdev * stdev, "observed", undeclared
    if undeclared:
        return None, UNDECLARED_PERIODICITY_STAMP, undeclared
    return None, ASSUMED_VARIANCE_STAMP, undeclared


@dataclass(frozen=True, slots=True)
class DeflatedSharpe:
    """A Sharpe ratio with the size of the search that found it taken out of it."""

    value: float
    observed_sharpe: float
    expected_max_sharpe: float
    selection_size: int
    sharpe_variance: float
    variance_basis: str
    sample_length: int
    skew: float
    kurtosis: float
    value_excluding_no_result: float
    selection_size_excluding_no_result: int
    unverified_inputs: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "deflated_sharpe": self.value,
            # Reported, not graded. The pair is the point: the spread between them is the
            # share of the deflation carried by rows that recorded no result, which was
            # previously invisible. No threshold reads the second one — it is absent from
            # the gate's vocabulary on purpose.
            "deflated_sharpe_excluding_no_result": self.value_excluding_no_result,
            "selection_size_excluding_no_result": self.selection_size_excluding_no_result,
            "observed_sharpe_per_period": self.observed_sharpe,
            "expected_max_sharpe": self.expected_max_sharpe,
            "selection_size": self.selection_size,
            "sharpe_variance": self.sharpe_variance,
            "variance_basis": self.variance_basis,
            "sample_length": self.sample_length,
            "skew": self.skew,
            "kurtosis": self.kurtosis,
        }


def per_period_sharpe_ratio(returns: ReturnSeries) -> float:
    """Sharpe of the net series, per period, zero risk-free rate."""
    return _math.sharpe(returns.net)


def annualised_sharpe_ratio(returns: ReturnSeries) -> float:
    """The per-period Sharpe scaled by ``sqrt(periods_per_year)``.

    Reported because it is what everyone reads, and used nowhere in the deflation: the
    square-root rule assumes serial independence, which an options book that holds a
    position across sessions does not have.
    """
    return per_period_sharpe_ratio(returns) * math.sqrt(returns.periods_per_year)


def probabilistic_sharpe_ratio(returns: ReturnSeries, *, benchmark_sharpe: float = 0.0) -> float:
    """PSR — the probability the true per-period Sharpe exceeds ``benchmark_sharpe``.

    Bailey and López de Prado (2012). ``benchmark_sharpe`` is per-period, and the default
    of zero asks the plainest question: is there any edge at all, given this many
    observations and this shape of return distribution.
    """
    _, _, skew, kurtosis = _math.moments(returns.net)
    return _math.probabilistic_sharpe(
        observed=per_period_sharpe_ratio(returns),
        benchmark=benchmark_sharpe,
        sample_length=len(returns),
        skew=skew,
        kurtosis=kurtosis,
    )


def deflated_sharpe_ratio(
    returns: ReturnSeries,
    *,
    universe: SelectionUniverse,
) -> DeflatedSharpe:
    """DSR: PSR measured against the Sharpe the *best of N tries on noise* would show.

    Bailey and López de Prado (2014). Two steps:

    1. :math:`SR^*` — the expected maximum Sharpe across ``universe.size`` trials under
       the null that none of them has any edge (``_math.expected_max_sharpe``).
    2. :math:`PSR(SR^*)` — the probability the observed Sharpe beats that, given the
       sample length, skew and kurtosis of *this* return series.

    The result is a probability. 0.95 is the conventional bar and it is a *threshold*,
    written down in the gate file before the run, not a constant in this function.

    The variance of trial Sharpes is read from the log when the trials recorded one.
    When they did not, the fallback is the null sampling variance :math:`1/(T-1)` — the
    variance of a per-period Sharpe estimated from ``T`` observations of a zero-Sharpe
    series — and the result is stamped ``dsr.sharpe_variance_assumed``. The fallback is
    honest but weak: a real strategy family's Sharpes disperse more than the null says,
    so an assumed variance understates :math:`SR^*` and therefore *flatters* the DSR.

    **The ``T`` in that fallback is the wrong ``T``, deliberately.** The quantity being
    approximated is the dispersion of *the trials'* Sharpes, so the sampling variance
    that belongs there is one over the length of a typical trial minus one — and the
    trials' lengths are not something this function can see (the log records each trial's
    window, but not every trial in a family need have run on the same amount of
    evidence). What is used instead is the length of the series being judged, which is
    the longest thing to hand. Since :math:`1/(T-1)` shrinks as ``T`` grows, and the
    judged series is typically at least as long as any single trial, the substitution
    makes the assumed variance *smaller*, :math:`SR^*` *lower*, and the DSR *higher* —
    it errs towards passing. Stated because a stamp saying "assumed" does not say in
    which direction, and this one is not conservative.
    """
    observed = per_period_sharpe_ratio(returns)
    _, _, skew, kurtosis = _math.moments(returns.net)
    sample_length = len(returns)
    stamps: list[str] = []
    variance = universe.sharpe_variance
    if variance is None:
        variance = 1.0 / (sample_length - 1)
        stamps.append(universe.variance_basis)
    if universe.undeclared_periodicity_trials and universe.variance_basis == "observed":
        stamps.append(PARTIAL_PERIODICITY_STAMP)
    benchmark = _math.expected_max_sharpe(sharpe_variance=variance, trials=universe.size)
    value = _math.probabilistic_sharpe(
        observed=observed,
        benchmark=benchmark,
        sample_length=sample_length,
        skew=skew,
        kurtosis=kurtosis,
    )
    # The same computation over the same family with the no-result rows set aside. It is
    # computed unconditionally rather than only when the two differ, so that a family
    # with nothing set aside reports two equal numbers rather than a missing one — an
    # absent field would have to be told apart from a zero spread by whoever read it.
    setting_aside = universe.size_excluding_no_result
    if setting_aside == universe.size:
        value_excluding = value
    else:
        # A family every one of whose rows recorded no result leaves setting_aside == 0,
        # and it is reachable: H26 v1 is two rows and both of them raised with no metrics.
        # The expected maximum of zero draws does not exist, and `expected_max_sharpe`
        # rightly refuses it. One draw is the nearest thing that does exist and it is the
        # correct reading of the limit — SR* = 0, no selection burden, so the number
        # reported is the undeflated probabilistic Sharpe. The *size* beside it is still
        # the true 0, because that is what was counted; only the deflation is evaluated at
        # the no-selection case, and reporting 1 there would misstate the log.
        value_excluding = _math.probabilistic_sharpe(
            observed=observed,
            benchmark=_math.expected_max_sharpe(
                sharpe_variance=variance, trials=max(setting_aside, 1)
            ),
            sample_length=sample_length,
            skew=skew,
            kurtosis=kurtosis,
        )
    return DeflatedSharpe(
        value=value,
        value_excluding_no_result=value_excluding,
        selection_size_excluding_no_result=setting_aside,
        observed_sharpe=observed,
        expected_max_sharpe=benchmark,
        selection_size=universe.size,
        sharpe_variance=variance,
        variance_basis=universe.variance_basis,
        sample_length=sample_length,
        skew=skew,
        kurtosis=kurtosis,
        unverified_inputs=tuple(stamps),
    )


@dataclass(frozen=True, slots=True)
class DrawdownFacts:
    """The worst peak-to-trough fall of the fixed-base equity path."""

    max_drawdown: float
    peak_date: dt.date
    trough_date: dt.date
    sessions_under_water: int
    ruined: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "max_drawdown": self.max_drawdown,
            "drawdown_peak": self.peak_date.isoformat(),
            "drawdown_trough": self.trough_date.isoformat(),
            "sessions_under_water": self.sessions_under_water,
            "ruined": self.ruined,
        }


def drawdown(returns: ReturnSeries) -> DrawdownFacts:
    """Maximum drawdown on the equity path implied by the fixed-base returns.

    The path is ``1 + cumsum(net)`` — additive, because the series is additive (see
    :class:`ReturnSeries`). If it ever reaches zero the book is wiped out; the drawdown
    is 1.0, ``ruined`` is set, and the numbers after that point describe a book that no
    longer exists.
    """
    equity = 1.0
    peak = 1.0
    peak_date = returns.dates[0]
    best_peak_date = returns.dates[0]
    worst = 0.0
    trough_date = returns.dates[0]
    under_water = 0
    ruined = False
    for day, value in zip(returns.dates, returns.net, strict=True):
        equity += value
        if equity <= 0.0:
            ruined = True
            return DrawdownFacts(
                1.0, best_peak_date if worst > 0 else peak_date, day, under_water + 1, ruined=True
            )
        if equity > peak:
            peak = equity
            peak_date = day
        elif equity < peak:
            # Strictly below. A session that closes exactly back at the previous peak has
            # recovered — counting it as under water overstates the recovery time, and on
            # a series with flat sessions (a conditional strategy out of the market) it
            # overstates it a lot.
            under_water += 1
        fall = (peak - equity) / peak
        if fall > worst:
            worst = fall
            trough_date = day
            best_peak_date = peak_date
    return DrawdownFacts(worst, best_peak_date, trough_date, under_water, ruined=ruined)


@dataclass(frozen=True, slots=True)
class TailMetrics:
    """What a Sharpe ratio hides about a short-option payoff.

    A short straddle earns a small premium most sessions and pays a large loss rarely.
    That shape has *low* standard deviation relative to its true risk, so the Sharpe
    ratio — which divides by exactly that — systematically flatters it. Each number here
    is chosen to be sensitive to the part the Sharpe is blind to: the third and fourth
    moments (``adjusted_sharpe``), the mean of the bad tail (``expected_shortfall``), and
    the path rather than the distribution (``max_drawdown``, ``calmar``).
    """

    annualised_sharpe: float
    adjusted_sharpe: float
    annualised_adjusted_sharpe: float
    skew: float
    kurtosis: float
    expected_shortfall: float
    worst_period: float
    max_drawdown: float
    calmar: float | None
    sessions_under_water: int
    ruined: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "annualised_sharpe": self.annualised_sharpe,
            # Named for the units. This used to be "adjusted_sharpe" while the gate read
            # `tails.annualised_adjusted_sharpe` under the same name — one label for two
            # numbers a factor of sqrt(252) = 15.9 apart, with the per-period one being
            # what landed in the trial log.
            "adjusted_sharpe_per_period": self.adjusted_sharpe,
            "annualised_adjusted_sharpe": self.annualised_adjusted_sharpe,
            "skew": self.skew,
            "kurtosis": self.kurtosis,
            "expected_shortfall_05": self.expected_shortfall,
            "worst_period": self.worst_period,
            "max_drawdown": self.max_drawdown,
            "calmar": self.calmar,
            "sessions_under_water": self.sessions_under_water,
            "ruined": self.ruined,
        }


def adjusted_sharpe_ratio(returns: ReturnSeries) -> float:
    """Pézier-White adjusted Sharpe, per period. See :func:`_math.adjusted_sharpe`."""
    _, _, skew, kurtosis = _math.moments(returns.net)
    return _math.adjusted_sharpe(
        observed=per_period_sharpe_ratio(returns), skew=skew, kurtosis=kurtosis
    )


def expected_shortfall(returns: ReturnSeries, *, tail: float = 0.05) -> float:
    """Mean of the worst ``tail`` fraction of periods (CVaR), as a negative number.

    At least one observation always enters the average, so a short series reports its
    worst period rather than nothing.
    """
    if not 0.0 < tail <= 1.0:
        raise ValueError(f"tail must be in (0, 1], got {tail}")
    ordered = sorted(returns.net)
    take = max(1, math.floor(tail * len(ordered)))
    return math.fsum(ordered[:take]) / take


def tail_metrics(returns: ReturnSeries) -> TailMetrics:
    """The tail block of the verdict."""
    _, _, skew, kurtosis = _math.moments(returns.net)
    per_period = per_period_sharpe_ratio(returns)
    adjusted = _math.adjusted_sharpe(observed=per_period, skew=skew, kurtosis=kurtosis)
    facts = drawdown(returns)
    annualised_return = math.fsum(returns.net) / len(returns) * returns.periods_per_year
    calmar = None if facts.max_drawdown <= 0.0 else annualised_return / facts.max_drawdown
    return TailMetrics(
        annualised_sharpe=per_period * math.sqrt(returns.periods_per_year),
        adjusted_sharpe=adjusted,
        annualised_adjusted_sharpe=adjusted * math.sqrt(returns.periods_per_year),
        skew=skew,
        kurtosis=kurtosis,
        expected_shortfall=expected_shortfall(returns),
        worst_period=min(returns.net),
        max_drawdown=facts.max_drawdown,
        calmar=calmar,
        sessions_under_water=facts.sessions_under_water,
        ruined=facts.ruined,
    )


@dataclass(frozen=True, slots=True)
class CostBreakeven:
    """**The headline number.** How wrong the cost model can be before the edge is gone.

    Spec §2.1: there are no realised fills, so the cost stack is a documented assumption
    rather than a calibration. The Sharpe of an uncalibrated backtest is a statement about
    a cost model; *how far that model can be wrong* is the only question the evidence can
    actually answer, so it is the number this component leads with.

    ``multiple`` is the factor by which every cost would have to rise for the mean net
    return to reach zero — which is also where the Sharpe reaches zero, since scaling
    costs shifts the mean and leaves nothing else fixed. Below 1.0 the strategy is already
    losing at the modelled rates.

    **It refuses to be a clean number when its inputs are not.** ``str()`` always carries
    the unverified stamps, and ``float()`` raises when there are any — a caller that wants
    the bare value while inputs are unverified has to reach for
    :attr:`multiple` and say so in its own code.
    """

    multiple: float
    mean_gross: float
    mean_drag: float
    unverified_inputs: tuple[str, ...] = ()

    @property
    def unbounded(self) -> bool:
        """True when the run recorded no costs at all — not a result, a missing input."""
        return math.isinf(self.multiple)

    @property
    def cost_share(self) -> float | None:
        """Share of the gross edge that costs already eat. ``1/multiple``, when finite."""
        return None if self.multiple == 0.0 or self.unbounded else 1.0 / self.multiple

    def __float__(self) -> float:
        if self.unverified_inputs:
            raise UnverifiedInputsError(
                f"the cost-breakeven multiple is {self.multiple:.2f}x but was computed from "
                f"unverified inputs ({', '.join(self.unverified_inputs)}). It cannot be "
                "handed on as a bare number. Read .multiple explicitly, and carry the "
                "stamps with it."
            )
        return self.multiple

    def __str__(self) -> str:
        rendered = "unbounded (no costs recorded)" if self.unbounded else f"{self.multiple:.2f}x"
        if not self.unverified_inputs:
            return f"cost-breakeven {rendered}"
        return (
            f"cost-breakeven {rendered} — computed from unverified inputs: "
            f"{', '.join(self.unverified_inputs)}"
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "cost_breakeven_multiple": self.multiple,
            "mean_gross_return": self.mean_gross,
            "mean_cost_drag": self.mean_drag,
            "cost_share_of_gross": self.cost_share,
            "unverified_inputs": list(self.unverified_inputs),
        }


def cost_breakeven(run: RunEvidence) -> CostBreakeven:
    """The multiple at which this run's edge disappears.

    A negative gross edge gives a multiple of 0.0: there is nothing for costs to consume,
    the strategy loses before them.
    """
    series = run.returns
    mean_gross = math.fsum(series.gross) / len(series)
    mean_drag = math.fsum(series.drag) / len(series)
    if mean_drag <= 0.0:
        multiple = math.inf
    elif mean_gross <= 0.0:
        multiple = 0.0
    else:
        multiple = mean_gross / mean_drag
    return CostBreakeven(
        multiple=multiple,
        mean_gross=mean_gross,
        mean_drag=mean_drag,
        unverified_inputs=tuple(run.unverified_inputs),
    )


@dataclass(frozen=True, slots=True)
class RiskMatchedIncrement:
    """What the candidate adds over the naive benchmark, at the same risk.

    Raw P&L is the wrong comparison and it is wrong in a direction that matters here: a
    *conditional* signal is out of the market much of the time, so it carries less risk
    and earns less money than an always-on benchmark however good its timing is. Matching
    on volatility is what makes the difference attributable to timing rather than to
    exposure.

    ``benchmark_scale`` is what the benchmark had to be multiplied by to reach the
    candidate's volatility. Above 1.0 the comparison is against a *levered* benchmark,
    which may not be reachable under margin — the increment is then an upper bound on
    what the candidate adds in practice, and ``leverage_caveat`` says so.
    """

    annualised_increment: float
    candidate_annualised_return: float
    benchmark_annualised_return: float
    benchmark_scale: float
    sharpe_difference: float
    candidate_exposure: float
    """Share of sessions with a non-zero return — a *proxy* for time in the market.

    It is not the same thing: a session held flat that happened to close exactly at its
    open reads as out of the market, and a session out of the market reads the same way.
    The two are indistinguishable from a return series alone, which is all this component
    is given. Read it as an upper bound on idleness, not as a position record."""

    benchmark_exposure: float
    overlapping_periods: int
    leverage_caveat: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "risk_matched_increment": self.annualised_increment,
            "candidate_annualised_return": self.candidate_annualised_return,
            "benchmark_annualised_return": self.benchmark_annualised_return,
            "benchmark_scale": self.benchmark_scale,
            "sharpe_difference": self.sharpe_difference,
            "candidate_exposure": self.candidate_exposure,
            "benchmark_exposure": self.benchmark_exposure,
            "overlapping_periods": self.overlapping_periods,
            "leverage_caveat": self.leverage_caveat,
        }


def risk_matched_increment(
    candidate: RunEvidence,
    *,
    benchmark: RunEvidence,
) -> RiskMatchedIncrement:
    """Compare candidate and benchmark at matched volatility over the identical window.

    Refuses a benchmark run on a different window (spec §3 C6: *the naive benchmark runs
    under the identical cost model, data and window*). The cost model and the data are the
    caller's to keep identical — this can see the window, and it checks the one it can.

    Note what the matching does *not* buy: scaling a return series to a common volatility
    makes the mean comparison rank-identical to a Sharpe comparison, so
    ``annualised_increment`` and ``sharpe_difference`` always agree in sign. The increment
    is reported because a number in return units is what an operator can size against; it
    is not independent evidence.
    """
    if candidate.window != benchmark.window:
        raise BenchmarkMismatchError(
            f"the benchmark ran over {benchmark.window} and the candidate over "
            f"{candidate.window}. A benchmark on a different window is not a benchmark, "
            "it is a second result."
        )
    left = candidate.returns
    right = benchmark.returns
    if left.periods_per_year != right.periods_per_year:
        # Both annualised returns below use the candidate's periodicity. If the two series
        # disagree about what a year is, the difference between them is partly a unit
        # conversion — which is not what "what the candidate adds" means.
        raise BenchmarkMismatchError(
            f"the candidate annualises by {left.periods_per_year} periods a year and the "
            f"benchmark by {right.periods_per_year}. The increment is a difference of two "
            "annualised returns, so it is only a comparison when both are in the same units."
        )
    days = sorted(set(left.dates) | set(right.dates))
    # A session missing from one series is a session that series was not in the market —
    # a zero return, not an absent observation. Dropping it instead would compare the
    # conditional strategy only on the days it chose to trade, which is the exact
    # selection bias this comparison exists to remove.
    left_by_day = dict(zip(left.dates, left.net, strict=True))
    right_by_day = dict(zip(right.dates, right.net, strict=True))
    candidate_net = tuple(left_by_day.get(day, 0.0) for day in days)
    benchmark_net = tuple(right_by_day.get(day, 0.0) for day in days)
    _, candidate_stdev, _, _ = _math.moments(candidate_net)
    _, benchmark_stdev, _, _ = _math.moments(benchmark_net)
    if benchmark_stdev <= 0.0 or candidate_stdev <= 0.0:
        raise BenchmarkMismatchError(
            "one of the series has zero volatility, so there is no risk to match on "
            f"(candidate {candidate_stdev:.3g}, benchmark {benchmark_stdev:.3g})"
        )
    scale = candidate_stdev / benchmark_stdev
    periods_per_year = left.periods_per_year
    candidate_annual = math.fsum(candidate_net) / len(days) * periods_per_year
    benchmark_annual = math.fsum(benchmark_net) / len(days) * periods_per_year * scale
    caveat = None
    if scale > 1.0:
        caveat = (
            f"the benchmark was levered {scale:.2f}x to reach the candidate's volatility; "
            "whether that leverage is reachable under margin is not checked here, so the "
            "increment is an upper bound on what the candidate adds in practice"
        )
    return RiskMatchedIncrement(
        annualised_increment=candidate_annual - benchmark_annual,
        candidate_annualised_return=candidate_annual,
        benchmark_annualised_return=benchmark_annual,
        benchmark_scale=scale,
        sharpe_difference=annualised_sharpe_ratio(left) - annualised_sharpe_ratio(right),
        candidate_exposure=sum(1 for value in candidate_net if value != 0.0) / len(days),
        benchmark_exposure=sum(1 for value in benchmark_net if value != 0.0) / len(days),
        overlapping_periods=len(days),
        leverage_caveat=caveat,
    )
