# Backtest — pledge-funded index option overlay (requirements v1.0, sections 3–4)

| Field | Value |
|---|---|
| Question | What return would the document's Nifty weekly iron-condor overlay have produced on ₹1 crore of Portfolio Capital? |
| Underlyings asked for | NIFTY and SENSEX |
| Underlyings answered | **NIFTY only.** SENSEX is not evaluable on the corpus we hold — [§6](#6-sensex-not-evaluable). |
| Data | Dhan 1-minute option chains, `/home/qa/runtime/data/backtest/datasets/dhan/NIFTY`, 1,250 sessions, 2021-06-01 → 2026-09-15 |
| Window run | 2021-09-20 → 2026-09-15 (starts after the corpus's 45-day 2021 capture hole) |
| Costs | The platform's dated statutory stack: STT, exchange transaction charge, SEBI turnover fee, stamp duty, GST, per-order brokerage, plus exercise STT where an option settles |
| Report status | In-sample description of what the rules would have done. No out-of-sample claim is made and no holdout was spent. |

## 1. The answer

**On ₹1 crore of Portfolio Capital, over five years of 1-minute NIFTY option data, the
strategy as specified returned +0.5% in total — about +0.11% a year — net of statutory costs
and slippage. The document's objective is 12% a year.**

It did not lose money either: maximum drawdown was 0.9% of Portfolio Capital against a 10%
objective, so the risk control worked. What the overlay did not do was earn anything. The
finding is not fragile. Across every variant tested — wing construction, the minimum-credit
gate, the margin assumption, the execution assumption — the annualised return sits between
**−0.13% and +0.33%**. Two further diagnostics, which deliberately break the specification
to find the ceiling, reach +0.36% and +0.67%. Nothing in the tested space reaches a
twentieth of the objective.

| Arm | Cycles | Net P&L | Return on PC | Annualised | Max DD | Win rate | Sharpe | Cost ratio |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **A — specified 350pt wings (modelled where unprinted)** | 142 | **50,795** | **0.51%** | **0.11%** | 0.91% | 51.4% | 0.20 | 2.5% |
| B — wings that printed at entry (100–400pt, per side) | 56 | -63,982 | -0.64% | -0.13% | 0.99% | 53.6% | -0.54 | 3.9% |
| C — minimum credit 0.15% of notional | 130 | 90,436 | 0.90% | 0.19% | 0.90% | 51.5% | 0.38 | 2.3% |
| D — minimum credit 0.20% (the document's default) | 49 | 35,839 | 0.36% | 0.07% | 0.78% | 49.0% | 0.20 | 1.7% |
| E — zero slippage | 142 | 159,452 | 1.59% | 0.33% | 0.84% | 54.9% | 0.66 | 2.5% |
| F — slippage ₹0.50 per unit per leg | 142 | -52,423 | -0.52% | -0.11% | 1.38% | 49.3% | -0.21 | 2.5% |
| G — margin = defined risk only (no CA-12 ELM) | 142 | 78,821 | 0.79% | 0.16% | 1.85% | 52.8% | 0.18 | 1.6% |
| H — *diagnostic*: participation caps 5% volume / 2% OI | 142 | 170,715 | 1.71% | 0.36% | 0.87% | 54.9% | 0.63 | 2.2% |
| I — *diagnostic*: H, with ST-20 rolls switched off | 142 | 321,632 | 3.22% | **0.67%** | 0.83% | **74.6%** | 0.89 | 1.5% |

Arm I is the most informative row in the table. Switch off the roll rule and loosen the
execution caps, and the structure behaves exactly as short-condor theory says it should:
**74.6% win rate**, 65% of positions closed at the profit target, median premium capture
0.54, profit factor 1.96. The trade works. It just does not work *enough*.

Two numbers explain why 12% was never reachable at this size, before any question of skill:

- The overlay **collected ₹21.5 lakh of net credit in total** across 142 positions in
  5.3 years — 4.1% of Portfolio Capital per year of gross premium. Twelve per cent a year
  cannot come out of four, whatever the win rate.
- It **kept 1.6% of it** (median premium capture per position). The gross premium was
  collected and then handed back.

The position size is not an oversight, it is the document's own rule. CA-12 requires the
worst-case margin *including* the expiry-day ELM on both short legs, even though ST-4
forbids holding to expiry day; on a NIFTY condor that add-on is roughly three times the
structure's entire defined risk. The result is a typical position of 5 lots — about ₹75 lakh
of notional, **gearing 0.75 against a cap of 2.5**. Arm G removes the add-on, the position
roughly doubles (median 9 lots), the gross credit doubles to ₹41.9 lakh — and the net return
goes to +0.16% a year. Scaling a zero scales to zero.

**The ceiling, stated as arithmetic.** Take the best case this study produced — arm I, the
structure working as designed, keeping 15% of gross credit after costs — and scale it to the
largest position the document allows. Gearing 2.5 is 3.3× the position actually taken, so
gross credit becomes about 13% of Portfolio Capital a year and the net about **2% a year**.
That is optimistic: slippage and the participation limits bite harder at 3× the size, and
the drawdown scales with the position while the 10% objective does not. **A 0.12-delta
weekly condor, sized inside this document's own gearing cap, cannot produce 12% a year.**
The gap is not a matter of tuning the filters; it is the size of the premium available at
that delta.

---

## 2. Where the money went

**How often it traded.** 142 positions against roughly 275 weekly expiry cycles in the
window — it entered about half the available weeks. The refusals, counted once per entry
session (arm A):

| Rule that refused the week | Entry sessions |
|---|---:|
| `ST-11` VRP filter (5-day realised > weekly ATM implied) | 65 |
| `ST-6` no strike in the 0.10–0.14 delta band **inside the captured strike band** | 59 |
| `ST-12` trend filter (\|close − 20d SMA\| > 4%) | 21 |
| `ST-13` gap filter (opening gap > 1%, still outside the band at 11:00) | 14 |

`ST-6` is a data limitation rather than a strategy decision — see
[§5](#5-what-the-corpus-can-and-cannot-answer). The other three are the document's filters
doing what they were written to do, and between them they stood the strategy down through
most of the high-realised-volatility stretches of 2022 and 2026.

Every completed position, grouped by the rule that closed it (arm A, 142 positions):

| Closed by | Positions | Total P&L | Median |
|---|---:|---:|---:|
| `ST-17` profit target | 64 | **+₹4,89,409** | +₹6,142 |
| `ST-39` entry never filled | 11 | ₹0 | ₹0 |
| `ST-21` second touch | 1 | −₹10,741 | −₹10,741 |
| `ST-4` deadline missed | 11 | −₹27,126 | −₹3,551 |
| `ST-4` time exit | 31 | −₹1,11,311 | −₹2,948 |
| `ST-19` weekly stop | 5 | −₹1,38,334 | −₹20,928 |
| `ST-22` structure-mismatch unwind | 19 | −₹1,51,101 | −₹6,758 |
| **net** | **142** | **+₹50,795** | |

The profit target does its job: 64 positions, ₹4.9 lakh, and it is the only line in the
table that is positive. Everything else is the cost of the positions that did not go
straight to target.

**The single largest destroyer of value is the ST-20 roll.**

| | Positions | Total P&L |
|---|---:|---:|
| Never rolled | 79 | **+₹4,67,740** |
| Rolled once | 63 | **−₹4,16,945** |

Forty-four per cent of positions hit the 0.28-delta roll trigger, and as a group they gave
back almost exactly what the unrolled ones earned. This is not an implementation artefact —
it is what the rule costs. ST-20 buys back a short that has run from 0.12 to 0.28 delta
(expensive by then) together with its wing, and re-sells the same vertical 350 points
further out (cheap by then). The measured cost of a roll is **₹29–52 per unit against an
entry credit of ₹39 per unit**: the adjustment routinely costs more than the position ever
stood to make. The arithmetic is the rule's, not the backtest's.

The finding replicates three ways, which is why it is stated this strongly:

- at the larger position size (arm G: rolled −₹7.66 lakh, unrolled +₹8.45 lakh);
- in the arm whose entry structure is priced entirely from real prints (arm B: rolled
  −₹1.67 lakh over 23 positions, unrolled +₹1.03 lakh over 33);
- and by removing the rule outright (arm I), which lifts the win rate from 51% to **75%**,
  the share closed at profit target from 45% to 65%, and the median premium capture from
  **0.016 to 0.54**. The roll is what turns a working short-condor into a coin flip.

There is a second, quieter cost inside that number. Nineteen of arm A's positions
(13%) closed as `ST-22_structure_mismatch_unwind`: a roll is an eight-leg order, the
participation caps resize an order group to its smallest fillable leg, and a roll that
half-executes leaves a book that is no longer the specified structure. The strategy unwinds
those rather than manage a shape the requirements do not define — correctly, but at a cost of
₹1.51 lakh. Rolls that cannot be executed atomically are a live operational risk, not a
backtest artefact: the same eight legs have to fill together on a real venue too.

**Costs are real but not the story.** ₹54,425 over five years — 0.54% of Portfolio Capital,
2.5% of gross credit. Three-quarters of it is flat per-order brokerage, which this structure
pays eight times a cycle on a small position.

**Execution is a bigger term than costs.** Slippage at ₹0.25 per unit per leg costs about
₹1.05 lakh over the run — twice the total statutory bill — and the sign of the answer moves
with it (arm E versus arm F below).

**Year by year** (arm A, by entry date): 2021 −₹21k (5 positions) · 2022 +₹34k (18) ·
2023 +₹27k (39) · 2024 +₹3k (26) · 2025 +₹62k (34) · 2026 −₹54k (20). No year is close to
the objective, in either direction.

---

## 3. The tail hedge is not in these numbers

ST-26 makes the Tail Hedge a precondition for opening any Core Position, so the overlay
above is not the strategy the document describes — it is the strategy minus a cost. The
hedge cannot be measured here at all: the corpus carries the nearest weekly expiry in a
±2.3% band, and ST-24 asks for a **monthly** put **9% out of the money**.

`research/overlay/hedge_drag.py` sizes it instead, Black-Scholes on the corpus's own spot
path, rolling at 15 DTE as ST-25 requires, 55% coverage of ₹1 crore:

| Assumed implied volatility of the hedge | Annual cost | As % of PC |
|---|---:|---:|
| 16% | ₹42,656 | **0.43%** |
| 20% | ₹1,37,219 | **1.37%** |
| 25% | ₹3,08,367 | **3.08%** |

The band is wide because the input is unobservable, and the number is an estimate in the
strict sense — it is Black-Scholes on an assumption, not a measurement. What it is precise
enough to say: **the hedge costs more than the overlay earns, under every assumption in the
range.** The specified strategy, taken whole, is a net loss on this data.

---

## 4. Sensitivities

The headline table in [§1](#1-the-answer) is the sensitivity study; what each arm
establishes is below.

- **A vs B — wing construction.** The specified 350-point wing (modelled) makes +0.11% a
  year over 142 positions; the narrower wings that actually printed at entry make −0.13%
  over 56. B trades a third as often because the wing it needs has to be visible, and its
  sample is tilted towards calm weeks ([§5](#5-what-the-corpus-can-and-cannot-answer)). The
  two arms disagree on the sign and agree on the magnitude: zero, either way.
- **C, D — the minimum-credit gate.** The document's 0.20% default refuses two-thirds of the
  weeks the 0.10% floor accepts (49 positions against 142) and does not improve the return.
  0.15% is the best of the three at +0.19% a year, which is a 0.08-point difference on a
  130-position sample and should not be read as a finding.
- **E, F — execution.** Zero slippage returns +0.33% a year; ₹0.50 per unit per leg returns
  −0.11%. The entire result lives inside the execution assumption, which is the honest
  summary of a strategy whose edge is smaller than its trading friction.
- **G — the margin assumption.** Dropping CA-12's expiry-day add-on doubles the position and
  doubles the drawdown (1.85%) for +0.05 points of annual return.
- **H, I — the two diagnostics**, which are not variants of the strategy but questions put
  to it. H asks how much of the result is the execution model: raising the participation
  caps from 1%/0.5% to 5%/2% of a minute's volume and open interest is worth +0.25 points a
  year, so a meaningful part of arm A's flatness is the cap, and an operator who can work an
  order over several minutes would do better than arm A shows. I then asks what ST-20 is
  worth once the caps are no longer what breaks it: +0.31 points more, and the trade profile
  becomes the textbook one.

### What would have to be true for 12%

Not a recommendation — a statement of what the arithmetic demands, given where the money
demonstrably is and is not:

| Lever | Measured effect | Enough for 12%? |
|---|---|---|
| Drop ST-20 rolls | +0.31 pts/yr, win rate 51% → 75% | No |
| Execute across minutes rather than one (caps 5%/2%) | +0.25 pts/yr | No |
| Halve slippage (₹0.25 → ₹0) | +0.22 pts/yr | No |
| Size to the gearing cap (0.75 → 2.5) | ×3.3 on both P&L and drawdown | No — about 2%/yr |
| All four together | roughly 2%/yr, drawdown ~3% | **No** |
| Sell a materially higher delta than 0.12 | not measured here | Unknown — and it is a different strategy, with a different tail |

The honest reading is that the 12% objective and the 0.12-delta/2.5-gearing structure were
specified independently of each other, and they do not meet. The structure is defensible as
a **risk-controlled, near-zero-return overlay**; it is not a 12% engine, and no parameter
inside the document's own allowed ranges makes it one.

---

---

## 5. What the corpus can and cannot answer

Everything in this section is produced by `research/overlay/coverage.py` and stored in
`research/overlay/results/coverage_NIFTY.json`.

**The capture is a band around spot, not a chain.** Each session carries the nearest weekly
expiry only, about 21–29 strikes, roughly ±2.3% of spot. That is ample for the intraday
strategies this corpus was built for and tight for this one, which needs a 0.12-delta strike
(1.5–2% out of the money at 5–6 days) *and* a 350-point wing beyond it (another ~1.5%).

| Fact | NIFTY |
|---|---|
| Sessions captured | 1,250 (2021-06-01 → 2026-09-15) |
| Trading days missing inside that range | 56 |
| Entry windows (nearest expiry 5 or 6 days out) | 295 |
| …with **both** 0.12-delta shorts inside the captured band at 10:00 | 198 (67%) |
| …with 300–400pt wings on both sides inside the band | **0** |
| …with at least 100pt of room beyond both shorts | 97 |
| Median room beyond the short strike | 150pt call side, 100pt put side |

Two consequences, and they shape every number in this report:

1. **The specified 350-point wing is never observable.** Not rarely — never, in 295 entry
   windows. Arm A prices it with the model described in `xman_research.overlay.greeks`,
   whose error was measured by holdout before it was used: median ₹1.42 per unit against a
   median true price of ₹14.35, biased ₹1.48 **low**. A cheap long wing flatters the entry
   credit and depresses the exit proceeds, so the two ends partly cancel.
2. **The short strikes are observable about two-thirds of the time**, and the third that is
   not is not random: the 0.12-delta strike leaves the band precisely when implied
   volatility is high, because that is when it sits further out. The weeks this study can
   measure are therefore tilted towards calmer ones. The direction of the resulting bias is
   not obvious — calm weeks pay less premium *and* lose less — but its existence is a fact
   about the sample, not a caveat about the method.

**A five-session hold needs prices for strikes that have since left the band.** The captured
band follows spot, so a wing bought on Monday can be outside the band by Wednesday — and not
merely unpriced: the session's instrument master does not list it either. A run without the
modelled extension cannot close its own positions. That was measured, not assumed: the first
fully observed five-year attempt failed on 2022-11-02 with an exit leg unlisted, and the
position ran to cash settlement. Both arms therefore read modelled prices *after* entry.
What "observed" honestly means for this strategy is **arm B**: every price the entry decision
rested on was a real print.

---

## 6. SENSEX: not evaluable

`research/overlay/results/coverage_SENSEX.json`.

| Fact | SENSEX |
|---|---|
| Sessions captured | 32 (2026-07-13 → 2026-08-27) |
| Trading days missing inside that range | 2 |
| Entry windows at 5–6 days to expiry | **6** |
| …with both 0.12-delta shorts inside the captured band | **0** |
| Smallest \|delta\| available at those windows (median) | 0.19 call side, 0.24 put side |

Six entry windows is not a sample, and in none of them does the captured band even reach the
0.14 delta the requirement's band tops out at — the *short* strike is unattainable, never
mind the wing. Running the strategy on SENSEX would not produce a weak result; it would
produce a different strategy's result on six observations.

What would unblock it: a Dhan backfill of SENSEX weeklies over a multi-year window with a
wider strike band (the present capture's band is the binding constraint as much as its
length). Whether Dhan serves expired BSE option chains that far back is not established
here; it is the first thing to check before committing to the work.

---

## 7. What is implemented, substituted and absent

| Requirement | Status |
|---|---|
| ST-3 entry window (5–6 DTE, 09:20–14:30) | Implemented. Driven off days-to-expiry read from the contract, not off the weekday — the corpus spans the Thursday→Tuesday expiry change. |
| ST-4 exit before expiry day | Implemented, and attempted from 14:00 rather than only at 15:15. Misses are counted, not absorbed. |
| ST-5–ST-7 structure | Implemented. Arm A uses the specified 350pt wing; arm B uses the widest wing that printed, per side. |
| ST-8 minimum credit | Implemented; the default is the study's main filter finding — [§4](#4-sensitivities). |
| ST-10 volatility filter | **Substituted.** No India VIX series exists in the corpus. The IV-percentile limb is evaluated against this corpus's own weekly at-the-money implied volatility over a trailing 252 sessions; the VIX-floor limb is recorded as inapplicable. |
| ST-11 VRP filter, ST-12 trend, ST-13 gap | Implemented from the corpus's own spot series. |
| ST-14–ST-16 event calendar | **Absent by configuration.** The mechanism is implemented and takes a calendar; no event source exists here, so every week is treated as a normal week. The document's fallback (missing calendar → HALF) is not applied: halving five years of positions would be a different strategy rather than a conservative version of this one. |
| ST-17/ST-19 profit target and stop | Implemented, evaluated every 15 minutes. |
| ST-20/ST-21 roll and second touch | Implemented. |
| ST-22 no naked short | Implemented structurally: entry, roll and exit are atomic leg groups, and a book that stops matching the structure is unwound. |
| ST-24–ST-27 Tail Hedge | **Absent.** A 9%-out-of-the-money *monthly* put exists in no captured session. Sized separately in [§3](#3-the-tail-hedge-is-not-in-these-numbers). |
| ST-30/ST-31 intraday margin monitoring | **Absent.** Both are driven by broker-reported blocked margin and collateral value, neither of which exists historically. Their effect would be to reduce positions in stressed weeks, so their absence flatters drawdown. |
| ST-32/ST-33 risk budget and drawdown scaling | Implemented, gated on the strategy's own mark-based estimate (pre-cost). |
| CA-2–CA-18 allocation | Implemented. Reproduces the document's section 8 worked example exactly (`tests/test_overlay_sizing.py`). |
| CA-19 stress test | Implemented and not disableable. |
| ST-37–ST-39 order requirements | Partly: leg role, rule ID and atomicity are carried; a per-day client order reference is not modelled. |

---

## 8. Reproducing this

```bash
# the corpus-coverage evidence (§5, §6)
uv run python research/overlay/coverage.py --underlying NIFTY \
    --out research/overlay/results/coverage_NIFTY.json
uv run python research/overlay/coverage.py --underlying SENSEX \
    --out research/overlay/results/coverage_SENSEX.json

# every arm of the study (§1, §4); writes one JSON per arm plus summary.json
uv run python research/overlay/sweep.py --out research/overlay/results

# the tail-hedge sizing (§3)
uv run python research/overlay/hedge_drag.py --out research/overlay/results/hedge_drag.json

# the tables in this document
uv run python research/overlay/report_tables.py --results research/overlay/results
```

Each arm files a trial in the canonical research log
(`/home/qa/runtime/data/research/trial_log.db`) with its parameters, its metrics and the
code version that produced it. Seven arms is seven trials, and the log says so — which is
the only honest way to present a sweep.
