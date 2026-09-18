"""What the Tail Hedge (ST-24..ST-27) would have cost, as arithmetic rather than a backtest.

The corpus cannot price this position: it carries the nearest weekly expiry only, in a band
about +/-2.3% wide, and the hedge is a **monthly** put **9% out of the money**. Neither the
expiry nor the strike exists in any captured session, and the implied volatility that far
down the skew is not observable here either.

So the hedge is sized, not measured. What follows is Black-Scholes on a stated volatility,
run over the actual spot path of the corpus, with the roll cadence the requirements specify
(ST-25: at 15 days to expiry, buy the next monthly, then sell the current). The output is a
drag range across volatility assumptions, and the assumption is the answer's dominant term —
which is the point of separating it from the overlay's measured return rather than netting
the two into one confident-looking number.

    uv run python research/overlay/hedge_drag.py --out research/overlay/results/hedge_drag.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
from pathlib import Path

from xman_research.overlay.context import load_context
from xman_research.overlay.greeks import bs_price
from xman_research.session_store import DEFAULT_CORPUS_ROOT

#: ST-24/ST-25 defaults.
HEDGE_OTM = 0.09
HEDGE_COVERAGE = 0.55
BUY_DTE = 45
ROLL_DTE = 15

#: The lot size the corpus's refdata declares for NIFTY across the captured window.
LOT_SIZE = 65

#: The volatility of a 9%-out-of-the-money monthly NIFTY put is not in this corpus. The
#: range spans a plausible skew: at-the-money monthly implied sits near 13-14% over the
#: captured period, and a 9% downside strike trades at a premium to it.
IV_ASSUMPTIONS = (0.16, 0.20, 0.25)


def drag(*, corpus_root: Path, underlying: str, portfolio_capital: float) -> dict[str, object]:
    context = load_context(corpus_root=corpus_root, underlying=underlying)
    frame = context.frame.dropna(subset=["close"])
    if frame.empty:
        return {"error": "no sessions"}

    rows = list(frame.itertuples())
    first, last = rows[0].session_date, rows[-1].session_date
    years = (last - first).days / 365.25

    results: dict[str, object] = {
        "underlying": underlying,
        "window": [first.isoformat(), last.isoformat()],
        "years": years,
        "portfolio_capital": portfolio_capital,
        "assumptions": {
            "hedge_otm": HEDGE_OTM,
            "coverage_of_pc": HEDGE_COVERAGE,
            "buy_at_dte": BUY_DTE,
            "roll_at_dte": ROLL_DTE,
            "note": (
                "Black-Scholes, zero rate, no dividend, on the corpus's own spot path; the "
                "hedge's implied volatility is assumed because a 9%-OTM monthly put is "
                "outside every captured chain. Statutory costs on the hedge are NOT "
                "included; they are small beside the premium and would make the drag worse."
            ),
        },
        "by_volatility": {},
    }

    # One roll every ~30 calendar days: buy at BUY_DTE, sell at ROLL_DTE, so each cycle
    # holds the option through (BUY_DTE - ROLL_DTE) days of decay and whatever spot did.
    by_date = {row.session_date: row.close for row in rows}
    dates = sorted(by_date)
    for iv in IV_ASSUMPTIONS:
        total_cost = 0.0
        cycles = 0
        index = 0
        while index < len(dates):
            buy_date = dates[index]
            spot_at_buy = by_date[buy_date]
            strike = round(spot_at_buy * (1.0 - HEDGE_OTM) / 50.0) * 50.0
            # ST-24 rounds *lots* up, not units: the hedge is a whole number of contracts.
            lots = math.ceil(HEDGE_COVERAGE * portfolio_capital / (spot_at_buy * LOT_SIZE))
            units = lots * LOT_SIZE
            premium_paid = bs_price(
                option_type="PE",
                spot=spot_at_buy,
                strike=strike,
                t_years=BUY_DTE / 365.0,
                iv=iv,
            )
            sell_date = _date_at_or_after(dates, buy_date + dt.timedelta(days=BUY_DTE - ROLL_DTE))
            if sell_date is None:
                break
            spot_at_sell = by_date[sell_date]
            proceeds = bs_price(
                option_type="PE",
                spot=spot_at_sell,
                strike=strike,
                t_years=ROLL_DTE / 365.0,
                iv=iv,
            )
            total_cost += (premium_paid - proceeds) * units
            cycles += 1
            index = dates.index(sell_date)
        annual = total_cost / years if years else 0.0
        results["by_volatility"][f"{iv:.0%}"] = {
            "cycles": cycles,
            "total_cost_rupees": total_cost,
            "annual_cost_rupees": annual,
            "annual_drag_pct_of_pc": annual / portfolio_capital,
        }
    return results


def _date_at_or_after(dates: list[dt.date], target: dt.date) -> dt.date | None:
    for value in dates:
        if value >= target:
            return value
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--underlying", default="NIFTY")
    parser.add_argument("--corpus-root", type=Path, default=DEFAULT_CORPUS_ROOT)
    parser.add_argument("--capital", type=float, default=10_000_000.0)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    facts = drag(
        corpus_root=args.corpus_root,
        underlying=args.underlying,
        portfolio_capital=args.capital,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(facts, indent=2, default=str))
    print(json.dumps(facts, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
