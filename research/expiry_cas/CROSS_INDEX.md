# Cross-index divergence — does Sensex dislocate against Nifty inside the closing auction?

**The thesis under test** (owner, 2026-08-29): *"Sensex jumped during CAS and option premiums skyrocketed; Nifty, highly correlated, didn't move during CAS, so none of Nifty's premiums moved — which means the Sensex move was going to revert. There is a short-term strategy here."*

**The verdict.** The reversion logic is sound and the microstructure supports it, but the dislocation the thesis is built on **is not in the derivatives market**. On 2026-08-27 the Sensex option-implied index moved **−0.40 %** over 15:14 → 15:39 while Nifty's moved **−0.17 %** — both indices moved, in the same direction, and the entire cross-index asymmetry was **280.60 points (−0.36 %) at its peak**. The published indicative index fell **2,199.72 points (−2.85 %)** over the same window. So the derivatives carried **12.8 %** of the dislocation the thesis assumes was tradeable; the other 87 % existed only in the cash auction's indicative feed, which no traded instrument printed and this corpus does not contain.

Consequences, in order of how much they cost:

1. **The trigger never fires.** Across 16 sessions and 400 session-minutes the largest |d| ever observed is **0.465 %** — below the smallest threshold the brief asked to test. At X = 0.5 %, 1 % and 1.5 % the strategies take **zero trades, on every session, including 08-27**.
2. **At an exploratory X = 0.25 % the trades lose money, and lose it on the dislocated session.** Four sessions fire; the paired spread nets **−₹1,807** across them at a 15:35 exit, and **08-27 itself is a −₹903 loser** because the divergence did not revert — only 31 % of it closed by the end of matching.
3. **The band-bounded short put dies on arithmetic before any backtest.** The deepest put that traded at the 08-27 trigger collected **3.80 points** against a band-bounded worst case of **1,274.97 points** — a reward-to-risk of **1 : 335**.
4. **The structurally-overpriced wing the thesis points at is outside the corpus.** Zero strike-minutes are structurally overpriced, and cannot be: on all 16 sessions the strike ladder reaches at most **−2.19 %** from the reference while the auction band binds at **−3 %**. Every listed strike is inside the band, so no listed option can be capped by it.

**One incidental finding worth acting on separately:** NIFTY 2026-08-20, 08-21 and 08-24 are in the *published* corpus with **8,085 call bars and zero put bars each**. Parity is impossible on them and any put-based study fails silently. See §5.

---

## 1. Method, in one paragraph

Both indices are recovered by put-call parity, `S = C − P + K`, at **one strike per session per underlying**, fixed for the whole session as the strike with the most both-legs-traded minutes over 15:00–15:39. Only minutes where both legs printed volume contribute. Fair value is `S_fair(t) = S_ref × (N_imp(t)/N_ref)^β` with both references at **15:14**, the last minute of continuous cash trading, and `d(t) = S_imp(t) − S_fair(t)`. Divergence is computed **only on minutes live on both indices** — never one side forward-filled to meet the other. Full rationale in the `cross_index.py` module docstring; generated tables in `cross_index_output.md`.

**β = 0.8703** (SE 0.0853), **R² = 0.7763**, n = 32 daily log-return pairs, 2026-07-14 … 2026-08-26, **2026-08-27 excluded** so the estimator is not fitted through the event it is built to detect. β instability is second-order here and is quantified rather than asserted: re-running the whole corpus at **β = 1** moves the 08-27 peak divergence from −280.60 to **−263.60 points**, a 17-point shift against a claimed dislocation of thousands. No conclusion in this document changes sign, magnitude class, or trigger count between the two.

---

## 2. Divergence per session

`d` in Sensex points. Positive = Sensex rich against Nifty-implied fair. `s_chg` / `n_chg` are each index's own implied move 15:14 → 15:39, which is the quantity the owner's thesis is stated in. **Q** = quarantined session.

| Session | S expiry | N expiry | d peak | % | at | d @15:30 | d @15:35 | d @15:39 | reverted by 15:35 | s_chg % | n_chg % |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-08-03 | | | −45.88 | −0.06 | 15:38 | −14.61 | −17.28 | −35.74 | 62.3 % | +0.03 | +0.09 |
| **2026-08-04** | | ✓ | **−365.89** | **−0.46** | 15:39 | −320.45 | −356.71 | −365.89 | 2.5 % | −0.03 | **+0.50** |
| 2026-08-05 | | | −75.18 | −0.10 | 15:15 | −30.87 | −45.65 | −43.72 | 39.3 % | −0.15 | −0.11 |
| 2026-08-06 | ✓ | | +325.28 | +0.41 | 15:24 | +54.66 | +64.88 | +57.55 | 80.1 % | +0.08 | +0.00 |
| 2026-08-07 | | | +22.53 | +0.03 | 15:15 | −0.15 | +10.84 | +21.43 | 51.9 % | +0.01 | −0.02 |
| 2026-08-10 | | | −19.15 | −0.02 | 15:37 | −2.17 | −12.71 | −11.30 | 33.6 % | −0.05 | −0.04 |
| 2026-08-11 | | ✓ | −54.82 | −0.07 | 15:38 | −13.40 | −41.37 | −54.52 | 24.5 % | −0.10 | −0.03 |
| 2026-08-12 | | | +19.69 | +0.03 | 15:27 | +10.37 | +16.63 | +13.84 | 15.5 % | +0.04 | +0.03 |
| 2026-08-13 | ✓ | | +215.95 | +0.28 | 15:38 | +205.30 | +205.66 | +215.92 | 4.8 % | +0.27 | −0.01 |
| 2026-08-14 | | | −18.62 | −0.02 | 15:39 | −3.76 | −4.96 | −18.62 | 73.4 % | −0.04 | −0.02 |
| 2026-08-17 | | | −10.83 | −0.01 | 15:25 | −1.24 | −0.82 | −4.76 | 92.4 % | −0.14 | −0.16 |
| 2026-08-18 | | ✓ | +117.30 | +0.15 | 15:27 | +75.60 | +43.65 | −5.75 | 62.8 % | −0.15 | −0.16 |
| 2026-08-19 | | | −25.59 | −0.03 | 15:39 | −9.92 | −12.26 | −25.59 | 52.1 % | −0.03 | +0.00 |
| 2026-08-25 **Q** | | ✓ | −185.78 | −0.24 | 15:28 | −157.48 | −101.28 | −99.88 | 45.5 % | +0.14 | +0.31 |
| 2026-08-26 | | | −72.19 | −0.09 | 15:29 | −47.25 | −57.30 | −50.73 | 20.6 % | −0.25 | −0.21 |
| **2026-08-27** | ✓ | | **−280.60** | **−0.36** | 15:27 | −227.00 | −193.28 | −195.16 | 31.1 % | **−0.40** | −0.17 |

Every session carries the full **25 of 25** minutes with **zero fallback minutes** — the fixed strike traded every minute of 15:15–15:39 on both indices, on all 16 sessions.

**Three readings.**

- **08-27 is not the extreme session.** The largest divergence in the corpus is **2026-08-04 at −365.89 points**, an ordinary Nifty expiry Tuesday, and it is driven entirely by the Nifty leg (+0.50 % while Sensex was flat) — an expiry pin on the *other* index, not a Sensex dislocation. A live detector keyed on |d| would have ranked the crash day **second**.
- **Divergence does not reliably revert.** Median closure by 15:35 across the four largest sessions is **17.9 %**; on 08-04 and 08-13 essentially none of it closed inside the window. Reversion of the auction dislocation, if it happens, happens *after* the derivatives session ends.
- **Both indices moved on 08-27.** The thesis's "Nifty didn't move" is true of the published Nifty *auction indicative* (−0.31 %) and false of Nifty's traded option-implied index over the same minutes (−0.17 %, against Sensex's −0.40 %). The asymmetry is real but is ~180 points, not ~2,200.

### |d| distribution, all 400 session-minutes

| p50 | p75 | p90 | p95 | max |
|---|---|---|---|---|
| 0.023 % | 0.074 % | 0.228 % | 0.277 % | **0.465 %** |

The 95th percentile of divergence is smaller than the smallest threshold the brief asked to test.

---

## 3. Trigger statistics

|d| ≥ X, over 16 sessions / 400 minutes:

| X | sessions fired | trigger minutes | median run | median % closed by 15:35 | sessions |
|---|---|---|---|---|---|
| **0.25 %** *(exploratory, post-hoc)* | 4 / 16 | 37 | 10.5 min | 17.9 % | 08-04, 08-06, 08-13, **08-27** |
| **0.50 %** | **0** / 16 | 0 | — | — | — |
| **1.00 %** | **0** / 16 | 0 | — | — | — |
| **1.50 %** | **0** / 16 | 0 | — | — | — |

X = 0.25 % is **not** one of the thresholds the brief specified. It was added after seeing that the specified ones never fire, so every number derived from it is post-hoc and carries no inferential weight — it exists to give the strategies trades to score and to price the false triggers. **Three of its four firings are on non-dislocated sessions**: the false-trigger rate at the only threshold that fires at all is 75 %.

---

## 4. Strategy results

Fills are at the **bar close**, on bars that printed volume, on every leg. This is optimistic: it assumes simultaneous execution at the last traded price on all legs, which is exactly what a real multi-leg order violates. All figures below are upper bounds. Costs come from `xman_research.backtest.costs` (BSE exchange transaction charge substituted with NSE's — the stack carries no BSE schedule, and the direction of that error is unknown).

### S1 — sell the wing put, risk-capped by the band

The band is the risk control: the settlement index cannot print below `S_ref × 0.97`, so a short put's worst case is `K − floor` and is known at entry. Only defined on an expiry session, since on a chain with days to run the band bounds today's close and says nothing about tomorrow's gap.

| Session | X | entry | strike | premium | band floor | worst case | reward : risk | net ₹/lot | worst ₹/lot | entry volume |
|---|---|---|---|---|---|---|---|---|---|---|
| 2026-08-27 | 0.25 % | 15:26 | 76,200 PE | 3.80 | 74,925.03 | **1,274.97 pts** | **1 : 335** | +52.25 | **−25,447.13** | 1,217,380 |

**No rows at X = 0.5 %, 1 % or 1.5 %** — the trigger never fires. The single exploratory trade wins (the put expired worthless; the implied settlement level of 76,934.15 is within 0.56 points of the official close of 76,933.59), and winning is beside the point: **collecting 3.80 points against a 1,275-point capped loss is not a strategy, it is a 335 : 1 lottery sold at a discount.** One band-limit event inside the corpus's own worst case wipes out 335 winning sessions. The arithmetic is decisive without a backtest and does not improve with a longer sample.

Note the strike: 76,200 is the lowest put that *traded* in the trigger minute, not the lowest listed (75,900). The wing the thesis targets — a **75,000 PE** — is below every strike this corpus carries.

### S2 / S3 — Sensex call spread against the beta-sized opposite Nifty spread

Two strikes wide on each index, so each leg is defined-risk. Nifty size is the notional-matched, beta-scaled one, rounded to whole lots: **1 Nifty lot per Sensex lot** on every session here (β × 77,242 × 20 / (24,216 × 65) ≈ 0.85 → 1). S2 = long Sensex spread / short Nifty when `d < −X`; S3 is the mirror.

| Session | leg | entry | d @entry | Sensex strikes | Nifty strikes | net ₹ @15:35 | net ₹ @15:39 | min leg volume |
|---|---|---|---|---|---|---|---|---|
| 2026-08-04 | S2 | 15:26 | −0.26 % | 78400/78600 | 24550/24650 | **−2,116.40** | −2,176.40 | 24,700 |
| 2026-08-06 | S3 | 15:23 | +0.34 % | 79200/79400 | 24700/24800 | **+1,431.76** | +1,468.51 | 17,080 |
| 2026-08-13 | S3 | 15:29 | +0.26 % | 78100/78300 | 24450/24550 | **−219.46** | −294.21 | 6,020 |
| **2026-08-27** | S2 | 15:26 | −0.28 % | 76900/77100 | 24200/24300 | **−902.66** | −980.41 | 26,300 |
| **Total** | | | | | | **−1,806.76** | **−1,982.51** | |

**No rows at X = 0.5 %, 1 % or 1.5 %.** At the exploratory threshold: **1 winner, 3 losers, negative in aggregate at both exit times, and the dislocated session is among the losers.** Costs are ~₹220 per round trip against gross moves of a few hundred to ~₹1,900, so on the two small trades the cost is the result.

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

**The null is arithmetic, not empirical.** The ladder is ATM±10 at a 100-point step, so it spans roughly ±1.3 % of spot at the moment it is struck and at most ±2.2 % after the day's drift. The band binds at ±3 %. **No strike this corpus carries can ever be capped by the band, on any session, so the structural-overpricing scan can only ever return zero rows.** It is reported as a null of the test, not evidence that no such option existed.

**What was missed, concretely.** The **75,000 PE** reported up ~4,800 % on 08-27 sits **900 points below the lowest listed strike here**. Against the published 15:15 close of 77,182.91 its band floor is 74,867.42, giving it a maximum possible settlement value of **132.58 points**; against this document's 15:14 implied reference the floor is 74,925.03 and the cap is **74.97 points**. Either way an option that can settle for at most ~75–133 points rose ~4,800 % — which is precisely the structural overpricing the thesis describes, and it is **outside the corpus**. That is the single most important limitation of this analysis: *the test is well-posed, and the data cannot run it where it matters.*

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
- **The specified thresholds produce zero trades.** X ∈ {0.5 %, 1 %, 1.5 %} never fire. X = 0.25 % was added post-hoc, after seeing the distribution, purely to obtain trades to score. Its four trades and their −₹1,807 aggregate are an illustration, not an estimate.
- **β is estimated from ~32 daily returns** (SE 0.0853, R² 0.7763) and excludes the dislocated session. The β = 1 rerun is reported alongside; it changes no conclusion. β from one month of daily data is not stable enough to size a real hedge.
- **Bar-close fills on every leg** — the optimism is stated above and is not small for a four-legged trade in the last ten minutes of a session.
- **The band bound is approximate**, computed from the 15:14 implied level rather than the unobservable reference-VWAP index. It is used only to establish a margin of more than 10×.
- **Structural overpricing is only defined on expiry sessions** — 08-06, 08-13, 08-27 for Sensex. On a chain with days to run no price can be called structurally too high, because the band does not bound tomorrow's gap.
- **The parity level carries a forward bias on non-expiring chains.** It cancels to first order in the ratio to each index's own 15:14 reference, which is why levels are never compared across underlyings. It does not cancel exactly, and no bound on the residual is established here.
- **BSE exchange transaction charges are substituted with NSE's.** The stack carries no BSE schedule; the direction of the error is unknown.
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
