# M1 — Near-week short ATM straddle (H1 expression)

| | |
|---|---|
| Hypothesis | H1 — index variance risk premium |
| Record | `h_817b33ff6b9f68e288161f5990739744` |
| Status | **Awaiting owner approval.** No re-validation until approved. |
| Prior result | FAILS_THRESHOLD, n=79, DSR 0.6043 vs 0.90 |

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

## 3. Signal

**None.** M1 is unconditional — it enters every session that satisfies §4. This is deliberate: it is the naive expression of H1 and the benchmark every conditional variant must beat risk-matched.

## 4. Entry

At decision minute $\tau$ = 09:20 IST on each session $t$:

$$K_t = \arg\min_{K \in \mathcal{K}_t} \left| K - S_{t,\tau} \right|$$

where $S_{t,\tau}$ is spot and $\mathcal{K}_t$ the listed strike grid. Enter

$$\text{position}_t = \{ -n_t \text{ CE}(K_t, T_t),\; -n_t \text{ PE}(K_t, T_t) \}$$

**Entry is suppressed when** $(T_t - t) < 1$ trading day, or either leg is unlisted, or either leg fails feasibility (§7).

**Atomicity:** both legs share a `leg_group`. If either is infeasible, neither trades. If caps grant different sizes, both take $\min$.

## 5. Sizing

$$n_t = \left\lfloor \frac{N^*}{S_{t,\tau} \cdot L_t} \right\rceil, \qquad n_t \geq 1$$

$N^*$ = target notional (parameter), $L_t$ = contract lot size on $t$, $\lfloor\cdot\rceil$ = round to nearest.

Sizing is by **notional, not lots**, so that $\text{Sharpe}$, $\text{MDD}$ and the cost-breakeven ratio are invariant to $L_t$. Residual from integer rounding is bounded by $\Delta L / (2 n_t L)$; the invariance test asserts both agreement and that this bound is under a stated ceiling.

## 6. Exit

Hold to expiry. European cash settlement at

$$S_{T} = \frac{1}{|W|}\sum_{u \in W} S_{T,u}, \qquad W = \text{last 30 min of } T$$

Payoff per unit: $-\max(S_T - K, 0) - \max(K - S_T, 0) = -|S_T - K|$.

**Known divergence:** NSE's rule is volume-weighted; the corpus carries no index-level volume, so $W$ is unweighted. Affects every held-to-expiry payoff. **From 2026-08-03** NSE uses the Closing Auction Session price; that rule is carried `implemented=False` and **refuses to settle**, so the usable end is 2026-08-03.

## 7. Feasibility

Per leg, requested units $q = n_t L_t$ against bar volume $V$ and open interest $\Omega$:

$$q^* = \min\left(q,\; \lfloor \alpha V \rfloor,\; \lfloor \beta \Omega \rfloor\right), \qquad \alpha = 0.01,\; \beta = 0.005$$

Verdicts: `FILLABLE` ($q^*=q$), `RESIZED` ($0<q^*<q$), `CAPPED_TO_ZERO`, `NO_LIQUIDITY` ($V=0$), `NO_BAR`, `GROUP_INCOMPLETE`.

Fill price = bar close $+$ slippage $s$ bps, $s = 0$ by default — **deliberately the optimistic case**, so the assumption is visible and the cost-breakeven sweep has a clean origin. No quote data exists; spread cannot be modelled.

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

## 9. Margin

$$M_t = \mu \sum_{\text{short legs}} q \cdot S_{t} \cdot \left( \rho_{\text{span}} + \rho_{\text{exp}} + \mathbb{1}[t = T]\cdot \rho_{\text{elm}} \right)$$

$\rho_{\text{span}}=0.10$ (UNVERIFIED), $\rho_{\text{exp}}=0.02$, $\rho_{\text{elm}}=0.02$ (SEBI 2024-11-20, sourced), $\mu$ = multiplier (sweep parameter).

No portfolio netting → **overstates** $M$, understates ROC (conservative). No volatility scaling → **understates** $M$ in drawdown (**not** conservative). No error bound is claimed: SPAN is a scenario engine with no citable percentage.

## 10. Null hypothesis

$$H_0:\; \mathbb{E}[r_t] \leq 0 \quad\text{after costs} \quad\wedge\quad \text{SR}(r) \leq \text{SR}(r^{\text{bench}})\ \text{risk-matched}$$

where $r_t$ = daily net return on capital base $N^*$.

## 11. Estimators

$$\widehat{\text{SR}} = \frac{\bar r}{s_r}, \qquad \text{PSR}(\text{SR}^*) = \Phi\!\left[\frac{(\widehat{\text{SR}} - \text{SR}^*)\sqrt{n-1}}{\sqrt{1 - \gamma_3 \widehat{\text{SR}} + \tfrac{\gamma_4-1}{4}\widehat{\text{SR}}^2}}\right]$$

$$\text{SR}^* = \sqrt{V[\widehat{\text{SR}}]}\left[(1-\gamma)\Phi^{-1}\!\left(1-\tfrac1N\right) + \gamma\,\Phi^{-1}\!\left(1-\tfrac{1}{Ne}\right)\right], \qquad \text{DSR} = \text{PSR}(\text{SR}^*)$$

$\gamma$ = Euler–Mascheroni, $\gamma_4$ **non-excess**, both Sharpes per-period. **$N$ = `count_family_trials`, read from the log — never supplied.**

$$\text{breakeven} = \sup\{ m : \bar r_{\text{gross}} - m\,\bar c > 0 \}$$

## 12. Parameters — pre-registered, no grid

| Symbol | Value | Basis |
|---|---|---|
| $\tau$ | 09:20 IST | post-open, pre-drift |
| $N^*$ | to be set at pre-registration | must round to $\geq 1$ lot every session |
| $\alpha$ | 0.01 | 1% of bar volume |
| $\beta$ | 0.005 | 0.5% of OI |
| $s$ | 0 bps | optimistic case, deliberate |
| $\mu$ | 1.0 | sweep separately, counted |

**One parameterisation, one trial.** Any sweep is a separate, explicitly counted exercise. This is where ATR-style models die and this one must not.

## 13. Window and epochs

Costable: **2024-10-01 → 2026-08-03** (STT floor; CAS settlement ceiling). Spans epochs: 2024-11-20 (weekly cull, contract size, expiry ELM), 2025-02-10, 2025-04-01, 2025-09-01 (**expiry Thu→Tue**), 2026-04-01 (STT).

Pooling five regimes yields a number describing no market that existed. **Report per-epoch and pooled; name which is graded.**

## 14. Known limits

1. Trial count is a **lower bound** — re-registering a reworded hypothesis resets the family (C4's documented hole).
2. $\gamma_4$ estimated on $n$ observations is itself noisy; DSR inherits that.
3. Expiry-eve entry has no exit — contract is dropped from the master on its expiry date (issue #23). Cost H26 ~43% of observations.
4. Only $\delta$ is primary-sourced. Every verdict carries `unverified_inputs`.
5. Settlement is unweighted where NSE's is volume-weighted.
