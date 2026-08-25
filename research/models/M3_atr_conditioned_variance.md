# M3 — ATR-band-conditioned near-week short straddle (H1 family, first conditioner)

| | |
|---|---|
| Hypothesis | H1 family — variance risk premium, conditioned on trend extension |
| Record | **not yet registered.** No `research/m3/`, no `gate.toml`. Registration follows approval. |
| Benchmark | **M1** (`research/models/M1_short_atm_straddle.md` §3) |
| Status | **Awaiting owner approval.** No pre-registration, no run, no trial. |
| Graded quantity | $\text{RMI}(\text{M3} \mid \text{M1})$ — the first quantity in this programme that is not identically zero |

Differences from **M1** are marked ▲. Everything unmarked is M1 verbatim — universe (§2), entry rule (§4), exit (§6), feasibility (§7), costs (§8), margin (§9), estimators (§11), window and epochs (§13).

**M3 differs from M1 in exactly one clause: §5, the sizing multiplier.** That is deliberate and it is the whole design. Every other degree of freedom is held at the benchmark's value, so the risk-matched increment measures the conditioning and nothing else.

---

## 1. Mechanism ▲

A large price move decomposes into information and forced flow:

$$\Delta S = \Delta S^{\text{info}} + \Delta S^{\text{flow}}$$

$\Delta S^{\text{info}}$ is a revision of fair value and does not revert. $\Delta S^{\text{flow}}$ is stop-outs, margin calls and mandated rebalancing — trades whose timing is imposed on the trader — and it does revert, because the pressure ends when the forced seller is done. Selling variance after an extension is being paid to absorb $\Delta S^{\text{flow}}$, and the compensation shows up twice: in the subsequent reversion, and in implied variance elevated above what the continuous process warrants.

So the conditioning predicts $\pi$ (M1 §1) is larger following extension:

$$\pi\!\left(\left|z\right|\right) \ \text{ increasing in } \ \left|z\right|$$

with $z$ a volatility-normalised measure of extension (§3).

**The India-specific risk to this mechanism, stated up front.** Sankar et al. (2020) decompose $RV = C + J$ and find that only the **continuous** part forecasts variance-swap returns; $\partial r / \partial J \approx 0$. An ATR-band extension is close to a jump. So M3's "sell rich IV after the move" leg may land precisely on the component that does not pay, and the mechanism above may be right about the flow and wrong about who is compensated for it.

**This makes a negative result informative rather than merely disappointing.** M1 established that the unconditional premium is real and small (annualised Sharpe 0.893 pooled, +0.124 in the current regime). If conditioning on extension adds nothing, that is direct evidence for Sankar's decomposition on Indian index options, from a different instrument than theirs — and it redirects the family to a continuous-variance conditioner (§9) rather than leaving the question open.

## 2. Why continuous conditioning, not regime classification ▲

**The episode arithmetic.** A regime label is only usable if it persists long enough to trade — otherwise the classifier is relabelling noise. Let $P$ be the minimum episode length in sessions for a label to be actionable. The corpus holds $1{,}233$ sessions ($\approx 5$ years). Across two states:

$$\text{episodes per state} \;\approx\; \frac{1{,}233}{2P}$$

| $P$ | interpretation | episodes per state |
|---:|---|---:|
| 250 | ≈ 1 year — the scale at which "the 2021 vol regime" and "the 2026 vol regime" are distinct objects | **2.5** |
| 120 | ≈ 6 months | 5.1 |
| 60 | ≈ 1 quarter | 10.3 |

**The independent unit under regime conditioning is the episode, not the session.** Within an episode every session carries the same label, and the label is the thing under test; the sessions are replicates of one draw, not independent draws. So a regime-conditional claim at deployable persistence has effective $n \approx 2\text{–}3$. No threshold in this apparatus is reachable at $n = 3$, and no amount of daily data inside those episodes changes it.

**Continuous conditioning replaces the label with a function of the state**, estimated across every entry the strategy makes. It is also **causal by construction** (§3.3): $z_t$ is a function of prices strictly before the decision minute, whereas a regime partition chosen by inspecting the sample is fitted to data the strategy would not have had.

**M3 conditions size, not timing.** M1 holds to expiry and enters when flat (M1 §3), so the entry session of each cycle is dictated by the previous cycle's settlement, not chosen. M3 cannot wait for a high-$|z|$ session; it sizes whatever $z$ happens to be on the one session per cycle when it is flat. Size is the only available channel, which is a further reason the design is a continuous multiplier rather than a filter — a filter would simply skip the cycle and forfeit the entry.

## 3. State variable ▲

### 3.1 Definition

$$\boxed{\;z_t \;=\; \frac{S_{t,\tau} - \text{EMA}_{n}(C)_{t-1}}{k \cdot \text{ATR}_{14,\,t-1}}\;}$$

| symbol | meaning |
|---|---|
| $S_{t,\tau}$ | NIFTY spot at the decision minute $\tau$ = 09:20 IST on session $t$ (M1 §4) |
| $C_u, H_u, L_u$ | daily close, high, low of session $u$ |
| $\text{EMA}_n(C)_{t-1}$ | $n$-period exponential moving average of closes, evaluated **through session $t-1$** |
| $\text{ATR}_{14,t-1}$ | Wilder 14-period average true range, evaluated **through session $t-1$** |
| $k$ | scale parameter — sets the saturation scale of §4's $f$ |

**EMA.** With $\alpha = 2/(n+1)$:

$$\text{EMA}_n(C)_u = \alpha\, C_u + (1-\alpha)\,\text{EMA}_n(C)_{u-1}, \qquad \text{EMA}_n(C)_{n} = \frac1n \sum_{i=1}^{n} C_i$$

**ATR (Wilder, not a simple mean).** True range and Wilder smoothing:

$$TR_u = \max\!\big(H_u - L_u,\; \left|H_u - C_{u-1}\right|,\; \left|L_u - C_{u-1}\right|\big)$$

$$\text{ATR}_{p,u} = \frac{(p-1)\,\text{ATR}_{p,u-1} + TR_u}{p}, \qquad \text{ATR}_{p,p} = \frac1p \sum_{i=1}^{p} TR_i, \qquad p = 14$$

Wilder smoothing is specified explicitly because a simple $p$-period mean of $TR$ is a different statistic and both are called "ATR" in the wild.

### 3.2 Why volatility-normalised

$S_t - \text{EMA}_n$ in points is not comparable across the window: the same 300-point extension is a large move in a 0.6% -a-day market and an ordinary one in a 1.4%-a-day market, and M1's own window spans regimes whose per-epoch Sharpes range from $-2.08$ to $+2.52$. Dividing by $\text{ATR}_{14}$ expresses extension in units of the market's own current daily range, so $z$ means the same thing in 2021 and in 2026. A raw trend measure does not, and would silently load the model onto whichever epoch happened to be most volatile.

### 3.3 Causality — the requirement and its enforcement

**Requirement.** $z_t$ must be measurable with respect to information available at or before $\tau$ on session $t$:

$$z_t \in \mathcal{F}_{t,\tau}$$

Satisfied by construction: $\text{EMA}$ and $\text{ATR}$ are evaluated **through $t-1$** — strictly completed sessions — and the only same-session input is $S_{t,\tau}$, which is observed at $\tau$. Session $t$'s own high, low and close are never read. No option price and no strategy return enters the state.

**Enforcement, and it must actually be run.** A truncation-invariance test: for every entry session $t$ in the window, recompute the state series from a corpus truncated at $t-1$, supply $S_{t,\tau}$ alone from session $t$, and assert the result equals the $z_t$ used by the run, exactly. This is not a code-reading argument — it is the same posture as M1 §12.1, and a spec that asserts causality without executing the check is asserting an assumption.

**Burn-in.** $z$ is undefined until both recursions have seeded and converged. Require $B = 60$ completed sessions strictly before the window's first session. The corpus begins well before the costable window's 2024-10-01 start, so the burn-in is drawn from pre-window data and **does not shorten the graded window** — verified at pre-registration (§12.1(d)), not assumed.

## 4. Sizing ▲ — the only clause that differs from M1

$$n_t \;=\; \left\lfloor \frac{N^{*} \cdot f(z_t)}{S_{t,\tau} \cdot L_t} \right\rceil, \qquad f(z) = \tanh\!\left(\left|z\right|\right)$$

M1 §5 with $N^{*} \to N^{*} f(z_t)$. Rounding, the absence of a one-lot floor, and the notional-not-lots rationale are M1 §5 unchanged.

### 4.1 Why $\tanh(|z|)$

| requirement | how $\tanh(\lvert z\rvert)$ meets it |
|---|---|
| $f : \mathbb{R} \to [0,1]$ | range $[0,1)$; approaches full size asymptotically, never exceeds it |
| monotone in $\lvert z\rvert$ | $f'(z) = \operatorname{sgn}(z)\operatorname{sech}^2(\lvert z\rvert)$, sign of $z$ only |
| degrades, does not switch | smooth and saturating; no threshold, no discontinuity in $f$ |
| symmetric in direction | a short straddle is delta-neutral — only the magnitude of extension is economically meaningful, and $f$ must not express a directional view it does not hold |
| **no free shape parameter** | see below |

**The last row is the argument.** Since $z = d/k$ with $d = \left(S_{t,\tau} - \text{EMA}_n\right)/\text{ATR}_{14}$, the scale $k$ **already is** the saturation scale of $f$. A logistic $1/(1 + e^{-a(|z| - z_0)})$ would add a slope $a$ and an offset $z_0$ that duplicate what $k$ does, giving three parameters for two degrees of freedom and three dimensions to sweep. $\tanh$ with unit scale spends the shape budget once.

Values, so the sizing is readable: $\tanh(0.5) = 0.462$, $\tanh(1) = 0.762$, $\tanh(2) = 0.964$, $\tanh(3) = 0.995$.

$f$ has a corner at $z = 0$, where $f = 0$ — **a kink in a position of zero size**, which is not a kink in anything the strategy does. Contrast a saturating ramp $\min(|z|/z_{\text{cap}}, 1)$, whose kink sits at $z_{\text{cap}}$ where size is *maximal*.

**Rejected, recorded:** the indicator $\mathbb{1}[|z| > c]$ — that is the regime switch §2 rejects; the logistic — duplicates $k$ and gives $f(0) > 0$, so the model takes size when there is no extension to be paid for; the ramp — kink where it matters.

### 4.2 What the multiplier does and does not put at risk

Because grading is **risk-matched** (§6), the *level* of $f$ cannot flatter the result: scaling every $n_t$ by a constant scales $\sigma$ and return together and leaves the increment unchanged. Only the **shape** of $f$ — the covariance between $f(z_t)$ and the forward outcome — can move the verdict. That is the quantity under test, and it is why $k$ is pre-registered rather than fitted, even though the level it sets is harmless.

## 5. Everything else — M1 verbatim

Universe (M1 §2), entry rule and strike selection (M1 §4), hold-to-expiry exit and settlement (M1 §6), feasibility caps (M1 §7), the cost stack (M1 §8), margin (M1 §9), window and epochs (M1 §13).

**Expiry boundaries, stated explicitly.** Near-week positions have both boundaries dark (issue #23):

- **No entry on expiry day** — the contract settles that evening.
- **No entry on expiry eve** — M1 §4 suppresses entry at $(T_t - t) < 1$ trading day; the expiring contract is dropped from the instrument master on its expiry date.

M3 takes M1's posture, not M2's: holding to expiry means settlement is on $S_T$ and needs no listed contract, so neither the expiry-eve drop nor the moving strike ladder (M1 §14.6) can refuse M3's exit. They cost stale marks (1.82% on M1's re-run), not runs.

**Consequence specific to M3, and it is a real limit.** Combining hold-to-expiry, enter-when-flat and the two dark boundaries, entries land on the first eligible session after each settlement — under Tuesday expiry, predominantly Wednesday. So $z_t$ is sampled roughly weekly on a near-fixed weekday, ~89 times in-sample. M3's conditioning claim is about the state on those sessions, and generalising it to every session is not supported.

## 6. Null hypothesis ▲

$$\boxed{\;H_0:\quad \text{RMI}\!\left(\text{M3} \,\middle|\, \text{M1}\right) \;\leq\; 0\;}$$

$$\text{RMI} \;=\; \bar{r}^{\,\text{M3}}_{\text{ann}} \;-\; \lambda\,\bar{r}^{\,\text{M1}}_{\text{ann}}, \qquad \lambda = \frac{\sigma\!\left(r^{\text{M3}}\right)}{\sigma\!\left(r^{\text{M1}}\right)}$$

Gross of statutory costs, per M1 §10. Both series run over the identical window, identical corpus, identical cost model, and differ only in §4.

**This is the first non-degenerate null in the programme.** M1's increment is identically zero (M1 §3); M3's is not, because M3 is a genuinely different portfolio from the benchmark.

### 6.1 The sign of the increment is not the verdict

$\text{RMI} > 0$ arises from noise about half the time. The inequality above is the null, not a threshold, and it is graded through the same machinery as everything else:

1. **DSR on M3's own return series**, $N$ read from `count_family_trials` (M1 §11), against a bar set at pre-registration by the synthetic calibration M1's gate used, at the realised $(n_{\text{obs}}, N)$.
2. **An RMI bar pre-registered at the same time**, calibrated the same way — the increment a true zero-effect conditioner produces at this $n$ by chance, at the chosen quantile.

Both committed before any number exists. Neither moves afterwards.

### 6.2 Do not pre-register $N$ as a constant

The family log stood at **9** after M1's re-run, so M3 grades at **10 or later**. M2's gate is the cautionary case: it fixed $N = 8$ into its calibration and the log moved to 9 through no act of M2's, leaving the inventory stale before the model ran. Record an inventory that may move; read $N$ from the log at grading.

### 6.3 The leverage caveat does not fire — checked, not assumed

Since $f \leq 1$, $\sigma(r^{\text{M3}}) \leq \sigma(r^{\text{M1}})$ in the ordinary case, so $\lambda \leq 1$ and risk-matching **de-levers** the benchmark. De-levering needs no margin, so H26's `leverage_caveat` — which made its $+16.30\%$/yr an upper bound — has nothing to attach to. Assert $\lambda \leq 1$ from the run's output rather than from this argument; if $\lambda > 1$ the caveat fires and the increment is an upper bound.

## 7. The two sample sizes, and which is which ▲

Conflating them would overstate the evidence, which is the failure this apparatus exists to prevent.

| quantity | symbol | value | what reads it |
|---|---|---:|---|
| daily return observations | $n_{\text{obs}}$ | **384** (385 sessions, M1's pre-registered window) | PSR, DSR, drawdown, the risk-matching |
| independent conditioning draws | $n_{\text{cond}}$ | **≈ 89** in-sample (M1 realised 89 straddles / 385 sessions) | the claim that $f(z)$ covaries with the outcome |

**The DSR reads 384. The conditioning claim rests on ~89.** Every session inside a held straddle inherits that cycle's single draw of $z_t$; the sessions are not independent evidence about the conditioning. Over the full 1,233-session corpus $n_{\text{cond}} \approx 250$.

~89 is small. It is also **30× the 2–3 that regime classification affords** (§2), which is the entire argument for the continuous form — not that 89 is comfortable, but that it is the largest number this position structure makes available.

## 8. Parameters — ONE pre-registered parameterisation, no grid ▲

| symbol | value | basis |
|---|---:|---|
| $p$ | **14** | ATR period, given |
| $n$ | **20** | EMA period — §8.1 |
| $k$ | **2** | state scale — §8.2 |
| $f$ | $\tanh(\lvert z\rvert)$ | §4.1 |
| $\tau$ | 09:20 IST | M1 §12 |
| $N^{*}$ | set at pre-registration | must satisfy §12.1(b) — **M1's value is disqualified** |
| $\alpha, \beta, s, \mu$ | M1 §12 | unchanged |

### 8.1 $n = 20$

- **Commensurability with $p = 14$.** $z$ is a ratio of two statistics estimated over comparable lookbacks, which keeps the ratio stable. At $n = 50$ against $\text{ATR}_{14}$ the numerator is a slow trend and the denominator a fast scale: $z$ then measures *trend*, not *extension*, and the mechanism in §1 is about extension.
- **Commensurability with the holding period.** The position lives $\leq 5$ trading days. $n = 20$ is ≈ one trading month, ≈ 4 near-week cycles — slow enough that the anchor is not dragged by the move being measured, fast enough that "extension" means recent.
- **Why not $n = 10$.** The EMA tracks spot closely, $S - \text{EMA}$ shrinks toward the daily increment, and $z$ becomes mostly the last day's noise.

### 8.2 $k = 2$

$k$ places the empirical distribution of $|z|$ relative to $\tanh$'s responsive band. $\tanh$ discriminates on $|z| \in [0,2]$ and is flat above $|z| \approx 2.5$, where all sessions are sized alike.

Writing $d_t$ for the un-scaled extension $\left(S_{t,\tau} - \text{EMA}_{20}\right)/\text{ATR}_{14}$, so $z = d/k$:

- $k = 1$: $|z|$ carries $d$'s own spread, a large fraction saturates at $f \approx 1$, and **M3 degenerates toward M1** — the conditioner stops conditioning and the increment collapses toward its identically-zero benchmark value.
- $k = 3$: mass concentrates near $z \approx 0$ where $f$ is small and near-linear; the model rarely takes meaningful size, and $n_{\text{cond}}$ effectively shrinks further.
- $k = 2$: mass in $[0,2]$, where $\operatorname{sech}^2$ is materially non-zero and the multiplier actually discriminates.

$k = 2$ is chosen **a priori from that requirement**. §12.1(a) verifies it held — from prices only.

### 8.3 Sweep discipline

**One parameterisation, one trial.** Any variation of $(p, n, k)$ or of $f$ is a **separate, explicitly counted exercise**: it appends a row to the family log and permanently raises $\text{SR}^{*}$ for every future member of the family, including this one's successors. M1's re-run is the measured precedent — a single extra trial moved $\text{SR}^{*}$ from $0.074552$ to $0.077708$ per period.

**This is where ATR models die.** The literature's ATR strategies are grids — three periods × four multipliers × two smoothings — reported as though one configuration had been tried. The trial log makes that unhideable here, and it is the reason the parameterisation above is committed before the first run rather than selected after it.

## 9. Rejected alternatives ▲

**Overlapping daily entries** (enter every session, run concurrent straddles) would raise $n_{\text{cond}}$ from ~89 to ~384. It gains nothing: the returns overlap, so the number of *independent* draws stays at the number of non-overlapping expiry cycles, while serial correlation inflates $\widehat{\text{SR}}$ and the margin stack multiplies. Rejected.

**$\text{IV} - \text{RV}^{\text{continuous}}$, the conditioner H1's decision record actually recommended.** `research/h1/DECISION.md` §5.3 names it: *enter only when ATM implied variance exceeds a trailing continuous realised variance by some margin*, on Sankar's reasoning. It is better motivated than ATR-band distance — it conditions on the component that the cited evidence says is compensated, rather than on one close to the component that is not (§1).

It is not first on **availability**, not on merit. ATR-band distance needs the spot series alone. $\text{IV} - \text{RV}^{c}$ needs (a) a clean ATM implied-variance series, which the spot-tracking strike ladder makes fragile — the ATM strike changes identity session to session and M1 already logs stale marks where a strike leaves the window — and (b) a jump/continuous decomposition (bipower variation or similar) on intraday data. Both are buildable; neither is buildable this week, and (a) shares a root cause with M2's blocker (M2 §1.3). **It should be the family's second conditioner**, and M3's result — positive or negative — sharpens what it is testing.

**Regime classification.** §2.

## 10. Known limits ▲

M1 §14 applies in full, plus:

1. **$n_{\text{cond}} \approx 89$**, weekday-clustered (§5, §7). Small, and the largest this position structure allows.
2. **The mechanism may be aimed at the wrong variance component** (§1). Sankar et al. find jumps do not forecast variance-swap returns, and an ATR-band extension is close to a jump.
3. **$N^{*}$ must exceed M1's**, so the cost-breakeven multiple is **not comparable** with M1's — brokerage $b$ is a flat ₹20/order and dilutes with size (M1 §11.1). Tolerable only because breakeven is a reported diagnostic and not a gate. Stamp it rather than compare it.
4. **The open-interest unit convention becomes load-bearing.** At M1's one lot, $\lfloor \beta \Omega \rfloor \geq 1$ held under either reading, so `corpus.open_interest_not_divisible_by_lot_size` was decorative (M1 §7). At M3's larger requested size it binds, and the convention is still unconfirmed. Under M3, that stamp means something.
5. **A binding participation cap truncates realised $f$ downward**, hardest where requested size is largest — i.e. where $f$ is largest, i.e. exactly where §1 predicts the payoff. **Direction of error: against the hypothesis**, so a positive result is not manufactured by it. It nonetheless breaks the scale-freeness of the M1 comparison, which is why §12.1(c) gates it to zero rather than stamping it.
6. **Two listed weekly expiries have no session file** (M1 §14.7); `infeasible_fraction` cleared its 10% not-evaluable limit by four legs on M1's re-run, and no census over the full corpus has been run. M3 inherits that exposure unchanged.
7. **$z$ is estimated, not observed.** $\text{ATR}_{14}$ on 14 observations is noisy, so $z$ carries estimation error into $f$, attenuating any true covariance between $f(z)$ and the outcome — again against the hypothesis.

## 11. Estimators

**M1 §11 unchanged**, including §11.1's demotion of cost-breakeven to a reported diagnostic. $N$ from `count_family_trials` (§6.2). Report PSR and DSR separately; the spread is the diagnostic, and M1's re-run shows H26's "the failure was almost entirely the correction" does not generalise.

## 12. Pre-registration gates ▲

M1 carries one (§12.1). M3 carries four, because continuous sizing puts three new quantities at risk. **Each must actually be run and pass before the validation run. None is an assumption.** Each is computed from **prices and contract metadata only** — never from strategy returns — so running them spends no evidence and appends no trial.

### 12.1(a) State-scale gate — is $k$ right for this window?

Over every entry session $t$ in the window:

$$\operatorname{median}_t \left|z_t\right| \in [0.4,\, 1.2] \qquad\wedge\qquad \Pr\!\left[\left|z_t\right| > 2.5\right] \leq 0.10$$

The first keeps the bulk of the sample in $\tanh$'s responsive band; the second bounds the fraction sized indistinguishably from M1. **If it fails, $k$ is wrong for the window** — a finding about the *parameter*, remedied at pre-registration by re-deriving $k$ from the $|d|$ distribution, never after seeing a return.

### 12.1(b) Sizing-resolution gate — is the conditioning expressible at all?

The claim in §4 is that size *degrades* rather than *switches*. Integer lots quantise it. With $n_{\text{base}} = N^{*}/(S_{t,\tau} L_t)$, require over the window's entry sessions:

$$\left|\left\{ \left\lfloor n_{\text{base}}\, f(z_t) + \tfrac12 \right\rfloor : t \in \text{entries} \right\}\right| \;\geq\; R \qquad\wedge\qquad n_{\text{base}}\left(f_{q90} - f_{q10}\right) \;\geq\; R, \qquad R = 10$$

**Bound on the realised $f$ distribution, not on $n_{\text{base}}$ alone.** A bare $n_{\text{base}} \geq R$ is not sufficient: at the bottom of the realised $f$ range, $\lfloor 20 \times 0.05 \rceil = 1$, and the quantisation is worst exactly where graceful degradation is the claim.

**M1's $N^{*}$ fails this by inspection.** At M1's parameterisation $n_{\text{base}} = 1$ (M1 §5), so the realised set is $\{0, 1\}$ and $R = 2$: $f$ collapses to a switch and M3 becomes the regime model §2 rejects. **The remedy is to raise $N^{*}$ at pre-registration, with the capital base raised in lockstep** so that Sharpe, drawdown and the increment stay scale-free and comparable to M1's. It is not to lower $R$.

### 12.1(c) Feasibility-slack gate — does the larger $N^{*}$ still fit?

At the chosen $N^{*}$, over the window:

$$\#\{\texttt{RESIZED}\} = 0 \qquad\wedge\qquad \#\{\texttt{CAPPED\_TO\_ZERO}\} = 0$$

M1 realised zero of both, which is what makes the M1 comparison scale-free. If M3's $N^{*}$ makes the caps bind, the two runs are no longer differing in one clause, and the realised $f$ is truncated (§10.5). **If it fails, $N^{*}$ is too large for the corpus's liquidity** — which, combined with (b)'s lower bound, is the honest possibility that **no $N^{*}$ satisfies both**. That would be a finding about the data platform, and it would be worth more than a deflated Sharpe.

### 12.1(d) Burn-in gate

At least $B = 60$ completed sessions exist in the corpus strictly before the window's first session, so the state series is seeded from pre-window data and the graded window is not shortened (§3.3).

### 12.1(e) M1 §12.1 unchanged

The sizing-floor check, run against $N^{*} f(z_t)$ rather than $N^{*}$. Note that $f \leq 1$ makes it **strictly harder** than M1's: the binding session is the one with the smallest $f$, not the smallest spot. Passing it is what keeps *which* sessions trade independent of $L_t$ — and under (b)'s resolution requirement the two gates work together, since a large $n_{\text{base}}$ is what stops small $f$ rounding to zero.
