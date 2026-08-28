# Expiry-day last 30 minutes and the closing-auction window — Nifty pass

**Scope — this is the Nifty half of a two-part answer.** The owner asked about **Sensex on Thursday 2026-08-27**, its weekly expiry. **Sensex is now published in the corpus** (32 sessions 2026-07-13..08-27; expiry Thursdays 07-23, 08-06, 08-13, 08-20, 08-27; 07-16 and 07-30 quarantined; strike step 100, lot 20; option bars to 15:39 with the index stopping at 15:29, so its auction-window spot needs the same ATM-parity derivation used here). **The Sensex pass is pending and is dispatched separately** — the tables below carry Nifty rows only, and Sensex rows append to them. This pass answers the same questions for **Nifty**, whose weekly expiry moved to **Tuesday** in September 2025. 2026-08-27 was therefore a *normal* Nifty session; the Nifty expiry nearest the owner's date is **2026-08-25**, and it is quarantined. Every script takes `--underlying`, so the Sensex pass re-runs them unchanged and appends rows.

**Headline, and it contradicts the hypothesis for Nifty.** On Nifty expiry sessions the closing-auction window is the *calmest and best-arbitraged* part of the day, not the wildest. The underlying moves **0.10–1.15 points** across the whole of 15:30–15:39, and cross-strike arbitrage residuals collapse to a median of **0.15–0.30 points with zero occurrences above round-trip cost** on three of the four sessions. The genuine volatility is in **15:00–15:29**, continuous trading, peaking 15:14–15:28.

**A caveat that attaches to the headline itself, not just the details.** If the index settlement value is effectively fixed at 15:30 — the feed prints exactly one value from then on — the auction window's calm is options **converging to an already-known number**, which is close to true by construction. If instead the close is only determined when the constituent auction completes, the calm is a real finding about the auction's indicative price. `settlement.py` records the post-CAS rule as **UNVERIFIED** (neither the SEBI nor the NSE circular was retrievable), so **this report cannot distinguish the two readings.** Read the headline as "the auction window shows no exploitable dislocation", which holds either way, rather than as a claim about market calm.

---

## 1. Sessions and their status

`n = 8` expiry sessions, split by a regime boundary that matters more than the sample size: NSE's Closing Auction Session went live **2026-08-03**. Before it, expiring options print **no post-close bars at all**. The owner's question has an effective sample of **three clean post-CAS expiries plus one quarantined one**, not eight.

| Date | Status | Regime | Expiry session | Auction window |
|---|---|---|---|---|
| 2026-07-07 / 07-14 / 07-21 / 07-28 | published | pre-CAS | yes | **no** |
| 2026-08-04 / 08-11 / 08-18 | published | post-CAS | yes | yes |
| **2026-08-25** | **quarantined** (spot coverage 61.3% < 95%) | post-CAS | yes | yes |
| 2026-08-26 / 08-27 / 08-28 | published | post-CAS | no — control | yes |

On **2026-08-25** the index symbol stops printing at **13:04**; its final-window path is recovered entirely from the option chain.

---

## 2. Per-session summary

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

## 3. Arbitrage residuals

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

## 4. Candidate strategies

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

## 5. Honesty section

- **Sample size.** Only **three published post-CAS** expiries (08-04, 08-11, 08-18) plus one quarantined (08-25) have an auction window. Every auction-window conclusion rests on **n = 3 clean sessions**. Pre-CAS sessions cannot speak to the auction question at all.
- **Quarantine.** 2026-08-25 failed publication at 61.3% spot coverage, is labelled in every table, and its index feed dies at 13:04. It is shown because it is the Nifty expiry nearest the owner's date, not because it is sound.
- **Settlement rule is UNVERIFIED**, and the headline depends on which reading is right — see the note under the headline. This is the largest single caveat in the report.
- **One source per series.** The feed freezes (~23 of 40 minutes post-CAS; a single value across all of 15:30–15:39), and on a non-expiring chain parity sits 65–88 points from it. An earlier cut of this report **spliced the two**, which manufactured a −136.75-point "1-minute move" on 08-26 and inflated control ranges 2–4× (169.60 where the single-source figure is 40.10). Every movement series is now the anchor pair's parity level throughout.
- **The 08-04 feed jump, stated precisely.** The feed's catch-up print at 15:28 was **+151.45** after twelve frozen minutes. Parity attributes **+65.60** of that to 15:28 itself and the rest to 15:24–15:27. The 65.60 in §2 is a real one-minute move; the 151.45 would not have been.
- **Parity circularity.** The movement series is the **anchor pair's** parity level, and the anchor strike is excluded from parity residuals — so the excluded strike really is the one whose residual is zero by construction. An earlier cut used the cross-strike *median* as the level while excluding the anchor, which left the manufactured zeros in (7.6% of rows on 08-04) and biased the residual distribution low.
- **Cross-strike contrasts cannot see common-mode mispricing** — true of box and parity alike (§3).
- **Bar-close fill optimism.** No bid/ask. Every residual and P&L assumes a simultaneous fill at the bar close on all legs. All "capturable" figures are **upper bounds**, and the cost threshold is one-lot.
- **Costs.** The repo's statutory stack. Exercise STT is **0.15% of intrinsic** from 2026-04-01 (every session here is later) and falls on the **long**; a short straddle is assigned, flattens with a BUY, and owes none.
- **Sensex is pending — and it is the owner's actual question.** 2026-08-27, the owner's primary case ("Sensex had wide fluctuation"), is **not** covered by any number in this report. Sensex data is now in the corpus and the pass is dispatched separately. BSE microstructure, lot size (20 vs 65), strike spacing (100 vs 50) and auction mechanics all differ, and Sensex's index bars stop at 15:29 so its auction-window spot is parity-derived throughout. **Nothing in this report should be assumed to transfer**, and in particular the finding that the auction window is calm is a *Nifty* finding — the owner's report of wide Sensex fluctuation is neither confirmed nor refuted here.

---

## 6. Reproducing

```bash
uv run python research/expiry_cas/analyze.py --underlying NIFTY \
  --dates 2026-07-07 2026-07-14 2026-07-21 2026-07-28 \
          2026-08-04 2026-08-11 2026-08-18 2026-08-25 \
  --controls 2026-08-26 2026-08-27 2026-08-28
```

Full output: `research/expiry_cas/metrics_output.md`. Figures: `fig/spot_final_window.png`, `fig/atm_time_value.png`, `fig/box_residuals.png`.
