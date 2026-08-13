# H1 — the decision

| | |
|---|---|
| **Hypothesis** | `h_817b33ff6b9f68e288161f5990739744` — NIFTY index variance risk premium |
| **Outcome** | **FAILS A THRESHOLD** — spec §6, row 2 |
| **Next** | Next hypothesis. The loop works. |
| **Holdout** | **NOT SPENT.** 2026-05-01 .. 2026-06-12 remains unread. |
| **Graded** | 2026-08-13T01:31:38.831267+00:00 |
| **Trial** | `t_1e98d041f6b344628ab50d401e8d302f`, created 2026-08-13T01:31:38.769791+00:00 |
| **Run fingerprint** | `2e0bb9e178e72cc6d04059eed2cf410c45dc5bf0df4bae1a15667f5815ce2d97` |

The MVP is done in the sense spec §6 defines: it has produced one decision on H1, and the
operator can say which of the four it was. It failed one pre-registered threshold — the
deflated Sharpe — and passed the other three. **A failure is a successful deliverable**:
the machinery ran end to end, refused nothing it should have graded, graded nothing it
should have refused, and produced a number that can be argued with.

Nothing below was tuned to reach this result. The thresholds were committed in `1efb580`,
before the first run; the run is `1efb580..HEAD`.

---

## 1. The verdict, metric by metric

Judged on 79 return observations from 80 NIFTY sessions, 2025-12-31 .. 2026-04-30.
No walk-forward: nothing is fitted, so there is no in-sample fit for an out-of-sample
fold to test, and folding would have spent sessions from an already-short sample.

| Metric | Required | Observed | |
|---|---|---|---|
| `deflated_sharpe` | ≥ 0.90 | **0.6043** | **FAIL, short by 0.296** |
| `cost_breakeven_multiple` | ≥ 2.0 | 12.889 | pass |
| `max_drawdown` | ≤ 0.10 | 0.0611 | pass |
| `risk_matched_increment` | ≥ 0.0 | 0.0 | pass (structurally — see §4) |

Supporting numbers, none of them gated:

| | |
|---|---|
| Annualised Sharpe | 0.480 |
| Annualised **adjusted** Sharpe (skew/kurtosis corrected) | 0.478 |
| Per-period Sharpe | 0.03021 |
| Probabilistic Sharpe | 0.6043 |
| Expected shortfall (5%) | −2.031% |
| Worst session | −2.146% |
| Net P&L | ₹16,159.42 on ₹10,00,000 starting cash (+1.62% over ~4 months) |
| Total statutory costs | ₹1,624.15 (0.162% of capital) |
| Peak margin | ₹4,76,378.63 |
| Sessions | 80 run, 36 entry legs (18 straddles), 34 settlements |
| Feasibility | 36 fillable, 0 resized, 0 no-bar, 0 no-liquidity, 0 capped-to-zero, 0 group-incomplete |

### What the failure actually says

**The premium showed up. The evidence did not.** The book made money, the drawdown stayed
inside the ruin bar, and the edge survives its modelled costs rising almost thirteenfold.
What it does not do is separate itself from noise: an annualised Sharpe of 0.48 over 79
observations yields a deflated Sharpe of 0.60, and the bar was 0.90.

The shortfall is not marginal. With one logged trial the deflation has nothing to deflate
(`expected_max_sharpe = 0.0`, so DSR is exactly the probabilistic Sharpe here), and the
probabilistic Sharpe is `Φ(SR_period × √(n−1))` to within 0.001 of the reported value.
Clearing 0.90 at 79 observations needs a per-period Sharpe of 0.145 — an **annualised
Sharpe of 2.30**, nearly five times what was observed. Conversely, at the observed effect
size:

| Sessions | Median probabilistic Sharpe (60 synthetic draws at this effect size) |
|---|---|
| 79 (what we have) | 0.651 |
| 500 (≈2 years) | 0.875 |
| **1,000 (≈4 years)** | **0.901** |
| 1,500 (≈6 years) | 0.922 |

So: about **four years of daily sessions** would give a strategy with this true effect size
even odds of clearing the bar, and a run whose point estimate stayed exactly at 0.48
annualised would need about **seven years** (n ≈ 1,800) before the estimate itself reached
0.90. We have four months.

**This is a statement about the sample, not a refutation of H1.** The gate file said so in
advance, before any number existed: *"at 80 sessions this test cannot distinguish a true
annualised Sharpe of 1.0–1.5 from zero at any bar that also controls false positives. A
miss at 0.90 is evidence of insufficient data, not evidence of no effect."* That sentence
was written to stop exactly the misreading this result invites, and it is honoured here.

Equally, nothing licenses reading the positive P&L as support. +1.62% over four months from
18 straddles is entirely consistent with a zero premium and a lucky window; that is what a
deflated Sharpe of 0.60 means — a 40% chance the true Sharpe is not positive at all.

---

## 2. The holdout is intact

**Not read. Not touched. 2026-05-01 .. 2026-06-12, 29 sessions, still sealed.**

This is deliberate and it is the right disposal of the resource. `Validator.grade_holdout`
writes its touch row *before* it grades, so a holdout grading that raises for any reason
leaves the months read and the log recording the read; the retry then sees that touch and
refuses. **A failed holdout grading destroys the holdout as surely as a successful one.**
`decide()` needs a holdout verdict only when the in-sample verdict PASSED, so the runner
reaches for it on that branch alone.

A candidate that could not clear its in-sample bar has nothing for the holdout to confirm.
Spending it here would have converted an intact one-shot resource into a second
underpowered number.

**The one contact that did happen, stated so nobody has to find it.** While sizing the
split, `SessionStore.resolve()` was called on `2026-05-01 .. 2026-06-12` and reported 29
complete sessions. That is a question to the *trading calendar and the file manifest* — how
many sessions exist and are any missing — not a read of a single price, return or contract.
No backtest ran over those dates, no trial in the log names them, and `inspect_holdout`
reads the log. Counting the days in an envelope is not opening it, but the distinction is
worth naming rather than leaving to be discovered.

The holdout path is not untested code, though — it would be a poor claim to say "we never
ran it" and leave it unproven. `tests/test_h1_decision.py` executes the whole branch against
the real corpus on throwaway windows, a throwaway log and a deliberately permissive gate, so
the first real execution of that code will not be paid for with the real holdout.

---

## 3. Every honesty stamp on this verdict

C6 carries a run's caveats into the verdict verbatim and refuses to hand back a clean
`float()` while any remain. All eighteen, and what each one costs:

**Cost and settlement model** (candidate and benchmark carry these identically; the
`benchmark:`-prefixed duplicates are the same eight stamps, prefixed because whose caveat it
is matters):

| Stamp | What it means |
|---|---|
| `stt.sell_option_premium:corroborated` | Secondary-sourced rate, cross-checked, not read off a primary circular |
| `nse.transaction_charge.options:corroborated` | Same |
| `sebi.turnover_fee:corroborated` | Same |
| `gst.broking_services:corroborated` | Same |
| `settlement.mean_of_underlying_minute_close_over_window:corroborated` | The settlement formula, corroborated not primary |
| `settlement.exchange_charge_assumed_not_levied:unverified` | **Unverified.** An assumed-zero charge at settlement |
| `margin.simplified_approximation:unverified` | **Unverified.** Margin is an approximation, which is why peak margin is reported and never used as a return denominator |
| `corpus.open_interest_not_divisible_by_lot_size:unverified` | **Unverified.** Vendor open-interest units do not divide by the lot size, so the participation cap's OI leg rests on an unconfirmed unit convention |

Note what is **not** in that list: **stamp duty is the only statutory rate in the stack that
is primary-sourced**, and it is therefore the only one that raises no caveat.

**Statistical**

| Stamp | What it means |
|---|---|
| `dsr.sharpe_variance_assumed` | The deflation could not read a cross-trial Sharpe variance from the log — that needs two or more trials that recorded a Sharpe with a declared periodicity, and there is one trial. It fell back to the null sampling variance, 1/78 = 0.01282 |
| `epochs.dates_not_primary_sourced` | The epoch boundary table is secondary-sourced throughout, including `stt_rise_2026` (2026-04-01), the one this window crosses |

**Not stamped, and worth saying so:** `costs.uniformly_allocated` is **absent**. The adapter
bucketed costs by the session that paid them, from the fill and settlement records, rather
than smearing `total_costs` evenly. The cost-breakeven multiple is the MVP's headline
number and it got the honest cost allocation.

`feasibility.not_reported` is also absent: the run reported real feasibility facts rather
than staying silent, and the infeasibility side is clean — **0 of 36 intents infeasible**,
read directly from the verdict counts.

**The stale-mark count is not evidenced here, and this record will not assert it.** C5's
`metrics()` does not surface `sessions_with_stale_marks`, so `decision.json` does not carry
it and neither does the verdict. What *is* evidenced is only the bound: the not-evaluable
rule on stale marks did not fire, so the stale fraction is at most the 0.20 limit. An
earlier draft of this section claimed "0 of 80 sessions stale"; that number was never read
from the payload and has been withdrawn rather than re-derived, because re-deriving it means
re-running the backtest, and re-running it against the canonical log appends a trial and
moves the selection count this whole verdict rests on. **Follow-up: surface
`sessions_with_stale_marks` in the run summary, so the next decision can state it instead of
bounding it.**

---

## 4. Four disclosures that qualify this verdict

**(a) The trial count is 1, and that makes the DSR weaker than it looks.** Read from the
log, never typed — `count_family_trials` returned 1, the single row above. With N=1 the
deflation is inert (`expected_max_sharpe = 0.0`) and the deflated Sharpe collapses to the
probabilistic Sharpe. It is also a *lower bound* by construction: the canonical log is new,
and any exploration done in this repository's test fixtures ran against temporary databases
that this count cannot see. The hypothesis was **not** reworded to reset a family count —
`h_817b33ff6b9f68e288161f5990739744` is the first and only H1 record, and the documented
C4 hole was left unused.

**(b) The risk-matched increment could not have failed.** The MVP expresses H1 as an
unconditional short ATM straddle, which is precisely what C5 names as the naive always-on
benchmark. Candidate and benchmark are the same portfolio, over the same window, under the
identical cost model — literally the same run, presented under two labels. The increment is
therefore exactly 0.0 and 0.0 ≥ 0.0 passes. The criterion is recorded rather than omitted so
that it is on the books *before* the first conditional variant exists to be judged by it;
until then it carries no information, and this record says so rather than letting a "pass"
imply otherwise.

**(c) A premise in the pre-registered `max_drawdown` rationale was wrong.** The gate file
justified the 0.10 bar by arguing that one NIFTY lot ties up "around 15%" of the ₹10,00,000
base, making a 10% drawdown roughly two-thirds of posted margin. The run reports peak margin
of **₹4,76,378.63 — 47.6% of capital**, not 15%. The reasoning behind the number was
therefore wrong by a factor of three. Disclosed rather than quietly corrected: the threshold
passed comfortably either way and did not decide the verdict, and editing a pre-registered
rationale after seeing the run is the move this whole apparatus exists to prevent. The
correct reading of the observed 6.1% drawdown is that it is about an eighth of posted
margin, not two-thirds. **Follow-up: re-derive the bar from measured margin before the next
hypothesis, and record the change as an amendment.**

**(d) The window pools two cost regimes.** It crosses `stt_rise_2026` (2026-04-01), under
the justification recorded in the gate file: C5 charged each side at its own date-effective
rate within the one run, a tax-rate change alters cost level rather than the traded object,
and the cost-breakeven multiple is the metric that absorbs a change in cost level. The
epochs spanned are recorded on the verdict: `2026-01-01..2026-03-31` and
`2026-04-01..2026-04-30`.

---

## 5. What the operator should do next

**Do not re-run H1 on this corpus with a softer bar.** That is the one move that would
invalidate everything above, and C6 would refuse it anyway — the gate is bound to the
content-addressed record, so softening a threshold changes the hypothesis id and the binding
check fails.

In rough order of expected value:

1. **Capture is the binding constraint, and it is losing value every day.** The whole
   verdict reduces to *79 observations is not enough*, and ~42 sessions after 2026-06-12
   were lost to a vendor outage that is now resolved. Two actions follow, and the first is
   urgent in the irreversible sense spec §1.2 names: **confirm nightly capture is running
   again and alerting on gaps**, and **backfill history as far as the vendor allows**. At
   the observed effect size the test needs on the order of four years of sessions; the
   corpus holds five and a half months. Nothing else on this list moves the answer as much.

2. **Resolve the quote-data question (spec §9).** The cost-breakeven multiple of 12.9x is
   reassuring only about the *statutory* stack. Fills are at the bar close with no spread,
   no impact and no slippage — the three costs a real short-straddle book actually pays.
   With quotes, the breakeven becomes a calibration instead of an assumption, and spec §2.1
   stops being the headline caveat of every result this platform produces.

3. **Then, and only then, condition the signal.** The India refinement recorded on the
   hypothesis — Sankar et al. (2020), only *continuous* variance forecasts variance-swap
   returns, jumps do not — is the obvious first variant: enter only when the ATM implied
   variance exceeds a trailing continuous realised variance by some margin. That variant is
   the first thing the naive-benchmark criterion can actually judge, since the benchmark
   would then be a genuinely different portfolio. It must be registered as an **amendment**
   to `h_817b33ff6b9f68e288161f5990739744`, not as a fresh record, so the trial count keeps
   accumulating against the family.

4. **Fix the two `unverified` inputs that are cheapest to close.** The assumed-zero exchange
   charge at settlement and the open-interest unit convention are both single lookups
   against a primary source, and both currently stamp every verdict this platform emits.

5. **Re-derive the `max_drawdown` bar from measured margin** — see disclosure (c).

**The holdout stays sealed** until a candidate passes its in-sample bars. It is 29 sessions
and it cannot be re-cut.

---

## 6. Reproducing this

> **Do not run the second command against the existing canonical log.** It appends a trial,
> moving the family count from 1 to 2 — the very selection count the deflated Sharpe above
> was computed against — and the reproduction would then disagree with the record it was
> meant to reproduce. Move or delete `research/h1/h1_research.db` first, or just read
> `decision.json`.

```bash
uv run python -m xman_research.h1.calibrate_thresholds     # the synthetic threshold calibration
uv run python -m xman_research.h1.run_decision --json-out research/h1/decision.json
uv run pytest tests/test_adapter.py tests/test_h1_decision.py -q
```

`research/h1/decision.json` carries the full machine-readable payload: the verdict, every
threshold result, both provenance blocks, the feasibility counts and every row of the trial
log at the moment of decision.

**One caveat on reproduction.** The canonical trial log (`research/h1/h1_research.db`) is
not committed — `*.db` is gitignored repo-wide and forcing an exception for one file would
change a repo convention to suit one branch. A fresh clone therefore starts with an empty
log, and re-running `run_decision` there would log its own trial and could reach a different
deflated Sharpe as the family count grows. The committed `decision.json` is the record of
what the log held when the decision was taken; `tests/test_h1_decision.py::test_same_inputs_same_verdict`
pins determinism end to end on temporary logs, and the backtest fingerprint above pins the
run itself.
