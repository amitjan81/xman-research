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
strategy as specified returned ₹2,395 — 0.02% in total, 0.00% a year — net of statutory
costs and slippage. The document's objective is 12% a year.**

It did not lose money either: maximum drawdown was 1.3% of Portfolio Capital against a 10%
objective, and the win rate was a perfectly ordinary 57.9% over 133 positions. The trade
works. What it does not do is earn anything: the wins are too small and the losses too
large, and they cancel almost exactly. Across every specification-faithful variant —
wing construction, the minimum-credit gate, the margin assumption — the annualised return
sits between **−0.04% and +0.06%**. The execution assumption moves it more than any rule
does (−0.17% to +0.19%), which is the signature of a strategy whose edge is smaller than its
trading friction. Switching off the roll and loosening the caps reaches +0.77%, still a
fifteenth of the objective.

| Arm | Cycles | Net P&L | Return on PC | Annualised | Max DD | Win rate |
|---|---:|---:|---:|---:|---:|---:|
| **A — specified 350pt wings (modelled where unprinted)** | 133 | **2,395** | **0.02%** | **0.00%** | 1.29% | 57.9% |
| B — wings that printed at entry (100–400pt, per side) | 34 | 15,005 | 0.15% | 0.03% | 0.41% | 67.7% |
| C — minimum credit 0.15% of notional | 100 | 27,944 | 0.28% | 0.06% | 1.18% | 61.0% |
| D — minimum credit 0.20% (the document's default) | 33 | -17,713 | -0.18% | -0.04% | 1.05% | 60.6% |
| E — zero slippage | 133 | 95,686 | 0.96% | 0.19% | 1.04% | 59.4% |
| F — slippage ₹0.50 per unit per leg | 133 | -85,885 | -0.86% | -0.17% | 1.78% | 57.1% |
| G — margin = defined risk only (no CA-12 ELM) | 133 | 97,216 | 0.97% | 0.19% | 1.80% | 60.2% |
| H — *diagnostic*: participation caps 5% volume / 2% OI | 135 | 11,005 | 0.11% | 0.02% | 1.35% | 57.0% |
| I — *diagnostic*: H, with ST-20 rolls switched off | 135 | 390,902 | 3.91% | 0.77% | 0.90% | **78.5%** |

Arm I is the most informative row in the table. Switch off the roll rule and loosen the
execution caps and the structure behaves exactly as short-condor theory says it should — a
**78.5% win rate** and the lowest drawdown in the study. The trade works. It just does not
work *enough*: 0.77% a year against an objective of 12%.

Two numbers explain why 12% was never reachable at this size, before any question of skill:

- The overlay **collected ₹18.4 lakh of net credit in total** across 133 positions in five
  years — about 3.7% of Portfolio Capital a year of gross premium. Twelve per cent a year
  cannot come out of under four, whatever the win rate.
- It **kept none of it on average**. The median position captured 48% of its credit — the
  profit target doing its job — but the mean capture is 0.00, because the losing quarter
  gave back everything the winning three-quarters made. Average win ₹7,226; average loss
  ₹9,893; profit factor 1.17.

The position size is not an oversight, it is the document's own rule. CA-12 requires the
worst-case margin *including* the expiry-day ELM on both short legs, even though ST-4
forbids holding to expiry day; on a NIFTY condor that add-on is roughly three times the
structure's entire defined risk. The result is a typical position of 6 lots — about ₹1.1 crore
of notional, **gearing 1.1 against a cap of 2.5**. Arm G removes the add-on, the position
roughly doubles — and the net return goes to +0.19% a year. Scaling a zero scales to zero.

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

**How often it traded.** 133 positions against roughly 250 weekly expiry cycles, plus 146
entry orders that were never filled — the participation caps refusing a four-leg group in a
quiet minute. The refusals, counted once per entry session:

| Rule that refused the week | Entry sessions |
|---|---:|
| `ST-11` VRP filter (5-day realised > weekly ATM implied) | 65 |
| `ST-6` no strike in the 0.10–0.14 delta band inside the captured band | 59 |
| `ST-12` trend filter (\|close − 20d SMA\| > 4%) | 21 |
| `ST-13` gap filter (opening gap > 1%, still outside the band at 11:00) | 14 |

The three filters that are the document's own stood the strategy down through most of the
high-realised-volatility stretches of 2022 and 2026, which is what they were written to do.
`ST-6` is mostly a data limitation — see [§5](#5-what-the-corpus-can-and-cannot-answer) —
though not entirely: a 50-point strike ladder sometimes steps over [0.10, 0.14] without
landing in it, and the journal now records the nearest delta the chain offered so the two
causes can be told apart.

Every completed position, grouped by the rule that closed it:

| Closed by | Positions | Share |
|---|---:|---:|
| `ST-17` profit target | 72 | 54% |
| `ST-21` touch after an unpriceable roll | 41 | 31% |
| `ST-19` weekly stop | 11 | 8% |
| `ST-4` time exit | 9 | 7% |

**Zero ST-4 breaches and zero structure-mismatch unwinds** — both were present before the
review fixes and both were defects rather than findings.

**ST-20's roll never executes, and that is the finding.** Forty-six positions reached the
0.28-delta trigger; none of them rolled. The rule's replacement short sits one wing-width
further out, which is precisely where the captured band ends, so its price would be one this
package modelled rather than one the market printed — and selling a modelled price is the one
thing the fabrication boundary forbids ([§5](#5-what-the-corpus-can-and-cannot-answer)). The
strategy records the refusal and closes on the next touch instead, which is where 31% of the
positions in the table above come from.

That is a statement about this corpus, not about the rule. What the rule costs is measurable
where the strikes *are* observable — in the tuned configurations of [§4a](#4a-what-reaches-12--the-tuned-configuration),
which trade nearer the money: switching ST-20 back on there costs **4.3 percentage points a
year** (13.25% → 8.90% in-sample, 11.15% → 8.40% out). An earlier version of this study,
before the fix that stopped modelled shorts, let the roll trade at fabricated prices and
measured its cost at ₹4.17 lakh against ₹4.68 lakh made by the positions that never rolled.
Both measurements point the same way. Only the second one is made of real prices.

**Costs are real but not the story.** ₹41,804 over five years — 0.42% of Portfolio Capital,
2.3% of gross credit. Three-quarters is flat per-order brokerage, which this structure pays
eight times a cycle on a small position.

**Execution is a bigger term than costs.** Slippage at ₹0.25 per unit per leg costs about
₹1.8 lakh over the run — four times the entire statutory bill — and the sign of the answer
moves with it (arm E versus arm F).

**Year by year**, by entry date: 2021 −₹20.5k (5 positions) · 2022 +₹20.0k (13) ·
2023 +₹82.8k (39) · 2024 −₹15.1k (23) · 2025 −₹34.1k (34) · 2026 −₹30.8k (19). One positive
year of any size in five, and none close to the objective in either direction.

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

### 4a. What reaches 12% — the tuned configuration

The owner's follow-up question was not "does the specified strategy make 12%" but "what
would". `research/overlay/tune.py` searched for it in five stages and 117 configurations,
with the in-sample/out-of-sample split fixed at 2025-03-31 **before the first run**.

**It is reachable, and the honest version of that sentence has three parts.** The tuned
configuration returns **12.26% a year over the full five years** — max drawdown 7.14%,
Sharpe 1.43, 71.6% win rate over 208 positions — which meets both of the document's
objectives on the realised path. Split at the date fixed before the search began, it returns
**14.92% in-sample and 9.89% out-of-sample**, and the out-of-sample drawdown is **10.62%**,
just past the 10% objective. The degradation is what a 117-configuration search should be
expected to produce, and the out-of-sample number is the one to plan against.

> **Corrected for four corpus defects, 2026-09-17.** The figures in this section were
> computed before `xman_research.corpus_hygiene` existed, and two of the defects it fixes
> reach the overlay's entry filters directly: the session `open` ST-13's gap filter reads was
> the feed's out-of-hours padding on 13.2% of sessions (a median of 80.6 index points wrong,
> up to 407), and the at-the-money implied volatility ST-10's percentile floor gates on was
> admitting solver zeros on 13.8% (a median of 4.2 vol points wrong). Re-running stage five
> on corrected data moves **every** in-sample return down and **no** out-of-sample return at
> all — the padding lives in 2021-22, which is the in-sample half. For the published
> parameter set (`s_sb12_d0.22_w600`): in-sample **13.26% → 12.24% a year** on 146 → 143
> positions; out-of-sample **15.21% → 15.21%** on 54 positions, identical to two decimals.
> Across all fourteen configurations the in-sample fall is 0.3 to 1.8 percentage points a
> year, and every one of them opened two to four fewer positions — trades the corrupted
> filters had been letting through, which happened to be winners.
>
> **The table below is therefore overstated in its in-sample row and sound in its
> out-of-sample one.** It is not re-derived here because the `FINAL_split` run that produced
> it used a bespoke script that no longer exists in the tree; reconstructing it is follow-up
> work, and until then the stage-five delta above is the honest correction to apply. The
> out-of-sample number — which this report already says is the one to plan against — does
> not move.

| Slice | Annualised | Max DD | Sharpe | Positions |
|---|---:|---:|---:|---:|
| Full window, 2021-09 → 2026-09 | **12.26%** | 7.14% | 1.43 | 208 |
| In-sample, to 2025-03-31 | 14.92% | 6.25% | 1.89 | 152 |
| **Out-of-sample, 2025-04 → 2026-09** | **9.89%** | **10.62%** | 0.79 | 56 |
| Held to CA-14's 2.5× gearing cap | 5.73% | 3.79% | 1.38 | 214 |
| At the engine's 1% participation caps | 2.74% | 7.40% | 0.57 | 210 |

The last two rows are the two constraints that decide whether any of this is real, and they
are worth more than every parameter in the search put together. **Gearing at the document's
own cap halves the return** — 5.73% against 12.26% — and that variant is the one an operator
could run without amending CA-14. **Execution at the engine's conservative participation
limit cuts it to 2.74%**, which says the result lives or dies on whether ~2,700 units a leg
can be worked into 5% of a minute's printed volume. Neither question is answerable from this
corpus; the first is a decision and the second is a measurement a broker's live book would
settle in a week.

| | Specified | Tuned | The document's rule |
|---|---|---|---|
| Short delta | 0.12 | **0.22** | ST-6: 0.10–0.14 ✗ |
| Entry window | 5–6 days to expiry | **1–2 sessions before expiry** | ST-3: 4–7 days ✗ (see below) |
| Wing width | 350 pts | **600 pts** | ST-7: 300–400 ✗ |
| ST-20 roll | on | **off** | ST-20 requires it ✗ |
| Cash-equivalent collateral | 15% | **50%** | §8's mix — but **CA-R2 recommends raising it** ✓ |
| Target utilisation | 30% | 35% | CA-9: 15–35% ✓ |
| Absolute lot cap | 50 | 200 | CA-15: 1–200 ✓ |
| **Gearing actually used** | 1.1× | **7.6× mean, 9.4× peak** | **CA-14: 2.5× ✗** |

Three of the eight changes are inside the document's own ranges, and the collateral one is
something the document instructs the platform to *recommend*: CA-R2 fires whenever non-cash
collateral is stranded, and §8's portfolio strands ₹52 lakh of it. **The gearing is the
change that matters.** Held to CA-14's 2.5× cap with everything else unchanged, the same
configuration returns 4.78% a year. Everything else on the list is worth a few points;
gearing is worth the difference between 5% and 12%.

**The entry window is a correction, not a deviation.** ST-3 is written in calendar days, and
calendar days do not survive NSE's move of the NIFTY weekly expiry from Thursday to Tuesday
in mid-2025: "two to three days before expiry" is Monday and Tuesday under the old regime and
**Saturday and Sunday** under the new one. The first tuned configuration this study produced
was tuned in calendar days, returned 11.46% a year, and had stopped trading entirely in
August 2025 — 163 positions before the change and one after. The annualised figure hid it,
because a year of not trading looks like a year of no losses. Counting *sessions* instead is
invariant: ST-3's 5–6 calendar days is 2–3 sessions under either regime, and the tuned
window of 1–2 sessions is one step closer in.

**It is a plateau, not a spike.** The nine configurations around the calendar-day winner
(delta 0.22/0.25/0.28 × wings 400/500/600) all returned 8.4–14.0% in-sample and 7.9–11.6%
out-of-sample, and the session-form search reproduced the ridge with the holdout spanning
the new regime. A search that found one configuration standing alone found noise; this
surface is smooth in both directions.

**What it is sensitive to, in order:**

| Perturbation | In-sample | Out-of-sample |
|---|---:|---:|
| The tuned configuration | 13.26% | 15.21% |
| Participation caps 5% → 1% of a minute's volume | **4.20%** | **6.06%** |
| CA-12's literal margin rule (expiry-day ELM included) | 5.92% | 4.95% |
| ST-20 roll switched back on | 8.90% | 8.40% |
| Slippage ₹0.25 → ₹1.00 per unit per leg | 8.87% | 9.16% |

Slippage barely moves it — four times the assumed cost still leaves ~9%. **Execution
capacity does.** The position averages 42 lots, about 2,700 units a leg, and the result
assumes that can be worked into 5% of a minute's printed volume. At the engine's
deliberately conservative 1% it falls to 4–6%. That assumption, not the strategy, is where
this number is most likely to be wrong — and it is testable before any capital moves, because
it is a question about the book depth of NIFTY weeklies at 0.22 delta that live quotes answer
and this corpus cannot.

**The risk the drawdown figure does not show.** 8.28% is what the path did. What the position
*permits* is larger: at 42 lots with 600-point wings the maximum loss on a single expiry is
about **₹20 lakh, or 20% of Portfolio Capital** — an index gap through the wing on one
Tuesday. The worst week in five years was −6.3%. The 10% drawdown objective is met by the
realised path and exceeded two-fold by the worst case the structure carries, and those are
different statements about the same trade. ST-32's weekly loss cap fired 23 times in 200
positions, which is the risk budget doing its job at this size and is also why the
full-window return (11.55%) is below either half taken alone.

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
