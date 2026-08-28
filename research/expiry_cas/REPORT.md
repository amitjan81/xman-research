# Expiry-day last 30 minutes and the closing-auction window — Nifty pass

**Scope.** The owner asked about **Sensex on Thursday 2026-08-27**, its weekly expiry, and
about wild fluctuation during the closing auction. Sensex is not in the corpus yet, so this
pass answers the same questions for **Nifty**, whose weekly expiry moved to **Tuesday** in
September 2025. 2026-08-27 was therefore a *normal* Nifty session; the Nifty expiry nearest
the owner's date is **2026-08-25**, and it is quarantined. Every script here takes
`--underlying`, so the Sensex pass re-runs them unchanged and appends rows to these tables.

**Headline, and it contradicts the hypothesis for Nifty.** On Nifty expiry sessions the
closing-auction window is the *calmest and best-arbitraged* part of the day, not the wildest.
The underlying moves **0.20–0.85 points** across the whole of 15:30–15:39, and cross-strike
arbitrage residuals collapse to a median of **0.15–0.30 points with zero occurrences above
round-trip cost** on three of the four sessions. The genuine volatility is in **15:00–15:29**,
continuous trading, peaking around 15:14–15:28 — and that is also where the residuals are.

---

## 1. Sessions and their status

`n = 8` expiry sessions, which split across a regime boundary that matters more than the
sample size: NSE's Closing Auction Session went live **2026-08-03**. Before it, expiring
options print **no post-close bars at all** — there is no auction window to analyse. So the
owner's question has an effective sample of **three clean post-CAS expiries plus one
quarantined one**, not eight.

| Date | Status | Regime | Expiry session | Auction window exists |
|---|---|---|---|---|
| 2026-07-07 | published | pre-CAS | yes | no |
| 2026-07-14 | published | pre-CAS | yes | no |
| 2026-07-21 | published | pre-CAS | yes | no |
| 2026-07-28 | published | pre-CAS | yes | no |
| 2026-08-04 | published | post-CAS | yes | yes |
| 2026-08-11 | published | post-CAS | yes | yes |
| 2026-08-18 | published | post-CAS | yes | yes |
| **2026-08-25** | **quarantined** (spot coverage 61.3% < 95%) | post-CAS | yes | yes |
| 2026-08-26 | published | post-CAS | no — control | yes |
| 2026-08-27 | published | post-CAS | no — control | yes |
| 2026-08-28 | published | post-CAS | no — control | yes |

On **2026-08-25** the index symbol stops printing at **13:04** — there is no index bar
anywhere in the final half hour. Its underlying path is recovered entirely from put-call
parity across the option chain.

---

## 2. Per-session summary

Ranges and moves in index points. Time value (TV) is the ATM straddle less intrinsic, at the
strike that was ATM at 15:00.

| Date | Status | 15:00–15:29 range | 15:30–15:39 range | Largest 1-min move | TV 15:00 | TV 15:29 | TV 15:39 |
|---|---|---|---|---|---|---|---|
| 2026-07-07 | published | 36.15 | — | −10.15 @ 15:05 | 4.30 | −0.05 | −0.05 |
| 2026-07-14 | published | 23.50 | — | +10.30 @ 15:05 | 14.65 | −0.05 | −0.05 |
| 2026-07-21 | published | 19.60 | — | −11.90 @ 15:04 | 22.90 | 0.10 | 0.10 |
| 2026-07-28 | published | 38.00 | — | +9.80 @ 15:19 | 16.50 | 0.20 | 0.20 |
| 2026-08-04 | published | **145.25** | **0.85** | **+65.40 @ 15:28** | 71.55 | −0.50 | −0.45 |
| 2026-08-11 | published | 52.65 | 0.20 | +28.80 @ 15:22 | 27.70 | 0.10 | 0.12 |
| 2026-08-18 | published | 99.50 | 0.20 | −22.30 @ 15:14 | 37.95 | 0.30 | −0.40 |
| 2026-08-25 | **quarantined** | 80.25 | 0.35 | +30.05 @ 15:20 | 44.88 | 0.10 | −0.33 |
| 2026-08-26 | published — control | 169.60 | 14.48 * | −136.75 @ 15:28 | 204.25 | 176.20 | 190.35 |
| 2026-08-27 | published — control | 137.95 | 18.78 * | +91.50 @ 15:29 | 205.90 | 170.00 | 179.90 |
| 2026-08-28 | published — control | 135.60 | 18.75 * | +78.00 @ 15:15 | 176.65 | 132.50 | 72.20 |

\* **The control auction-window ranges are not comparable to the expiry ones and must not be
read as "controls move more".** On an expiry session parity spot is exact (T→0); on a control
session the chain has days left, so the recovered level carries a forward/basis term plus vega
noise from every leg. The 14–19 points is mostly estimation noise. The controls are a valid
control for **15:00–15:29 only**.

**Reading it.** The auction window on expiry day is flat to within a point. The one session
with genuinely wild movement, **2026-08-04 (145-point range, a 65-point single minute)**, had
that move at **15:28 — two minutes before the auction window opened.**

TV at 15:29 and 15:39 sits at ~0 on every expiry session. That is **a consistency check, not
a finding**: parity spot forces straddle = |S−K| at expiry, so TV→0 is partly definitional.
**TV at 15:00 is the real measurement** — 4–23 points pre-CAS versus 28–72 points post-CAS.

---

## 3. Arbitrage residuals

Three relation families, and the distinction between them is the whole credibility of this
section:

- **Box, vertical, butterfly — spot-free.** They involve only option prices. On a session
  whose underlying is unobservable these are the *only* trustworthy mispricing evidence.
- **Put-call parity — needs a spot.** Where the spot is itself parity-derived, the residual is
  zero by construction at the anchor strike (excluded mechanically) and elsewhere can only
  measure *disagreement between strikes* — never a mispricing common to the whole chain.

All rows below are the **traded-bars gate**: every leg printed volume in that same minute. A
zero-volume bar carries a forward-filled close, and differencing a stale close against a live
one manufactures a residual that is pure staleness. Cost threshold is a 4-leg round trip on
the repo's statutory stack (`src/xman_research/backtest/costs.py`), ≈ **1.8–2.5 points**.

### Box spread — the spot-free headline

| Date | Window | n | median abs | p95 | max | n > cost | % > cost | persistent (≥2 min) | median volume of those |
|---|---|---|---|---|---|---|---|---|---|
| 2026-08-04 | 15:00–15:29 | 595 | 0.65 | 4.72 | 32.25 | 117 | 19.7% | 38 | 2,925 |
| 2026-08-04 | **15:30–15:39** | 181 | **0.30** | 1.65 | 4.55 | **3** | **1.7%** | **0** | 585 |
| 2026-08-11 | 15:00–15:29 | 586 | 0.60 | 4.24 | 18.45 | 99 | 16.9% | 44 | 650 |
| 2026-08-11 | **15:30–15:39** | 183 | **0.15** | 0.85 | 1.65 | **0** | **0.0%** | **0** | — |
| 2026-08-18 | 15:00–15:29 | 579 | 0.70 | 4.10 | 15.30 | 118 | 20.4% | 28 | 3,868 |
| 2026-08-18 | **15:30–15:39** | 172 | **0.15** | 0.65 | 1.40 | **0** | **0.0%** | **0** | — |
| 2026-08-25 Q | 15:00–15:29 | 579 | 0.70 | 4.65 | 20.25 | 110 | 19.0% | 35 | 2,535 |
| 2026-08-25 Q | **15:30–15:39** | 173 | **0.20** | 0.97 | 1.80 | **0** | **0.0%** | **0** | — |
| pre-CAS ×4 | 15:00–15:29 | 569–596 | 0.35–0.45 | 1.98–2.50 | 4.80–33.80 | 37–56 | 6.5–9.6% | 5–17 | 423–1,593 |
| controls ×3 | 15:30–15:39 | 190–197 | 0.60–0.80 | 2.98–4.11 | 11.95–45.10 | 13–23 | 6.8–11.7% | 0–3 | 325–780 |

**The auction window is where mispricing goes to die on expiry day.** Every strike settles to
pure intrinsic and they all agree. The controls, whose chain does *not* expire, keep their
residuals in the auction window — confirming the collapse is an expiry effect, not a
data-coverage artefact of the window itself.

### Put-call parity, butterfly, vertical

| Relation | Post-CAS expiry, 15:00–15:29 | Post-CAS expiry, 15:30–15:39 |
|---|---|---|
| parity (anchor excluded) | median 0.50–0.58, **11.7–15.0% > cost**, 18–31 persistent | median 0.22–0.35, **0–1.1% > cost**, **0 persistent** |
| butterfly CE | median 0.00, 7.6–8.4% > cost, 5–16 persistent | median 0.00, 0.6–3.7% > cost, 0–2 persistent |
| vertical PE | median 0.00, 3.0–4.1% > cost, 2–6 persistent | median 0.00, 0–0.6% > cost, 0 persistent |

**A control-session artefact worth naming.** Control parity residuals in 15:00–15:29 have a
median of **65–88 points**. That is not arbitrage — it is the forward/basis term
`K(1−e^{−rT})` plus the Sep-future basis, which parity attributes to the residual whenever the
chain has time left. It is exactly why no parity-based conclusion in this report is drawn from
a non-expiring chain, and it is a useful calibration of how badly this relation misleads when
T > 0.

---

## 4. Candidate strategies

| # | Strategy | Evidence (per lot, lot = 65) | Hit rate | Worst session | Verdict |
|---|---|---|---|---|---|
| a | **Box/parity arb**, residual > cost, ≥2-min persistence | 28–44 persistent box occurrences per post-CAS expiry, **all in 15:00–15:29**, median volume 650–3,868 contracts. **Zero** in the auction window. | n/a | n/a | **Not from these bars.** See below. |
| b | **Sell ATM straddle 15:00 → settlement** | pre-CAS: −1,983 / +1,587 / +727 / −947. post-CAS: **−4,654 / +3,381 / −3,440 / −2,240** | **2 / 8** | **−₹4,654** (08-04) | **No.** Loses in aggregate; short gamma into a moving spot. |
| c | **Buy 2-strike OTM strangle 15:25 → 15:39** | post-CAS: **+1,726** / −140 / −750 / −196. Pre-CAS all ≈ −₹94 (no auction window; wings already at ₹0.10). | **1 / 4** | −₹750 (08-18) | **No, as stated.** Sum is positive only via 08-04, whose move happened at 15:28 — *before* the window. |
| d | **Fade the first 15:30 auction print** | Jump from continuous close: **1.50 / −0.30 / −0.35 / −0.02 points**. Retracement is a fraction of that. | n/a | n/a | **No.** There is nothing to fade — the jump is under two points. |
| e | **Delta-hedged gamma scalp of ATM straddle** | — | — | — | **Not evaluable.** The index is not tradeable, index futures are not in the corpus, and the bars carry no bid/ask. |

**On (a), the one the owner's hypothesis pointed at.** The residuals are real in the data and
they are *not* in the auction window. Even for 15:00–15:29 this report does **not** claim a
tradeable arb: those minutes are exactly when the market moves fastest, which is when
non-simultaneous prints across four legs most easily manufacture a bar-close residual that no
one could have traded. Two-minute persistence is weak evidence, and the volume figures are
per-minute totals for the strike, not depth available at one price. Verdict: **worth a proper
quote-level study, not a backtest on these bars.**

**The direction that did survive.** The clearest repeatable structure is the **premium crush
into 15:29**, not the auction: post-CAS ATM time value falls from **28–72 points at 15:00 to
≈0 at 15:29**. Strategy (b) fails to harvest it because a fixed ATM strike is short gamma
against a 50–145 point range. A **delta-neutral or strike-following** version of (b), or an
iron-fly with bought wings capping the 08-04 loss, is the one candidate worth a real backtest.

---

## 5. Honesty section

- **Sample size.** Eight expiry sessions, but only **three published post-CAS** ones (08-04,
  08-11, 08-18) plus one quarantined (08-25) have an auction window at all. Every
  auction-window conclusion rests on **n = 3 clean sessions**. Pre-CAS sessions cannot speak to
  the auction question — they have no post-close bars.
- **Quarantine.** 2026-08-25 failed publication at 61.3% spot coverage and is labelled in every
  table. Its index feed dies at 13:04 and its entire final-window path is parity-derived. It is
  shown because it is the Nifty expiry nearest the owner's date, not because it is sound.
- **Spot freeze.** The index feed holds one value for 23 of the 40 minutes in 15:00–15:39 on
  every post-CAS session, and exactly one value across all of 15:30–15:39. Differencing that
  series reports a 12-minute catch-up jump as a one-minute move. This report therefore uses
  **parity spot on expiry sessions** (exact at T→0, and it prints every minute). An earlier
  cut of these tables used the raw feed and reported a spurious 65.75-point "one-minute move"
  at 15:28 on 08-04 that was an artefact of the freeze.
- **Parity circularity.** The parity spot is a cross-strike median; the strike that anchors it
  is excluded from residual statistics mechanically, because its residual is zero by
  construction. What remains measures cross-strike *disagreement* and **cannot detect a
  mispricing common to every strike**. The box/vertical/butterfly relations carry the load
  precisely because they need no spot.
- **Bar-close fill optimism.** These are OHLC bars with **no bid/ask**. Every residual and every
  strategy P&L assumes a simultaneous fill at the bar close on all legs — the assumption a real
  multi-leg trade violates most. All "capturable" figures are **upper bounds**.
- **Auction prints.** The exchange settles on the auction's equilibrium price. That print is not
  in this corpus; `settlement.py` records the rule as `UNVERIFIED` with neither the SEBI nor the
  NSE circular retrievable, and computes a proxy. Anything here about settlement inherits that.
- **Costs.** The repo's statutory stack, including **exercise STT at 0.125% of intrinsic** on
  held-to-expiry longs. Note that STT-on-sell-premium may be **extrapolated** for older
  sessions, which overcharges and can suppress a real effect rather than invent one.
- **Sensex is pending.** The owner's actual instrument, its actual date, and its Thursday expiry
  are not covered. BSE microstructure, lot size, strike spacing and auction mechanics differ.
  **Nothing in this report should be assumed to transfer.** The scripts are underlying-agnostic
  so the Sensex pass appends rows to these tables rather than rewriting the text.

---

## 6. Reproducing

```bash
uv run python research/expiry_cas/analyze.py --underlying NIFTY \
  --dates 2026-07-07 2026-07-14 2026-07-21 2026-07-28 \
          2026-08-04 2026-08-11 2026-08-18 2026-08-25 \
  --controls 2026-08-26 2026-08-27 2026-08-28
```

Full metric output is committed at `research/expiry_cas/metrics_output.md`. Figures:
`fig/spot_final_window.png`, `fig/atm_time_value.png`, `fig/box_residuals.png`.
