# BANKNIFTY — top 5 strategies by alpha, 1–5 session holds

Stage-one screen, `research/banknifty/screen_v1.json`. Window 2024-10-01 .. 2026-05-29,
352 return observations. 102 candidate instances plus the benchmark. BANKNIFTY sessions
from 2026-06-01 are sealed and none was read.

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

**What the alpha metric penalises.** Alpha here is the annualised Sharpe of the candidate's
per-session net return series minus the benchmark's, aligned on the union of their session
dates with a **zero for a session either side sat out**. That last clause is the whole
result. A conditioner does not improve the trade it takes; it declines trades. Every session
it sits out contributes a zero to its series while the benchmark books the premium, so the
conditioner forfeits the premium on precisely those sessions and pays for the privilege in
Sharpe. The screen's best conditioner takes 5 round trips where the benchmark takes 22.

**This mirrors the NIFTY result.** The premium is the edge; the conditioners subtract trades.
`research/h1` reached the same shape on NIFTY — the mechanism showed up in the P&L and could
not separate itself from noise. BANKNIFTY reproduces it with a wider search and the same
conclusion: **breadth of search did not find a better trade than the simple one.**

---

## 2. Table A — top 5 by alpha (least negative)

Alpha = candidate annualised Sharpe − benchmark annualised Sharpe. All n = 352.
"Legs" is filled **entry legs**, not sessions — `screen.py` counts entry fills, and a
straddle is two legs per round trip.

| # | Strategy | Params | Alpha | Sharpe | Max DD | Round trips | Legs | Risk-matched incr. | Feasibility | Regime |
|---|---|---|---|---|---|---|---|---|---|
| 1 | short ATM straddle | hold 1 | **−0.656** | 1.590 | 0.074 | 26 | 52 | **+0.0067** | 62 fillable / 270 unsettleable / 114 capped-to-zero | only structure positive in high IV−RV (+0.00007); negative in low and mid |
| 2 | short ATM straddle after ≥1.5σ overnight gap | gap 1.5σ, hold 3 | −0.725 | 2.477 | 0.005 | **5** | 10 | +0.0506 | 10 fillable / 20 unsettleable | **negative in all three tagged regimes**; entire gain sits in 15 untagged sessions (+0.0106) |
| 3 | short ATM straddle after ≥1.5σ overnight gap | gap 1.5σ, hold 1 | −0.788 | 2.326 | 0.005 | **5** | 10 | +0.0419 | 10 fillable / 20 unsettleable | as above; same 15 untagged sessions carry it |
| 4 | short ATM straddle after ≥1.5σ overnight gap | gap 1.5σ, hold 5 | −0.916 | 0.877 | 0.113 | **5** | 10 | −0.0667 | 6 fillable / — | negative throughout |
| 5 | short ATM straddle | hold 5 | −1.147 | 0.693 | 0.137 | 14 | 28 | −0.1418 | 20 fillable / 226 unsettleable | negative in every regime including untagged |

**Read rows 2–4 with care.** Three of the top five by alpha are the same conditioner at three
holds, each on **5 round trips**. Their attractive Sharpes and near-zero drawdowns are
statements about ten entry legs. Their regime breakdown is the tell: all three are *negative*
in every one of the three volatility-tagged regimes, and the positive number comes entirely
from 15 sessions the regime tagger could not tag. That is not an edge; it is a handful of
sessions.

Row 1 is the only row in Table A that is both readable and positive on the volatility-matched
comparison (`risk_matched_increment` +0.0067) — the repository's own like-for-like measure,
which scales the benchmark to the candidate's volatility before differencing.

---

## 3. Table B — top 5 by risk-adjusted return (annualised Sharpe, tie-break shallower DD)

Includes the unconditional family, which the alpha ranking cannot rank because one member of
it is the benchmark. **Rows with fewer than 10 round trips are not readable** and are marked.

| # | Strategy | Params | Sharpe | Max DD | Round trips | Legs | Readable? |
|---|---|---|---|---|---|---|---|
| 1 | short ATM straddle after ≥1.5σ gap | gap 1.5σ, hold 3 | 2.477 | 0.005 | 5 | 10 | **NO — 5 round trips** |
| 2 | short ATM straddle after ≥1.5σ gap | gap 1.5σ, hold 1 | 2.326 | 0.005 | 5 | 10 | **NO — 5 round trips** |
| 3 | **short ATM straddle (unconditional)** | **hold 1** | **1.590** | **0.074** | **26** | 52 | **yes** |
| 4 | **short ATM straddle (unconditional)** | **hold 3** — *the benchmark* | **1.536** | **0.116** | **22** | 44 | yes — but **breaches the drawdown bar**, see below |
| 5 | short ATM strangle after ≥1.5σ gap | 1×ATR, gap 1.5σ, hold 3 | 1.417 | 0.000 | **1** | 2 | **NO — 1 round trip** |
| *memo* | short ATM straddle on EMA20 z-band | thr 0.5, hold 3 | 1.202 | 0.047 | 18 | 36 | yes — highest-Sharpe **readable conditioner** |
| *memo* | short ATM straddle on EMA20 z-band | thr 1.0, hold 1 | 1.080 | 0.033 | 12 | 24 | yes |

**Three of the top five are unreadable.** That is the honest headline of Table B: ranking a
102-instance screen by raw Sharpe surfaces whatever took the fewest trades, because a small
sample of lucky trades makes a high ratio. Only rows 3 and 4 — both unconditional — clear
10 round trips.

**Row 4 breaches a pre-registered bar.** `max_drawdown ≤ 0.10` is the ruin bound recorded in
`research/m1/gate.toml` and carried unchanged into `research/banknifty/gate_v1.toml`. The
hold-3 straddle draws down **0.116**. The hold-1 straddle draws down **0.074** and is inside
it. Between the two unconditional holds, hold-1 has the better Sharpe, the shallower
drawdown, more round trips (26 vs 22), the less-negative alpha, and a positive risk-matched
increment. **Hold-1 is the recommendation; hold-3 is not, and the drawdown is why.**

---

## 4. Stage-two gate — BLOCKED, no verdict on any instance

Four instances were pre-registered for grading in `research/banknifty/gate_v1.toml`, committed
ahead of any result: ranks 1, 2, 8 and 11. **None produced a verdict.** Full record and
verbatim errors: [`gates/BLOCKED.md`](gates/BLOCKED.md).

| Instance | Verdict | Deflated Sharpe | DSR bar | Max DD | Cost breakeven | Reason |
|---|---|---|---|---|---|---|
| rank 1 — straddle hold 1 | **none — gate refused** | not computed | 0.90 | 0.074 (stage 1) | not computed | engine defect |
| rank 2 — post-gap hold 3 | **none — gate refused** | not computed | 0.90 | 0.005 (stage 1) | not computed | engine defect |
| rank 8 — EMA band hold 1 | **none — gate refused** | not computed | 0.90 | 0.033 (stage 1) | not computed | engine defect |
| rank 11 — EMA band hold 3 | **none — gate refused** | not computed | 0.90 | 0.047 (stage 1) | not computed | engine defect |
| hold-3 straddle (benchmark) | **not gateable by rank** | — | 0.90 | 0.116 (stage 1) | — | null alpha; `gate.py` refuses an unmeasured row |

**The defect.** The stage-one spec registered `thresholds = {alpha_to_advance = 0.5}` on the
hypothesis record. `check_binding` then *requires* the gate to carry that criterion, while
`DecisionGate.__post_init__` *refuses* any gate naming it, because no component computes it.
No gate file satisfies both. Any hypothesis registered with `alpha_to_advance` can never be
stage-two gated.

**The family is intact.** 107 trials before the first attempt, 107 after the eighth. Nothing
appended, no verdict produced and discarded. **The holdout is deferred, not spent** — BANKNIFTY
from 2026-06-01 remains sealed and unread.

**The gate would not have passed anyway, and this is the more important number.** At
n = 352 observations against N = 109 logged trials:

| true annualised Sharpe | 0.0 | 0.5 | 1.0 | 1.5 | 2.0 | 2.5 | 3.0 |
|---|---|---|---|---|---|---|---|
| median DSR | 0.025 | 0.082 | 0.206 | 0.406 | 0.634 | 0.822 | 0.933 |
| share clearing 0.90 | 0.0% | 0.0% | 0.0% | **7.5%** | 15.0% | 35.0% | 55.0% |

A true Sharpe of 1.5 — about what the best instance shows — clears the bar in 7.5% of draws.
Fixing the defect would have bought four `FAILS_THRESHOLD` verdicts, not a pass. **A
102-instance screen over 352 observations cannot separate any one of its instances from its
own breadth**, and that is what `gate_v1.toml` said in advance a miss would mean.

---

## 5. Caveats

1. **Corpus completeness 87%.** 353 of 407 expected sessions on disk. 53 were quarantined by
   the producer (42 for premium-below-intrinsic candles with a >0.5% rolling-spot divergence,
   clustered Apr–Jul 2025; 1 for the premium check alone; 10 for expiry-day convergence
   failure). 2024-11-20 was never a session — NSE did not trade (Maharashtra state election).
2. **Quarantined expiry days dominate feasibility.** Ten of the window's 27 expiry cycles have
   no settlement session, so the engine declines them at entry: the benchmark shows **258
   unsettleable against 44 fillable**. The population is quarantine-*selected*, not random —
   expiry-day convergence failure is likeliest on the expiries where the ATM straddle held the
   most residual value, which is not independent of what a short straddle earns there. **This
   plausibly biases the measured premium upward** and nothing here corrects for it.
3. **Stale and capped marks.** Every instance carries a large `capped_to_zero` count (114 on
   rank 1, 71 on the benchmark) and a `resized` count (48 and 38) — positions the ladder could
   not fill at the requested size. Sizes actually traded are frequently not the sizes modelled.
4. **Lot-size regimes.** The declared lot size moves across the window (15 / 30 / 35 boundaries)
   and the corpus audit records sessions where the declared value contradicts what the bars
   support. Notional is held at ₹50L, so the contract count changes underneath the strategy.
5. **Sample size — 352 observations, ~20 months.** This is the binding constraint. From the
   table in §4, at N = 109 trials a **true** annualised Sharpe of 1.5 reaches median DSR 0.406
   and clears 0.90 in 7.5% of draws. Reaching 90% power at that Sharpe needs roughly
   **3,000 sessions — about twelve years** of daily data. `research/h1/DECISION.md` §1 recorded
   the same shape on 79 observations: the premium showed up, the evidence did not. More
   instances make this worse, not better — each one deflates the rest.
6. **Monthly-only expiry after 2024-11-13.** BANKNIFTY weekly expiries were culled six weeks
   into the window. The pooled series is overwhelmingly a monthly-expiry series with a short
   weekly prologue, and it is not a statement about the weekly regime.

---

## 6. Recommendation

**Paper-trade first:** the **unconditional short ATM straddle at hold 1** — Sharpe 1.590,
drawdown 0.074 (inside the 0.10 ruin bar, which hold-3 breaches at 0.116), 26 round trips,
the least-negative alpha and the only readable positive risk-matched increment. Size so the
contract count is **n ≥ 2 lots** at every session, so a capped-to-zero fill cannot silently
turn a position into no position.

**Keep testing:** `ema_atr_band` — at threshold 0.5 / hold 3 it is the highest-Sharpe
*readable* conditioner (1.202 on 18 round trips) at a third of the benchmark's drawdown
(0.047 vs 0.116). It loses on alpha only by sitting out sessions. If the objective is
drawdown-adjusted rather than premium-maximising, it is the one worth a narrow,
pre-registered hypothesis of its own — graded against a **fresh family**, not this one.

**Drop:** every `post_gap` variant and the 1-round-trip strangles. Their high Sharpes rest on
5 and 1 round trips, and their regime breakdown is negative in all three tagged regimes with
the entire gain in 15 untagged sessions. Also drop hold-5 across the board — it is the worst
unconditional hold on every measure.
