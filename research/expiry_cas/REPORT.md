# Expiry-day last 30 minutes and the closing-auction window — Sensex and Nifty

The owner's ask: *"fetch option chain of Sensex and Nifty for Thursday August 27 (expiry day) especially during last 30 minutes of trading including CAS… such fluctuations seem to offer lot of arb strategy… come up with some strategy to capture these wild swings."*

**2026-08-27 was the Sensex weekly expiry**, so Sensex is the owner's actual case and leads this report. Nifty's weekly expiry has been **Tuesday** since 2025-09-01, so 08-27 was an ordinary Nifty session; the Nifty pass is §2.

---

## Headline — the premise is half right, and the half that is wrong is the half the strategies depend on

**Sensex 2026-08-27 was genuinely wild, and the wildness was over before the auction opened.**

The underlying fell **382.35 points from 15:00 to the close** (77,315.95 → 76,933.60, −0.49%), of which **−325.00 landed inside 15:20–15:29**, including **−194.60 in the single minute 15:25→15:26**. Then, across the whole closing-auction window 15:30–15:39, the underlying moved a **total range of 0.95 points** — 0.0012% — and **every option across the liquid ladder traded at intrinsic to the tick** against the 15:29 level. (Scoped precisely in §1.5: 23 of 42 contracts settle within 0.10 of intrinsic and every out-of-the-money one prints the 0.05 tick, while the deep in-the-money wings drift up to 7.35 points rich on puts and 1.85 cheap on calls at the thinnest volume on the board.)

The owner saw real fluctuation and attributed it to the wrong window. The same shape holds on all four post-CAS Sensex expiries, and it is the same shape the Nifty pass found at roughly three times the point amplitude — because the index is three times higher. Normalised, the two markets are indistinguishable (§3).

**Arbitrage, directly:** on all four post-CAS Sensex expiries the number of box-spread residuals exceeding round-trip cost in 15:30–15:39 is **zero**, with **zero** persistent occurrences. Every one of the five candidate strategies is negative or not evaluable for Sensex, as for Nifty.

**A caveat that attaches to the headline itself.** Options sitting at exact intrinsic through 15:30–15:39 shows the settlement number was *known* by 15:30. It cannot distinguish "the value was fixed at 15:29" from "the auction's indicative price was stable throughout". No bar in this corpus separates those readings, and the settlement rules are **unverified** here — `settlement.py` records NSE's post-CAS rule as UNVERIFIED, and no BSE rule was established (no external sources were consulted for this pass). Read the headline as **"the auction window shows no exploitable dislocation"**, which holds either way, rather than as a claim about market calm.

---

# §1 — Sensex

## 1.1 Sessions and their status

Corpus: `/home/qa/runtime/data/backtest/datasets/dhan/SENSEX/`, 32 sessions 2026-07-13..2026-08-27. Expiry is **Thursday**. The regime boundary matters more than the sample size: **2026-08-03** is the first session in this corpus with post-close bars. Before it, expiring Sensex options print **nothing at or after 15:30**.

| Date | Status | Regime | Expiry session | Auction window |
|---|---|---|---|---|
| 2026-07-16 **Q**, 2026-07-30 **Q** | **quarantined** | pre-CAS | yes | **no** |
| 2026-07-23 | published | pre-CAS | yes | **no** |
| 2026-08-06 / 08-13 / 08-20 / **08-27** | published | post-CAS | yes | yes |
| 2026-08-25 / 08-26 | published | post-CAS | no — control | yes |

**The effective sample for the owner's question is n = 4** published post-CAS expiries. **Q** marks a quarantined session in every table below; both quarantined sessions are pre-CAS and cannot speak to the auction question at all.

Facts held constant: strike step **100**, lot size **20** (read from each session's own refdata), 29 strike-and-type contracts in the file (21 strikes × 2 types survive into the auction window on 08-27), `minute_ts` in microseconds. **The `SENSEX` index symbol stops printing at 15:29 on every session**, so the entire auction window's underlying is derived from the ATM pair by put-call parity, `S = C − P + K`. The feed and the parity series are **never mixed inside one range or difference** — see §4.

## 1.2 Per-session summary

Index points. **The two range columns are different measurements, not a cross-check.**

- `range (parity)` differences the **anchor pair's** parity level. One source, every minute; all 40 minutes present on every post-CAS session.
- `range (feed)` is the index feed's own fresh prints. On post-CAS sessions the feed is fresh only **15:00–15:14 and then a single print at 15:29** (23–24 of 40 minutes stale). Its "range" is therefore mostly **the step down to that one settlement print**, not observed movement: on 08-27 the fresh prints 15:00–15:14 span **84.07** points and the remaining **248.02** of the 332.09 is the gap to the 15:29 print. **Do not read this column as a second estimate of volatility.**

TV is the ATM straddle less intrinsic at the strike ATM at 15:00.

| Date | Status | range 15:00–15:29 (parity) | as % | range (feed) † | range 15:30–15:39 | Largest 1-min | TV 15:00 | TV 15:29 | TV 15:39 |
|---|---|---|---|---|---|---|---|---|---|
| 2026-07-16 **Q** | quarantined | 214.95 | 0.28% | 258.59 | — | −78.40 @ 15:02 | 68.80 | 0.10 | — |
| 2026-07-23 | published | 131.80 | 0.17% | 155.19 | — | +38.10 @ 15:02 | 39.30 | 0.10 | — |
| 2026-07-30 **Q** | quarantined | 280.85 | 0.36% | 293.34 | — | +107.30 @ 15:01 | 31.10 | 0.10 | — |
| 2026-08-06 | published | **474.00** | 0.60% | 245.80 | **0.35** | −180.10 @ 15:25 | 341.00 | 1.80 | 0.10 |
| 2026-08-13 | published | 235.60 | 0.30% | 281.63 | **0.90** | +83.90 @ 15:25 | 82.70 | 0.20 | 0.10 |
| 2026-08-20 | published | 82.85 | 0.11% | 129.73 | **0.25** | −37.70 @ 15:20 | 78.60 | 0.70 | 0.10 |
| **2026-08-27** | published | **468.35** | **0.61%** | 332.09 | **0.95** | **−194.60 @ 15:26** | 73.80 | 0.10 | 0.10 |
| 2026-08-25 | control | 98.00 | 0.13% | 155.47 | 58.90 ‡ | +25.50 @ 15:31 | 309.80 | 237.20 | 195.20 |
| 2026-08-26 | control | 184.10 | 0.24% | 179.83 | 45.50 ‡ | −52.10 @ 15:27 | 196.30 | 315.50 | 313.30 |

† See the caveat above — not an independent volatility estimate on post-CAS sessions.
‡ Control auction ranges are **not comparable** to the expiry ones: parity is exact at T→0 on an expiry chain but a vega-noisy, level-biased proxy on a chain with days left. Both columns are single-source, so the controls are a valid *shape* comparison for 15:00–15:29 only.

**Reading it.** The auction window is flat to **within one point** on every Sensex expiry, against 82.85–474.00 points in the preceding half hour of the same sessions. Per session the range ratio is **1,354× / 262× / 331× / 493×** (08-06 / 08-13 / 08-20 / 08-27). The controls show the half hour is not simply always calm: on a non-expiry day the auction window carries 45–59 points of proxy noise, which is what the *absence* of a pinned settlement looks like.

TV at 15:29/15:39 sits at 0.1–1.8 on every expiry session. That is **a consistency check, not a finding** — parity forces straddle = |S−K| at expiry. **TV at 15:00 is the real measurement** (31.10–341.00). The pre/post gap is not read as a market change here: pre-CAS settlement is a different statistic, so the two are not the same quantity.

**On the pre-CAS sessions.** Parity is damped against the feed on all three (214.95 vs 258.59; 131.80 vs 155.19; 280.85 vs 293.34) — the signature of options pricing an *averaged* settlement rather than an endpoint. **The BSE pre-CAS settlement rule is unverified in this report**, so the damping is stated as observed and not attributed to a specific rule. Pre- and post-CAS are never pooled.

## 1.3 2026-08-27, minute by minute

Anchor strike 77,200; level from the ATM pair's parity. The feed is shown nowhere in this table because it is frozen from 15:15 and is never differenced against parity.

| Minute | Level | Δ1min | | Minute | Level | Δ1min |
|---|---|---|---|---|---|---|
| 15:00 | 77,315.95 | — | | **15:20** | 77,162.45 | **−96.15** |
| 15:05 | 77,263.75 | +1.90 | | 15:21 | 77,181.90 | +19.45 |
| 15:10 | 77,257.35 | +19.25 | | 15:22 | 77,184.45 | +2.55 |
| 15:14 | 77,242.30 | +11.50 | | 15:23 | 77,166.05 | −18.40 |
| 15:15 | 77,260.65 | +18.35 | | **15:24** | 77,094.50 | **−71.55** |
| 15:16 | 77,232.50 | −28.15 | | 15:25 | 77,143.40 | +48.90 |
| 15:17 | 77,267.95 | +35.45 | | **15:26** | **76,948.80** | **−194.60** |
| 15:18 | 77,267.45 | −0.50 | | **15:27** | 76,847.60 | **−101.20** |
| 15:19 | 77,258.60 | −8.85 | | 15:28 | 76,868.50 | +20.90 |
| | | | | **15:29** | **76,933.60** | **+65.10** |
| **15:30** | **76,933.40** | −0.20 | | 15:35 | 76,933.25 | +0.05 |
| 15:31 | 76,933.40 | 0.00 | | 15:36 | 76,933.30 | +0.05 |
| 15:32 | 76,933.65 | +0.25 | | 15:37 | 76,933.55 | +0.25 |
| 15:33 | 76,934.00 | +0.35 | | 15:38 | 76,933.45 | −0.10 |
| 15:34 | 76,933.20 | −0.80 | | 15:39 | 76,934.15 | +0.70 |

**What actually moved, and when.** The first twenty minutes are quiet — 77,316 drifting to 77,259, largest minute −33.60. The session breaks at **15:20 (−96.15)**, steadies three minutes, then sells off hard: **15:24 −71.55, 15:26 −194.60, 15:27 −101.20**, bottoming at 76,847.60 before a two-minute bounce to **76,933.60 at 15:29**. Total 15:20–15:29: **−325.00 points — 85% of the half hour's whole move, in ten minutes.**

**Then it stops dead.** Across 15:30–15:39 the largest single minute is **0.80 points** and the total range is **0.95**. Mean |Δ1min| is **63.88 points** over 15:20–15:29 against **0.275** over 15:30–15:39 — a factor of **232**.

**Two corroborations that the number was already fixed at 15:29.** First, the index feed — which has run a median **−54.71 points** away from the parity level all day (§4) — prints **76,933.59** at 15:29 against a parity level of **76,933.60**: agreement to **0.01 of a point**, after disagreeing by tens of points on every fresh minute before it. The same convergence holds on the other three post-CAS expiries (|feed − parity| at 15:29 = 0.29 / 0.61 / 0.42). Second, the liquid ladder prices at intrinsic to the tick against that number — CE 76900 → 33.45 (intrinsic 33.60), PE 77000 → 66.35 (66.40), PE 77100 → 166.35 (166.40), and every out-of-the-money contract — all calls at 77,000 and above, all puts at 76,900 and below — prints the **0.05** tick.

**The auction window is not empty — it is enormous and it is uniform.** **416 of 420** contract-minutes trade with volume in 15:30–15:39 (21 strikes × 2 types × 10 minutes). The volume field decays monotonically from the 15:30 bar to the 15:39 bar in a ratio of **39.6 : 1**, with **~38% of the window's total in its first minute**. (Only the shape is claimed; the absolute vendor volume figures are left uninterpreted.) A window with very heavy participation, complete price agreement, and nothing to arbitrage — the opposite of the dislocation the strategy thesis needs.

---

## 1.4 Arbitrage residuals

Traded-bars gate throughout: every leg printed volume that minute. **The box residual is `implied(K1) − implied(K2)` and the parity residual is `implied(K) − implied(anchor)`** — both are linear contrasts of the same per-minute implied-spot vector, so **parity is exactly as spot-free as the box, and neither can detect a mispricing common to every strike**. Vertical and butterfly are the genuinely different relations (each uses a single option type).

`persistent` counts consecutive **same-sign** pairs at one strike; a k-minute run contributes k−1. The same-sign condition is the point: a residual flipping ± between adjacent minutes is the signature of prints landing in a different order within each bar.

### Box spread

| Date | Window | n | median abs | p95 | max | cost | n > cost | % > cost | persistent | median vol |
|---|---|---|---|---|---|---|---|---|---|---|
| 2026-07-16 **Q** | 15:00–15:29 | 580 | 1.05 | 6.45 | 22.00 | 5.84 | 38 | 6.55% | 6 | 610 |
| 2026-07-23 | 15:00–15:29 | 590 | 0.90 | 4.90 | 20.00 | 6.17 | 17 | 2.88% | 2 | 220 |
| 2026-07-30 **Q** | 15:00–15:29 | 583 | 1.10 | 6.12 | 17.45 | 5.76 | 32 | 5.49% | 0 | 360 |
| 2026-08-06 | 15:00–15:29 | 600 | 2.45 | 11.91 | 54.25 | 7.79 | 72 | 12.00% | 6 | 4,120 |
| 2026-08-06 | **15:30–15:39** | 197 | **0.40** | 2.12 | 3.55 | 7.79 | **0** | **0.0%** | **0** | — |
| 2026-08-13 | 15:00–15:29 | 589 | 1.45 | 9.09 | 30.30 | 5.92 | 54 | 9.17% | 8 | 490 |
| 2026-08-13 | **15:30–15:39** | 189 | **0.25** | 1.61 | 3.75 | 5.92 | **0** | **0.0%** | **0** | — |
| 2026-08-20 | 15:00–15:29 | 600 | 1.30 | 8.36 | 29.85 | 5.78 | 60 | 10.00% | 6 | 790 |
| 2026-08-20 | **15:30–15:39** | 194 | **0.35** | 2.24 | 4.50 | 5.78 | **0** | **0.0%** | **0** | — |
| **2026-08-27** | 15:00–15:29 | 592 | 1.97 | 18.04 | 54.85 | 6.05 | 116 | **19.59%** | 21 | 27,770 |
| **2026-08-27** | **15:30–15:39** | 195 | **0.35** | 2.12 | 5.75 | 6.05 | **0** | **0.0%** | **0** | — |

**Zero above cost and zero persistent on every post-CAS expiry, in exactly the window the owner asked about.** The residuals are real and they are entirely in continuous trading — and on 08-27, the wildest session, they are the largest of any (19.59% above a 6.05-point threshold).

### Parity, butterfly, vertical — post-CAS expiry sessions, traded bars

| Relation | 15:00–15:29 | 15:30–15:39 |
|---|---|---|
| parity (anchor excluded) | median 1.35–2.45, **9.6–20.1% > cost**, 3–21 persistent | median 0.50–0.65, **0–0.5% > cost**, **0 persistent** |
| butterfly CE | median 0.00, 4.2–6.2% > cost, 4–8 persistent | median 0.00, **0.0% > cost**, **0 persistent** |
| butterfly PE | median 0.00, 2.6–6.7% > cost, 1–6 persistent | median 0.00, 0–0.6% > cost, **0 persistent** |
| vertical CE | median 0.00, 1.7–3.9% > cost, 1–5 persistent | median 0.00, **0.0% > cost**, **0 persistent** |
| vertical PE | median 0.00, 0.5–4.0% > cost, 0–4 persistent | median 0.00, **0.0% > cost**, **0 persistent** |

Every relation agrees, including the two genuinely independent of the parity family: the auction window carries no residual above cost.

**The cost threshold is a per-unit, one-lot figure and is not size-invariant.** It runs **5.78–7.79 points** on Sensex against **1.8–2.5** on Nifty. Decomposing the 4-leg round trip per unit:

| Component | Sensex 08-27 (premium 135.12, lot 20) | Nifty 08-04 (premium 53.10, lot 65) |
|---|---|---|
| brokerage (₹20/order) | **4.000 — 66.1%** | **1.231 — 62.6%** |
| STT | 0.811 — 13.4% | 0.319 — 16.2% |
| GST | 0.768 — 12.7% | 0.239 — 12.2% |
| exercise STT | 0.203 — 3.4% | 0.080 — 4.0% |
| exchange transaction charge | 0.189 — 3.1% | 0.074 — 3.8% |
| SEBI turnover fee | 0.077 — 1.3% | 0.025 — 1.3% |
| **total** | **6.048** | **1.968** |

**The gap is not a market difference, but it is not all brokerage either.** Per-order brokerage is a flat ₹20 spread over 20 units instead of 65, which is **3.25× per unit and accounts for 68% of the 4.08-point gap**. The remaining 1.31 points is STT, GST and exchange charge scaling with an ATM premium that is 2.5× higher (135.12 vs 53.10) — an ad-valorem effect, not a dislocation. The same arithmetic explains the **5.78–7.79 spread within Sensex**: brokerage is a flat 4.000 on every session, so the whole 2-point spread is premium (08-06 carries a 325.12 premium against 08-27's 135.12, and its STT alone is 1.951 against 0.811). Larger orders lower the brokerage share proportionally and every `% > cost` rises accordingly. The threshold is applied strictly (`> cost`, not `≥`).

**Costs, and the one substitution made.** The repo's statutory stack (`src/xman_research/backtest/costs.py`) carries no BSE-specific transaction-charge schedule, so **`nse.transaction_charge.options` is used for the BSE legs**. That component is **3.1% of the Sensex threshold (0.19 points, rising to 0.46 on the highest-premium session)**, so the substitution moves the threshold by a fraction of a point; **the direction of the error is unknown**, since BSE's own rate is not established here. STT, exercise STT (0.15% of intrinsic from 2026-04-01), stamp duty and the SEBI turnover fee are statutory and exchange-independent; GST is levied on brokerage plus the exchange charge plus the SEBI fee, so it carries a small share of the same uncertainty.

**The threshold is conservative in one respect that is not corrected here.** `roundtrip_cost_points` books all four opening legs as `Side.SELL`, so premium STT (sell-side only) is charged on the two legs a box actually buys, and buy-side stamp duty on none. That overstates the Sensex 08-27 threshold by ≈0.4 points (≈7%). Overstating the threshold can only *hide* a residual above cost, never manufacture one, so it cannot flatter the "zero above cost in the auction window" result.

## 1.5 The per-strike "wild swings" — lottery and crush, 15:25 → 15:39

This is where the owner's visual impression comes from, and it is worth separating from the underlying's behaviour.

| Date | contracts | median return | to zero (≤ −95%) | best | multibag (≥ +100%) |
|---|---|---|---|---|---|
| 2026-08-06 | 38 | **−87.15%** | **50.0%** | +19.35% | 0.0% |
| 2026-08-13 | 38 | −58.72% | 10.5% | **+515.00%** | 5.3% |
| 2026-08-20 | 42 | −62.09% | 19.1% | +46.74% | 0.0% |
| **2026-08-27** | 36 | **−92.64%** | **50.0%** | **+116.46%** | 5.6% |

**08-27 in full** (15:25 → 15:39, settlement 76,933.60):

| CE strike | 15:25 → 15:39 (vs intrinsic) | | PE strike | 15:25 → 15:39 (vs intrinsic) |
|---|---|---|---|---|
| 76200 | 952.20 → 732.75 (−23%, −0.85) | | 76200–76900 | 4.8–30.2 → **0.05 (−99 to −100%)** |
| 76500 | 650.10 → 432.80 (−33%, −0.80) | | 77000 | 52.40 → 66.35 (**+27%**, −0.05) |
| 76800 | 347.20 → 133.30 (−62%, −0.30) | | **77100** | 76.80 → 166.35 (**+116%**, −0.05) |
| 76900 | 269.90 → 33.45 (−88%, −0.15) | | **77200** | 126.30 → 265.90 (**+110%**, −0.50) |
| **77000–77900** | 182.3–2.1 → **0.05 (−98 to −100%)** | | 77500 | 365.90 → 568.55 (+55%, **+2.15**) |
| | | | **77800** | 665.90 → 873.75 (+31%, **+7.35**) |

**Half the ladder went to the 0.05 tick and two strikes more than doubled, in fourteen minutes.** That is the "wild swing" the owner saw. It is **neither volatility nor arbitrage** — it is the deterministic collapse of every option to |S−K| against a settlement value already determined by 15:29.

**How exact is "exact intrinsic"? Precisely this exact.** Across the 42 contracts trading at 15:39, **23 settle within 0.10 of intrinsic** and every out-of-the-money one prints the 0.05 tick. The exceptions are the **deep in-the-money wings**, which drift **rich on puts** (+7.35 at PE 77800, +5.25 at PE 77900, +2.15 at PE 77500) and **cheap on calls** (−1.85 at CE 76000, −1.05 at CE 75900) — the thinnest contracts on the board, ~300+ points from the money. That drift is the **single** auction-window parity residual above cost on 08-27 (max_abs 7.85, n_over_cost 1 of 196, **0 persistent**). So the honest form of the claim is: **intrinsic to the tick across the liquid ladder, with one non-persistent deep-ITM residual above cost in 200 strike-minutes** — which still leaves nothing to trade, since it neither repeats nor appears at a strike anyone is quoting size in.

## 1.6 Candidate strategies, scored on Sensex

Every figure is a **single-path point estimate** at n ≤ 4. There is no dispersion estimate, and where one session determines a sign it is named.

| # | Strategy | Sensex evidence (₹/lot, lot = 20) | Hit rate | Worst | Verdict |
|---|---|---|---|---|---|
| a | Box/parity arb > cost, ≥2-min same-sign persistence | **0 above cost and 0 persistent in 15:30–15:39 on all four** post-CAS expiries; 6 / 8 / 6 / 21 persistent box pairs in 15:00–15:29 | n/a | n/a | **No** — nothing in the window asked about |
| b | Sell ATM straddle 15:00 → settlement | **post-CAS +5,337 / −2,612 / +1,572 / −1,578** (sum **+2,719**) — pre-CAS shown separately below, never pooled | **2 / 4** post-CAS | **−₹2,612** (08-13) | **No** — see below |
| c | Buy 2-strike OTM strangle 15:25 → 15:39 | post-CAS **−3,967 / +1,235 / −444 / −73** (sum **−₹3,249**) | **1 / 4** | −₹3,967 | **No** |
| d | Fade the first 15:30 auction print | expiry jumps **−0.55 / −0.20 / +0.60 / −0.20** points | n/a | n/a | **No** — sub-point; nothing to fade |
| e | Delta-hedged gamma scalp | — | — | — | **Not evaluable** — index untradeable, no futures in corpus, no bid/ask |

**On (b), and why the positive post-CAS sum is not a result.** The whole post-CAS sign rests on **08-06's +₹5,337**; drop that session and the remaining three are **−₹2,618**. 08-06 is also the largest-range session (474.00 points) and carries a 15:00 ATM straddle of **424.55** with **341.00** of time value — 0.43% of spot, four times the other three (0.09–0.11%). That entry is **not** a staleness artefact: the anchor pair's 15:00 bar traded on both legs (CE 1,203,300 / PE 1,653,640 units), so the premium is real, and genuinely exceptional. A short straddle remains short gamma into a half hour that ranges 83–474 points.

**Pre-CAS is reported separately and never pooled into the above:** 2026-07-16 **Q** −₹2,619, 2026-07-23 −₹268, 2026-07-30 **Q** −₹3,152 (0 / 3). A 15:00→settlement straddle is paid out *by* the settlement statistic, and the pre-CAS statistic is a different one (§1.2), so a seven-session sum or hit rate would cross exactly the regime boundary this report refuses to cross elsewhere. Two of those three sessions are quarantined besides.

**On (c), the wings are not always wings.** Strikes are `15:00-ATM ± 2`, and the underlying moves before 15:25. Spot at 15:25 against the two wing strikes: on **08-06 the call wing was ITM by 53 points** (entry premium 193.00 — a directional ATM buy, not a lottery ticket, and it is the −₹3,967 loss); on 08-13 the call wing was OTM by only 40; **08-20 and 08-27 were genuinely OTM** (by 322/78 and 257/143). The verdict survives on all four, but only two of the four tested what the description says.

**What survives on Sensex, as on Nifty.** The one repeatable structure is the **premium crush into 15:29** — post-CAS ATM time value falls from 73.80–341.00 points at 15:00 to ≈0.1–1.8. Strategy (b) fails to harvest it only because a *fixed* ATM strike is short gamma. A **delta-neutral or strike-following** variant, or an iron-fly capping the 08-06/08-27 tail, is the one candidate worth a real backtest. That is a claim about 15:00–15:29, not about the auction window.

**A mechanism the bars are consistent with.** Exercise STT falls on the **long** at 0.15% of intrinsic, so an ITM long has a direct incentive to sell at intrinsic in 15:30–15:39 rather than be exercised — which would explain both the very heavy auction-window volume (416/420 contract-minutes trading) and the exact-intrinsic pin. **A hypothesis the corpus is consistent with, not a tested finding.**

---

# §2 — Nifty

Nifty's weekly expiry moved to **Tuesday** in September 2025, so 2026-08-27 was an ordinary Nifty session and the Nifty expiry nearest the owner's date is **2026-08-25**, which is quarantined.

**Same conclusion, reached independently.** On Nifty expiry sessions the auction window moves **0.10–1.15 points** and cross-strike residuals collapse to a median of 0.15–0.30 with **zero occurrences above cost** on three of four sessions. The genuine volatility is 15:00–15:29, peaking 15:14–15:28. The one session with a wild move, **2026-08-04 (147.05-point range, +65.60 in one minute)**, had it at **15:28 — two minutes before the auction window opened**.

## 2.1 Sessions and their status

`n = 8` expiry sessions, split by a regime boundary that matters more than the sample size: **2026-08-03** is the first session in this corpus with post-close bars. Before it, expiring options print **no post-close bars at all**. (No external source was consulted for a go-live date; this is what the bars show.) The owner's question has an effective sample of **three clean post-CAS expiries plus one quarantined one**, not eight.

| Date | Status | Regime | Expiry session | Auction window |
|---|---|---|---|---|
| 2026-07-07 / 07-14 / 07-21 / 07-28 | published | pre-CAS | yes | **no** |
| 2026-08-04 / 08-11 / 08-18 | published | post-CAS | yes | yes |
| **2026-08-25** | **quarantined** (spot coverage 61.3% < 95%) | post-CAS | yes | yes |
| 2026-08-26 / 08-27 / 08-28 | published | post-CAS | no — control | yes |

On **2026-08-25** the index symbol stops printing at **13:04**; its final-window path is recovered entirely from the option chain.

---

## 2.2 Per-session summary

Index points. **Two underlying ranges are shown and they are different measurements, not a cross-check.** `range (parity)` differences the anchor pair's put–call parity level — one source, every minute. `range (feed)` is the index feed's own fresh prints. On **pre-CAS** sessions options priced against the expected 15:00–15:30 *average*, so parity tracks a damped blend while the feed tracks the index; they legitimately disagree (07-07: 36.00 vs 86.25). Time value (TV) is the ATM straddle less intrinsic at the strike ATM at 15:00.

| Date | Status | range 15:00–15:29 (parity) | range (feed) | range 15:30–15:39 | Largest 1-min | TV 15:00 | TV 15:29 | TV 15:39 |
|---|---|---|---|---|---|---|---|---|
| 2026-07-07 | published | 36.00 | 86.25 | — | −11.20 @ 15:05 | 4.50 | 0.10 | — |
| 2026-07-14 | published | 24.00 | 34.25 | — | +10.30 @ 15:05 | 15.40 | 0.10 | — |
| 2026-07-21 | published | 18.65 | 15.35 | — | −11.35 @ 15:04 | 22.50 | 0.10 | — |
| 2026-07-28 | published | 37.55 | 49.45 | — | +10.00 @ 15:19 | 15.50 | 0.10 | — |
| 2026-08-04 | published | **147.05** | 166.05 | **1.15** | **+65.60 @ 15:28** | 71.40 | 0.40 | 0.10 |
| 2026-08-11 | published | 53.60 | 24.75 | 0.10 | +29.55 @ 15:22 | 27.20 | 0.30 | 0.10 |
| 2026-08-18 | published | 100.45 | 73.35 | 0.25 | −22.45 @ 15:14 | 38.40 | 0.30 | 0.10 |
| 2026-08-25 | **quarantined** | 80.10 | 93.30 | 0.25 | +28.65 @ 15:20 | 45.10 | 0.10 | 0.10 |
| 2026-08-26 | control | 40.10 | 82.00 | 15.70 \* | −19.25 @ 15:30 | 155.40 | 176.70 | 189.50 |
| 2026-08-27 | control | 64.50 | 69.60 | 19.15 \* | −18.25 @ 15:20 | 123.00 | 170.30 | 179.90 |
| 2026-08-28 | control | 70.55 | 68.50 | 18.15 \* | +37.35 @ 15:11 | 109.70 | 68.90 | 71.10 |

\* Control auction ranges are **not comparable** to the expiry ones: parity is exact at T→0 on an expiry chain but a vega-noisy, level-biased proxy on a chain with days left. Both windows are now single-source, so the controls are a valid *shape* comparison for 15:00–15:29; the 15:30–15:39 column for controls is dominated by proxy noise.

**Reading it.** Post-CAS **expiry** sessions run 53.60–147.05 in the final half hour against **controls at 40.10–70.55** — expiry days are the wilder ones. The auction window on expiry day is flat to a point. And the one session with genuinely wild movement, **2026-08-04**, had its 65-point minute at **15:28 — two minutes before the auction window opened**.

TV at 15:29/15:39 sits at ~0.1 on every expiry session. That is **a consistency check, not a finding** — parity forces straddle = |S−K| at expiry. **TV at 15:00 is the real measurement**, but the pre/post gap (4–23 vs 27–71) is **largely the settlement rule, not a market change**: a straddle on an *average* over the remaining window carries roughly a third the variance of an endpoint straddle. Do not read it as "post-CAS expiries carry more premium".

---

## 2.3 Arbitrage residuals

**These families are less independent than they look.** The box residual is `implied(K1) − implied(K2)`; the parity residual is `implied(K) − implied(anchor)`. Both are linear contrasts of the *same* per-minute implied-spot vector, so parity is exactly as spot-free as the box — and **neither can detect a mispricing common to every strike**, since a uniform call-rich/put-cheap shift leaves every cross-strike contrast unchanged. **Vertical and butterfly are the genuinely different relations** (each uses a single option type). The earlier framing of box as independent corroboration of parity was wrong.

All rows are the **traded-bars gate**: every leg printed volume that minute. Cost threshold is a 4-leg round trip on the repo's statutory stack, ≈1.8–2.5 points — **a one-lot figure dominated by ₹20/order brokerage**. At 5 lots per order it falls to ≈0.6 points and every `% > cost` roughly triples, so these counts are **not size-invariant**.

`persistent` counts consecutive same-sign pairs at one strike (a k-minute run contributes k−1). The same-sign condition is the point: a residual flipping ± between adjacent minutes is the signature of prints landing in different orders within each bar — the artefact the measure exists to screen out.

### Box spread

| Date | Window | n | median abs | p95 | max | n > cost | % > cost | persistent | median vol |
|---|---|---|---|---|---|---|---|---|---|
| 2026-08-04 | 15:00–15:29 | 595 | 0.65 | 4.72 | 32.25 | 117 | 19.7% | 22 | 2,925 |
| 2026-08-04 | **15:30–15:39** | 181 | **0.30** | 1.65 | 4.55 | **3** | **1.7%** | **0** | 585 |
| 2026-08-11 | 15:00–15:29 | 586 | 0.60 | 4.24 | 18.45 | 99 | 16.9% | 23 | 650 |
| 2026-08-11 | **15:30–15:39** | 183 | **0.15** | 0.85 | 1.65 | **0** | **0.0%** | **0** | — |
| 2026-08-18 | 15:00–15:29 | 579 | 0.70 | 4.10 | 15.30 | 118 | 20.4% | 10 | 3,868 |
| 2026-08-18 | **15:30–15:39** | 172 | **0.15** | 0.65 | 1.40 | **0** | **0.0%** | **0** | — |
| 2026-08-25 Q | 15:00–15:29 | 579 | 0.70 | 4.65 | 20.25 | 110 | 19.0% | 11 | 2,535 |
| 2026-08-25 Q | **15:30–15:39** | 173 | **0.20** | 0.97 | 1.80 | **0** | **0.0%** | **0** | — |

### Parity (anchor excluded), butterfly, vertical

Post-CAS expiry sessions, traded bars. The quarantined 08-25 is included in every range below and is the upper end of the parity 15:00–15:29 figures.

| Relation | 15:00–15:29 | 15:30–15:39 |
|---|---|---|
| parity | median 0.55–0.65, **15.2–19.2% > cost**, 15–18 persistent | median 0.30–0.45, **0–1.1% > cost**, **0 persistent** |
| butterfly CE | median 0.00, 7.0–8.4% > cost, 5–16 persistent | median 0.00, 0.6–3.7% > cost, 0–2 persistent |
| vertical PE | median 0.00, 3.0–4.1% > cost, 2–6 persistent | median 0.00, 0–0.6% > cost, 0 persistent |

**On the control sessions' parity offset.** Control parity residuals in 15:00–15:29 sit **65–88 points** from the feed. This report previously called that the forward/carry term; **that attribution is wrong** — carry on a 6-day, 6.5% basis at 24,300 is ≈26 points, three times smaller, and the offset's own spread (65…136 within one day) is not the near-constant a carry term would be. **The cause is unexplained.** It is stated here as an unexplained offset, and it is why no parity-based conclusion is drawn from a non-expiring chain.

---

## 2.4 Candidate strategies

Every figure below is a **single-path point estimate**. There is no dispersion estimate at n≤4, and strategy (c)'s positive sum is determined entirely by one session.

| # | Strategy | Evidence (₹/lot, lot = 65) | Hit rate | Worst | Verdict |
|---|---|---|---|---|---|
| a | Box/parity arb, > cost, ≥2-min same-sign persistence | 10–23 persistent box pairs per post-CAS expiry, **all in 15:00–15:29**; **zero** in the auction window | n/a | n/a | **Not from these bars** |
| b | Sell ATM straddle 15:00 → settlement | pre: −1,973 / +1,599 / +728 / −952. post: **−4,614 / +3,383 / −3,405 / −2,210**. Sum **−₹7,444** | **3 / 8** | **−₹4,614** (08-04) | **No** — short gamma into a 54–147 pt range |
| c | Buy 2-strike OTM strangle 15:25 → 15:39 | post: **+1,726** / −140 / −750 / −196 | **1 / 4** | −₹750 | **No** — and the 08-04 winner is mislabelled, below |
| d | Fade the first 15:30 auction print | expiry jumps: **1.80 / 0.05 / −0.15 / −0.20 points** | n/a | n/a | **No** — sub-point; nothing to fade |
| e | Delta-hedged gamma scalp | — | — | — | **Not evaluable** — index untradeable, no futures in corpus, no bid/ask |

**On (a).** The residuals are real and they are *not* in the auction window. This report does **not** claim a tradeable arb even for 15:00–15:29: those are the fastest-moving minutes, when non-simultaneous prints across four legs most easily manufacture a bar-close residual nobody could trade. Two-minute persistence is weak evidence, and the volume figures are per-minute strike totals, not depth at one price. **Worth a quote-level study, not a backtest on these bars.**

**On (c) — the description is wrong even though the verdict stands.** Strikes are `15:00-ATM ± 2`, but by 15:25 on 08-04 the underlying had moved ~87 points, so the "OTM" call was at/in the money at entry (premium 36.80). That one winning session is a **directional ATM buy after the move had started**, not a cheap-wings lottery.

**What did survive.** The clearest repeatable structure is the **premium crush into 15:29** — post-CAS ATM time value falls from 27–71 points at 15:00 to ≈0.1. Strategy (b) fails to harvest it only because a *fixed* ATM strike is short gamma. A **delta-neutral or strike-following** variant, or an iron-fly capping the 08-04 tail, is the one candidate worth a real backtest.

**A mechanism worth naming, from the per-strike data.** Over 15:25→15:39 on 08-04, **25% of strikes go to zero** (`ret_min` −99.85%) while the best gains +81.5%; on 08-25 one strike returns +128%. The option-price "wild swings" the owner observed are largely the **deterministic crush of OTM legs**, not underlying volatility. Meanwhile 172–183 of 200 strike-minutes still trade *with volume* in the auction window at intrinsic. Since exercise STT falls on the **long** at 0.15% of intrinsic, an ITM long has a direct incentive to sell at intrinsic in 15:30–15:39 rather than be exercised — which would explain both the volume and the pin. **This is a hypothesis the corpus is consistent with, not a tested finding.**

---

---

# §3 — Does the Sensex auction window differ from Nifty's?

**No. Once the index level is divided out the two are indistinguishable at this sample size, and the auction window is if anything tighter on Sensex.** ("Indistinguishable" is a statement about n = 4 against n = 3–4 with no dispersion estimate — see §4 — not a test.)

| Measure | Sensex | Nifty | Normalised (÷ index level) |
|---|---|---|---|
| Biggest final-half-hour range | 474.00 (08-06) / 468.35 (08-27) | 147.05 (08-04) | **0.60% vs 0.60%** |
| Auction-window range, expiry (widest) | 0.95 | 1.15 | **1.23e-5 vs 4.70e-5 — Sensex 3.8× tighter** |
| Box residual median, 15:00–15:29 | 1.97 (08-27) | 0.65 (08-04) | **2.55e-5 vs 2.66e-5** |
| Box residual median, auction | 0.35 | 0.30 | **4.53e-6 vs 1.23e-5** |
| Box occurrences > cost, auction | **0 on all 4 sessions** | 3 on one of 4 sessions | — |
| Round-trip cost threshold | 5.78–7.79 pts | 1.8–2.5 pts | lot 20 vs 65 — not a market difference |

**The two figures that look like a Sensex/Nifty difference are both arithmetic.** Sensex box residuals appear 3× Nifty's only because the index is 3× higher — normalised they are **2.55e-5 vs 2.66e-5**. The cost threshold is 3× higher mostly for the reverse reason: **68% of that gap is ₹20/order brokerage** spread over 20 units instead of 65, and the remaining 1.31 points is ad-valorem STT/GST/exchange charge on a 2.5× larger premium (§1.4). **A reader taking the raw point figures at face value would conclude Sensex is three times more dislocated, which is the opposite of what the data says** — in the auction window the Sensex box residual is normalised **2.7× tighter** than Nifty's, with zero occurrences above cost on all four sessions against three on one Nifty session.

**The direction survives every pairing, but "tighter" is a choice of scale.** Auction box medians are 0.40 / 0.25 / 0.35 / 0.35 on Sensex against 0.30 / 0.15 / 0.15 / 0.20 on Nifty; divided by index level that is 3.2–5.2e-6 against 6.1–12.3e-6, so Sensex is tighter on **every** session pairing, not just the two quoted. Two other scales say otherwise and are named rather than buried: **in ticks** both markets quote in 0.05, so the Sensex medians are 5–8 ticks against Nifty's 3–6 — Sensex is *wider*; **relative to its own cost threshold** Sensex is 0.35/6.05 = 5.8% against Nifty's 0.30/1.97 = 15.2% — tighter again. Index level is the right denominator for a *price-error* statistic, because a put-call parity violation is an error in a quantity denominated in index points and scales with the level. Tick count is the right denominator for a *quotation-granularity* question, which is not the question here.

**On BSE auction mechanics.** The bars support one structural statement and no more: on Sensex expiry sessions the index feed's final print at 15:29 agrees with the chain's implied level to **0.01–0.61 points**, after running a median 15–55 points away from it all day, and every option then trades at exact intrinsic against that number for ten minutes on very heavy volume. That is what a **settlement value determined at or before 15:30** looks like from the bars. Whether BSE's rule fixes it at 15:29, or the auction's indicative price simply never moves, is **not distinguishable from this corpus**, and no external source was consulted. Nifty shows the same pattern, so nothing here is a BSE-specific mechanism — the two exchanges' auction windows are not observably different in this data.

---

# §4 — Honesty section

- **Sample size.** Four published post-CAS Sensex expiries and three published post-CAS Nifty ones (08-04, 08-11, 08-18) plus one quarantined Nifty session. Every auction-window conclusion rests on **n = 4** and **n = 3** respectively. Pre-CAS sessions cannot speak to the auction question at all.
- **Quarantine.** Sensex 07-16 and 07-30 are quarantined and labelled **Q** in every table; both are pre-CAS, so neither contributes to an auction-window claim. Nifty 2026-08-25 failed publication at 61.3% spot coverage and its index feed dies at 13:04; it is shown because it is the Nifty expiry nearest the owner's date, not because it is sound.
- **Settlement rules are UNVERIFIED**, and the headline depends on which reading is right — see the note under the headline. `settlement.py` records NSE's post-CAS rule as UNVERIFIED; no BSE rule, pre- or post-CAS, is established here. No external sources were consulted for this pass. This is the largest single caveat in the report.
- **One source per series, always.** The feed freezes (~23–24 of 40 minutes post-CAS on both underlyings; on Sensex the index symbol stops entirely at 15:29), and parity sits tens of points from it. A movement series assembled from whichever source looked better each minute reports that offset as volatility. Every series here is the **anchor pair's parity level** throughout; the feed appears only in its own labelled column and never enters the *movement* series. (Feed and parity are compared as levels in this section and in §1.3 — that is a diagnostic of the offset, not a series anything is differenced along.) An earlier cut of the Nifty pass **spliced the two**, manufacturing a −136.75-point "1-minute move" on 08-26 and inflating control ranges 2–4× (169.60 where the single-source figure is 40.10).
- **The feed/parity offset is unexplained, and it is present on Sensex expiry sessions too.** Median feed − parity over fresh-feed minutes on the four post-CAS Sensex expiries: **−14.93 / −30.08 / −21.78 / −54.71** points, ranging −110 to +43 within a session. Intraday carry on an expiring chain is essentially zero, so **this is not the forward term** — it is the same unexplained offset the Nifty control sessions show, now appearing where the report elsewhere calls parity "exact at T→0". A lag search (`feed.shift(−k)` against parity, k = 0…7) finds **no lag that reduces it**; k = 0 minimises on three of four sessions, so it is a level effect, not a broadcast delay. Consequences: (a) the `range (feed)` column on post-CAS sessions is **not** an independent volatility estimate and is labelled as such; (b) "exact at T→0" holds for the *auction window*, where feed and parity converge to ≤0.61 points and every option is at intrinsic, but **not** for the earlier part of the day. On Nifty controls the same offset runs 65–88 points; an earlier cut attributed it to carry, which is wrong (carry on a 6-day, 6.5% basis at 24,300 is ≈26 points, and the spread of 65…136 within one day is not the near-constant a carry term would be).
- **The 08-04 Nifty feed jump, stated precisely.** The feed's catch-up print at 15:28 was **+151.45** after twelve frozen minutes. Parity attributes **+65.60** to 15:28 itself and the rest to 15:24–15:27. The 65.60 in §2.2 is a real one-minute move; the 151.45 would not have been.
- **Parity circularity.** The movement series is the **anchor pair's** parity level, and the anchor strike is excluded mechanically from parity residuals — so the excluded strike really is the one whose residual is zero by construction. An earlier cut used the cross-strike *median* as the level while excluding the anchor, leaving manufactured zeros in (7.6% of rows on 08-04) and biasing the distribution low. `tests/test_expiry_cas.py` now pins this.
- **Cross-strike contrasts cannot see common-mode mispricing** — true of box and parity alike (§1.4). Vertical and butterfly are the genuinely different relations, and they agree.
- **Bar-close fill optimism.** No bid/ask in this corpus. Every residual and P&L assumes a simultaneous fill at the bar close on all legs, which is exactly what a real spread trade violates. All "capturable" figures are **upper bounds**. Two-minute persistence is weak evidence, and the volume figures are per-minute strike totals, not depth at one price.
- **Cost threshold is one-lot and not size-invariant**, and is dominated by per-order brokerage (§1.4). Exercise STT is **0.15% of intrinsic** from 2026-04-01 (every session here is later) and falls on the **long**; a short straddle is assigned, flattens with a BUY, and owes none. **The BSE exchange transaction charge is substituted with NSE's** — the stack carries no BSE schedule — and the direction of that error is unknown.
- **Single-path point estimates.** No dispersion estimate exists at n ≤ 4. Where one session determines a sign it is named: **08-06** for Sensex strategy (b), **08-04** for Nifty strategy (c).
- **The volume field is uninterpreted.** Only its shape (monotone decay, 39.6:1 across the Sensex 08-27 auction window) and traded-bar counts (416 of 420 contract-minutes) are claimed.
- **Refdata exchange labels.** The Sensex refdata bundles carry `NSE`/`NFO` exchange labels. Cosmetic in this corpus — lot size, strikes and expiry all parse correctly — and ignored.

---

# §5 — Reproducing

```bash
# Sensex — the owner's case
uv run python research/expiry_cas/analyze.py --underlying SENSEX \
  --dates 2026-07-16 2026-07-23 2026-07-30 \
          2026-08-06 2026-08-13 2026-08-20 2026-08-27 \
  --controls 2026-08-25 2026-08-26 \
  --outdir research/expiry_cas/fig/sensex

# Nifty
uv run python research/expiry_cas/analyze.py --underlying NIFTY \
  --dates 2026-07-07 2026-07-14 2026-07-21 2026-07-28 \
          2026-08-04 2026-08-11 2026-08-18 2026-08-25 \
  --controls 2026-08-26 2026-08-27 2026-08-28 \
  --outdir research/expiry_cas/fig/nifty
```

Full output: `metrics_output_sensex.md`, `metrics_output.md`.
Figures: `fig/sensex/` and `fig/nifty/`, each carrying `spot_final_window.png`, `atm_time_value.png`, `minute_moves_log.png`, `box_residuals.png`. **`minute_moves_log.png` is the one worth opening** — |1-minute move| on a log axis, where the 15:30 drop from ~100 points to ~0.3 spans two orders of magnitude. A linear axis renders the whole auction window as the zero line, which is why the rebased-percent figure hides the finding.
