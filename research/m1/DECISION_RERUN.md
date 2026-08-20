# M1 — near-week short ATM straddle, re-run after the wedged-book fix (issue #26)

| | |
|---|---|
| Record | `h_0b2ecbbc4bddb543599add3968e0cf88` (amendment of H1 `h_817b33ff6b9f68e288161f5990739744`) |
| Gate | `research/m1/gate.toml`, commit `1921a5b` — **REUSED, NOT REWRITTEN**, see §2 |
| Window | in-sample **2024-10-01 .. 2026-04-30**, 385 sessions, 384 return observations |
| Holdout | 2026-05-01 .. 2026-08-03, 64 sessions — **STILL SEALED, NOT READ** |
| Family trials at grading | **9** (was 8; the fix cost one — §8) |
| Trial | `t_868db3c902904004b1b183bbd4b834dc`, graded 2026-08-20 |
| Fingerprint | `8eaadc6bec591b88bc75c532e044782bbeb005754b3ed3431898be1e385fa74e` |
| **OUTCOME** | **FAILS_THRESHOLD** — on two thresholds, not one |

**This record does not replace `research/m1/DECISION.md`, and that file is not edited.**
The wedged run happened; its record stays exactly as written, on the branch that produced
it. This is the posture `gate.toml` takes toward `research/h1/gate.toml` — a superseded
record that stays in the repository saying what it said is worth more than a corrected one
that hides that the correction was needed.

---

## 1. The defect, measured rather than inferred

Issue #26 attributes the wedge to the **2025-09-01 expiry Thursday→Tuesday transition**,
on the strength of 162 zero-return sessions beginning exactly at that date. **That is not
the cause, and the dead region is four months longer than reported.**

The straddle that wedged the book was entered on **2025-04-24** into the **2025-04-30**
expiry. 2025-04-30 is one of the three sessions the run's own gap policy names as missing
from the corpus. `_settle_expiring` keys on `position.contract.expiry == session.session_date`,
so a run that never *visits* the expiry date never settles against it: the engine walked
past 2025-04-30 and the straddle stayed on the book. Its legs print no bar from 2025-04-25
onward — verified directly, not assumed — so equity was flat from that session, and M1
enters only when flat, so nothing traded again.

The evidence chain, each link measured:

| | |
|---|---|
| entry that wedged | 2025-04-24, ATM straddle on the **2025-04-30** expiry |
| 2025-04-30 in corpus | **no** — one of the three gap-accepted dates (2024-11-20, 2025-04-30, 2025-05-08) |
| legs print bars after 2025-04-24 | **no**, on every session 2025-04-25 .. 2025-05-15 checked |
| sessions from 2025-04-25 to window end | **248 of 385 = 64.4%** |
| wedged run's measured stale-mark fraction | **64.7%** (249 sessions) |

248 against 249 is the onset. The extra session is a stale mark elsewhere in the window.
The two epochs the issue names as silent are simply the two that lie *wholly* inside the
dead region; `intraday_position_limits_2025` was 86/101 dead and was reported as a live
epoch with a −1.633 Sharpe, which is why the true onset was invisible in the table.

**2025-09-01 has nothing to do with it.** The correlation is an artefact of the epoch
partition. What the date does mark is a boundary the eye reaches for — which is the
general warning: the wedged run's own per-epoch table was the thing that made a
four-month-old defect look like a regime-change defect.

**A second missing expiry, which the issue does not mention.** 2025-05-08 is also absent
and is also a listed weekly expiry (2024-11-20, the third gap, is not an expiry and is
harmless — the gate already argued this and was right). Two consecutive cycles are
unsettleable, not one.

**The bug was documented as intended behaviour.** `test_a_gap_can_be_accepted_only_against_a_written_reason`
asserted `result.daily[-1].open_positions == 2` and its docstring called that "a partial
window visible in the output". Accepting a missing *observation* was silently extended to
accepting an unclosable *position*, and a test locked it in.

## 2. What the engine now does, and why not the alternatives

Two refusals at different blast radii. Neither invents a payoff.

1. **`Feasibility.UNSETTLEABLE`** — the engine refuses to *open* a position whose expiry is
   not a session this run visits. Counted in `feasibility_counts` and `fills_infeasible`,
   broken out as `fills_unsettleable`, stamped `corpus.expiry_session_absent`.
2. **`PositionOutlivedItsExpiryError`** — raised the moment a session opens holding a
   contract that expired earlier. The invariant behind (1), and the loud failure issue #26
   asks for.

**Why not raise and stop the run, only.** It is the cleanest posture and it was rejected on
one ground: a corpus missing one expiry session would make a pre-registered 385-session
window unrunnable, and "one absent file" is not a reason to be unable to measure the other
384 sessions. The raise is kept as the invariant, where it costs nothing when the screening
works and stops everything when it does not.

**Why not force-settle at the last mark.** A held-to-expiry straddle's entire payoff is
−|S_T − K| at the settlement value of the *missing* session. The last mark is a six-day-old
option price standing in for the one number the trade exists to measure. That is not a
stamped estimate; it is a fabricated result, fabricated on precisely the observation whose
absence caused the problem.

**Why reading the run's calendar is not lookahead.** It reads which files exist, never their
contents — no price, no volume, no outcome. A run already conditions on apparatus facts
everywhere: `accept_gaps` names the missing sessions, the cost stack refuses dates outside
its rate schedule, the settlement table refuses rules it has not implemented. This is the
same kind of fact at the one place it was missing.

**It does change the traded population**, which is why it is a counted verdict rather than a
silent skip: 14 legs over 7 sessions, all visible in the output. Whether that fraction is
tolerable is the gate's call through `max_infeasible_fraction`, not the engine's.

**The classification of `unsettleable` as *infeasible* was committed before this run**
(commit `5777fe8`, ahead of any number). The argument for excluding it — like `settled`, it
is not the market's verdict — is real and was rejected: `infeasible_fraction` feeds the
not-evaluable rule, whose whole job is to notice when too much of a run is not a
measurement, and excluding it would have been the one classification incapable of tripping
the gate.

**The window's far edge is the opposite case.** A position expiring *after* the run ends is
kept, not refused — otherwise the window's right-hand edge silently decides which trades a
strategy takes — and is now reported in `open_at_end` with a `book.open_at_run_end` stamp.
This run ends holding two legs of the 2026-05-05 expiry, entered legitimately.

**Gate reuse, proved mechanically.** `1921a5b` was cherry-picked and
`git show 1921a5b:research/m1/gate.toml | diff - research/m1/gate.toml` is **empty**. Same
window, same thresholds, same holdout boundary, same gap policy naming the same three dates.
Nothing about the window changed; a bug was fixed. Writing fresh thresholds after a failed
run is the move pre-registration exists to prevent.

## 3. The denominator — `sessions_run` stays at 385, and it is no longer the question

Issue #26 asks whether `sessions_run` should exclude sessions where the strategy could not
act. **It should not, and after the fix the premise has largely dissolved.**

- The 162 no-op sessions were a **defect**, not a property of the strategy. They are gone:
  the book now holds a position on **297 of 385** sessions and candidate exposure is
  **0.9636**, against 0.3516 in the wedged run.
- The 7 sessions where entry is refused are real no-ops, and they are reported as a
  descriptive count (`fills_unsettleable = 14` legs) and folded into `infeasible_fraction`
  — where the gate can already act on them. That is the honest place for them.
- **Decisive:** the gate is pre-registered for **385 sessions / 384 observations**, and both
  PSR and DSR depend on n. Redefining the denominator would change n and break the match
  with the reused gate — the one thing that must not happen here. A denominator changed
  after seeing a result is a threshold changed after seeing a result.

Stated plainly so it is not a silent choice: `sessions_run` counts every session the run
walked, including the 7 it declined to trade.

## 4. Every metric against its threshold

| metric | observed | required | verdict |
|---|---:|---:|---|
| `deflated_sharpe` | **0.342328** | ≥ 0.90 | **FAIL** |
| `cost_breakeven_multiple` | **23.4384** | ≥ 2.0 | pass |
| `max_drawdown` | **0.120334** | ≤ 0.10 | **FAIL** |
| `risk_matched_increment` | **0.0000** | ≥ 0.0 | pass — structurally cannot fail |

`not_evaluable_reasons` is **empty**. Both fourth-outcome checks were computed and cleared:

| | observed | limit |
|---|---:|---:|
| stale-mark fraction | **1.82%** (7 / 385) | 20% |
| infeasible fraction | **7.87%** (14 / 178) | 10% |

Supporting statistics, none of them gated:

| | |
|---|---:|
| annualised Sharpe | 0.892802 |
| annualised adjusted Sharpe | 0.882604 |
| observed Sharpe per period | 0.056241 |
| **probabilistic Sharpe (PSR)** | **0.856334** |
| expected max Sharpe (SR\*) | 0.077708 /period ≈ 1.233 annualised |
| Sharpe variance | 0.0026110 (`dsr.sharpe_variance_assumed`) |
| skew / kurtosis | −1.1553 / 7.5077 |
| Calmar | 0.808553 |
| 5% expected shortfall | −1.8580% |
| worst session | −3.8653% |
| sessions under water | 346 / 384 |
| candidate exposure | 0.963542 |
| net P&L | ₹1,52,604.75 on a ₹10,00,000 base |
| peak margin | ₹4,76,378.63 (47.6% of capital) |
| return on peak margin | 32.03% |
| total costs | ₹6,674.39 — 4.267% of gross |
| STT / STT on exercise | ₹1,897.23 / ₹0.00 |
| fills attempted / filled / unsettleable | 178 / 164 / 14 |
| settlements | 162 |
| positions open at run end | 2 (`NIFTY-05May2026-24100-CE`/`-PE`) |

**The failure is on two thresholds, and the drawdown one is the more informative.** The gate
pre-wrote the reading: *"if M1 fails on max_drawdown alone, the correct reading is that a
19-month unconditional short-straddle book drew down past a tenth of its capital, which is a
true and useful finding and not an artefact of the bar."* That is now the measured result —
12.03% — and it was reachable only because the book was actually trading. The wedged run's
9.435% "pass by 0.6 pp" was a drawdown taken over a book that was flat for 64% of the window.

## 5. Against the wedged run, and against H1

| | H1 | M1 wedged | M1 re-run |
|---|---:|---:|---:|
| return observations | 79 | 384 | 384 |
| family trials (N) | 1 | 8 | **9** |
| candidate exposure | — | 0.3516 | **0.9635** |
| stale-mark fraction | — | **64.7%** | **1.82%** |
| annualised Sharpe | 0.4796 | 0.1957 | **0.8928** |
| PSR | 0.6043 | 0.5941 | **0.8563** |
| DSR | 0.6043 | 0.1149 | **0.3423** |
| DSR bar | 0.90 | 0.90 | 0.90 |
| PSR − DSR spread | 0.0000 | 0.4792 | **0.5140** |
| cost-breakeven | 12.89 | 9.986 | **23.44** |
| max drawdown | ~6.1% | 9.435% | **12.03%** |
| outcome | FAILS_THRESHOLD | NOT_EVALUABLE | **FAILS_THRESHOLD** |

Three things worth saying about this table.

**The strategy is far better than the wedged run made it look, and still misses.** Sharpe
nearly quintuples (0.196 → 0.893) and PSR moves from 0.594 to 0.856 — the unwedged M1 is a
genuinely positive-expectancy book, +15.3% on capital over 19 months at 47.6% peak margin.
It fails anyway, and it fails on evidence rather than on an apparatus artefact.

**The deflation is now doing real work, and it is the larger of the two gaps.** At N=9,
SR\* = 0.0777 per period ≈ 1.233 annualised. M1 delivered 0.893. PSR alone — no
multiple-testing correction at all — is 0.856 and would also have missed the 0.90 bar, but
only just; the correction is what makes the miss unambiguous. The wedged record's
conclusion that "the correction and the raw evidence agree" survives, but the reason
changes: there, the measured Sharpe was an artefact; here it is real and still below the
selection threshold nine trials imply.

**The gate's own calibration says what this miss means.** At n=384, N≈6-9, a true annualised
Sharpe of 2.0 clears 0.90 in 60% of draws and 3.0 in 87.5%. So this is evidence against a
true Sharpe of 2.0 or better. It remains uninformative below roughly 1.0 — and 0.893 sits
exactly in that uninformative band. **The honest summary is not "M1 does not work"; it is
"M1's effect, if real, is the size this apparatus was built unable to resolve."**

## 6. Per-epoch breakdown — DESCRIPTIVE, UNGRADED

Pre-registered in `gate.toml` before any of it was computed. **No threshold reads this table
and it cannot change the outcome.** The pooled verdict is the graded one.

| epoch | start | end | sessions | net return | ann. Sharpe | max DD | skew | kurtosis |
|---|---|---|---:|---:|---:|---:|---:|---:|
| `stt_rise_2024` | 2024-10-03 | 2024-11-19 | 32 | +3.183% | **+2.099** | 2.92% | −1.82 | 9.89 |
| `weekly_expiry_cull_2024` | 2024-11-21 | 2025-02-07 | 56 | +6.668% | **+2.516** | 3.22% | −0.33 | 3.61 |
| `calendar_spread_relief_removed_2025` | 2025-02-10 | 2025-03-28 | 33 | −2.591% | **−2.079** | 4.81% | −1.12 | 4.26 |
| `intraday_position_limits_2025` | 2025-04-01 | 2025-08-29 | 101 | +1.037% | +0.224 | 10.06% | −2.16 | 11.40 |
| `nse_expiry_tuesday_2025` | 2025-09-01 | 2026-03-30 | 142 | **+0.722%** | **+0.124** | 5.85% | −0.61 | 4.98 |
| `stt_rise_2026` | 2026-04-01 | 2026-04-30 | 20 | **+5.807%** | **+8.037** | 0.94% | +0.33 | 3.07 |

**The last two rows are 162 sessions nobody has ever seen.** They are the largest and the
smallest slices in the table, and they point the same way: positive, and — for the
142-session one, the only slice here long enough to carry a Sharpe at all — *small*. A
+0.124 annualised Sharpe over the Tuesday-expiry regime is the single most consequential
number in this document, because it is the regime the market is currently in.

**The first three rows are byte-identical to the wedged run.** That is the control: the fix
is inert before 2025-04-25 and changes only what came after. `intraday_position_limits_2025`
moves from −1.633 to +0.224 because 86 of its 101 sessions were dead, not because anything
about April–August 2025 was re-measured.

**On the pre-committed sign, which the earlier table reported wrong twice.** The prediction
was a positive mean in every epoch, with `weekly_expiry_cull_2024` named the most likely
exception. Re-measured: **the sign holds in 5 of 6 epochs**, which is a substantially better
showing than the wedged table's 2-of-4-plus-2-silent — but the *named* exception is wrong
again, and in the same direction: the cull epoch is once more the strongest of the six
(+2.516), and the one negative epoch is `calendar_spread_relief_removed_2025`, which nobody
predicted. So one half of the prediction is now right and the other half is wrong for the
second time on the same clause. A mechanism that predicts the sign but never the exception
is not yet a mechanism that predicts the exception.

**Two cautions carried forward.** `stt_rise_2026`'s +8.037 Sharpe is 20 sessions and the gate
says in advance that nothing under ~60 sessions carries a readable Sharpe — it is noise with
a decimal point. And the 2025-02-10 sign flip still coincides with an epoch date the gate's
own table flags `confidence="secondary"` and possibly wrong by nine days.

## 7. Stamps

Eleven `unverified_inputs`, two of them new from this fix:

```
book.open_at_run_end:unverified                        <- NEW: 2 legs held past the window
corpus.expiry_session_absent:unverified                <- NEW: 14 legs refused, 7 sessions
corpus.declared_lot_size_contradicted:unverified
corpus.open_interest_not_divisible_by_lot_size:unverified
margin.simplified_approximation:unverified
settlement.exchange_charge_assumed_not_levied:unverified
gst.broking_services:corroborated
nse.transaction_charge.options:corroborated
sebi.turnover_fee:corroborated
settlement.mean_of_underlying_minute_close_over_window:corroborated
stt.sell_option_premium:corroborated
```

§12.1's sizing-floor check is unchanged and is not re-executed: it depends on spot, lot size
and the window, none of which moved. Its defect — the spec names `reference_lot_size` while
the engine sizes on the declared value — stands as `gate.toml` reports it.

## 8. The trial count, and what the fix cost

**N = 9**, read from the canonical log at grading, never supplied. The log held 8 rows; this
run appended one.

The gate's pre-registered inventory expected **6**. The wedged run graded at 8 and explained
the gap. This run graded at **9, and the extra trial is the price of the bug**: a defect in
the apparatus cost the family a permanent, irreversible increment to the multiple-testing
correction that every future member of this family will be deflated by. Nothing recovers it
— deleting the row would be the exact move the append-only log exists to prevent.

Concretely, at n=384 the SR\* bar rose from 0.074552/period (N=8) to 0.077708 (N=9): every
future hypothesis in H1's family now needs a slightly larger true Sharpe to clear the same
bar, because an engine bug was fixed. **Issue #14 is the standing question about exactly
this** — whether a re-run forced by an apparatus defect should count against the researcher's
trial budget. This run is a clean instance of the cost: the re-run tested the same
pre-registered configuration over the same window, and the only thing that changed between
trial 8 and trial 9 was that trial 8 was measuring a book that was not trading.

## 9. What was NOT done

**The holdout was not read, and could not have been.** The runner spends the holdout
automatically on a PASSED in-sample verdict, so the run was smoke-tested first against a
**temporary** log with `_spend_the_holdout` replaced by a raise. That smoke returned
FAILS_THRESHOLD at N=2 — and since a temp log holds fewer trials, a smaller N gives a
*higher* DSR, so a non-PASSED verdict there guarantees a non-PASSED verdict against the
canonical log's N=9. The canonical run then confirmed it: `holdout_spent: false`. The
smoke run's fingerprint is identical to the canonical run's, which is what makes it evidence
about this run rather than about a similar one.

The holdout thresholds recorded in `gate.toml` remain unspent and unread.

## 10. Next step

The answer is no longer about execution. It is about size: 0.893 annualised, +0.124 in the
regime that is currently in force, against a bar that nine trials put at 1.233. The
conditional variants M2 and beyond now have a benchmark that is real — the risk-matched
increment they must beat is a genuine 0.893, not the 0.196 the wedged run would have handed
them, and that is a materially harder benchmark than it looked yesterday.
