# Cross-index divergence — does Sensex dislocate against Nifty inside the closing auction?

**The thesis under test** (owner, 2026-08-29): *"Sensex jumped during CAS and option premiums skyrocketed; Nifty, highly correlated, didn't move during CAS, so none of Nifty's premiums moved — which means the Sensex move was going to revert. There is a short-term strategy here."*

**The verdict.** The reversion logic is sound and the microstructure supports it, but the dislocation the thesis is built on **is not in the derivatives market**, and the trigger the strategies need does not fire on the session that matters.

**The timing is the sharpest way to see it.** The published indicative index fell 2,199.72 points (−2.85 %) between **15:18 and 15:23**. Across exactly those minutes the Sensex option-implied index sat between **77,162.45 and 77,267.45** — within ~80 points of its 15:14 reference of 77,242.30 — and the cross-index divergence `d` ran **+0.28 to −44.93 points (≤0.06 %)**. The derivatives carried **~2 % of the dislocation while it was happening**, and did not follow the auction down at all.

What the derivatives did do came later and was much smaller. Sensex implied troughed at **76,847.60 at 15:27** — **−394.70 points (−0.511 %)**, or **17.9 %** of the indicative drop, and four minutes *after* the indicative had already recovered. The Nifty-adjusted residual `d` peaked at **−276.08 points (−0.36 %)** in that same minute, **12.6 %** of the indicative drop. Over 15:14 → 15:39 Sensex implied moved **−0.40 %** and Nifty implied **−0.17 %**: both indices moved, the same way, and the entire cross-index asymmetry is ~180 points.

Consequences, in order of how much they cost:

1. **The trigger never fires on the dislocated session, under any β considered.** The largest |d| at the fitted β is **0.4818 %** over 400 session-minutes, below the smallest threshold the brief asked to test. At X = 0.5 %, 1 % and 1.5 % the strategies take **zero trades on 08-27** at every β from β̂−SE through β = 1. The one place X = 0.5 % fires at all is at β̂+SE and β = 1 — **once, on 2026-08-04**, an ordinary Nifty expiry (§3.1).
2. **The band-bounded short put dies on arithmetic before any backtest.** The deepest put that traded at the 08-27 trigger collected **3.80 points gross, 2.61 net** against a band-bounded worst case of **1,274.97 points** — reward-to-risk **1 : 335 gross, 1 : 488 net**.
3. **The wing the thesis points at is outside the corpus, so the overpricing claim cannot be tested either way.** No listed strike lies outside the ±3 % band on any session, and no in-band strike ever traded above its own cap. The **75,000 PE** that reportedly rose ~4,800 % is 900 points below the lowest strike here and has no bar at any minute (§5).

**Held out of that list deliberately:** the P&L of the exploratory X = 0.25 % trades. That threshold was chosen after seeing the distribution and sits between p90 (0.234 %) and p95 (0.276 %), so it selects the four largest-|d| sessions **by construction**. Its four trades net −₹1,807 and the crash session is among the losers — an illustration of what these structures cost when they fire, not an estimate of anything (§3, §4).

**One incidental finding worth acting on separately:** NIFTY 2026-08-20, 08-21 and 08-24 are in the *published* corpus with **8,085 call bars and zero put bars each**. Parity is impossible on them and any put-based study fails silently. See §5.

---

## 1. Method, in one paragraph

Both indices are recovered by put-call parity, `S = C − P + K`, at **one strike per session per underlying**, fixed for the whole session as the strike with the most both-legs-traded minutes over 15:00–15:39. Only minutes where both legs printed volume contribute. Fair value is `S_fair(t) = S_ref × (N_imp(t)/N_ref)^β` with both references at **15:14**, the last minute of continuous cash trading, and `d(t) = S_imp(t) − S_fair(t)`. Divergence is computed **only on minutes live on both indices** — never one side forward-filled to meet the other. Full rationale in the `cross_index.py` module docstring; generated tables in `cross_index_output.md`.

**β = 0.9048** (SE 0.0735), **R² = 0.8392**, n = 31 daily log-return pairs, 2026-07-14 … 2026-08-26, **2026-08-27 excluded** so the estimator is not fitted through the event it is built to detect. Closes are each session's last index bar **before 16:00**, and only where that bar lands at or after 15:20: the NIFTY feed carries stub bars hours after the close on some sessions, and a session whose feed dies mid-afternoon (the quarantined 08-25, last bar 13:04) has no close to contribute and is dropped rather than have a mid-day level differenced as one. β instability is quantified rather than assumed away: at **β = 1** the 08-27 peak moves from −276.08 to **-263.60 points**, which changes nothing — but the trigger count at X = 0.5 % *does* change, and §3.1 reports it.

---

## 2. Divergence per session

`d` in Sensex points. Positive = Sensex rich against Nifty-implied fair. `s_chg` / `n_chg` are each index's own implied move 15:14 → 15:39, which is the quantity the owner's thesis is stated in. **Q** = quarantined session.

| Session | S expiry | N expiry | d peak | % | at | d @15:30 | d @15:35 | d @15:39 | closed by 15:35 | s_chg % | n_chg % |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-08-03 |  |  | −48.23 | −0.06 | 15:38 ▲ | −16.48 | −19.76 | −38.06 | 17.0 % | +0.03 | +0.09 |
| **2026-08-04** |  | ✓ | **−379.49** | **−0.48** | 15:39 ▲ | −333.99 | −370.30 | −379.49 | 2.3 % | −0.03 | +0.50 |
| 2026-08-05 |  |  | −68.74 | −0.09 | 15:15 | −30.06 | −43.23 | −40.71 | 37.1 % | −0.15 | −0.11 |
| 2026-08-06 | ✓ |  | +324.59 | +0.41 | 15:24 | +54.43 | +65.04 | +57.43 | 80.0 % | +0.08 | −0.00 |
| 2026-08-07 |  |  | +22.03 | +0.03 | 15:15 | +0.59 | +10.97 | +21.97 | 50.2 % | +0.01 | −0.02 |
| 2026-08-10 |  |  | −18.34 | −0.02 | 15:37 ▲ | −1.96 | −12.05 | −10.18 | **0.0 %** | −0.05 | −0.04 |
| 2026-08-11 |  | ✓ | −53.97 | −0.07 | 15:38 ▲ | −12.53 | −40.52 | −53.67 | 24.3 % | −0.10 | −0.03 |
| 2026-08-12 |  |  | +19.27 | +0.02 | 15:27 | +9.62 | +15.90 | +13.13 | 17.5 % | +0.04 | +0.03 |
| 2026-08-13 | ✓ |  | +216.10 | +0.28 | 15:38 ▲ | +205.03 | +205.39 | +216.05 | **0.0 %** | +0.27 | −0.01 |
| 2026-08-14 |  |  | −18.15 | −0.02 | 15:39 ▲ | −3.01 | −4.60 | −18.15 | 1.3 % | −0.04 | −0.02 |
| 2026-08-17 |  |  | −10.07 | −0.01 | 15:25 | +2.13 | +3.03 | −0.58 | 69.9 % | −0.14 | −0.16 |
| 2026-08-18 |  | ✓ | +122.50 | +0.16 | 15:27 | +79.84 | +47.89 | −1.51 | 60.9 % | −0.15 | −0.16 |
| 2026-08-19 |  |  | −25.62 | −0.03 | 15:39 ▲ | −10.86 | −12.68 | −25.62 | 43.1 % | −0.03 | −0.00 |
| 2026-08-25 **Q** |  | ✓ | −194.23 | −0.25 | 15:28 | −165.90 | −109.70 | −108.30 | 43.5 % | +0.14 | +0.31 |
| 2026-08-26 |  |  | −68.45 | −0.09 | 15:29 | −41.29 | −51.71 | −45.10 | 24.4 % | −0.25 | −0.21 |
| **2026-08-27** | ✓ |  | **−276.08** | **−0.36** | 15:27 | −223.76 | −188.70 | −190.68 | 31.6 % | −0.40 | −0.17 |

**Closure is measured against the peak reached by 15:35, not the peak over the whole window.** ▲ marks the seven sessions whose largest divergence arrives *after* matching ends — for those, a full-window peak divided by the 15:35 level would not be a reversion statistic at all, and would report a still-widening session as partly reverted. Under the correct definition three of them close by exactly nothing.

Every session carries the full **25 of 25** minutes with **zero fallback minutes** — the fixed strike traded every minute of 15:15–15:39 on both indices, on all 16 sessions.

**Three readings.**

- **08-27 is not the extreme session.** The largest divergence in the corpus is **2026-08-04 at −379.49 points**, an ordinary Nifty expiry Tuesday, driven entirely by the Nifty leg (+0.50 % while Sensex was flat) — an expiry pin on the *other* index, not a Sensex dislocation. A live detector keyed on |d| would have ranked the crash day **third**, behind 08-04 and 08-06 (+324.59); two of the three largest divergences in the corpus are expiry pins.
- **Divergence does not reliably revert.** Median closure by 15:35 across the four largest sessions is **17.0 %**, and on 08-10 and 08-13 it is **exactly zero** — those sessions were at their widest at 15:35 and still widening. Reversion of the auction dislocation, if it happens, happens *after* the derivatives session ends.
- **Both indices moved on 08-27.** The thesis's "Nifty didn't move" is true of the published Nifty *auction indicative* (−0.31 %) and false of Nifty's traded option-implied index over the same minutes (−0.17 %, against Sensex's −0.40 %). The asymmetry is real but is ~180 points, not ~2,200.

### |d| distribution, all 400 session-minutes

| p50 | p75 | p90 | p95 | max |
|---|---|---|---|---|
| 0.024 % | 0.071 % | 0.234 % | 0.276 % | **0.482 %** |

The 95th percentile of divergence is smaller than the smallest threshold the brief asked to test.

---

## 3. Trigger statistics

|d| ≥ X, over 16 sessions / 400 minutes:

| X | sessions fired | trigger minutes | median of per-session longest run | median % closed by 15:35 | sessions |
|---|---|---|---|---|---|
| **0.25 %** *(exploratory, post-hoc)* | 4 / 16 | 35 | 10.0 min | 17.0 % | 08-04, 08-06, 08-13, **08-27** |
| **0.50 %** | **0** / 16 | 0 | — | — | — |
| **1.00 %** | **0** / 16 | 0 | — | — | — |
| **1.50 %** | **0** / 16 | 0 | — | — | — |

The largest |d| at the fitted β is **0.4818 %** — below the smallest specified threshold, but by only **3.6 %**, and it occurs on 2026-08-04 rather than on the dislocated session.

X = 0.25 % is **not** one of the thresholds the brief specified. It was added after seeing that the specified ones never fire, so every number derived from it is post-hoc. It sits between p90 (0.234 %) and p95 (0.276 %), so "4 of 16 fired" carries no information — the threshold **selects the four largest-|d| sessions by construction**, and the closure statistic beside it is conditioned on those peaks. **Three of its four firings are non-dislocated sessions**, which is worth knowing as an illustration and is not a false-trigger *rate*: n = 4, chosen post-hoc.

### 3.1 Does the trigger survive the β estimate's own uncertainty?

The zero-trigger result is this report's central claim, so it is recomputed across β rather than asserted from the point estimate. Sessions firing at each threshold:

| case | beta | max_abs_d_pct | fired at 0.25% | fired at 0.5% | fired at 1.0% | fired at 1.5% |
|---|---|---|---|---|---|---|
| beta - SE | 0.8312 | 0.4451 | 4 (08-04, 08-06, 08-13, 08-27) | 0 (—) | 0 (—) | 0 (—) |
| beta (fitted) | 0.9048 | 0.4818 | 4 (08-04, 08-06, 08-13, 08-27) | 0 (—) | 0 (—) | 0 (—) |
| beta + SE | 0.9783 | 0.5185 | 5 (08-04, 08-06, 08-13, 08-25, 08-27) | 1 (08-04) | 0 (—) | 0 (—) |
| beta = 1 | 1.0000 | 0.5293 | 5 (08-04, 08-06, 08-13, 08-25, 08-27) | 1 (08-04) | 0 (—) | 0 (—) |

**08-27 never fires at X = 0.5 % under any β in this range** — that part is robust. What is *not* robust is the blanket claim "0.5 % never fires": at β̂+SE (0.9783) and at β = 1 it fires once, on **08-04**, the ordinary Nifty expiry. β = 1 is 1.3 SE from β̂, so a reader who prefers the unit-beta assumption gets one trade, on the wrong session for the thesis. X = 1 % and 1.5 % fire nowhere under any β.

---

## 4. Strategy results

Fills are at the **bar close**, on bars that printed volume, on every leg. This is optimistic: it assumes simultaneous execution at the last traded price on all legs, which is exactly what a real multi-leg order violates. All figures below are upper bounds. Costs come from `xman_research.backtest.costs` (BSE exchange transaction charge substituted with NSE's — the stack carries no BSE schedule, and the direction of that error is unknown).

### S1 — sell the wing put, risk-capped by the band

The band is the risk control: the settlement index cannot print below `S_ref × 0.97`, so a short put's worst case is `K − floor` and is known at entry. Only defined on an expiry session, since on a chain with days to run the band bounds today's close and says nothing about tomorrow's gap.

| Session | X | entry | strike | premium | band floor | worst case | reward : risk | net ₹/lot | worst ₹/lot | entry volume |
|---|---|---|---|---|---|---|---|---|---|---|
| 2026-08-27 | 0.25 % | 15:26 | 76,200 PE | 3.80 | 74,925.03 | **1,274.97 pts** | **1 : 335** gross, 1 : 488 net | +52.25 | **−25,447.13** | 1,217,380 |

**No rows at X = 0.5 %, 1 % or 1.5 %** — the trigger never fires. The single exploratory trade wins (the put expired worthless; the implied settlement level of 76,934.15 is within 0.56 points of the official close of 76,933.59), and winning is beside the point: **collecting 3.80 points gross — 2.61 net of cost — against a 1,275-point capped loss is not a strategy, it is a 335 : 1 lottery (488 : 1 after costs) sold at a discount.** One band-limit event inside the corpus's own worst case wipes out 335 winning sessions. The arithmetic is decisive without a backtest and does not improve with a longer sample.

Note the strike: 76,200 is the lowest put that *traded* in the trigger minute, not the lowest listed (75,900). The wing the thesis targets — a **75,000 PE** — is below every strike this corpus carries.

### S2 / S3 — Sensex call spread against the notional-sized opposite Nifty spread

Two strikes wide on each index, so each leg is defined-risk. Nifty size is notional-matched on the **underlying** and beta-scaled, rounded to whole lots: **1 Nifty lot per Sensex lot** on every session here (β × 77,242 × 20 / (24,216 × 65) ≈ 0.89 → 1).

**This is notional-sized, not delta-neutral, and the distinction bites.** Neither spread's delta enters the sizing, and the two spreads do not have equal payoff capacity: the Sensex spread is bounded at 200 × 20 = ₹4,000 per lot, the Nifty spread at 100 × 65 = ₹6,500, so at 1 : 1 the "hedge" carries **1.6×** the capacity of the leg it hedges. On **08-04 that is the entire result** — −₹1,856 of the −₹1,896 gross comes from the Nifty leg alone (an expiring Nifty call spread pinning ITM) against −₹2 on the Sensex leg. That row is a Nifty-expiry artefact, not a cross-index trade. S2 = long Sensex spread / short Nifty when `d < −X`; S3 is the mirror.

| Session | leg | entry | d @entry | Sensex strikes | Nifty strikes | net ₹ @15:35 | net ₹ @15:39 | min leg volume (entry & 15:39 exit) |
|---|---|---|---|---|---|---|---|---|
| 2026-08-04 | S2 | 15:26 | −0.26 % | 78400/78600 | 24550/24650 | **−2,116.40** | −2,176.40 | 24,700 |
| 2026-08-06 | S3 | 15:23 | +0.34 % | 79200/79400 | 24700/24800 | **+1,431.76** | +1,468.51 | 17,080 |
| 2026-08-13 | S3 | 15:29 | +0.26 % | 78100/78300 | 24450/24550 | **−219.46** | −294.21 | 6,020 |
| **2026-08-27** | S2 | 15:26 | −0.28 % | 76900/77100 | 24200/24300 | **−902.66** | −980.41 | 26,300 |
| **Total** | | | | | | **−1,806.76** | **−1,982.51** | |

**No rows at X = 0.5 %, 1 % or 1.5 %.** At the exploratory threshold: **1 winner, 3 losers, negative in aggregate at both exit times, and the dislocated session is among the losers.** Costs are ~₹220 per round trip. On **08-13** the cost *is* the result (gross −₹9.75 against ₹209.71 of cost); on 08-27 cost is 24 % of the loss.

**A structural obstacle the table cannot show.** The brief allows a settlement exit on expiry days. A *paired* trade cannot take one: Sensex expires Thursday and Nifty Tuesday, so on every session in this corpus at most one leg is expiring. Holding to settlement means holding an unhedged overnight position in the other index — a different trade with different risk, not this one.

### S3 mirror, stated plainly

S3 is not a separate finding: it is the same estimator with the sign flipped, and it fires on 08-06 and 08-13 — both Sensex expiry sessions with a positive pin, neither dislocated. Its one winner (08-06, +₹1,432) is the corpus's single profitable trade and rests on one session.

---

## 5. The band against the ladder — why the wing test returns nothing

Each constituent's auction price is confined to ±3 % of its 15:00–15:15 VWAP, so an index of bounded constituents is bounded by ±3 % of the index computed on those VWAP references. That reference index is not in this corpus; the floor and ceiling here use the 15:14 implied level, a close proxy and not the same number. The bound is approximate at the edges — and the margin below is more than an order of magnitude, so the conclusion survives the approximation.

| | 2026-08-27 | range over all 16 sessions |
|---|---|---|
| Reference (15:14 implied) | 77,242.30 | — |
| Band floor (−3 %) | **74,925.03** | — |
| Band ceiling (+3 %) | 79,559.57 | — |
| Lowest listed strike | 75,900 (**−1.74 %**) | −1.50 % … **−2.19 %** |
| Highest listed strike | 78,700 (+1.89 %) | +1.06 % … +1.90 % |
| Strikes below floor | **0** | **0 on every session** |
| Strikes above ceiling | **0** | **0 on every session** |
| Structurally overpriced strike-minutes | **0** | **0** |

**Two claims live here, and only one is arithmetic.**

*Arithmetic:* **no listed strike lies outside the band**, on any session. The ladder is ATM±10 at a 100-point step, spanning roughly ±1.3 % of spot when struck and at most ±2.2 % after drift, against a band at ±3 %. So the strongest form of the test — a put *below the floor*, which cannot settle in the money at all and whose every rupee of price is a claim the band will break — has **no candidate instrument in this corpus and never can**.

*Empirical:* **no in-band strike ever traded above its own cap.** An in-band put is capped at `K − floor`, a finite number a price could in principle exceed. The tightest cap anywhere in the corpus is **629.70 points (0.81 % of spot) on 08-25**; on 08-27 the lowest strike's cap is 1,274.97. Nothing arithmetic forbids a print above those — it is economically absurd, which is an empirical statement, and the zero count is its evidence.

The brief also asks for the *volume* on the overpriced strike-minutes: with zero such minutes there is no volume to report, and the 1,217,380 contracts on S1's entry bar are a different quantity that should not stand in for it.

**What was missed, concretely.** The **75,000 PE** reported up ~4,800 % on 08-27 sits **900 points below the lowest listed strike here**. Against the published 15:15 close of 77,182.91 its band floor is 74,867.42, giving it a maximum possible settlement value of **132.58 points**; against this document's 15:14 implied reference the floor is 74,925.03 and the cap is **74.97 points**. **A ~4,800 % rise is not by itself evidence of overpricing.** ₹0.05 → ₹2.45 is ~4,800 % and sits entirely inside a 75–133-point cap. Structural overpricing requires *price > cap*, and this corpus carries **no bar for the 75,000 PE at any minute**, so the claim can be tested neither way. That is the single most important limitation of this analysis: *the test is well-posed, and the data cannot run it where it matters* — the strike where the thesis's mechanism would bite hardest is exactly the one the corpus cannot see.

---

## 6. Corpus defect found while doing this

| Session | Underlying | CE bars | PE bars | Corpus |
|---|---|---|---|---|
| 2026-08-20 | NIFTY | 8,085 | **0** | published |
| 2026-08-21 | NIFTY | 8,085 | **0** | published |
| 2026-08-24 | NIFTY | 8,085 | **0** | published |

Three NIFTY sessions are in the **published** corpus carrying calls only. Put-call parity is impossible on them, which is why this analysis covers 16 sessions and not 19; SENSEX on the same three dates is complete. Any put-based or parity-based study silently loses these sessions rather than failing. This is a publication-gate gap, not a research finding, and belongs in its own issue.

---

## 7. What this analysis cannot see

| Blind spot | Consequence |
|---|---|
| **The indicative index, entirely** | The 2,200-point path the thesis is about exists only in the exchange's CAS dissemination. The vendor carries no indicative series, so `d` measures derivatives-vs-derivatives divergence and never derivatives-vs-indicative. |
| **Every strike outside ATM±10** | The wing that actually moved (75,000 PE) has no bars. Section 5's null is a statement about the ladder, not about the option chain. |
| **The auction itself** | Settlement is on an equilibrium price the feed never observes. Every "settle" figure here is the option-implied level at 15:39, which on 08-27 matched the official close to 0.56 points — good evidence, still a proxy. |
| **Bid/ask, and depth at a price** | No quotes in this corpus. Volume figures are per-minute strike totals, not depth. Every P&L is an upper bound. |
| **The cash leg** | BSE equity minute bars stop at 15:14, so no constituent's auction behaviour — the actual cause — is visible. |

---

## 8. Honesty

- **n = 16 sessions, one dislocated.** Every statement about behaviour *during a dislocation* rests on a single session. There is no dispersion estimate, no hit rate, and no out-of-sample.
- **The zero-trigger result is robust where it counts and marginal elsewhere.** At X = 0.5 % the dislocated session never fires at any β from β̂−SE to 1; 08-04 does fire at β̂+SE and β = 1. "The threshold never fires" is true of the fitted β and one SE below it, not of the whole plausible β range (§3.1).
- **The specified thresholds produce zero trades.** X ∈ {0.5 %, 1 %, 1.5 %} never fire. X = 0.25 % was added post-hoc, after seeing the distribution, purely to obtain trades to score. Its four trades and their −₹1,807 aggregate are an illustration, not an estimate.
- **β is estimated from 31 daily returns** (SE 0.0735, R² 0.8392) and excludes the dislocated session. Closes are each session's last index bar before 16:00, taken only where that bar lands at or after 15:20 — the NIFTY feed carries stub bars hours after the close on some sessions, and the quarantined 08-25 ends at 13:04, which is not a close. Dropping 08-25 makes one pair a two-session return rather than a one-session one; it is a contemporaneous pair either way, so it remains a valid observation of *relative* move. β from one month of daily data is not stable enough to size a real hedge, which is why §3.1 reports the trigger count across β rather than at the point estimate alone.
- **Bar-close fills on every leg** — the optimism is stated above and is not small for a four-legged trade in the last ten minutes of a session.
- **The band bound is approximate**, computed from the 15:14 implied level rather than the unobservable reference-VWAP index. It is used only to establish a margin of more than 10×.
- **Structural overpricing is only defined on expiry sessions** — 08-06, 08-13, 08-27 for Sensex. On a chain with days to run no price can be called structurally too high, because the band does not bound tomorrow's gap.
- **The parity level carries a forward bias on non-expiring chains.** It cancels to first order in the ratio to each index's own 15:14 reference, which is why levels are never compared across underlyings. It does not cancel exactly, and no bound on the residual is established here.
- **BSE exchange transaction charges are substituted with NSE's.** The stack carries no BSE schedule; the direction of the error is unknown.
- **"Closed by 15:35" is peak-to-15:35 within 15:15–15:35 only**, and says nothing about what happened after the derivatives session ended — which, given seven sessions peak in the last four minutes, is where any real reversion would have to live. The corpus ends at 15:39 and cannot follow it.
- **"Median of per-session longest run"** is exactly that — the median across sessions of each session's longest unbroken trigger run. It is not the median length of a run, and it overstates typical persistence if read as one.
- **S2/S3 sizing is notional, not delta-neutral**, and the 08-04 row is dominated by an expiring Nifty leg rather than by any cross-index relationship.
- **The band's reference is a proxy with measurable error.** The 15:14 implied level is 77,242.30 against a published 15:15 close of 77,182.91 — 59 points apart — and the 15:00–15:15 reference-VWAP index is unknown. A 0.1–0.3 % proxy error against the 0.81 % tightest ladder-to-band margin is a factor of **3–8×**, not the order of magnitude an earlier draft of this section claimed. The arithmetic claim survives that comfortably; the empirical one is labelled empirical.
- **The band bound assumes the index is linear in constituent prices with fixed positive intraday weights**, which is what makes a bound on each constituent a bound on the index.
- **`estimate_beta`, `trigger_stats`, `_first_trigger` and the S2/S3 sign convention are not unit-tested.** The tests cover the implied-index construction, the divergence algebra, the closure statistic and the band test; the strategy and trigger numbers rest on code checked by reading and by the §3.1 robustness table agreeing across four βs.
- **`s_chg` / `n_chg` are implied moves, not index moves.** The traded index level does not exist in 15:15–15:39 on either underlying; that is the premise of the whole exercise.

---

## 9. Reproducing

```bash
uv run python research/expiry_cas/cross_index.py \
  --outdir research/expiry_cas/fig/cross_index \
  --out research/expiry_cas/cross_index_output.md
uv run pytest tests/test_cross_index.py -q
```

Generated tables: `cross_index_output.md`. Figures: `fig/cross_index/` — `divergence_paths.png` (all 16 sessions, 08-27 in red, with the ±0.5 % trigger lines that are never touched), `divergence_2026-08-27.png` (implied Sensex against Nifty-implied fair, with the published indicative low marked for scale), `band_vs_ladder.png` (ladder extent against the ±3 % band on every session).
