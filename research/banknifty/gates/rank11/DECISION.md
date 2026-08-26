# BANKNIFTY stage two, rank 11 — NOT_EVALUABLE

`short_atm_straddle_ema_atr_band[ema_band_threshold=0.5,hold_sessions=3.0,target_notional=5000000.0] (in-sample)` — short ATM straddle conditioned on an EMA/ATR band of 0.5, hold 3 sessions.

**Verdict: NOT_EVALUABLE.** Not a pass and not a threshold failure. The gate stopped before
any bar was applied, because the run does not describe trades this corpus can show the
market would have taken.

## Why

> 78.4% of 306 intents could not have been filled (limit 10.0%); the P&L describes trades the market would not have taken

The pre-registered feasibility bar is `max_infeasible_fraction = 0.10`, in
`research/banknifty/gate_v1.toml`, committed before any instance was graded. At 78.4% the
run misses it by most of an order of magnitude. Ten of the window's 27 expiry cycles have no
session at which a position would have cash-settled, so the engine declines those cycles at
entry; what is left is too few fillable intents to grade anything.

**This is a result about the corpus, not about the variance premium.** The gate file said so
in advance: *"the finding is 'this corpus cannot evaluate this family at the pre-registered
feasibility bar', and that is a result about the corpus. It is not a result about the
strategy, and it will not be reported as one."*

## The numbers the run did produce

They are recorded because they were measured, not because they decide anything — a verdict
of NOT_EVALUABLE means no threshold was applied to them.

| quantity | value |
|---|---|
| deflated Sharpe | 0.1547 (bar 0.90, not applied) |
| annualised Sharpe | 1.202 |
| trial family size at deflation | 115 |
| return observations | 352 |

`115` is the 107 trials the stage-one screen logged against this hypothesis's family, plus
the rows each gate run appends for itself before the count is read. The family is that of
`h_307a83a24fd9a8018c3567322b00097f`, the amendment of the screen's own record — the parent
link is what keeps the screen's breadth in the count.

Even had the run been evaluable, the deflated Sharpe is below its 0.90 bar. At n=352 against
this family size, a *true* annualised Sharpe of 1.5 clears 0.90 in about 7.5% of draws
(`uv run python -m xman_research.h1.calibrate_thresholds --case 352:109 --bar 0.90`), and
that calibration is iid Gaussian, so it understates the deflation a fat-tailed short-variance
series earns.

## The holdout

`holdout_spent: False`. The holdout is measured only on a PASSED in-sample verdict, and
this verdict is not one. No sealed BANKNIFTY session was opened; the sealed months from
2026-06-01 are deferred, not spent. The `--seal-override` this run carried is recorded in
`decision.json` under `holdout_seal.override_reason`.

## Next step, as the record states it

> The answer is about execution — resolve the quote-data question before continuing.
