"""Each statistic against a value that was computed somewhere other than this package.

Three kinds of reference are used, and the distinction matters when reading a failure:

* **published constants** — the normal quantiles, which are tabulated to 15 digits;
* **closed forms written out with literals** in the test itself, evaluated through
  ``math.erf`` rather than through the code under test;
* **seeded Monte Carlo**, for the one expression that has no closed form (the expected
  maximum of N Sharpe ratios).

What is *not* used anywhere here: the code under test as its own reference. A wrong
deflated Sharpe is worse than no deflated Sharpe, because it launders overfitting as
rigour, so nothing below asserts that the implementation agrees with itself.

**No published worked example of the DSR was available offline**, so the DSR is checked
by composition — its two halves against their own references, plus the invariants that
pin the composition (PSR at the benchmark is exactly 0.5, one trial deflates by nothing,
more trials deflate more). That is weaker than a end-to-end reference value and it is
stated rather than papered over.
"""

from __future__ import annotations

import datetime as dt
import math

import numpy as np
import pytest

from xman_research import DataWindow, HypothesisRecord, ResearchSession
from xman_research.validation import _math
from xman_research.validation.series import FeasibilityFacts, ReturnSeries, RunEvidence, SeriesError
from xman_research.validation.statistics import (
    BenchmarkMismatchError,
    SelectionUniverse,
    UnverifiedInputsError,
    adjusted_sharpe_ratio,
    annualised_sharpe_ratio,
    cost_breakeven,
    deflated_sharpe_ratio,
    drawdown,
    expected_shortfall,
    per_period_sharpe_ratio,
    risk_matched_increment,
    tail_metrics,
)

RUN_AT = dt.datetime(2026, 8, 5, 12, 0, tzinfo=dt.UTC)


def series(
    values: list[float], *, drag: float = 0.0, start: dt.date = dt.date(2025, 1, 6)
) -> ReturnSeries:
    days = [start + dt.timedelta(days=index) for index in range(len(values))]
    return ReturnSeries(
        dates=tuple(days),
        net=tuple(values),
        drag=tuple(drag for _ in values),
        label="fixture",
    )


# --------------------------------------------------------------------- the normal law


@pytest.mark.parametrize(
    "probability,quantile",
    [
        (0.90, 1.2815515655446004),
        (0.95, 1.6448536269514722),
        (0.975, 1.959963984540054),
        (0.99, 2.3263478740408408),
        (0.999, 3.090232306167813),
        (0.5, 0.0),
    ],
)
def test_normal_ppf_matches_published_quantiles(probability: float, quantile: float) -> None:
    """Standard normal quantiles, as tabulated. The Halley step is what buys the digits."""
    assert _math.normal_ppf(probability) == pytest.approx(quantile, abs=1e-12)


def test_normal_cdf_and_ppf_are_inverse() -> None:
    for probability in (0.001, 0.02, 0.3, 0.5, 0.84, 0.9999):
        assert _math.normal_cdf(_math.normal_ppf(probability)) == pytest.approx(
            probability, abs=1e-12
        )


def test_normal_ppf_refuses_degenerate_probabilities() -> None:
    for probability in (0.0, 1.0, -0.1, 1.5):
        with pytest.raises(ValueError, match="0 < p < 1"):
            _math.normal_ppf(probability)


# ------------------------------------------------------------------------- moments


def test_moments_against_hand_computed_values() -> None:
    """A four-point series whose moments are arithmetic anyone can redo on paper.

    values 1, 2, 3, 6: mean 3, deviations -2 -1 0 3, m2 = 14/4 = 3.5,
    sample stdev = sqrt(14/3), m3 = (-8 -1 + 0 + 27)/4 = 4.5, m4 = (16 + 1 + 0 + 81)/4 = 24.5.
    """
    mean, stdev, skew, kurtosis = _math.moments((1.0, 2.0, 3.0, 6.0))
    assert mean == pytest.approx(3.0)
    assert stdev == pytest.approx(math.sqrt(14.0 / 3.0))
    assert skew == pytest.approx(4.5 / 3.5**1.5)
    assert kurtosis == pytest.approx(24.5 / 3.5**2)


def test_sharpe_is_mean_over_sample_stdev() -> None:
    values = (0.01, -0.005, 0.02, 0.0, 0.015)
    mean = sum(values) / 5
    stdev = math.sqrt(sum((value - mean) ** 2 for value in values) / 4)
    assert per_period_sharpe_ratio(series(list(values))) == pytest.approx(mean / stdev)


def test_annualisation_is_the_square_root_rule() -> None:
    data = series([0.01, -0.005, 0.02, 0.0, 0.015])
    assert annualised_sharpe_ratio(data) == pytest.approx(
        per_period_sharpe_ratio(data) * math.sqrt(252.0)
    )


# ----------------------------------------------------------- probabilistic Sharpe ratio


def test_psr_is_exactly_one_half_at_the_benchmark() -> None:
    """PSR(SR*) = Phi(0) = 0.5 when the observed Sharpe equals the benchmark, always."""
    for skew, kurtosis in ((0.0, 3.0), (-1.5, 9.0), (0.7, 4.2)):
        assert _math.probabilistic_sharpe(
            observed=0.12, benchmark=0.12, sample_length=500, skew=skew, kurtosis=kurtosis
        ) == pytest.approx(0.5, abs=1e-15)


def test_psr_reduces_to_the_normal_closed_form_for_normal_returns() -> None:
    """With skew 0 and kurtosis 3 the variance term is exactly ``1 + SR^2/2``.

    Written out here with literals and evaluated through ``math.erf``, not through the
    module under test. Note what it is *not*: the denominator does not vanish for normal
    returns — that would need a kurtosis of 1, which no distribution has.
    """
    observed, sample_length = 0.08, 400
    argument = (observed * math.sqrt(399)) / math.sqrt(1.0 + 0.5 * observed**2)
    expected = 0.5 * (1.0 + math.erf(argument / math.sqrt(2.0)))
    assert _math.probabilistic_sharpe(
        observed=observed, benchmark=0.0, sample_length=sample_length, skew=0.0, kurtosis=3.0
    ) == pytest.approx(expected, abs=1e-14)


def test_psr_falls_when_returns_are_negatively_skewed() -> None:
    """The property that makes PSR worth having for a short-option payoff."""
    symmetric = _math.probabilistic_sharpe(
        observed=0.1, benchmark=0.0, sample_length=500, skew=0.0, kurtosis=3.0
    )
    skewed = _math.probabilistic_sharpe(
        observed=0.1, benchmark=0.0, sample_length=500, skew=-1.5, kurtosis=8.0
    )
    assert skewed < symmetric


def test_psr_refuses_a_non_positive_variance_term() -> None:
    with pytest.raises(ValueError, match="non-positive"):
        _math.probabilistic_sharpe(
            observed=3.0, benchmark=0.0, sample_length=100, skew=2.0, kurtosis=1.0
        )


# ------------------------------------------------------- the expected maximum Sharpe


def test_one_trial_deflates_by_nothing() -> None:
    assert _math.expected_max_sharpe(sharpe_variance=0.25, trials=1) == 0.0


def test_expected_max_sharpe_matches_monte_carlo_at_large_n() -> None:
    """The Gumbel expression against the sampled maximum of N standard draws.

    The approximation is asymptotic in N, so this is checked where it is meant to hold —
    N = 1000, tolerance 2% — not at N = 10, where it is visibly biased and the
    discrepancy would be the formula's rather than the implementation's.
    """
    rng = np.random.default_rng(20260812)
    variance = 0.04
    trials = 1000
    sampled = float(
        np.mean([np.max(rng.normal(0.0, math.sqrt(variance), size=trials)) for _ in range(400)])
    )
    predicted = _math.expected_max_sharpe(sharpe_variance=variance, trials=trials)
    assert predicted == pytest.approx(sampled, rel=0.02)


def test_expected_max_sharpe_grows_with_the_size_of_the_search() -> None:
    values = [
        _math.expected_max_sharpe(sharpe_variance=0.01, trials=trials)
        for trials in (2, 10, 100, 1000)
    ]
    assert values == sorted(values)


# ----------------------------------------------------------------- adjusted Sharpe


def test_adjusted_sharpe_matches_the_pezier_white_expression() -> None:
    observed, skew, kurtosis = 0.15, -1.2, 7.0
    expected = observed * (1.0 + (skew / 6.0) * observed - ((kurtosis - 3.0) / 24.0) * observed**2)
    assert _math.adjusted_sharpe(observed=observed, skew=skew, kurtosis=kurtosis) == pytest.approx(
        expected
    )


def test_adjusted_sharpe_penalises_the_short_option_shape() -> None:
    """A negatively skewed, fat-tailed series is marked down relative to its Sharpe."""
    values = [0.004] * 40 + [-0.05]
    data = series(values)
    assert adjusted_sharpe_ratio(data) < per_period_sharpe_ratio(data)


# ------------------------------------------------------------------- tail metrics


def test_max_drawdown_on_a_hand_traced_path() -> None:
    """Path 1 -> 1.10 -> 0.99 -> 1.04: peak 1.10, trough 0.99, drawdown 0.11/1.10 = 10%."""
    facts = drawdown(series([0.10, -0.11, 0.05]))
    assert facts.max_drawdown == pytest.approx(0.1)
    assert facts.trough_date == dt.date(2025, 1, 7)
    assert facts.sessions_under_water == 2
    assert not facts.ruined


def test_a_wiped_out_book_is_reported_as_ruin() -> None:
    facts = drawdown(series([0.1, -1.5, 0.4]))
    assert facts.ruined and facts.max_drawdown == 1.0


def test_expected_shortfall_averages_the_worst_tail() -> None:
    """20 observations, 5% tail -> exactly one observation: the worst one."""
    values = [0.01] * 19 + [-0.30]
    assert expected_shortfall(series(values)) == pytest.approx(-0.30)
    # A 25% tail takes the worst five, four of which are +0.01.
    assert expected_shortfall(series(values), tail=0.25) == pytest.approx((-0.30 + 0.04) / 5)


def test_tail_metrics_report_the_whole_block() -> None:
    metrics = tail_metrics(series([0.004] * 40 + [-0.05]))
    assert metrics.skew < 0 and metrics.kurtosis > 3
    assert metrics.max_drawdown > 0
    assert metrics.calmar is not None
    assert metrics.annualised_adjusted_sharpe < metrics.annualised_sharpe


# ------------------------------------------------------------------ cost breakeven


def test_cost_breakeven_is_gross_edge_over_cost_drag() -> None:
    """Mean gross 0.0012, mean drag 0.0003 -> costs can quadruple before the edge is gone."""
    data = ReturnSeries(
        dates=tuple(dt.date(2025, 1, 6) + dt.timedelta(days=i) for i in range(4)),
        net=(0.0009, 0.0009, 0.0009, 0.0009),
        drag=(0.0003, 0.0003, 0.0003, 0.0003),
        label="fixture",
    )
    run = RunEvidence(label="candidate", returns=data, run_at=RUN_AT)
    breakeven = cost_breakeven(run)
    assert breakeven.multiple == pytest.approx(4.0)
    assert breakeven.cost_share == pytest.approx(0.25)
    assert float(breakeven) == pytest.approx(4.0)


def test_a_run_that_loses_before_costs_breaks_even_at_zero() -> None:
    data = ReturnSeries(
        dates=tuple(dt.date(2025, 1, 6) + dt.timedelta(days=i) for i in range(4)),
        net=(-0.002, -0.001, -0.003, -0.001),
        drag=(0.0003,) * 4,
        label="loser",
    )
    assert cost_breakeven(RunEvidence(label="loser", returns=data, run_at=RUN_AT)).multiple == 0.0


def test_a_run_with_no_costs_is_unbounded_not_excellent() -> None:
    run = RunEvidence(label="costless", returns=series([0.001, 0.002, 0.0015]), run_at=RUN_AT)
    assert cost_breakeven(run).unbounded


def test_the_headline_refuses_to_be_a_bare_number_while_inputs_are_unverified() -> None:
    """Honesty requirement: a verdict computed from unverified rates must say so."""
    data = ReturnSeries(
        dates=tuple(dt.date(2025, 1, 6) + dt.timedelta(days=i) for i in range(4)),
        net=(0.0009,) * 4,
        drag=(0.0003,) * 4,
        label="fixture",
    )
    run = RunEvidence(
        label="candidate",
        returns=data,
        unverified_inputs=("costs.brokerage_rate_card", "margin.simplified_approximation"),
        run_at=RUN_AT,
    )
    breakeven = cost_breakeven(run)
    assert "unverified" in str(breakeven)
    assert "costs.brokerage_rate_card" in str(breakeven)
    with pytest.raises(UnverifiedInputsError, match="unverified"):
        float(breakeven)
    # The value is still reachable — deliberately, and only by naming it.
    assert breakeven.multiple == pytest.approx(4.0)


def test_scaling_costs_moves_the_series_the_way_the_breakeven_says() -> None:
    data = ReturnSeries(
        dates=tuple(dt.date(2025, 1, 6) + dt.timedelta(days=i) for i in range(4)),
        net=(0.0009,) * 4,
        drag=(0.0003,) * 4,
        label="fixture",
    )
    at_breakeven = data.at_cost_multiple(4.0)
    assert math.fsum(at_breakeven.net) == pytest.approx(0.0, abs=1e-15)


# ------------------------------------------------------- risk-matched increment


def test_a_conditional_strategy_trails_on_raw_pnl_and_leads_when_risk_matched() -> None:
    """The failure mode the criterion exists to prevent, in its simplest form.

    The candidate is in the market on four of eight sessions and earns 0.002 on each of
    them: total 0.008, and a standard deviation of about 0.00107. The benchmark is in
    every session, alternating +0.005 and -0.002: total 0.012 — a bigger number — for a
    standard deviation of about 0.00374, three and a half times the risk.

    Raw P&L says the benchmark wins by half. Scaled to the candidate's volatility, the
    benchmark returns about 0.00043 a session against the candidate's 0.001, so the
    candidate leads by more than two to one on the comparison that is actually about
    timing rather than about exposure.
    """
    days = tuple(dt.date(2025, 1, 6) + dt.timedelta(days=index) for index in range(8))
    candidate_net = (0.002, 0.0, 0.002, 0.0, 0.002, 0.0, 0.002, 0.0)
    benchmark_net = (0.005, -0.002) * 4
    candidate = RunEvidence(
        label="conditional",
        returns=ReturnSeries(dates=days, net=candidate_net, drag=(0.0,) * 8, label="conditional"),
        run_at=RUN_AT,
    )
    benchmark = RunEvidence(
        label="always-on",
        returns=ReturnSeries(dates=days, net=benchmark_net, drag=(0.0,) * 8, label="always-on"),
        run_at=RUN_AT,
    )
    assert sum(benchmark_net) > sum(candidate_net)  # raw P&L says the benchmark wins
    increment = risk_matched_increment(candidate, benchmark=benchmark)
    assert increment.annualised_increment > 0
    assert increment.sharpe_difference > 0
    assert increment.benchmark_scale < 0.35
    assert increment.candidate_exposure == pytest.approx(0.5)
    assert increment.benchmark_exposure == pytest.approx(1.0)


def test_the_increment_reports_the_leverage_the_match_required() -> None:
    days = tuple(dt.date(2025, 1, 6) + dt.timedelta(days=index) for index in range(6))
    candidate = RunEvidence(
        label="volatile",
        returns=ReturnSeries(
            dates=days, net=(0.02, -0.01, 0.03, -0.02, 0.01, 0.0), drag=(0.0,) * 6, label="v"
        ),
        run_at=RUN_AT,
    )
    benchmark = RunEvidence(
        label="quiet",
        returns=ReturnSeries(
            dates=days, net=(0.002, -0.001, 0.003, -0.002, 0.001, 0.0), drag=(0.0,) * 6, label="q"
        ),
        run_at=RUN_AT,
    )
    increment = risk_matched_increment(candidate, benchmark=benchmark)
    assert increment.benchmark_scale == pytest.approx(10.0, rel=1e-9)
    assert increment.leverage_caveat is not None and "levered" in increment.leverage_caveat


def test_a_benchmark_on_another_window_is_refused() -> None:
    candidate = RunEvidence(label="c", returns=series([0.001, 0.002, 0.003]), run_at=RUN_AT)
    benchmark = RunEvidence(
        label="b",
        returns=series([0.001, 0.002, 0.003], start=dt.date(2024, 1, 8)),
        run_at=RUN_AT,
    )
    with pytest.raises(BenchmarkMismatchError, match="different window"):
        risk_matched_increment(candidate, benchmark=benchmark)


# ------------------------------------------------- deflated Sharpe, criterion 2


def hypothesis(name: str = "H1 — index variance risk premium") -> HypothesisRecord:
    return HypothesisRecord(
        name=name,
        mechanism="Hedgers pay up for index protection, so implied sits above realised.",
        null_hypothesis="Implied minus realised has no positive mean after costs.",
        thresholds={"deflated_sharpe": 0.95},
        predictors=["iv_30d"],
    )


def log_trials(session: ResearchSession, record: HypothesisRecord, *, how_many: int) -> None:
    window = DataWindow(dt.date(2025, 1, 1), dt.date(2025, 6, 30))
    for index in range(how_many):
        with session.trial(record, data_window=window, params={"variant": index}) as trial:
            trial.record_metrics(sharpe_per_period=0.02 * (index % 5))


def test_the_selection_universe_reads_the_count_from_the_log(
    session: ResearchSession,
) -> None:
    """Criterion 2: the deflation's N comes from the log, and there is no other way in."""
    record = hypothesis()
    session.register(record)
    log_trials(session, record, how_many=7)
    universe = SelectionUniverse(session, record)
    assert universe.size == 7 == session.count_family_trials(record)
    assert universe.hypothesis_id == record.id


def test_more_logged_trials_deflate_further(session: ResearchSession) -> None:
    """The whole point of the deflation: a wider search makes the same Sharpe worth less."""
    record = hypothesis()
    session.register(record)
    log_trials(session, record, how_many=3)
    data = series([0.01, 0.012, -0.004, 0.02, 0.008, 0.011, -0.002, 0.015] * 12)
    modest = deflated_sharpe_ratio(data, universe=SelectionUniverse(session, record))
    log_trials(session, record, how_many=200)
    wide = deflated_sharpe_ratio(data, universe=SelectionUniverse(session, record))
    assert wide.selection_size == 203
    assert wide.expected_max_sharpe > modest.expected_max_sharpe
    assert wide.value < modest.value


def test_the_deflation_composes_its_two_halves(session: ResearchSession) -> None:
    """DSR = PSR measured against SR*, and both halves are checked separately above."""
    record = hypothesis()
    session.register(record)
    log_trials(session, record, how_many=9)
    data = series([0.01, 0.012, -0.004, 0.02, 0.008, 0.011, -0.002, 0.015] * 12)
    result = deflated_sharpe_ratio(data, universe=SelectionUniverse(session, record))
    _, _, skew, kurtosis = _math.moments(data.net)
    expected_benchmark = _math.expected_max_sharpe(sharpe_variance=result.sharpe_variance, trials=9)
    assert result.expected_max_sharpe == pytest.approx(expected_benchmark)
    assert result.value == pytest.approx(
        _math.probabilistic_sharpe(
            observed=per_period_sharpe_ratio(data),
            benchmark=expected_benchmark,
            sample_length=len(data),
            skew=skew,
            kurtosis=kurtosis,
        )
    )


def test_the_sharpe_variance_is_read_from_logged_trials_when_they_carry_one(
    session: ResearchSession,
) -> None:
    record = hypothesis()
    session.register(record)
    log_trials(session, record, how_many=10)
    universe = SelectionUniverse(session, record)
    assert universe.variance_basis == "observed"
    assert universe.sharpe_variance is not None and universe.sharpe_variance > 0


def test_an_annualised_trial_sharpe_without_a_periodicity_is_refused_not_guessed(
    session: ResearchSession,
) -> None:
    """A Sharpe of unknown periodicity is 15.9x wrong if assumed per-period, and the
    error inflates the trial-Sharpe variance, which *flatters* every later verdict."""
    record = hypothesis()
    session.register(record)
    window = DataWindow(dt.date(2025, 1, 1), dt.date(2025, 6, 30))
    for index in range(6):
        with session.trial(record, data_window=window) as trial:
            trial.record_metrics(sharpe=1.2 + index * 0.1)
    universe = SelectionUniverse(session, record)
    assert universe.sharpe_variance is None
    assert universe.variance_basis == "dsr.trial_sharpes_lack_declared_periodicity"
    data = series([0.01, 0.012, -0.004, 0.02, 0.008, 0.011, -0.002, 0.015] * 12)
    result = deflated_sharpe_ratio(data, universe=universe)
    assert result.unverified_inputs == ("dsr.trial_sharpes_lack_declared_periodicity",)


def test_a_declared_periodicity_is_converted_rather_than_dropped(
    session: ResearchSession,
) -> None:
    record = hypothesis()
    session.register(record)
    window = DataWindow(dt.date(2025, 1, 1), dt.date(2025, 6, 30))
    annualised = [1.0, 1.6, 2.2, 0.4]
    for value in annualised:
        with session.trial(record, data_window=window) as trial:
            trial.record_metrics(sharpe=value, sharpe_periods_per_year=252)
    universe = SelectionUniverse(session, record)
    per_period = [value / math.sqrt(252) for value in annualised]
    _, stdev, _, _ = _math.moments(tuple(per_period))
    assert universe.sharpe_variance == pytest.approx(stdev**2)


# ----------------------------------------------------------------- the series itself


def test_a_series_refuses_to_hide_a_gap_or_a_reordering() -> None:
    days = (dt.date(2025, 1, 6), dt.date(2025, 1, 6))
    with pytest.raises(SeriesError, match="strictly increasing"):
        ReturnSeries(dates=days, net=(0.1, 0.2), drag=(0.0, 0.0))


def test_a_negative_cost_drag_is_refused() -> None:
    days = (dt.date(2025, 1, 6), dt.date(2025, 1, 7))
    with pytest.raises(SeriesError, match="negative cost drag"):
        ReturnSeries(dates=days, net=(0.1, 0.2), drag=(0.0, -0.1))


def test_the_equity_curve_adapter_needs_a_cost_input() -> None:
    points = [(dt.date(2025, 1, 6) + dt.timedelta(days=i), 1_000_000.0 + i * 100) for i in range(5)]
    with pytest.raises(SeriesError, match="exactly one of cost_by_date"):
        RunEvidence.from_equity_curve(points, label="c", capital_base=1_000_000.0)


def test_the_equity_curve_adapter_stamps_uniformly_allocated_costs() -> None:
    points = [(dt.date(2025, 1, 6) + dt.timedelta(days=i), 1_000_000.0 + i * 100) for i in range(5)]
    run = RunEvidence.from_equity_curve(
        points,
        label="c",
        capital_base=1_000_000.0,
        total_cost=400.0,
        feasibility=FeasibilityFacts(intents_attempted=8, sessions_run=5),
    )
    assert "costs.uniformly_allocated" in run.unverified_inputs
    assert run.returns.net == pytest.approx((0.0001, 0.0001, 0.0001, 0.0001))
    assert run.returns.drag == pytest.approx((0.0001, 0.0001, 0.0001, 0.0001))
    # And therefore a breakeven of exactly 2.0: gross 0.0002 against drag 0.0001.
    assert cost_breakeven(run).multiple == pytest.approx(2.0)
