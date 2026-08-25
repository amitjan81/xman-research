# M1 — Near-week short ATM straddle (H1 expression)

| | |
|---|---|
| Hypothesis | H1 — index variance risk premium |
| Record | `h_817b33ff6b9f68e288161f5990739744` |
| **Role** | **BENCHMARK.** Not a candidate. Every conditional model is graded against this series (§3). |
| Status | **Awaiting owner approval** as a whole; no re-validation until approved. The §5 sizing amendment and its §12.1 gate are **owner-approved 2026-08-19**. The §3/§10 reframing is **awaiting approval**. |
| Prior results | H1: FAILS_THRESHOLD, n=79, DSR 0.6043 vs 0.90. M1 re-run (`h_0b2ecbbc…`, post-wedge-fix): FAILS_THRESHOLD on two bars, n=384, DSR 0.3423 vs 0.90, MDD 12.03% vs 10%. |

---

## 1. Mechanism

Intermediation rent. Let $Q_t$ be net public demand for convexity. Dealers absorb $-Q_t$ and cannot fully hedge it: jump exposure is unspanned by dynamic hedging, and margin binds when the payout occurs. The compensation appears as

$$\mathbb{E}[\sigma^2_{\text{imp}}] - \mathbb{E}[\sigma^2_{\text{real}}] = \pi > 0$$

**Rejected mechanism:** preference-based crash insurance. If frictionless synthetic options show no negative alpha over a century, that channel is $\approx 0$ and cannot be the source.

**India refinement (Sankar et al. 2020):** decomposing realised variance into continuous and jump parts, $RV = C + J$, only $C$ forecasts variance-swap returns; $\partial r / \partial J \approx 0$. A jump-loaded estimator degrades the signal.

## 2. Universe

Near week only. Let $\mathcal{E}_t$ be the ordered set of listed NIFTY expiries at $t$. The traded expiry is

$$T_t = \min\{ e \in \mathcal{E}_t : e > t \}$$

Back-week and monthly cycles are excluded (liquidity). Underlying: NIFTY.

## 3. Signal — none, and that is what makes this the benchmark

**None.** M1 is unconditional: it enters every session satisfying §4, and holds to expiry, so it enters when flat — one straddle per weekly cycle.

C5 names the unconditional always-on short straddle as the naive benchmark. **M1 *is* that portfolio.** Candidate and benchmark are the same run under two labels, over the same window, under the identical cost model, so

$$\text{RMI}(\text{M1}) \;\equiv\; \text{SR}(r) - \text{SR}\!\left(r^{\text{bench}}\right)\Big|_{\text{risk-matched}} \;=\; 0$$

**identically** — an algebraic identity, not a measurement. It holds for every window, every corpus and every sample size. Measured 0.0000 on both graded runs (H1 n=79; M1 re-run n=384), and it could not have been anything else.

**Consequence: M1 cannot show alpha on any amount of data.** More sessions do not help. This is not a weak result awaiting power; it is a model that is definitionally incapable of producing the quantity the research programme grades on. M1's job is to *supply* the benchmark series, and it does that job whether or not it clears any bar of its own.

The re-run makes the benchmark real: annualised Sharpe **0.8928** on 384 observations, against the wedged run's 0.196. Conditional models inherit that as the number to beat.

## 4. Entry

At decision minute $\tau$ = 09:20 IST on each session $t$:

$$K_t = \arg\min_{K \in \mathcal{K}_t} \left| K - S_{t,\tau} \right|$$

where $S_{t,\tau}$ is spot and $\mathcal{K}_t$ the listed strike grid. Enter

$$\text{position}_t = \{ -n_t \text{ CE}(K_t, T_t),\; -n_t \text{ PE}(K_t, T_t) \}$$

**Entry is suppressed when** $(T_t - t) < 1$ trading day, or either leg is unlisted, or either leg fails feasibility (§7), or $n_t = 0$ (§5), or the book is not flat, or $T_t$ is not a session this run visits (`UNSETTLEABLE`, §14.7).

**Atomicity:** both legs share a `leg_group`. If either is infeasible, neither trades. If caps grant different sizes, both take $\min$.

## 5. Sizing

$$n_t = \left\lfloor \frac{N^*}{S_{t,\tau} \cdot L_t} \right\rceil$$

$N^*$ = target notional (parameter), $L_t$ = contract lot size on $t$, $\lfloor\cdot\rceil$ = round to nearest (implemented as $\lfloor x + 1/2 \rfloor$, not banker's rounding, so the tie does not break on the parity of a quotient).

**There is no floor at one lot.** When the target is under half a contract $n_t = 0$ and the session simply does not trade (§4). Rounding *up* to one lot would take a position **larger than $N^*$ asks for** — it would substitute the exchange's minimum for the exposure the research question specified, and do it silently on exactly the sessions where the two differ most.

*Amended 2026-08-19 (owner-approved) from an earlier form carrying $n_t \geq 1$.* The floor was a spec/code mismatch: the implementation has always returned 0 below half a contract. The floor is the wrong side of the mismatch to keep, and §12's pre-registration check is what makes removing it safe.

Sizing is by **notional, not lots**, so that $\text{Sharpe}$, $\text{MDD}$ and the cost-breakeven ratio are invariant to $L_t$. Residual from integer rounding is bounded by $\Delta L / (2 n_t L)$; the invariance test asserts both agreement and that this bound is under a stated ceiling.

**The $n_t = 0$ branch is the one place sizing could re-introduce a dependence on $L_t$** — *which* sessions trade would become a function of the contract multiplier. §12's check is what removes it, by verifying no session reaches the branch, rather than assuming so.

**Realised scale, and why a conditional model cannot inherit it.** The graded value is $N^{*} = ₹15{,}00{,}000$ of index notional. Against a lot of 75 units and NIFTY in the 20,000–26,500 range the window spans,

$$n_{\text{base}} \;=\; \frac{N^{*}}{S_{t,\tau} L_t} \;\in\; [0.75,\ 1.00] \;\Rightarrow\; n_t = \left\lfloor n_{\text{base}} + \tfrac12 \right\rfloor = 1 \ \text{ lot per leg, every entry}$$

Corroborated by the margin: peak ₹4,76,378.63 against $\rho_{\text{span}} + \rho_{\text{exp}} = 0.12$ over two legs implies $q S \approx ₹19.8$ lakh, i.e. $q = 75$ units. And by the counts — 178 legs / 385 sessions = 89 straddles, one per weekly cycle.

**$n_{\text{base}} < 1$ is the problem for any conditional model.** A continuous multiplier $f \in [0,1]$ gives $n_t = \lfloor n_{\text{base}} f + 1/2 \rfloor \in \{0,1\}$: not a size, a **switch**, tripping at $f^{*} = 0.5 / n_{\text{base}} \in [0.50,\ 0.67]$. **M1's $N^*$ is therefore unusable for any model that sizes continuously** (M3 §12.1(b)).

## 6. Exit

Hold to expiry. European cash settlement at

$$S_{T} = \frac{1}{|W|}\sum_{u \in W} S_{T,u}, \qquad W = \text{last 30 min of } T$$

Payoff per unit: $-\max(S_T - K, 0) - \max(K - S_T, 0) = -|S_T - K|$.

**Known divergence:** NSE's rule is volume-weighted; the corpus carries no index-level volume, so $W$ is unweighted. Affects every held-to-expiry payoff. **From 2026-08-03** NSE uses the Closing Auction Session price; that rule is carried `implemented=False` and **refuses to settle**, so the usable end is 2026-08-03.

A position expiring after the run's right edge is **kept, not refused** — otherwise the window silently decides which trades the strategy takes — and reported in `open_at_end` with a `book.open_at_run_end` stamp.

## 7. Feasibility

Per leg, requested units $q = n_t L_t$ against bar volume $V$ and open interest $\Omega$:

$$q^* = \min\left(q,\; \lfloor \alpha V \rfloor,\; \lfloor \beta \Omega \rfloor\right), \qquad \alpha = 0.01,\; \beta = 0.005$$

Verdicts: `FILLABLE` ($q^*=q$), `RESIZED` ($0<q^*<q$), `CAPPED_TO_ZERO`, `NO_LIQUIDITY` ($V=0$), `NO_BAR`, `GROUP_INCOMPLETE`, `UNSETTLEABLE` (§14.7).

Fill price = bar close $+$ slippage $s$ bps, $s = 0$ by default — **deliberately the optimistic case**, so the assumption is visible and the cost-breakeven sweep has a clean origin. No quote data exists; spread cannot be modelled.

**The caps were slack at $n_t = 1$ and are not slack in general.** M1 realised 0 `RESIZED` and 0 `CAPPED_TO_ZERO` across both graded runs, so $\alpha$ and $\beta$ never bound. At one lot, $\lfloor \beta \Omega \rfloor \geq 1$ holds under either open-interest unit convention, which is why `corpus.open_interest_not_divisible_by_lot_size` has so far been decorative. At larger $N^*$ it becomes load-bearing and the convention is still unconfirmed.

## 8. Costs

Per leg, premium turnover $P = q \cdot p$:

$$c = \underbrace{\mathbb{1}[\text{sell}] \cdot \sigma_1(t) P}_{\text{STT}} + \underbrace{\theta(t) P}_{\text{exch}} + \underbrace{\phi P}_{\text{SEBI}} + \underbrace{\mathbb{1}[\text{buy}] \cdot \delta P}_{\text{stamp}} + \underbrace{b}_{\text{brokerage}} + \underbrace{g(\theta(t) P + \phi P + b)}_{\text{GST}}$$

At settlement, on intrinsic $I = q\max(S_T-K,0)$, paid by the **purchaser only**:

$$c_{\text{settle}} = \sigma_2(t) \cdot I$$

| Symbol | Value | Effective | Confidence |
|---|---|---|---|
| $\sigma_1$ | 0.001 → 0.0015 | 2024-10-01 → 2026-04-01 | corroborated |
| $\sigma_2$ | 0.00125 → 0.0015 | → 2026-04-01 | corroborated |
| $\theta$ | 0.0003503 | 2024-10-01 | corroborated (brokers show 0.0003553; no circular found) |
| $\phi$ | 0.000001 | — | rate corroborated, **date unverified** |
| $\delta$ | 0.00003 | 2020-07-01 | **CONFIRMED** |
| $g$ | 0.18 | 2017-07-01 | corroborated |
| $b$ | ₹20/order | — | parameter |

$\sigma_1, \sigma_2$ **undefined before 2024-10-01** — `RateNotInForceError`. This bounds the costable window.

**Direction of error:** an assigned short pays no exercise STT, which makes short-variance results *cheaper*. It is a never-folded line item for that reason.

**The whole stack stays in the model and stays stamped.** What changed is what it gates — §10.

## 9. Margin

$$M_t = \mu \sum_{\text{short legs}} q \cdot S_{t} \cdot \left( \rho_{\text{span}} + \rho_{\text{exp}} + \mathbb{1}[t = T]\cdot \rho_{\text{elm}} \right)$$

$\rho_{\text{span}}=0.10$ (UNVERIFIED), $\rho_{\text{exp}}=0.02$, $\rho_{\text{elm}}=0.02$ (SEBI 2024-11-20, sourced), $\mu$ = multiplier (sweep parameter).

No portfolio netting → **overstates** $M$, understates ROC (conservative). No volatility scaling → **understates** $M$ in drawdown (**not** conservative). No error bound is claimed: SPAN is a scenario engine with no citable percentage. Margin is never a return denominator.

## 10. Null hypothesis — the unconditional variance premium, not an edge

M1 does not test for alpha (§3). It estimates the quantity conditional models' alpha is measured *relative to*. Its null is therefore a statement about the market:

$$H_0:\quad \pi \;\equiv\; \mathbb{E}\!\left[\sigma^2_{\text{imp}}\right] - \mathbb{E}\!\left[\sigma^2_{\text{real}}\right] \;\leq\; 0$$

estimated by the sign of the **gross** return on the unconditional short straddle:

$$H_0:\quad \mathbb{E}\!\left[r_t^{\text{gross}}\right] \;\leq\; 0, \qquad r_t^{\text{gross}} \text{ = daily return on capital base } N^*, \text{ before } §8$$

**Gross, and deliberately.** $\pi$ is a property of the price process. Statutory costs are a property of the tax code and the broker; folding them into the null makes the existence of the premium contingent on a fee schedule, which is a category error. A premium that exists and is not harvestable net of costs is a *financing* result — size, venue, broker — and it is a different question, asked later, of models that have already shown alpha.

**Superseded form**, recorded rather than deleted:

$$H_0^{\text{old}}:\ \mathbb{E}[r_t] \leq 0 \ \text{after costs} \;\wedge\; \text{SR}(r) \leq \text{SR}(r^{\text{bench}})\ \text{risk-matched}$$

Both conjuncts were defective. The second is vacuous — it compares M1 with itself (§3). The first made a cost model the gate on an alpha question.

**What M1 is still graded on.** `deflated_sharpe` and `max_drawdown` remain live: the first asks whether $\hat\pi > 0$ survives selection, the second whether the benchmark series is usable at all. Both were missed on the re-run (0.3423 vs 0.90; 12.03% vs 10%), and §5's note on the gate's own calibration applies — 0.893 annualised sits inside the band this apparatus was built unable to resolve.

## 11. Estimators

$$\widehat{\text{SR}} = \frac{\bar r}{s_r}, \qquad \text{PSR}(\text{SR}^*) = \Phi\!\left[\frac{(\widehat{\text{SR}} - \text{SR}^*)\sqrt{n-1}}{\sqrt{1 - \gamma_3 \widehat{\text{SR}} + \tfrac{\gamma_4-1}{4}\widehat{\text{SR}}^2}}\right]$$

$$\text{SR}^* = \sqrt{V[\widehat{\text{SR}}]}\left[(1-\gamma)\Phi^{-1}\!\left(1-\tfrac1N\right) + \gamma\,\Phi^{-1}\!\left(1-\tfrac{1}{Ne}\right)\right], \qquad \text{DSR} = \text{PSR}(\text{SR}^*)$$

$\gamma$ = Euler–Mascheroni, $\gamma_4$ **non-excess**, both Sharpes per-period. **$N$ = `count_family_trials`, read from the log — never supplied.**

$$\text{breakeven} = \sup\{ m : \bar r_{\text{gross}} - m\,\bar c > 0 \}$$

### 11.1 Cost-breakeven — reported diagnostic, not a gate

`cost_breakeven_multiple` answers *"how wrong can the cost model be before the gross effect is eaten"*. That is a question about deployability, and it is asked of hypotheses that have already shown alpha. It is computed and reported on every run and **does not gate the alpha verdict**.

Observed: **12.889** (H1, n=79), **23.4384** (M1 re-run, n=384). Both comfortable, and neither decided a verdict.

**Not comparable across models with different $N^*$.** Brokerage $b$ is a flat ₹20/order: doubling $N^*$ halves $b$ as a fraction of turnover and raises the multiple with no change in any effect. Compare breakeven only within one $N^*$. This matters because a continuously-sized model must raise $N^*$ to be expressible at all (§5, M3 §12.1(b)).

## 12. Parameters — pre-registered, no grid

| Symbol | Value | Basis |
|---|---|---|
| $\tau$ | 09:20 IST | post-open, pre-drift |
| $N^*$ | to be set at pre-registration | must satisfy the sizing-floor check below |
| $\alpha$ | 0.01 | 1% of bar volume |
| $\beta$ | 0.005 | 0.5% of OI |
| $s$ | 0 bps | optimistic case, deliberate |
| $\mu$ | 1.0 | sweep separately, counted |

**One parameterisation, one trial.** Any sweep is a separate, explicitly counted exercise. This is where ATR-style models die and this one must not.

### 12.1 Sizing-floor check — pre-registration gate

Before the validation run, over every session $t$ in the run's window:

$$\min_t \frac{N^*}{S_{t,\tau} \cdot L_t} \;\geq\; 0.5$$

**This must actually be run and pass. It is not an assumption.** If it fails, $N^*$ is too small for the window — that is a finding about the *parameter*, not about the model, and the remedy is to raise $N^*$ at pre-registration, never to floor $n_t$ after the fact.

$L_t$ here is the **bars-supported** lot size — `LotSizeAudit.reference_lot_size`, the multiplier the session's own bars divide by, which falls back to the declared value where the bars do not convict it. It is not the declared value alone: the two disagree on 1,077 of the corpus's 1,233 sessions, and $L_t$ being wrong there is the reason this model's sizing rule was rewritten at all; running the check on the declared value would verify the wrong quantity on precisely the sessions that motivated it.

**Not `lot_size.epoch_for`, which an earlier wording of this clause named.** That function answers a narrower question — which lot-size regime has been *recorded* with written evidence — and its table deliberately covers only expiries from 2025-12-16 onward, returning `None` everywhere else: on **1,071 of the corpus's 1,233 sessions (87%)**, and so on every session of this model's own costable window (§13) before 2025-12-16. Naming it made this gate incomputable on the bulk of the window it is mandatory over, which matters because §12.1 requires re-execution whenever $N^*$ or the window changes. `reference_lot_size` is defined on every session and is the quantity the check was in fact executed against.

**What the check buys, stated exactly.** $\lfloor x + 1/2 \rfloor \geq 1 \iff x \geq 0.5$, so a passing check means no session reaches §5's $n_t = 0$ branch and §4's corresponding suppression never fires on this window. That makes the two clauses belt-and-braces rather than contradictory: the suppression is the honest behaviour *if* the branch is ever reached, and the check is the evidence that it is not. Without the check, which sessions trade would be a function of $L_t$ — the one dependence the notional rule exists to remove — and the invariance would hold for the statistics while quietly failing for the population.

**Known defect, unresolved:** this clause names `reference_lot_size` while the engine sizes on the declared value. Recorded in `research/m1/gate.toml` and not silently fixed.

## 13. Window and epochs

Costable: **2024-10-01 → 2026-08-03** (STT floor; CAS settlement ceiling). Spans epochs: 2024-11-20 (weekly cull, contract size, expiry ELM), 2025-02-10, 2025-04-01, 2025-09-01 (**expiry Thu→Tue**), 2026-04-01 (STT).

Pooling five regimes yields a number describing no market that existed. **Report per-epoch and pooled; name which is graded.**

Measured per-epoch on the re-run: the pre-committed positive sign holds in 5 of 6 epochs, and the current regime (`nse_expiry_tuesday_2025`, 142 sessions) returns an annualised Sharpe of **+0.124**. That is the benchmark a conditional model actually faces today.

## 14. Known limits

1. Trial count is a **lower bound** — re-registering a reworded hypothesis resets the family (C4's documented hole). The log stood at **9** after the re-run; it moves, and is read, never supplied.
2. $\gamma_4$ estimated on $n$ observations is itself noisy; DSR inherits that.
3. Expiry-eve entry has no exit — contract is dropped from the master on its expiry date (issue #23). Cost H26 ~43% of observations. M1 held to expiry is exposed on the entry side only.
4. Only $\delta$ is primary-sourced. Every verdict carries `unverified_inputs`.
5. Settlement is unweighted where NSE's is volume-weighted.
6. **The strike ladder $\mathcal{K}_t$ is a spot-tracking moving window, not a fixed grid** (`corpus.strike_ladder_is_a_moving_window`). For M1 this costs *marks*, not runs: settlement is on $S_T$ and needs no listed contract, so a strike that leaves the ladder mid-hold produces a stale mark rather than a refusal — measured stale-mark fraction 1.82% on the re-run. It is **fatal** for any model needing to re-trade a specific strike (M2 §1).
7. Two listed weekly expiries have **no session file** in the corpus (2025-04-30, 2025-05-08). The engine refuses to open a position it cannot settle (`UNSETTLEABLE`) and raises if one is ever held past its expiry. Cost: 14 legs over 7 sessions, `infeasible_fraction` 7.87% against a 10% not-evaluable limit. **A third missing expiry would have returned NOT_EVALUABLE instead of a verdict**, and no census of missing expiries over the full 1,233-session corpus has been run.
8. An apparatus defect permanently taxes the family: fixing the wedged book cost one trial, raising $\text{SR}^*$ for every future member. Issue #14 is the standing question of whether it should.
