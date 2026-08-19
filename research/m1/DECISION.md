# M1 — near-week short ATM straddle, on the backfilled corpus

| | |
|---|---|
| Record | `h_0b2ecbbc4bddb543599add3968e0cf88` (amendment of H1 `h_817b33ff6b9f68e288161f5990739744`) |
| Gate | `research/m1/gate.toml`, committed in `1921a5b`, before this result existed |
| Window | in-sample **2024-10-01 .. 2026-04-30**, 385 sessions, 384 return observations |
| Holdout | 2026-05-01 .. 2026-08-03, 64 sessions — **SEALED, not read** |
| Family trials at grading | **8** (pre-registered inventory said 6 — see §7) |
| **OUTCOME** | **NOT_EVALUABLE** |
| Next step | The answer is about execution — resolve the quote-data question before continuing. |

**Prior verdict for comparison:** H1, FAILS_THRESHOLD, n=79, DSR 0.6043 vs 0.90.

---

## 1. The outcome, and why it is not FAILS_THRESHOLD

The gate refused to grade the run before pass/fail was reached:

> **64.7% of sessions carried a position at a stale mark (limit 20.0%); the equity curve is partly an estimate**

That is spec §6's fourth outcome behaving exactly as `research/h1/gate.toml` and this gate
described it in advance — *"past a fifth of sessions marked stale, the equity curve is
substantially an estimate rather than a measurement."* The limit was left at C6's default
and was **not** set after seeing this number; it has been 0.20 since H1.

NOT_EVALUABLE is a successful deliverable. It is also, here, the *informative* one: the
thresholds below were computed and are reported, but they describe an equity curve the
apparatus has just declared partly estimated, and they should be read only through §2.

## 2. What actually happened — the book wedged, and stayed wedged

The finding that dominates this run is not a threshold. It is in the per-epoch table (§6):

| epoch | sessions | net return on capital |
|---|---:|---:|
| `nse_expiry_tuesday_2025` (2025-09-01 .. 2026-03-30) | 142 | **0.000000** |
| `stt_rise_2026` (2026-04-01 .. 2026-04-30) | 20 | **0.000000** |

**162 of 385 sessions — 42% of the graded window — produced exactly zero return**, with
zero dispersion. Not "small". Zero.

The supporting counts agree. Over 385 sessions the run attempted **62 fills** (31
straddles) and recorded **60 settlements** (30 straddles). One straddle entered and never
settled. Candidate exposure is 0.3516, and `fills_infeasible`, `no_bar`, `no_liquidity`
and `capped_to_zero` are all **0** — so nothing was refused at execution. No intent was
issued at all.

It is not an instrument-availability problem. Checked directly at the 09:20 decision minute
on four sessions inside the dead region — 2025-09-03, 2025-10-15, 2026-02-11 and the last
live session 2025-08-28 — the near-week expiry resolves, the strike ladder carries 23-25
strikes, the ATM contract is listed, and it has bars. The strategy *could* have entered on
every one of them.

The reading the evidence supports: **M1 enters only when flat, and it never went flat
again.** A straddle entered around late August 2025 was never settled, so the position sat
on the book across the Thursday-to-Tuesday expiry transition for the remaining 162
sessions — marked stale because its contract no longer prints bars, contributing no P&L
change, and tripping the stale-mark limit that produced this verdict.

**The stale-mark gate is the only thing that caught this.** Every threshold below was
computable, three of the four passed, and a reader who saw only the threshold table would
have concluded M1 lost narrowly on the Sharpe. The fourth outcome is what turned a
plausible-looking failure into a diagnosis. That is the strongest argument this run
produces for keeping NOT_EVALUABLE ahead of pass/fail in the order of checks.

## 3. Every metric against its threshold

| metric | observed | required | verdict |
|---|---:|---:|---|
| `deflated_sharpe` | **0.1149** | ≥ 0.90 | **FAIL** |
| `cost_breakeven_multiple` | **9.986** | ≥ 2.0 | pass |
| `max_drawdown` | **0.09435** | ≤ 0.10 | pass (by 0.6 pp) |
| `risk_matched_increment` | **0.0000** | ≥ 0.0 | pass — structurally cannot fail |

Supporting statistics, none of them gated:

| | |
|---|---:|
| annualised Sharpe | 0.1957 |
| annualised adjusted Sharpe | 0.1948 |
| observed Sharpe per period | 0.012331 |
| **probabilistic Sharpe (PSR)** | **0.5941** |
| expected max Sharpe (SR\*) | 0.074552 /period ≈ **1.183 annualised** |
| Sharpe variance | 0.0026110 (`dsr.sharpe_variance_assumed`) |
| skew / kurtosis | −2.203 / 21.52 |
| 5% expected shortfall | −1.4731% |
| worst session | −3.8653% |
| sessions under water | 361 / 384 |
| candidate exposure | 0.3516 |
| net P&L | ₹26,658.62 on a ₹10,00,000 base |
| peak margin | ₹4,59,841.20 (46.0% of capital) |
| return on peak margin | 5.797% |
| total costs | ₹2,550.21 — 10.01% of gross |
| fills attempted / filled / infeasible | 62 / 62 / 0 |
| settlements | 60 |
| fingerprint | `29d452d36913ac7fa6b9b319b91da34c910e1713baad3cde921b3f87b75e9f7f` |

## 4. Against H1, and the PSR/DSR spread

| | H1 | M1 |
|---|---:|---:|
| return observations | 79 | **384** |
| family trials (N) | 1 | **8** |
| annualised Sharpe | 0.4796 | **0.1957** |
| PSR | 0.6043 | **0.5941** |
| DSR | 0.6043 | **0.1149** |
| DSR bar | 0.90 | 0.90 |
| PSR − DSR spread | **0.0000** | **0.4792** |
| cost-breakeven | 12.89 | 9.986 |
| max drawdown | ~6.1% | 9.435% |

**The expectation stated in the brief was that more observations move DSR toward PSR. That
is not what happened, and the reason is worth stating precisely, because both the brief's
version and a naive reading of my own calibration would get it wrong.**

The calibration is still correct on its own terms: *at a fixed true Sharpe*, more
observations raise DSR. At N=6 a true annualised Sharpe of 3.0 gives median DSR 0.704 at
n=79 and 0.998 at n=384. Nothing here contradicts that.

But H1's spread was zero for a structural reason, not a statistical one: at **N=1** the
expected maximum Sharpe under selection is exactly 0.0, so DSR ≡ PSR by construction. H1's
identical numbers were never evidence that deflation is mild — they were evidence that
there was nothing to deflate. Comparing a spread against that baseline can only go one way.

At N=8 the selection threshold is real: **SR\* = 0.0746 per period, an annualised Sharpe of
about 1.18**. M1 delivered 0.196. The DSR is low because the strategy cleared neither bar,
not because the correction was punitive — and note that PSR alone, which carries no
multiple-testing correction at all, is 0.594 and would also have missed a 0.90 bar.

So the honest summary: **H26's diagnosis — "almost the entire failure was the
multiple-testing correction" — does not carry over to M1.** Here the correction and the
raw evidence agree, and they agree because the measured Sharpe is 0.196, which is itself
mostly an artefact of the wedged book in §2.

## 5. M1 §12.1 — executed, passed, and a defect in the check

Run before the gate was committed, over the graded window, reported in `gate.toml`:

```
min_t  N* / (S_t,09:20 · L_t)  ≥  0.5,   N* = 1,500,000
AS SPECIFIED (reference_lot_size):  PASS  min 0.7610 on 2025-12-01 (spot 26,281.15, L=75)
AS EXECUTED  (declared lot size):   PASS  min 0.8767 on 2026-01-05 (spot 26,323.90, L=65)
```

385 sessions checked, none lacking a spot at the decision minute. Because
`floor(x + ½) ≥ 1 ⟺ x ≥ 0.5`, no session reached §5's `n_t = 0` branch and §4's
suppression never fired — so which sessions trade does not depend on the contract
multiplier, which is the whole purpose of the check.

**The defect, reported rather than patched.** §12.1 names
`LotSizeAudit.reference_lot_size`. The **engine sizes on the declared lot size** —
`engine.py` says so in terms, citing the owner decision of 2026-08-13 that turned an
unoverridable refusal into a stamp, and `Contract.lot_size` is read verbatim from the
refdata `LotSize` column. The two disagree on 1,077 of the corpus's 1,233 sessions. Since
`n_t` falls as `L` rises, **§12.1 as written can pass while the engine still reaches the
zero branch**, on any window where declared exceeds reference.

On *this* window the gap runs in the safe direction: where the two differ, declared is the
smaller (65 against a bars-supported 75), so the engine sizes *larger* than the checked
quantity and is further from the zero branch, not closer. **That is a fact about this
window, not a property of the spec.** Both minima are therefore reported, and the check is
recorded as defective rather than silently redirected — §12.1 is owner-approved text.

Pre-registered re-execution rule: this check re-runs over the holdout window if and only if
the holdout is spent. It reads spot prices, a stronger read than H26's presence-only gap
census, so it is never run over sealed sessions.

## 6. Per-epoch breakdown — DESCRIPTIVE, UNGRADED

Pre-registered in `gate.toml` before computation. **No threshold reads this table and it
cannot change the outcome.** The pooled verdict is the graded one.

| epoch | start | end | sessions | net return | ann. Sharpe | max DD | skew | kurtosis |
|---|---|---|---:|---:|---:|---:|---:|---:|
| `stt_rise_2024` | 2024-10-03 | 2024-11-19 | 32 | +3.183% | **+2.099** | 2.92% | −1.82 | 9.89 |
| `weekly_expiry_cull_2024` | 2024-11-21 | 2025-02-07 | 56 | +6.668% | **+2.516** | 3.22% | −0.33 | 3.61 |
| `calendar_spread_relief_removed_2025` | 2025-02-10 | 2025-03-28 | 33 | −2.591% | −2.079 | 4.81% | −1.12 | 4.26 |
| `intraday_position_limits_2025` | 2025-04-01 | 2025-08-29 | 101 | −5.029% | −1.633 | 7.19% | −5.16 | 41.18 |
| `nse_expiry_tuesday_2025` | 2025-09-01 | 2026-03-30 | 142 | **0.000%** | — | — | — | — |
| `stt_rise_2026` | 2026-04-01 | 2026-04-30 | 20 | **0.000%** | — | — | — | — |

Dispersion statistics are `None` where the slice has zero dispersion. That is not a small
sample, it is an undefined statistic, and reporting a number there would be an invention.

**Predicted sign was positive in every epoch** (dealer capacity constraints are not a
feature of any one regulatory regime), with `weekly_expiry_cull_2024` named as the most
likely genuine exception. **Both halves of that prediction are wrong.** The cull epoch is
the *strongest* of the six (+2.516). The premium is positive and large in the two epochs
before 2025-02-10 and negative in the two after it, and the last two are silent for the
mechanical reason in §2.

**This is exactly the "effect lives in one regime" case the brief asked about, and it must
not be over-read.** The pooled number is the graded one, it was declared so in advance, and
this table is not a licence to select the favourable half. Two further cautions: 42% of the
window is a wedged book rather than a market observation, and the sign flip at 2025-02-10
coincides with an epoch date the gate's own table flags as `confidence="secondary"` and
possibly wrong by nine days.

## 7. Trial count and family

Family: H1 → {H26 v1 → H26 v2 → M2}, {M1}. The count spans the whole tree.

**Pre-registered inventory: 6. Realised: 8.** The disagreement is reported rather than
absorbed, which is what the inventory is for. Its cause:

| seq | hypothesis | outcome | note |
|---|---|---|---|
| 1 | H1 | completed | replayed from `research/h1/decision.json` |
| 2 | H26 v1 | error | `TypeError` in the exit path |
| 3 | H26 v1 | error | `KeyError`, strike not in instrument master 2026-02-03 |
| 4 | H26 v2 | completed | candidate |
| 5 | H26 v2 | completed | benchmark |
| 6 | **M1** | completed | **first M1 run — graded, then lost** |
| 7 | M2 | error | `KeyError`, strike not in instrument master 2025-04-07 |
| 8 | **M1** | completed | **this run** |

Rows 6 and 8 are both M1 over the identical window. Row 6's backtest and grading
*succeeded*; the run then died in this repository's own per-epoch reporting code on a
slice with zero dispersion — the 142-session dead region of §2, whose Sharpe is undefined —
before the payload was written. The bug was in the reporting layer, not the model, and it
is fixed. The lost verdict could only be recovered by running again, which cost a trial.

**Row 6 is kept.** Deleting a row from an append-only research log to reach a
pre-registered count is the flattering move even when it is justified, and no result from
row 6 was ever observed or selected on. Row 7 is kept for the same reason.

The realised N=8 was calibrated for: `gate.toml` records the n=384/N=8 grid alongside
N=6, and at 0.90 the two differ by 2.5 points of power at a true Sharpe of 2.0 (60.0% vs
57.5%). **No threshold was moved after the count was known.**

## 8. Honesty stamps

Every stamp the run carried, verbatim:

```
corpus.declared_lot_size_contradicted:unverified
corpus.open_interest_not_divisible_by_lot_size:unverified
gst.broking_services:corroborated
margin.simplified_approximation:unverified
nse.transaction_charge.options:corroborated
sebi.turnover_fee:corroborated
settlement.exchange_charge_assumed_not_levied:unverified
settlement.mean_of_underlying_minute_close_over_window:corroborated
stt.sell_option_premium:corroborated
dsr.sharpe_variance_assumed
epochs.dates_not_primary_sourced
```

plus the same nine repeated under a `benchmark:` prefix, because candidate and benchmark
are the same run presented twice.

`corpus.declared_lot_size_contradicted` is **new relative to H1** and is not decorative:
it is the stamp §5 is about. Only stamp duty (δ) is primary-sourced anywhere in the cost
stack; settlement is unweighted where NSE's is volume-weighted; slippage is 0 bps by M1
§7's deliberately optimistic default and no quote data exists to model a spread.

## 9. Gap policy

`accept_gaps` with a written reason naming all three missing sessions — **2024-11-20,
2025-04-30, 2025-05-08** — recorded in `decision.json` under `gap_policy`. The window was
not narrowed: narrowing would either fragment one pre-registered trial into three or
discard ~140 sessions including the regime change the per-epoch table exists to examine.

2024-11-20 is itself an epoch boundary (SEBI weekly-expiry cull, contract size, expiry
ELM). Losing it costs little: it was a Wednesday, and pre-Tuesday-change expiries fell on
Thursdays, so **no settlement is lost** — the boundary merely lacks its first day's marks,
which biases neither side of it.

## 10. What to do next

1. **Diagnose the wedged book (§2) before any re-run.** Find the straddle that entered
   around late August 2025 and never settled, and establish whether the contract was
   dropped from the instrument master across the Thursday-to-Tuesday expiry transition
   before `_settle_expiring` could fire. Until that is answered, no M1 number over a window
   containing 2025-09-01 means anything.
2. **Take §5's §12.1 defect to the owner as a separate spec amendment.** The check should
   name the lot size the engine sizes with, or the engine should size on the one the check
   names. They must not be different quantities.
3. **Do not re-run M1 casually.** Every run appends a trial and moves N.
4. **The holdout is still sealed** and this verdict does not touch it. `decide()` reaches
   for the holdout only from a PASSED verdict; NOT_EVALUABLE leaves it intact, which is a
   strictly better state to leave the programme in.
