# M2 — Near-week overnight vs intraday variance split (H26 expression)

| | |
|---|---|
| Hypothesis | H26 — overnight vs intraday variance premium |
| Record | `h_cacfc556d38a2bda25efef59eb5544cf`, chain H1 → H26 v1 → v2 → M2 `h_a63a756a…` |
| **Status** | **NOT RUNNABLE ON THIS CORPUS.** Structural, not a bug (§0). No re-validation may be attempted until §0.3 is satisfied. |
| Approval | The §0 blocker and the §6 alpha reframing are **awaiting owner approval**. |
| Prior results | H26 v2: FAILS_THRESHOLD, 45 gaps, DSR 0.2413 vs 0.80, PSR 0.7010. M2: **NO VERDICT** — engine refused 128 sessions in, trial `t_ba74b7d8…` logged `error`. |

Differences from **M1** are marked ▲. Everything unmarked is M1 §2, §5, §7–§9, §11 verbatim.

---

## 0. This model cannot be executed on this corpus ▲

Stated first because it governs everything below. The specification is sound; the data cannot express it.

### 0.1 The mechanism of the failure

The corpus's strike ladder $\mathcal{K}_t$ is a **spot-tracking moving window**, not a fixed grid. Let $\underline{K}_t = \min \mathcal{K}_t$ and $\overline{K}_t = \max \mathcal{K}_t$. Both track $S_t$. M2's overnight arm sells $K_t = \arg\min_{K \in \mathcal{K}_t} |K - S_{t,\text{close}}|$ and must buy it back at $\text{open}(t{+}1)$, which requires

$$K_t \in \mathcal{K}_{t+1}$$

A large overnight gap moves the window far enough that the condition fails. The buy-back cannot be expressed and the engine refuses — correctly; composing a trading symbol absent from the instrument master is how a backtest trades an instrument that was never listed.

Both known instances, measured directly:

| session | spot 15:25 | near expiry | ladder | strike sold | in $\mathcal{K}_{t+1}$? |
|---|---:|---|---|---|---|
| 2025-04-04 (Fri) | 22,904.50 | 2025-04-09 | 27 strikes | 22,900 | — |
| **2025-04-07 (Mon)** | **22,232.20** (−2.9%) | 2025-04-09 | 30 strikes | 22,900 | **NO** — dropped off the top |
| 2026-02-02 (Mon) | 25,095.70 | 2026-02-03 | 24,200 – 25,600 | 25,100 | — |
| **2026-02-03 (Tue)** | **25,719.95** (+2.5%) | 2026-02-03 | 25,150 – 26,350 | 25,100 | **NO** — dropped off the bottom |

By the following session the strike is listed again. The contract did not expire and was not delisted; **the ladder moved.**

**H26's diagnosis of the same crash was wrong.** `research/h26/gate.toml` attributes the 2026-02-03 `KeyError` to issue #23 — the expiring contract dropped from the master on its expiry date — and fixes it by tightening the entry guard to `MIN_CALENDAR_DAYS_TO_EXPIRY`. That guard removed the symptom on H26's 80-session window only by coincidence: 2026-02-03 *was* an expiry date. **2025-04-07 is not** (expiry 2025-04-09); the guard passed and the same `KeyError` occurred. H26's verdict stands — the guard was the right change for a different reason — but the stated cause is wrong and the wrong cause was propagating. `research/h26/gate.toml` is frozen and is not edited; this clause is the correction.

### 0.2 Why no guard is acceptable

The failure is **selective on exactly the population M2 exists to measure.**

$$\Pr\left[K_t \notin \mathcal{K}_{t+1}\right] \ \text{ is increasing in } \ \left| r^{\text{on}}_t \right|$$

by construction: the further spot gaps, the further the window rolls, the more likely last night's ATM strike is outside this morning's ladder. Both observed instances are among the largest gaps in the sample.

So any guard that skips the offending sessions — an entry filter, a narrowed window, a try/except that omits the gap — conditions the sample on

$$\left| r^{\text{on}}_t \right| < \text{(whatever the ladder happened to span)}$$

**A gap-risk seller collects the premium on small gaps and pays on large ones.** Discarding the large ones keeps every session where he collects and removes the ones where he pays. On a hypothesis whose subject *is* gap risk, that is not a power loss; it is the selection bias that would manufacture the result. A guarded M2 would return a **flattering** number, not a neutral one, and nothing in the output would say so.

This is categorically worse than §4's ~43% unobservable gaps. That is a limit on **power**. This is a limit on **validity**.

### 0.3 The two conditions under which M2 becomes runnable

Neither is a code change. Both are data-acquisition facts.

1. **A vendor able to serve a wider historical ladder** — a strike grid at each session $t$ spanning enough of the distribution of $S_{t+1}$ that $\Pr[K_t \notin \mathcal{K}_{t+1}]$ is negligible, and demonstrably not spot-tracking. Retrospective, and it fixes the existing corpus.
2. **Prospective capture at full width** — capture every listed strike from today forward, independent of spot. Costs nothing but time, and buys a clean sample only from the capture date.

Until one holds, M2 is not re-run. **Every attempt burns a family trial and permanently deflates every future member of the family** (§8), for no result.

**Prerequisite to either, and not yet done:** establish the ladder rule empirically over the full **1,233**-session corpus — how many strikes are carried, how the window is centred, and the realised frequency of $K_t \notin \mathcal{K}_{t+1}$. That frequency is the actual measure of how much of M2's population is unreachable. The stamp `corpus.strike_ladder_is_a_moving_window` records the finding; it has no code behind it yet.

## 1. Mechanism ▲

Variance accrues in **trading** time; decay is charged in **calendar** time. Over an interval $[t_1,t_2]$ let $\Delta_{\text{cal}} = t_2 - t_1$ in calendar days and $\Delta_{\text{trd}}$ in trading days. Option time value decays $\propto \Delta_{\text{cal}}$ while realised variance accrues $\propto \Delta_{\text{trd}}$. For any non-trading interval $\Delta_{\text{trd}} = 0$ while $\Delta_{\text{cal}} > 0$, so the seller is paid decay for hours in which the underlying provably cannot move.

The compensation is for **gap risk**: $S$ may reopen away from its close. Writing $r^{\text{on}}$ for the close-to-open return and $r^{\text{in}}$ for open-to-close,

$$\mathbb{E}\!\left[\pi^{\text{on}}\right] > \mathbb{E}\!\left[\pi^{\text{in}}\right]$$

is the claim, where $\pi$ is the per-unit-time premium captured. This is a mismatch between two clocks, not a preference or a behavioural bias — it requires nobody to be wrong.

**India sharpening:** NSE's holiday calendar is heavy, so the $\Delta_{\text{cal}} / \Delta_{\text{trd}}$ wedge exceeds the US studies this comes from.

## 2. Family ▲

**Amendment of H1, not a new family.** The surviving argument is direction of error: an amendment inflates $N$ and can only make M2 *harder* to pass; a fresh family resets the count, which is C4's documented hole.

**Rejected argument, recorded:** that M2's returns "exactly partition" M1's. False — M1 holds to settlement and never re-strikes; M2 re-strikes twice daily and never settles. The two clocks partition *the day*, not M1's P&L.

**Bound:** "same corpus" is **not** sufficient grounds for amendment, or hypothesis twelve inherits eleven unrelated tries.

## 3. Positions ▲

Two arms on the same near-week ATM straddle (M1 §2, §4 for $K_t, T_t$):

$$A^{\text{on}}_t:\ \text{enter at close}(t),\ \text{exit at open}(t{+}1) \qquad A^{\text{in}}_t:\ \text{enter at open}(t),\ \text{exit at close}(t)$$

Both short. Sizing, atomicity, feasibility, costs, margin: **M1 §5, §7, §8, §9 unchanged.**

Neither arm settles. Note this doubles the cost incidence versus M1: four legs crossed per session against M1's two entries and a spread-free settlement.

**Both arms require a round trip in a named strike**, which is what §0 blocks. M1 is exposed to the same moving ladder and survives it, because settlement is on $S_T$ and needs no listed contract — a strike leaving the ladder costs M1 a stale mark, and costs M2 the run.

## 4. Observable gaps ▲

A gap $t \to t{+}1$ is observable iff both endpoints are priced. Three exclusions:

$$\mathcal{G} = \{ t : t \neq T_t \ \wedge\ t{+}1 \neq T_{t+1} \ \wedge\ \text{both legs listed at both endpoints} \}$$

- $t = T$: the contract **settles**; there is no close-side exit.
- $t{+}1 = T$: the contract is **dropped from the instrument master on its expiry date** (issue #23), so there is no open-side entry.
- $K_t \notin \mathcal{K}_{t+1}$: **the ladder moved** (§0). Not a filter — the engine refuses, and it must not be converted into one.

With Tuesday expiry, every Monday and Tuesday entry is lost to the first two. Measured on the prior run: $79 \to 63 \to 50 \to 45$, i.e. **~43% of candidate observations lost to a data limitation, not a market fact.** $|\mathcal{G}|$ must be reported alongside the calendar-gap count and never conflated with it.

## 5. Stratification — reported, NOT graded ▲

Partition $\mathcal{G}$ by $\Delta_{\text{cal}}$: 1 day (weekday), 2 (mid-week holiday), 3 (weekend), $\geq 4$ (holiday-extended). Pre-register the predicted sign: premium increasing in $\Delta_{\text{cal}}$.

**Descriptive only.** On the prior corpus the $\geq 4$ bucket held **3 events**. Grading a bucket that small is not a verdict. The prior run's OLS slope of +₹211.56 per extra calendar day had the predicted sign and rested on three straddles, while the best-populated multi-day bucket — the weekend, 11 straddles — was **negative**.

## 6. Null hypothesis — alpha over the benchmark, gross ▲

M1 is the benchmark (M1 §3). M2's claim is that splitting M1's holding period by clock produces a portfolio M1 does not:

$$H_0:\quad \text{RMI}\!\left(A^{\text{on}} \,\middle|\, \text{M1}\right) \;\leq\; 0$$

and the mechanism-specific clause, which is what distinguishes M2 from a re-sampling of M1:

$$H_0:\quad \mathbb{E}\!\left[r^{\text{on,gross}}\right] - \mathbb{E}\!\left[r^{\text{in,gross}}\right] \;\leq\; 0$$

Both **gross of statutory costs**, per M1 §10. Without the second clause a positive $r^{\text{on}}$ is just the unconditional variance premium sampled on a subinterval.

**Superseded form:** $\mathbb{E}[r^{\text{on}}] \leq 0$ *after costs* $\wedge\ \mathbb{E}[r^{\text{on}}] - \mathbb{E}[r^{\text{in}}] \leq 0$. The cost conjunct made a fee schedule the gate on an alpha question.

**A benchmark caveat that survives the reframing.** H26 graded the intraday arm as benchmark, and the two arms trade the same instrument in complementary hours, so the comparison is conditionally toothless in one direction. Grading against M1 as well is what makes the increment mean what it says.

**Cost-breakeven is a reported diagnostic** (M1 §11.1), and M2 is the model most exposed to what it cannot see: four legs crossed per session, every fill a spread-free bar close, $s = 0$. Under M2 the missing quote data is load-bearing rather than decorative. Report it; do not gate on it.

## 7. Parameters ▲

| Symbol | Value | Basis |
|---|---|---|
| entry/exit | session close / session open | the two clocks; no free parameter |
| DSR bar | set at pre-registration for realised $\|\mathcal{G}\|$ | must be neither auto-failing nor a non-gate |
| breakeven | reported, ungated | M1 §11.1 |

No sweep. Entry and exit times are *defined by* the hypothesis, not chosen.

**Do not pre-register $N$ as a constant.** M2's existing gate states *"at M2's in-sample grading the family should hold eight rows, N = 8"* and calibrates against that row of the grid. The log has since moved to 9 through no act of M2's, so that inventory was stale before M2 ran. $N$ is read from the log at grading (M1 §11); an inventory is an expectation that may move, never a calibrated constant.

## 8. Estimators

**M1 §11 unchanged.** $N$ from `count_family_trials` on H1's family.

▲ Report $\text{PSR}$ **and** $\text{DSR}$ separately. On the prior run PSR was 0.7010 and DSR 0.2413 — almost the entire failure was the multiple-testing correction, and two of the five trials were **infrastructure crashes** (issue #14). The spread between the two is the diagnostic. M1's re-run shows that spread does not generalise: 0.8563 against 0.3423, where the measured Sharpe was real.

**M2's own failed attempt is row 7 in the family and it was kept.** No result was ever observed from it, so nothing was selected on, but it counts and it makes every subsequent verdict harder. That is the standing cost of re-running a blocked model, and the reason §1.3 forbids it.

## 9. Known limits

M1 §14 applies in full, plus:

1. **The model does not run** (§0). Everything below is conditional on §0.3 being satisfied first.
2. ~43% of candidate gaps are unobservable (§4). Caps the power of any gap-based model on this corpus, independently of §0.
3. On the prior run **>50% of P&L came from straddles that never closed** and cash-settled — i.e. from M1's path, not M2's. Any repeat must report the decomposition.
4. Skew $+1.19$, kurtosis $12.59$ on the prior sample indicates the position captured **decay**, not payment for insuring a gap event. The premium is compensation for a tail that did not arrive, and the skew/kurtosis correction can only adjust for a tail it observes. This is the sharpest evidence against the mechanism and must be re-checked.
5. The prior benchmark ran levered $1.35\times$ with no check that the leverage is reachable under margin; that increment was an **upper bound**.
