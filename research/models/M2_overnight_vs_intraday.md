# M2 — Near-week overnight vs intraday variance split (H26 expression)

| | |
|---|---|
| Hypothesis | H26 — overnight vs intraday variance premium |
| Record | `h_cacfc556d38a2bda25efef59eb5544cf`, chain H1 → H26 v1 → v2 |
| Status | **Awaiting owner approval.** No re-validation until approved. |
| Prior result | FAILS_THRESHOLD, 45 gaps, DSR 0.2413 vs 0.80, PSR 0.7010 |

Differences from **M1** are marked ▲. Everything unmarked is M1 §2, §5, §7–§9, §11 verbatim.

---

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

Neither arm settles. Note this doubles the cost incidence versus M1: four legs crossed per session against M1's two entries and a spread-free settlement — which is why the breakeven bar is set higher (§7).

## 4. Observable gaps ▲

A gap $t \to t{+}1$ is observable iff both endpoints are priced. Two exclusions, both structural:

$$\mathcal{G} = \{ t : t \neq T_t \ \wedge\ t{+}1 \neq T_{t+1} \ \wedge\ \text{both legs listed at both endpoints} \}$$

- $t = T$: the contract **settles**; there is no close-side exit.
- $t{+}1 = T$: the contract is **dropped from the instrument master on its expiry date** (issue #23), so there is no open-side entry.

With Tuesday expiry, every Monday and Tuesday entry is lost. Measured on the prior run: $79 \to 63 \to 50 \to 45$, i.e. **~43% of candidate observations lost to a data limitation, not a market fact.** $|\mathcal{G}|$ must be reported alongside the calendar-gap count and never conflated with it.

## 5. Stratification — reported, NOT graded ▲

Partition $\mathcal{G}$ by $\Delta_{\text{cal}}$: 1 day (weekday), 2 (mid-week holiday), 3 (weekend), $\geq 4$ (holiday-extended). Pre-register the predicted sign: premium increasing in $\Delta_{\text{cal}}$.

**Descriptive only.** On the prior corpus the $\geq 4$ bucket held **3 events**. Grading a bucket that small is not a verdict.

## 6. Null hypothesis ▲

$$H_0:\ \mathbb{E}\!\left[r^{\text{on}}\right] \leq 0 \ \text{ after costs} \quad\wedge\quad \mathbb{E}\!\left[r^{\text{on}}\right] - \mathbb{E}\!\left[r^{\text{in}}\right] \leq 0$$

The second clause is what separates M2 from M1. Without it, a positive $r^{\text{on}}$ is just the unconditional variance premium (M1) sampled on a subinterval.

## 7. Parameters ▲

| Symbol | Value | Basis |
|---|---|---|
| entry/exit | session close / session open | the two clocks; no free parameter |
| breakeven bar | **3.0** (M1: 2.0) | four legs crossed per session vs M1's two, exits spread-free |
| DSR bar | set at pre-registration for realised $\|\mathcal{G}\|$ | must be neither auto-failing nor a non-gate |

No sweep. Entry and exit times are *defined by* the hypothesis, not chosen.

## 8. Estimators

**M1 §11 unchanged.** $N$ from `count_family_trials` on H1's family.

▲ Report $\text{PSR}$ **and** $\text{DSR}$ separately. On the prior run PSR was 0.7010 and DSR 0.2413 — almost the entire failure was the multiple-testing correction, and two of the five trials were **infrastructure crashes** (issue #14). The spread between the two is the diagnostic.

## 9. Known limits

M1 §14 applies in full, plus:

1. ~43% of candidate gaps are unobservable (§4). Caps the power of any gap-based model on this corpus.
2. On the prior run **>50% of P&L came from straddles that never closed** and cash-settled — i.e. from M1's path, not M2's. Any repeat must report the decomposition.
3. Skew $+1.19$, kurtosis $12.59$ on the prior sample indicates the position captured **decay**, not payment for insuring a gap event. This is the sharpest evidence against the mechanism and must be re-checked.
4. The benchmark ran levered $1.35\times$; the risk-matched increment is therefore an **upper bound**.
