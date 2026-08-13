"""The statistics, as formulae, with nothing that knows what a hypothesis is.

**This module is private on purpose, and the reason is a guard, not taste.**
:func:`expected_max_sharpe` genuinely needs the number of trials as an argument — the
deflation *is* a function of it. Every public callable in this package is forbidden from
accepting such an argument (``tests/test_no_caller_supplied_count.py`` walks the package
and fails on the parameter name), because the researcher must never be the source of that
number. Both facts are true at once only if the parameterised form is unreachable from the
public surface: the number reaches it from
:meth:`xman_research.trial_log.TrialLog.count_family_trials` and from nowhere else.

Import discipline that keeps that true: a public module must not re-export these names
under a public alias. ``from xman_research.validation import _math`` and call
``_math.expected_max_sharpe(...)``; the guard enumerates members of public modules and
would happily flag a re-exported ``expected_max_sharpe(..., trials=...)``.

References
----------
Bailey, D. H. and López de Prado, M. (2014). "The Deflated Sharpe Ratio: Correcting for
Selection Bias, Backtest Overfitting and Non-Normality." *Journal of Portfolio
Management*, 40(5), 94-107.

Bailey, D. H. and López de Prado, M. (2012). "The Sharpe Ratio Efficient Frontier."
*Journal of Risk*, 15(2), 3-44. (The probabilistic Sharpe ratio.)

Pézier, J. and White, A. (2006). "The Relative Merits of Investable Hedge Fund Indices
and of Funds of Hedge Funds in Optimal Passive Portfolios." ICMA Centre Discussion Paper
DP2006-10. (The skew/kurtosis-adjusted Sharpe ratio.)

Acklam, P. J. (2003). "An algorithm for computing the inverse normal cumulative
distribution function." (The rational approximation refined below to full double
precision by one Halley step against ``math.erfc``.)
"""

from __future__ import annotations

import math

# Euler-Mascheroni constant, as it appears in the expected-maximum expression.
EULER_MASCHERONI = 0.5772156649015329

_ACKLAM_A = (
    -3.969683028665376e01,
    2.209460984245205e02,
    -2.759285104469687e02,
    1.383577518672690e02,
    -3.066479806614716e01,
    2.506628277459239e00,
)
_ACKLAM_B = (
    -5.447609879822406e01,
    1.615858368580409e02,
    -1.556989798598866e02,
    6.680131188771972e01,
    -1.328068155288572e01,
)
_ACKLAM_C = (
    -7.784894002430293e-03,
    -3.223964580411365e-01,
    -2.400758277161838e00,
    -2.549732539343734e00,
    4.374664141464968e00,
    2.938163982698783e00,
)
_ACKLAM_D = (
    7.784695709041462e-03,
    3.224671290700398e-01,
    2.445134137142996e00,
    3.754408661907416e00,
)
_P_LOW = 0.02425


def normal_cdf(x: float) -> float:
    """Standard normal CDF. Exact to machine precision via ``math.erfc``."""
    return 0.5 * math.erfc(-x / math.sqrt(2.0))


def normal_ppf(p: float) -> float:
    """Standard normal quantile function.

    Refused at ``p <= 0`` or ``p >= 1`` rather than returning an infinity: every caller
    here divides by, multiplies or compares the result, and a silent ``inf`` turns a
    degenerate input into a plausible-looking statistic.
    """
    if not 0.0 < p < 1.0:
        raise ValueError(f"normal_ppf needs 0 < p < 1, got {p!r}")
    if p < _P_LOW:
        q = math.sqrt(-2.0 * math.log(p))
        x = _tail_branch(q)
    elif p > 1.0 - _P_LOW:
        q = math.sqrt(-2.0 * math.log(1.0 - p))
        x = -_tail_branch(q)
    else:
        q = p - 0.5
        r = q * q
        num = (
            (
                (((_ACKLAM_A[0] * r + _ACKLAM_A[1]) * r + _ACKLAM_A[2]) * r + _ACKLAM_A[3]) * r
                + _ACKLAM_A[4]
            )
            * r
            + _ACKLAM_A[5]
        ) * q
        den = (
            (((_ACKLAM_B[0] * r + _ACKLAM_B[1]) * r + _ACKLAM_B[2]) * r + _ACKLAM_B[3]) * r
            + _ACKLAM_B[4]
        ) * r + 1.0
        x = num / den
    # One Halley refinement against the exact CDF: the raw approximation is good to
    # ~1.15e-9, which is not good enough to be checked against published quantiles.
    err = normal_cdf(x) - p
    u = err * math.sqrt(2.0 * math.pi) * math.exp(x * x / 2.0)
    return x - u / (1.0 + x * u / 2.0)


def _tail_branch(q: float) -> float:
    num = (
        (((_ACKLAM_C[0] * q + _ACKLAM_C[1]) * q + _ACKLAM_C[2]) * q + _ACKLAM_C[3]) * q
        + _ACKLAM_C[4]
    ) * q + _ACKLAM_C[5]
    den = (((_ACKLAM_D[0] * q + _ACKLAM_D[1]) * q + _ACKLAM_D[2]) * q + _ACKLAM_D[3]) * q + 1.0
    return num / den


def moments(values: tuple[float, ...]) -> tuple[float, float, float, float]:
    """``(mean, stdev, skew, kurtosis)``, with kurtosis **non-excess** (normal = 3).

    The stdev is the sample estimate (``ddof=1``) because it is the denominator of a
    Sharpe ratio; the third and fourth moments are the plug-in estimates
    ``m3 / m2**1.5`` and ``m4 / m2**2``, which is the form Bailey and López de Prado's
    :math:`\\hat\\gamma_3` and :math:`\\hat\\gamma_4` take.
    """
    length = len(values)
    if length < 2:
        raise ValueError(f"moments needs at least 2 observations, got {length}")
    mean = math.fsum(values) / length
    deviations = [value - mean for value in values]
    m2 = math.fsum(d * d for d in deviations) / length
    stdev = math.sqrt(math.fsum(d * d for d in deviations) / (length - 1))
    if m2 <= 0.0:
        return mean, 0.0, 0.0, 3.0
    m3 = math.fsum(d**3 for d in deviations) / length
    m4 = math.fsum(d**4 for d in deviations) / length
    return mean, stdev, m3 / m2**1.5, m4 / (m2 * m2)


def sharpe(values: tuple[float, ...]) -> float:
    """Per-period Sharpe ratio, zero risk-free rate. Not annualised — see the module note.

    Everything downstream (PSR, the expected maximum, DSR) is stated in per-period units.
    Mixing an annualised Sharpe into any of them inflates it by ``sqrt(periods_per_year)``
    and the result still looks like a probability, which is why nothing here annualises
    silently.
    """
    mean, stdev, _, _ = moments(values)
    if stdev <= 0.0:
        raise ValueError("Sharpe ratio is undefined for a series with zero dispersion")
    return mean / stdev


def probabilistic_sharpe(
    *,
    observed: float,
    benchmark: float,
    sample_length: int,
    skew: float,
    kurtosis: float,
) -> float:
    """PSR: the probability that the true Sharpe exceeds ``benchmark``.

    .. math::

        \\widehat{PSR}(SR^*) = \\Phi\\left[
            \\frac{(\\hat{SR} - SR^*)\\sqrt{T-1}}
                 {\\sqrt{1 - \\hat\\gamma_3 \\hat{SR} + \\frac{\\hat\\gamma_4 - 1}{4}\\hat{SR}^2}}
        \\right]

    Bailey and López de Prado (2012), eq. 4. ``kurtosis`` is non-excess. Both Sharpes are
    per-period. Negative skew *raises* the denominator and so lowers the PSR, which is the
    behaviour that matters for a short-option payoff: the ratio is the same, the
    confidence in it is lower.
    """
    if sample_length < 2:
        raise ValueError(f"PSR needs at least 2 observations, got {sample_length}")
    variance = 1.0 - skew * observed + (kurtosis - 1.0) / 4.0 * observed * observed
    if variance <= 0.0:
        # Reachable with strong positive skew and a large Sharpe. The estimator has no
        # meaning there, and a nan would propagate into a verdict as a silent pass.
        raise ValueError(
            "the PSR estimator's variance term is non-positive "
            f"(skew={skew:.4f}, kurtosis={kurtosis:.4f}, sharpe={observed:.4f}); "
            "the normal approximation does not hold for this return distribution"
        )
    return normal_cdf((observed - benchmark) * math.sqrt(sample_length - 1) / math.sqrt(variance))


def expected_max_sharpe(*, sharpe_variance: float, trials: int) -> float:
    """:math:`E[\\max_n \\hat{SR}_n]` under the null that every trial has zero true Sharpe.

    .. math::

        SR^* = \\sqrt{V[\\hat{SR}_n]}\\left[
            (1-\\gamma)Z^{-1}\\!\\left(1 - \\frac{1}{N}\\right)
            + \\gamma Z^{-1}\\!\\left(1 - \\frac{1}{Ne}\\right)\\right]

    Bailey and López de Prado (2014), eq. 5 — the Gumbel-limit approximation to the
    expected maximum of ``N`` independent draws, with :math:`\\gamma` the
    Euler-Mascheroni constant. It is asymptotic in ``N``: at ``N`` in the tens it is
    visibly biased, at ``N`` in the hundreds it is close.

    ``trials = 1`` is the no-selection case and returns exactly 0: with one trial there is
    no maximum to have been selected, and the expression itself is undefined there
    (``Z^{-1}(0) = -inf``).

    **This is the parameter the rest of the package may not have.** See the module
    docstring.
    """
    if trials < 1:
        raise ValueError(f"expected_max_sharpe needs at least 1 trial, got {trials}")
    if sharpe_variance < 0.0:
        raise ValueError(f"sharpe_variance must be non-negative, got {sharpe_variance}")
    if trials == 1:
        return 0.0
    scale = math.sqrt(sharpe_variance)
    first = normal_ppf(1.0 - 1.0 / trials)
    second = normal_ppf(1.0 - 1.0 / (trials * math.e))
    return scale * ((1.0 - EULER_MASCHERONI) * first + EULER_MASCHERONI * second)


def adjusted_sharpe(*, observed: float, skew: float, kurtosis: float) -> float:
    """Pézier-White adjusted Sharpe: a Sharpe penalised for negative skew and fat tails.

    .. math::

        ASR = \\hat{SR}\\left[1 + \\frac{\\hat\\gamma_3}{6}\\hat{SR}
              - \\frac{\\hat\\gamma_4 - 3}{24}\\hat{SR}^2\\right]

    ``kurtosis`` is non-excess, so the bracket subtracts *excess* kurtosis. This exists
    because a short-option return series is negatively skewed and fat-tailed by
    construction — collect a little, often; pay a lot, rarely — and a plain Sharpe reads
    that shape as low volatility. The adjustment is a third-order expansion of expected
    utility, not a law: it is reported alongside the Sharpe, never instead of the
    drawdown and shortfall numbers.
    """
    return observed * (
        1.0 + (skew / 6.0) * observed - ((kurtosis - 3.0) / 24.0) * observed * observed
    )
