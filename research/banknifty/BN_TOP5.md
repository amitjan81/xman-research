# BANKNIFTY — top 5 strategies by alpha, 1–5 session holds

Stage-one screen, `research/banknifty/screen_v1.json`. Window 2024-10-01 .. 2026-05-29,
352 return observations. 102 candidate instances plus the benchmark. BANKNIFTY sessions
from 2026-06-01 are sealed; the record that no run read one is in
[`gates/BLOCKED.md`](gates/BLOCKED.md), which carries the invocations.

---

## 1. The finding

**Nothing beats the unconditional short ATM straddle.** The benchmark — sell the ATM
straddle every session, hold 3 sessions, ₹50L notional — returns an annualised Sharpe of
**1.536**, and no conditioner in a 102-instance screen produced a positive excess-return
Sharpe over it.

The decomposition is exact, and it is not "all 102 were negative":

| | count | |
|---|---|---|
| measured candidates with a defined alpha | **89** | **every one negative**, best −0.656 |
| instance identical to the benchmark | 1 | hold-3 straddle; alpha undefined, not negative |
| instances that never entered | 12 | entry rules refused every session |
| | **102** | |

The hold-3 unconditional straddle carries a null alpha because it **is** the benchmark. The
sheet says why: *"the spread over the benchmark is identically flat, so it has no dispersion
to form a ratio."* Reporting it as a negative alpha would be wrong.

**What the alpha metric penalises.** Alpha is the annualised Sharpe of the **difference
series** — the candidate's per-session net return minus the benchmark's, aligned on the union
of their session dates with a **zero for a session either side sat out**. That last clause
drives most of the table. A conditioner does not improve the trade it takes; it declines
trades. Every session it sits out contributes a zero to its series while the benchmark books
the premium, so the conditioner forfeits the premium on those sessions and pays for it in
Sharpe. The screen's best conditioner takes 5 round trips where the benchmark takes 22.

**That mechanism does not explain row 1, and the difference matters.** The hold-1
unconditional straddle sits out nothing (exposure 0.426 against the benchmark's 0.432). Its
alpha is −0.656 because it earns *less per session* — 0.000773 against 0.000971, annualising
to 19.5% against 24.5% — at lower volatility. So a row can carry a **higher** Sharpe than the
benchmark (1.590 vs 1.536) and still show a negative alpha: the difference series has its own
dispersion, and a lower-return, lower-vol book differs from the benchmark in a direction that
scores negatively.

**This mirrors the NIFTY result** in `research/h1` — the premium showed up in the P&L and
could not separate itself from noise. The designs differ (h1 gated one pre-registered instance
at N = 6; this is a 102-instance screen), so what mirrors is the conclusion, not the method:
**the variance premium is the edge, and breadth of search did not find a better trade than the
simple one.**

---

## 2. Table A — top 5 by alpha (least negative)

**Alpha** = annualised Sharpe of the difference series (§1), **not** the difference of the two
Sharpes. Those are different numbers: row 1 has an alpha of −0.656 and a Sharpe *difference*
of +0.054. All n = 352.

"Legs" is filled **entry legs**, not sessions — `screen.py` counts entry fills, and a straddle
is two legs per round trip. Feasibility counts are **leg-level fill outcomes**, not sessions:
they do not sum to 352, and `fillable` exceeds twice the round-trip count, so a leg can be
counted under more than one outcome. Regime figures are **mean excess return over the
benchmark** per session, not the instance's own return.

| # | Strategy | Params | Alpha | Sharpe | Max DD | Round trips | Legs | Risk-matched incr. | Feasibility (legs) | Regime (excess over benchmark) |
|---|---|---|---|---|---|---|---|---|---|
| 1 | short ATM straddle | hold 1 | **−0.656** | 1.590 | 0.074 | 26 | 52 | +0.0067 | 62 fillable / 270 unsettleable / 114 capped-to-zero | ≈0 in high IV−RV (+0.00007), negative in low/mid, +0.00069 untagged |
| 2 | short ATM straddle after ≥1.5σ overnight gap | gap 1.5σ, hold 3 | −0.725 | 2.477 | 0.005 | **5** | 10 | +0.0506 | 10 fillable / 20 unsettleable | negative in all three tagged regimes; +0.0106 in 15 untagged sessions |
| 3 | short ATM straddle after ≥1.5σ overnight gap | gap 1.5σ, hold 1 | −0.788 | 2.326 | 0.005 | **5** | 10 | +0.0419 | 10 fillable / 20 unsettleable | as above; same 15 untagged sessions |
| 4 | short ATM straddle after ≥1.5σ overnight gap | gap 1.5σ, hold 5 | −0.916 | 0.877 | 0.113 | **5** | 10 | −0.0667 | 6 fillable / 20 unsettleable | negative in all three tagged regimes; +0.0050 untagged |
| 5 | short ATM straddle | hold 5 | −1.147 | 0.693 | 0.137 | 14 | 28 | −0.1418 | 20 fillable / 226 unsettleable | negative in every regime including untagged |

**Read rows 2–4 with care.** Three of the top five by alpha are the same conditioner at three
holds, each on **5 round trips**. Their attractive Sharpes and near-zero drawdowns are
statements about ten entry legs. Their regime breakdown is the tell: all three are *negative*
in every one of the three volatility-tagged regimes and positive only in 15 sessions the
regime tagger could not tag.

But note what that breakdown is and is not. It measures **excess over the benchmark**, so
"negative in the tagged regimes" for an instance at 8% exposure mostly says *the benchmark
earned premium there while this instance sat out*. It is not a decomposition of where the
instance's own Sharpe of 2.477 came from, and it cannot be one. What it does show is a
concentration: rank 2 out-earned the benchmark by ~15.8% cumulative across those 15 untagged
sessions and lost to it everywhere else. **The 15 untagged sessions are not identified in the
sheet.** The feature series covers 337 of 353 sessions, so they are plausibly the window's
IV/RV warm-up — which would place them in the six-week weekly-expiry prologue this document
says the result is not a statement about. That is unconfirmed and should be confirmed before
anyone acts on rows 2–4.

Row 1 is the only row in Table A that is both readable and non-negative on the
volatility-matched comparison. Its `risk_matched_increment` of **+0.0067 is +0.67% annualised
return — inside noise**, not a demonstrated edge.

---

## 3. Table B — top 5 by risk-adjusted return (annualised Sharpe, tie-break shallower DD)

Includes the unconditional family, which the alpha ranking cannot rank because one member of
it is the benchmark. The **10-round-trip readability floor below is arbitrary and used only
for presentation** — it is not pre-registered and nothing was graded against it.

| # | Strategy | Params | Sharpe | Max DD | Round trips | Legs | Readable? |
|---|---|---|---|---|---|---|---|
| 1 | short ATM straddle after ≥1.5σ gap | gap 1.5σ, hold 3 | 2.477 | 0.005 | 5 | 10 | **NO — 5 round trips** |
| 2 | short ATM straddle after ≥1.5σ gap | gap 1.5σ, hold 1 | 2.326 | 0.005 | 5 | 10 | **NO — 5 round trips** |
| 3 | **short ATM straddle (unconditional)** | **hold 1** | **1.590** | **0.074** | **26** | 52 | **yes** |
| 4 | **short ATM straddle (unconditional)** | **hold 3** — *the benchmark* | **1.536** | **0.116** | **22** | 44 | yes — misses the drawdown bar, see below |
| 5 | short ATM strangle after ≥1.5σ gap | 1×ATR, gap 1.5σ, hold 3 | 1.417 | 0.000 | **1** | 2 | **NO — 1 round trip** |
| *memo* | short ATM straddle on EMA20 z-band | thr 0.5, hold 3 | 1.202 | 0.047 | 18 | 36 | yes — highest-Sharpe **readable conditioner** |
| *memo* | short ATM straddle on EMA20 z-band | thr 1.0, hold 1 | 1.080 | 0.033 | 12 | 24 | yes |

**Three of the top five are unreadable.** That is the honest headline of Table B: ranking a
102-instance screen by raw Sharpe surfaces whatever took the fewest trades, because a small
sample of lucky trades makes a high ratio. Only rows 3 and 4 — both unconditional — clear 10
round trips.

**Hold-1 versus hold-3, stated with its uncertainty.** Hold-1 clears the pre-registered
`max_drawdown ≤ 0.10` ruin bar by 0.026; hold-3 misses it by 0.016. That is the one criterion
either was ever measured against in advance, and it is why hold-1 is preferred. But **on 22–26
round trips the two drawdowns are not distinguishable from each other** — the sampling
variance of a max-drawdown estimate at that trade count is far wider than the 0.042 gap
between them, so "inside the bar" versus "outside it" is roughly one bad trade's difference
and is not a property of the strategies. The Sharpe gap (0.054) and hold-1's risk-matched
increment (+0.67%/yr) are likewise within noise. Hold-1 also has more round trips (26 vs 22).

---

## 4. Stage-two gate — four NOT_EVALUABLE verdicts

All four pre-registered ranks were graded against `research/banknifty/gate_v1.toml`. Every
one returned **NOT_EVALUABLE**, which is what the gate file pre-committed to expecting. It is
a result, and it is a result about the corpus rather than about the variance premium.

| rank | instance | verdict | deflated Sharpe | family size at deflation | infeasible fraction | holdout spent |
|---|---|---|---|---|---|---|
| 1 | short ATM straddle, hold 1 | **NOT_EVALUABLE** | 0.2701 | 109 | 80.6% | no |
| 2 | post-gap straddle, hold 3 | **NOT_EVALUABLE** | 0.7875 | 111 | 69.0% | no |
| 8 | EMA/ATR band 1.0, hold 1 | **NOT_EVALUABLE** | 0.1164 | 113 | 67.6% | no |
| 11 | EMA/ATR band 0.5, hold 3 | **NOT_EVALUABLE** | 0.1547 | 115 | 78.4% | no |

**Why every one is NOT_EVALUABLE.** The pre-registered `max_infeasible_fraction = 0.10` is
missed by most of an order of magnitude on all four. The reason recorded on each decision,
verbatim for rank 1: *"80.6% of 566 intents could not have been filled (limit 10.0%); the P&L describes trades the market would not have taken"*. Ten of the window's 27 expiry cycles have no session
at which a position would have cash-settled, so the engine declines those cycles at entry.

**No threshold was applied to any number in that table.** NOT_EVALUABLE is returned ahead of
any pass/fail outcome, so the deflated Sharpes are recorded because they were measured, not
because they decided anything. They are all below the 0.90 bar in any case, and the family
size is why: the count is the 107 trials the stage-one screen logged plus the rows each run
appends for itself. At n=352 against a family of this size a *true* annualised Sharpe of 1.5
clears 0.90 in about 7.5% of draws, and that calibration is iid Gaussian — it understates the
deflation a fat-tailed short-variance series earns.

**The holdout is unspent on all four.** It is measured only on a PASSED in-sample verdict.
No BANKNIFTY session on or after 2026-06-01 was opened by any of these runs.

**The family is intact and the amendment did not reset it.** These runs are filed against
`h_307a83a24fd9a8018c3567322b00097f`, the amendment of the screen's record
`h_a2c7cc855f6f06b2581afb7f2079121d`. The amendment moved the screen's own `alpha_to_advance`
bar to `screen_criteria` — the field for a criterion no gate grades — and registered the gate
bars the record is actually judged against. The parent link keeps the screen's 107 trials in
the family, which is why the deflation counts them.

Per-rank write-ups: `research/banknifty/gates/rank{1,2,8,11}/DECISION.md`. The engine defect
that blocked the first eight attempts, and its resolution, are in
`research/banknifty/gates/BLOCKED.md`.

## 5. Caveats

1. **Corpus completeness 87%.** 353 of 407 expected sessions on disk. 53 were quarantined by
   the producer (42 for premium-below-intrinsic candles with a >0.5% rolling-spot divergence,
   clustered Apr–Jul 2025; 1 for the premium check alone; 10 for expiry-day convergence
   failure). 2024-11-20 was never a session — NSE did not trade (Maharashtra state election).
2. **Both quarantine populations are stress-selected, and both plausibly bias the measured
   premium upward.** Ten of 27 expiry cycles have no settlement session, so the engine declines
   them at entry — the benchmark shows **258 unsettleable legs against 44 fillable**.
   Expiry-day convergence failure is likeliest on the expiries where the ATM straddle held the
   most residual value, which is not independent of what a short straddle earns there. The 42
   Apr–Jul 2025 sessions are selected the same way from the other side: premium-below-intrinsic
   with dislocated spot is precisely when a short-gamma book loses. **Nothing here corrects for
   either.** The fate of a hold-3 position spanning a quarantined non-expiry session is not
   documented in the sheet; the benchmark's `no_bar = 34` suggests such legs are declined
   rather than zero-filled, but that is inference, not a recorded rule.
3. **Stale and capped marks.** Every instance carries a large `capped_to_zero` count (114 on
   rank 1, 71 on the benchmark) and a `resized` count (48 and 38) — positions the ladder could
   not fill at the requested size. Sizes actually traded are frequently not the sizes modelled.
4. **Lot-size regimes.** The declared lot size moves across the window (15 / 30 / 35 boundaries)
   and the corpus audit records sessions where the declared value contradicts what the bars
   support. Notional is held at ₹50L, so the contract count changes underneath the strategy.
   A further entry restriction, `min_calendar_days_to_expiry = 6`, is carried in every
   instance's `strategy_parameters` and excludes the final week of each cycle.
5. **Sample size — 352 observations, ~20 months.** This is the binding constraint. From §4, at
   N = 109 a **true** annualised Sharpe of 1.5 reaches median DSR 0.406 and clears 0.90 in 7.5%
   of draws. Reaching 90% power at that Sharpe needs roughly **3,000 sessions — about twelve
   years** (`--case 3000:109` → 90.0%), and that figure inherits the Gaussian optimism in §4.
   `research/h1/DECISION.md` §1 recorded the same shape on 79 observations: the premium showed
   up, the evidence did not. More instances make this worse, not better — each deflates the rest.
6. **Monthly-only expiry after 2024-11-13, and annualisation across it.** BANKNIFTY weekly
   expiries were culled six weeks into the window. The pooled series is overwhelmingly a
   monthly-expiry series with a short weekly prologue, and is not a statement about the weekly
   regime. The annualisation constant is nonetheless applied across the boundary, where both
   the cycles-per-year and the independence of successive observations changed. Sharpe is also
   computed on the **zero-padded** series, so a low-exposure instance already carries a
   √exposure penalty: rank 2's 2.477 at ~8% exposure corresponds to roughly 8.6 on its active
   sessions alone. Overlapping hold-3 and hold-5 returns on daily observations are not
   corrected for.

---

## 6. Recommendation

**Paper-trade first:** the **unconditional short ATM straddle at hold 1**. It clears the one
pre-registered bar either unconditional hold was measured against (DD 0.074 ≤ 0.10, which
hold-3 misses at 0.116), has the higher Sharpe (1.590) and more round trips (26). Size so the
contract count is **n ≥ 2 lots** at every session, so a capped-to-zero fill cannot silently
turn a position into no position. **State plainly what this pick is:** an ungated, post-hoc
selection from a 102-instance screen — the exact selection the deflated Sharpe exists to charge
for — whose margin over hold-3 is inside noise on every measure. It is being paper-traded, not
advanced.

**Keep testing:** `ema_atr_band` at threshold 0.5 / hold 3 — the highest-Sharpe *readable*
conditioner (1.202 on 18 round trips) at about **40%** of the benchmark's drawdown (0.047 vs
0.116) while carrying **76%** of its exposure, so part of that shallower drawdown is mechanical.
It is **negative on the risk-matched increment (−0.020)**, the like-for-like measure this
document leans on elsewhere: under that metric it subtracts. It is worth a narrow,
pre-registered hypothesis of its own — graded against a **fresh family**, not this one — only
if the objective is explicitly drawdown-adjusted rather than premium-maximising.

**Drop:** the 1.5σ `post_gap` variants and the 1-round-trip strangles, whose Sharpes rest on 5
and 1 round trips. Drop the 1.0σ `post_gap` variants too — those *are* readable (10–16 round
trips) but on their own merits: drawdowns of 0.14–0.22 and alpha ≤ −1.27. Drop hold-5 across
the board — it is the worst unconditional hold on Sharpe, drawdown, alpha, risk-matched
increment and round trips alike.
