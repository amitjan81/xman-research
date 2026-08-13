# H26 — the decision

| | |
|---|---|
| **Hypothesis** | `h_cacfc556d38a2bda25efef59eb5544cf` — overnight vs intraday variance premium |
| **Family** | H1 `h_817b33ff…` → H26 v1 `h_4095cf35…` → **H26 v2** (this record) |
| **Outcome** | **FAILS A THRESHOLD** — spec §6, row 2 |
| **Next** | Next hypothesis. The loop works. |
| **Holdout** | **NOT SPENT.** 2026-05-01 .. 2026-08-12, 71 sessions, still sealed. |
| **Trial count at decision** | **5**, read from the log |
| **Run fingerprint (candidate)** | `bd520ab4319637bf…` |

H26 failed one pre-registered threshold — the deflated Sharpe — and passed the other three.
**A failure is a successful deliverable.** Nothing below was tuned to reach it: the
thresholds were committed in `dccb379` and superseded in `3988b6a`, both before any number
existed, and **no bar was moved at any point**.

The headline is not the verdict. It is that **the mechanism's directional prediction came
true and the evidence still cannot carry it** — and that a third of the reason it cannot is
this apparatus's own bookkeeping, not the market.

---

## 1. The verdict, metric by metric

Judged on 79 return observations from 80 sessions, 2025-12-31 .. 2026-04-30.

| Metric | Required | Observed | |
|---|---|---|---|
| `deflated_sharpe` | ≥ 0.80 | **0.2413** | **FAIL, short by 0.559** |
| `cost_breakeven_multiple` | ≥ 3.0 | 3.765 | pass |
| `max_drawdown` | ≤ 0.10 | 0.0269 | pass |
| `risk_matched_increment` | ≥ 0.0 | **+0.1630** (+16.30%/yr) | pass |

Supporting numbers, none of them gated:

| | Candidate (gap-held) | Benchmark (intraday) |
|---|---|---|
| Net P&L on ₹10,00,000 | **+₹18,089.59** | **−₹26,789.80** |
| Annualised return | +5.79% | −10.51% |
| Annualised Sharpe | 0.919 (adjusted 0.929) | — |
| Total statutory costs | ₹6,632.30 | ₹7,088.30 |
| Peak margin | ₹4,59,260.62 | ₹4,10,836.92 |
| Fills attempted / filled | 190 / 188 | 200 / 200 |
| Infeasible | 2 (`no_bar`) | 0 |
| Settlements | **10 legs (5 straddles)** | 0 |

Other reported values: per-period Sharpe 0.0579, probabilistic Sharpe 0.7010, expected
maximum Sharpe under selection 0.1350, skew **+1.187**, kurtosis **12.59**, 5% expected
shortfall −1.025%, worst session −1.169%, Calmar 2.15, sessions under water 64,
cost share of gross 26.6%, benchmark scaled **1.35x** to match candidate volatility.

### What the failure actually says

**The two-clock prediction is visible in the data, and it is not subtle.** Holding the
identical straddle over only *non-trading* time returned **+5.79%/yr**; holding it over only
*trading* time returned **−10.51%/yr**. Same instrument, same strike rule, same size, same
eligibility, same cost model, same 80 sessions — one flag's difference. Risk-matched, the
gap arm adds **+16.30%/yr**. H26's annualised Sharpe of 0.92 is nearly double H1's 0.48.

**And it still fails, mostly because of the selection count.** The probabilistic Sharpe is
0.7010 — the evidence favours a positive true Sharpe about 70/30 on its own terms. The
deflation then subtracts the expected maximum of **five** logged trials (SR\* = 0.1350
against an observed 0.0579 per period) and the deflated Sharpe collapses to **0.2413**.

The gate said this would happen, in advance, in `3988b6a`: at N=4 even a *true* annualised
Sharpe of 3.0 has a median deflated Sharpe of 0.782, under the bar. The realised N was 5,
worse still. **This gate was close to unreachable before the run started, and the record
said so before the run started.** That is why the bar was not moved afterwards.

So the honest reading, exactly as pre-written: **a miss here is a statement about the
sample and the trial count, not a refutation of H26.**

---

## 2. Three things that cut against the result

Reported here rather than in a footnote, because each one weakens the headline.

**(a) Most of the candidate's P&L did not come from gap holds.** Pairing every entry with
its exit gives 44 completed round trips summing to **+₹7,748.90** net of costs. The run's
net P&L is +₹18,089.59. The difference — roughly **₹10,341, over half the total** — comes
from the 5 straddles that were never bought back and instead **cash-settled**, plus
end-of-window marks. Those five were held through an entire expiry session; they are not
pure overnight holds and they are not what the hypothesis is about. A P&L whose majority
comes from the contaminated minority is weak support for the clean claim.

**(b) The dose-response has the predicted sign and does not survive its own
decomposition.** Pre-registered as descriptive and ungraded, with the positive sign
committed in advance (`gate.toml`). Per straddle leg, net of that round trip's own costs:

| Gap spans | Straddles | Mean P&L per leg | Total |
|---|---|---|---|
| 1 calendar day | 30 | −₹16.62 | −₹997.01 |
| 2 calendar days | 2 | +₹725.02 | +₹2,900.07 |
| **3 calendar days (weekend)** | **11** | **−₹26.30** | −₹578.68 |
| 4 calendar days (holiday) | 1 | +₹3,212.26 | +₹6,424.52 |

OLS slope: **+₹211.56 per extra calendar day** — the predicted direction.

**It should not be believed.** The slope rests on **three straddles** in the two rarest
buckets, and the single 4-day observation alone contributes +₹6,424. The *weekend* bucket —
the archetypal calendar/trading wedge, and by far the largest multi-day category with 11
straddles — is **negative**. The mechanism's sharpest and best-populated prediction is the
one the data declines to support. The gate pre-committed that no claim about
holiday-extended gaps is admissible from this window; that stands, and it now also applies
to the slope those gaps produce.

**(c) The premium is compensation for a tail that did not arrive, and the correction cannot
see it.** Skew is **+1.187** and kurtosis **12.59** on a short-variance book — a short
straddle's economics are the other way round, so this shape says the sample contains the
decay and not the gap event being insured against. The adjusted Sharpe (0.929) can only
correct for a tail it observes. This was written into the record before the run for exactly
this reason: **a favourable number here is evidence the seller was paid in a window where
the insured event mostly did not happen**, which is not evidence the premium is free.

Add (d), from the machinery: the **`leverage_caveat` fired**. The benchmark was levered
**1.35x** to match the candidate's volatility, and whether that leverage is reachable under
margin is not checked — so **+16.30%/yr is an upper bound**, not an estimate.

---

## 3. The trial count, and what it cost

**5, read from the log, never typed.** The pre-registered inventory in `dccb379` said 3 and
the superseding gate in `3988b6a` said 4. **Both were wrong, and the disagreement is the
finding the inventory existed to surface:**

| # | Trial | Hypothesis | Outcome |
|---|---|---|---|
| 1 | `t_1e98d041f6…` | H1 `h_817b33ff…` | completed (replayed) |
| 2 | `t_78e63a635d…` | H26 v1 | **error**, no metrics — `TypeError` in the exit path |
| 3 | `t_26ddf64a12…` | H26 v1 | **error**, no metrics — expiry-eve entry had no exit |
| 4 | `t_afca6799f0…` | H26 v2 | completed — candidate |
| 5 | `t_16abd0ac98…` | H26 v2 | completed — benchmark |

Rows 2 and 3 are crashed runs that computed nothing and produced no number anyone could
select on. **They were kept anyway.** Deleting rows from an append-only research log to
reach a pre-registered count is the flattering move even when justified, and the cost of
keeping them is only a harder bar.

That cost turned out to be the whole verdict. Had the family held the 3 rows originally
pre-registered, SR\* would have been materially lower. **Two coding bugs and one honest
correction consumed the hypothesis's statistical budget.** That is a real property of this
design worth stating plainly: under a deflated-Sharpe gate, *every crashed run permanently
taxes the hypothesis*, and the tax is indistinguishable from evidence against it.

Whether that is the right design is a question for the platform, not for this record. It is
noted as a follow-up rather than resolved by quietly deleting a row.

---

## 4. The sample: 45 observable gaps, not 79 transitions

The unit of evidence is the overnight transition held, not the session. The funnel:

```
79 session transitions in-sample
→ 63 sessions whose front expiry is after the session date   (17 expiry sessions removed)
→ 50 sessions surviving the ≥2-calendar-day entry guard      (13 expiry-eve removed)
→ 45 observable gaps   (4 residual holiday cases + 1 dangling final session)
```

**Both boundaries of the weekly expiry cycle are dark, for two different reasons.** No entry
*on* expiry day: the contract settles that evening. No entry the session *before* it: the
expiring contract is **dropped from the instrument master on its expiry date**, so the
buy-back cannot even be expressed. With Tuesday expiries, every Monday and every Tuesday
entry is absent — surviving entry weekdays are Wednesday, Thursday and Friday only.

This is a **capture/refdata limitation** (front weekly expiry only, spec §3 C1), not a
market fact. Nothing here is evidence about post-expiry or pre-expiry overnights, and the
missing Tuesday→Wednesday gap is a distinctive population — the first night of a new front
week after an IV reset.

Realised feasibility was otherwise clean: 188 of 190 candidate intents filled, the 2 misses
being `no_bar`, zero `group_incomplete`, zero resized, zero capped-to-zero.

---

## 5. Every honesty stamp on this verdict

Sixteen stamps. The cost/settlement set is H1's and unchanged in meaning:

| Stamp | Cost |
|---|---|
| `stt.sell_option_premium:corroborated` | Secondary-sourced rate |
| `nse.transaction_charge.options:corroborated` | Same |
| `sebi.turnover_fee:corroborated` | Same |
| `gst.broking_services:corroborated` | Same |
| `settlement.mean_of_underlying_minute_close_over_window:corroborated` | Settlement formula |
| `settlement.exchange_charge_assumed_not_levied:unverified` | **Unverified** assumed-zero charge |
| `margin.simplified_approximation:unverified` | **Unverified**; why peak margin is never a return denominator |
| `corpus.open_interest_not_divisible_by_lot_size:unverified` | **Unverified** OI unit convention |

**Stamp duty remains the only primary-sourced statutory rate in the stack**, and the only
one raising no caveat.

The `benchmark:`-prefixed duplicates carry six of those eight — **the benchmark carries no
settlement stamps at all**, because the intraday arm is flat at every close and never
settled. That asymmetry is itself evidence the two arms behaved as designed.

Statistical: `dsr.sharpe_variance_assumed` (the deflation could not read a cross-trial
Sharpe variance, so it used the null sampling variance 1/78 = 0.01282) and
`epochs.dates_not_primary_sourced` (the epoch table is secondary-sourced throughout,
including `stt_rise_2026`, the boundary this window crosses).

**Absent, and worth saying so:** `costs.uniformly_allocated` — costs were bucketed to the
session that paid them. `feasibility.not_reported` — real counts were reported.

---

## 6. The holdout is intact

**Not read. 2026-05-01 .. 2026-08-12, 71 sessions, sealed.**

H26 is an amendment, so it shares H1's family and H1's sealed months. When the corpus was
backfilled to 2026-08-12, the tempting move was to push `holdout_first_date` to 2026-06-13
and harvest 29 more in-sample sessions for a question already short of evidence. **It was
refused.** That field is editable and bound to no content-addressed record, so it is exactly
the channel through which a disappointing result gets rescued; using it once would establish
that a holdout is negotiable whenever someone wants more data.

The boundary was inherited unchanged and the backfill was spent on the other side: **the
family's holdout grew from 29 sessions to 71** (40 observable gaps). The price was paid
in-sample and is visible in §1.

A candidate that could not clear its in-sample bar has nothing for the holdout to confirm.
`decide()` reaches for it only from a PASSED verdict, and `grade_holdout` writes its touch
row *before* grading — so a failed holdout grading destroys it as surely as a successful
one.

---

## 7. What the operator should do next

1. **The trial-log defect is the most urgent item here, and it is bigger than H26.** H1's
   canonical log did not exist: `*.db` is gitignored, the log lived in the H1 worktree, and
   that worktree was removed during post-merge cleanup. `research/h1/trial_log_export.json`,
   which H1's `DECISION.md` names as the committed substitute, **was never committed**. So
   H1's trial count of 1 — the number its deflated Sharpe was computed against — survived
   only as an assertion inside `decision.json`. This branch applies the fix C6's own review
   prescribed and nobody had applied: the canonical path is now pinned in config at
   `/home/qa/runtime/data/research/trial_log.db`, outside every worktree, and each decision
   commits `trial_log_export.json` so the count is auditable from the repo alone.
   **H1's row here is a hash-gated reconstruction, not the original evidence** — its
   `created_at` and `code_sha` are provably wrong, stamped by the replaying process. The
   hash gate validates H1's *record text*, nothing about the row.

2. **Decide whether crashed runs should deflate.** §3 is the live question: two bugs cost
   this hypothesis more Sharpe than the market did. Options include logging crashed
   attempts under a non-selecting outcome the deflation excludes, or splitting the log's
   "how many things were tried" from "how many results existed to choose among". Either is
   a design change and belongs in a proposal, not in a decision record.

3. **Capture the missing expiry boundary.** Extending capture past the front weekly expiry
   would restore both dark boundaries and add the Tuesday→Wednesday population outright.
   That is spec §3 C1 and it is the cheapest large increase in observable gaps available.

4. **Resolve the quote-data question (spec §9).** A breakeven of 3.76x is reassuring only
   about the *statutory* stack. H26 crosses the spread four legs a session and every fill is
   a spread-free bar close, so this is the hypothesis most exposed to that gap in the model.
   Under H26, unlike H1, the caveat is load-bearing rather than decorative.

5. **Do not re-run H26 on this corpus with a softer bar.** C6 would refuse it — the gate is
   bound to the content-addressed record, so softening a threshold changes the id and the
   binding check fails.

---

## 8. Reproducing this

> **Do not run the decision against the canonical log.** It appends two more trials, moving
> the family count past the 5 this verdict was computed against. Read `decision.json`, or
> point `trial_log_path` at a throwaway file first.

```bash
uv run python -m xman_research.h26.calibrate_thresholds     # synthetic threshold calibration
uv run python -m xman_research.h26.run_decision --json-out research/h26/decision.json
uv run pytest tests/test_h26_decision.py -q
```

`research/h26/decision.json` carries the full machine-readable payload;
`research/h26/trial_log_export.json` is the committed, auditable copy of every family row at
the moment of decision — including `code_sha`, `code_dirty` and `error`, the fields H1's
missing export could not have restored.

The descriptive dose-response in §2(b) was recomputed on a **throwaway** log so the
canonical count stayed at 5; its run fingerprint was verified identical to the graded
candidate run (`bd520ab4319637bf…`).
