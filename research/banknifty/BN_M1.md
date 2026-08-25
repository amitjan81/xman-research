# BN-M1 — BANKNIFTY near-expiry short ATM straddle (benchmark)

**This is an engine proof and a benchmark. It is not a candidate and it decides nothing.**
No gate file reads it, no holdout was spent, no decision was recorded. What it establishes
is that the research engine runs end to end on an underlying that is not NIFTY, and what a
naive always-on short straddle actually collected on BANKNIFTY over the in-sample corpus —
the number a conditional BANKNIFTY signal will have to beat.

| | |
|---|---|
| Hypothesis | `h_1be59cf40faafce9635a4609b04e4f24` |
| Trial | `t_418d0cf301e04595b16fa3c535746804` (second trial in BANKNIFTY's family; the first ran an earlier wording of the gap reason) |
| Window | 2024-10-01 .. 2026-05-29, 353 sessions run |
| Strategy | `short_atm_straddle`, target notional ₹1,500,000, min 1 day to expiry |
| Fingerprint | `105afff4cf3884b2…` |
| Full payload | `bn_m1_benchmark.json` |

The window starts at the STT floor rather than at the corpus start; `README.md` says why.
The holdout, 2026-06-01 onward, was not read.

## What it returned

| | |
|---|---|
| Annualised Sharpe | **0.185** |
| Max drawdown | **9.37%** (peak 2024-11-21, trough 2025-10-28) |
| Sessions under water | 332 of 352 |
| n (return observations) | 352 |
| Net P&L | ₹24,923 on a ₹1,000,000 capital base (+2.49% over 20 months) |
| Return on peak margin | 4.86% (peak margin ₹513,009) |
| Total costs | ₹1,933 (STT ₹837, none on exercise) |
| Cost-breakeven multiple | 13.9× |

## What it actually traded

| | |
|---|---|
| Entry intents attempted | 342 |
| Filled | 32 (16 straddles) |
| Refused `UNSETTLEABLE` | 310 |
| Resized by a participation cap | 0 |
| Group-incomplete legs | 0 |
| Settlements | 30 (15 straddles) |
| Open at run end | 2 legs — the 30Jun2026 55100 CE/PE |
| Sessions with stale marks | 47 of 353 (13.3%) |
| Sessions with unmargined shorts | 0 |

**16 straddles in 20 months.** That is the honest shape of hold-to-expiry in a monthly
regime: the strategy opens on the first session after each settlement and holds ~20
sessions, so the number of independent observations is the number of expiry cycles, not
the number of sessions. 15 of the 16 settled; the 16th expires 2026-06-30, past the window
edge, and is reported open at run end and marked at its last price — deliberate engine
behaviour (a window's right-hand edge must not decide which trades a strategy takes), and
the run carries `book.open_at_run_end` to say part of the P&L is unresolved.

**The 310 refusals are 10 cycles, not 310 opportunities.** The strategy proposes an entry
on every session it is flat, so one unsettleable cycle produces two refused legs per
session for the whole cycle. The underlying fact is that 10 of the window's 27 expiry
sessions were quarantined by the producer and never published, so the engine — correctly —
declined to open a position it could prove it could not close. That refusal was not
softened. `CORPUS.md` names all ten.

## Reading this honestly

**The Sharpe is not evidence of anything.** 0.185 annualised on 15 settled cycles is
indistinguishable from zero at any sample size worth quoting, and the deflated statistic
that would price the multiple comparisons has deliberately not been computed here — this
record is not graded, and computing a decision statistic for a run with no gate is how a
benchmark quietly becomes a candidate.

**The drawdown is the more informative number.** 9.37% peak-to-trough against a 2.49% total
return, with 332 of 352 sessions under water, describes a position that spent nearly the
whole window below its high-water mark and finished slightly up. That is what selling a
sector index's variance and holding it for a month at a time looks like on this corpus.

**Costs are not the story on this underlying.** A 13.9× breakeven multiple means gross P&L
was fourteen times the frictions, which is unsurprising at 16 round trips in 20 months —
turnover this low cannot be taxed to death. A BANKNIFTY strategy that trades weekly would
face a completely different ratio, and nothing here speaks to it.

**The population is quarantine-selected, and this is the finding that limits the number
most.** The 10 declined cycles are declined because their expiry session failed the
producer's expiry-day convergence check — which fires when the ATM straddle still carried
residual time value at the close. That is not independent of what a short straddle earns on
that expiry, so the cycles that survive are a biased sample of the 27, in a direction this
package cannot measure or correct. 17 of the 27 have an expiry session on disk; the last of
those expires past the window edge, so 16 straddles were opened and 15 settled inside the
run. The fix is producer-side. Until then, no BANKNIFTY
verdict over this corpus is entitled to be read as a verdict over BANKNIFTY.

**The lot size the run used is wrong on more than half the window, on purpose.** Per the
owner's decision of 2026-08-13, the run computes on the *declared* lot size and stamps
itself: 182 of the 353 sessions carry
`corpus.declared_lot_size_contradicted`. Because sizing targets a notional rather than a
contract count, the scale-free statistics above — Sharpe, drawdown, return on peak margin,
the cost-breakeven ratio — survive the wrong multiplier up to a rounding residual. The
participation caps and the flat per-order brokerage do not, and should not be relied on.
**102 of those 182 stamps exist only because this change added 35 to `CANDIDATE_LOT_SIZES`**;
before it, the 2025-07..2025-12 regime was undetectable and those sessions ran clean.

## Stamps the run carries

```
book.open_at_run_end:unverified
corpus.declared_lot_size_contradicted:unverified
corpus.expiry_session_absent:unverified
corpus.open_interest_not_divisible_by_lot_size:unverified
margin.simplified_approximation:unverified
settlement.exchange_charge_assumed_not_levied:unverified
settlement.mean_of_underlying_minute_close_over_window:corroborated
gst.broking_services:corroborated
nse.transaction_charge.options:corroborated
sebi.turnover_fee:corroborated
stt.sell_option_premium:corroborated
```

25 symbols carry open interest that does not divide by the lot size the bars support;
they are reported in the payload's `lot_size_audit` and diagnosed nowhere, which is the
same treatment NIFTY's equivalents get.

Notably **absent**: no `costs.rate_extrapolated:*`. Every session in this window is inside
every rate schedule, which is what starting at 2024-10-01 bought.

## Engine defects found

**None.** The engine is genuinely underlying-parameterised: nothing hardcoded a strike
step, a lot size, or a NIFTY expiry cadence, and the run completed without a single
refusal that needed a code change. Two behaviours looked like defects and are not:

* **A straddle expiring after the window end was opened rather than refused.**
  `_SettlementCalendar.can_settle` returns True for `expiry > run_end` on purpose and says
  so in its docstring: a window that ends before a contract expires has not lost the
  settlement, it has stopped before it. The position is reported in `open_at_end` and
  stamped.
* **310 `UNSETTLEABLE` verdicts.** This is the guard working, on a corpus that is missing
  ten expiry sessions. It is a data finding, not an engine one.

One **pre-existing** defect was measured rather than fixed, per its own deferral note:
`epoch_for` is called with a session date where it expects an expiry. On BANKNIFTY's
monthly cycle that costs the corroboration sentence in the contradiction message on 13
in-sample sessions and never attaches a wrong epoch. `CORPUS.md` has the detail.

## Reproducing

```
uv run python -m xman_research.models.bn_benchmark
```

Writes `bn_m1_benchmark.json` and appends one trial to the canonical family log at
`/home/qa/runtime/data/research/trial_log.db`. Re-running appends another trial — the log
is append-only by construction — so re-run it only when the run's inputs have changed. The
gap reason is one of those inputs: it travels in the config provenance and is hashed into
the fingerprint, so rewording it is a new run and not a cosmetic edit.

A BANKNIFTY **candidate** extends this record with `HypothesisRecord.amend`, so the family
trial count accumulates. Minting it fresh would open a third family at zero and inherit
none of the comparisons made here.
