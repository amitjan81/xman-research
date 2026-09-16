"""Black-Scholes on the captured implied volatility, and the smile extrapolation.

**Why the strategy computes delta instead of reading it.** The corpus carries a vendor
``delta`` column, but :class:`~xman_research.backtest.market.Bar` does not expose it and
the requirement (ST-6) asks for a delta computed from the traded price and the
IV at the moment of entry, with the method recorded. So the method is here, it is the
textbook one, and :func:`delta` is what selects every short strike. The vendor column is
used once, in the tests, as an independent check that this implementation agrees with the
producer's to within a few thousandths of a delta.

**The forward.** Index options are priced off the futures, not the spot, and the corpus
carries no futures series. This module uses spot with a zero rate and no dividend, which
is the same simplification the vendor's own greeks appear to make (see the agreement test).
Its effect is a small, symmetric shift of the moneyness axis; it moves both the call and
the put strike selection in the same direction, which is the direction that matters least
for a delta-symmetric structure.

**The extrapolation** (:func:`extrapolated_wing_price`) exists because the capture holds
only about a +/-2.3% strike band, so a 350-point wing is usually outside it. Candidates
were measured against a holdout — hide the outermost three strikes of a side, fit on what
is left, predict them back — on entry-window sessions:

======================================  ==============  =====  ======
method                                  median |error|  p90    bias
======================================  ==============  =====  ======
flat edge IV, Black-Scholes             Rs 2.29         4.52   -1.04
**flat edge IV, edge-calibrated**       **Rs 1.42**     3.14   -1.48
flat edge IV, additive edge correction  Rs 2.33         5.75   -1.49
linear fit on last five strikes         Rs 2.47         4.93   -0.25
quadratic fit on the whole side         Rs 2.74         5.33   +0.41
======================================  ==============  =====  ======

against a median true price of Rs 14.35. The winner holds the outermost observed IV flat,
prices with Black-Scholes, and then multiplies by the ratio between the *printed* price of
that outermost strike and its own Black-Scholes value. The calibration matters because the
vendor's IV does not reprice its own printed close exactly — a median Rs 6 gap on a Rs 96
option, presumably a forward or a mid/last difference — and the ratio cancels whatever that
is at the nearest point where both numbers are observed.

The residual bias is **negative**: the model under-prices the wing by about Rs 1.5 per unit.
A cheaper long wing flatters entry credit and depresses exit proceeds, so the two ends
partly cancel; what does not cancel is stated in the report rather than corrected away,
because a correction fitted to the holdout would be fitted to this corpus.

Flat IV is used rather than a fitted smile for one more reason: it is the only candidate
that cannot produce a negative or exploding implied volatility when pushed past its last
observation.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise

__all__ = [
    "HOLDOUT_BIAS_RUPEES",
    "HOLDOUT_MEDIAN_ABS_ERROR_RUPEES",
    "ObservedQuote",
    "bs_delta",
    "bs_price",
    "extrapolated_wing_price",
    "flat_iv_beyond_band",
    "year_fraction",
]

#: Measured on 150 entry-window sessions, outermost three strikes per side held out, for
#: the edge-calibrated method this module actually uses. Quoted in the report so the
#: modelled-wing arm carries its own error bar rather than an implied claim of exactness.
HOLDOUT_MEDIAN_ABS_ERROR_RUPEES = 1.42
#: Signed mean error of the same measurement: the model under-prices the wing.
HOLDOUT_BIAS_RUPEES = -1.48

_SETTLEMENT_HOUR = 15.5
"""Expiry-day settlement is 15:30 IST; a position's life ends there, not at midnight."""


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def year_fraction(*, minute_hour: float, days_to_expiry: int) -> float:
    """Time to expiry in years, measured to 15:30 IST on expiry day.

    ``minute_hour`` is the decision minute as a decimal hour (09:20 -> 9.333). A session
    that is *on* expiry day therefore has a positive but shrinking value rather than zero,
    which keeps delta finite for the rules that read it up to the exit deadline.
    """
    hours = days_to_expiry * 24.0 + (_SETTLEMENT_HOUR - minute_hour)
    return max(hours / (365.0 * 24.0), 1.0 / (365.0 * 24.0 * 60.0))


def bs_price(*, option_type: str, spot: float, strike: float, t_years: float, iv: float) -> float:
    """Black-Scholes premium per unit, zero rate, zero dividend."""
    if t_years <= 0.0 or iv <= 0.0:
        return max(0.0, spot - strike) if option_type == "CE" else max(0.0, strike - spot)
    vol_t = iv * math.sqrt(t_years)
    d1 = (math.log(spot / strike) + 0.5 * iv * iv * t_years) / vol_t
    d2 = d1 - vol_t
    if option_type == "CE":
        return spot * _norm_cdf(d1) - strike * _norm_cdf(d2)
    return strike * _norm_cdf(-d2) - spot * _norm_cdf(-d1)


def bs_delta(*, option_type: str, spot: float, strike: float, t_years: float, iv: float) -> float:
    """Signed delta per unit: positive for calls, negative for puts.

    At or past expiry, or with a non-positive volatility, delta degenerates to the
    indicator of being in the money — which is what the position is worth defending at
    that point anyway.
    """
    if t_years <= 0.0 or iv <= 0.0:
        if option_type == "CE":
            return 1.0 if spot > strike else 0.0
        return -1.0 if spot < strike else 0.0
    vol_t = iv * math.sqrt(t_years)
    d1 = (math.log(spot / strike) + 0.5 * iv * iv * t_years) / vol_t
    return _norm_cdf(d1) if option_type == "CE" else _norm_cdf(d1) - 1.0


@dataclass(frozen=True, slots=True)
class ObservedQuote:
    """One strike of one side, as the session actually printed it."""

    strike: float
    iv: float
    close: float
    volume_units: float
    open_interest_units: float


def extrapolated_wing_price(
    *,
    option_type: str,
    spot: float,
    strike: float,
    t_years: float,
    observed: Sequence[ObservedQuote],
) -> tuple[float, float] | None:
    """Modelled ``(price, iv)`` for a strike the capture does not carry.

    ``observed`` are the printed quotes of the same side and expiry, at the same minute.
    The outermost one in the direction of ``strike`` supplies both the flat implied
    volatility and the calibration ratio; see the module docstring for the holdout that
    chose this over four alternatives. ``None`` when the side printed nothing usable.

    The returned price is floored at one tick-ish (Rs 0.05) rather than at zero: a listed
    option that is genuinely worthless still costs something to buy, and a zero-priced long
    wing would hand the strategy free insurance.
    """
    usable = [q for q in observed if q.iv > 0.0 and q.close > 0.0]
    if not usable:
        return None
    if option_type == "CE":
        edge = max(usable, key=lambda q: q.strike)
        if strike <= edge.strike:
            edge = min(usable, key=lambda q: abs(q.strike - strike))
    else:
        edge = min(usable, key=lambda q: q.strike)
        if strike >= edge.strike:
            edge = min(usable, key=lambda q: abs(q.strike - strike))
    edge_model = bs_price(
        option_type=option_type, spot=spot, strike=edge.strike, t_years=t_years, iv=edge.iv
    )
    ratio = edge.close / edge_model if edge_model > 0.01 else 1.0
    # A ratio far from one means the edge strike's own model price is not trustworthy
    # enough to calibrate with — clamp rather than propagate it into the wing.
    ratio = min(max(ratio, 0.5), 2.0)
    raw = bs_price(option_type=option_type, spot=spot, strike=strike, t_years=t_years, iv=edge.iv)
    return max(raw * ratio, 0.05), edge.iv


def flat_iv_beyond_band(
    *, observed: Sequence[tuple[float, float]], strike: float, spot: float
) -> float | None:
    """Implied volatility for ``strike``, from the observed ``(strike, iv)`` pairs.

    Inside the observed range the two neighbouring strikes are interpolated linearly in
    log-moneyness. Outside it the nearest observed IV is held flat — see the module
    docstring for the holdout that chose flat over fitting. ``None`` when there is nothing
    to extrapolate from.
    """
    points = sorted((float(k), float(v)) for k, v in observed if v is not None and v > 0.0)
    if not points:
        return None
    if strike <= points[0][0]:
        return points[0][1]
    if strike >= points[-1][0]:
        return points[-1][1]
    for (k_lo, iv_lo), (k_hi, iv_hi) in pairwise(points):
        if k_lo <= strike <= k_hi:
            x_lo, x_hi = math.log(k_lo / spot), math.log(k_hi / spot)
            x = math.log(strike / spot)
            if x_hi == x_lo:
                return iv_lo
            weight = (x - x_lo) / (x_hi - x_lo)
            return iv_lo + weight * (iv_hi - iv_lo)
    return points[-1][1]
