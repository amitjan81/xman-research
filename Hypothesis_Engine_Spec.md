# Hypothesis Engine — Design Specification

| | |
|---|---|
| **Version** | **0.3** (frequency-scoped) |
| **Status** | Proposed |
| **Date** | 12 August 2026 |
| **Parents** | FRD v0.2 (requirements baseline); Options Research Platform HLD v0.3 (architecture) |
| **Scope** | The subsystem deciding *what to research*, *what to trade*, and *when*: hypothesis registry and seed catalogue, exploration, regime detection, regime→hypothesis gating, the gate ladder, and the allocator |
| **Convention** | **Requirements owned by the FRD are referenced by ID and never restated** (HLD rule). Requirements introduced here use `<AREA>-FR-nn` and are candidates for a future FRD revision — see §2.4 |

## Revision history

| Version | Date | Summary |
|---|---|---|
| **0.3** | 12 Aug 2026 | **Frequency scoping (owner decision).** The platform is mid-frequency: mean holding period measured in hours or longer, with individual short holds acceptable but not as the average. §5.7 added, separating the three axes that this constraint is usually conflated across — data sampling frequency, holding period, and execution latency sensitivity — and classifying every catalogue entry against them. *Catalogue changes:* **H19 (surface relative value) withdrawn** as out of scope; **H15 split** into H15a (0DTE intraday gamma, out of scope) and H15b (1DTE entered T-1 and held through expiry, in scope); H11's conditioner-only status given a second justification; H14 and H17 marked borderline with their specific reasons. *Schema:* three locked fields added — `data_frequency`, `latency_sensitivity`, `expected_mean_holding_period`. *Gates:* G1 rejects hypotheses whose expected mean hold is under one hour; a new portfolio-level check monitors the **live book's realised** mean holding period, because individually acceptable signals can aggregate into a de facto intraday book. |
| **0.2** | 12 Aug 2026 | **Full incorporation of the v0.1 review** (1 critical, 19 major, 12 minor). *Critical:* §3 added — the runtime-enforcement boundary with xman, mapping every control this subsystem introduces to where it is actually enforced. *Science:* §1.1's India transfer rewritten — the Dew-Becker & Giglio friction is a **structural** constraint on option writing which does **not** exist in India; the argument now runs through demand-pressure and limits-to-arbitrage, with H12 named as its identification input. H1's mechanism rewritten to the intermediation-rent channel, with the preference channel recorded as the *rejected* alternative it contradicted. The SEBI interventions are no longer described as separable experiments (three fall on one day) and their pre-2024 data dependency is stated. §6.3/6.4 tables attributed and evidence-graded. *Catalogue:* three canonical hypotheses added (jump/tail premium, overnight-vs-intraday variance, trend as short-vol conditioner); role taxonomy reconciled. *Epochs:* definition widened to admit enforcement and participation shocks (the July 2025 Jane Street order); the October 2024 STT change added; "hard-coded calendar" replaced by the parents' epoch registry. *Gates:* the §6.1 gating experiment now tests the design actually specified rather than a strawman; the prefix-property check moved from G4 to G1; G4 restated honestly as a demotion gate, since the spec's own episode arithmetic makes it unpassable for roughly a decade; G6's structural exception to threshold-locking named and given its own discipline. *Allocator:* weighting unit defined as risk-based with an explicit margin budget; the regime multiplier no longer applies uniformly; conflict resolution given per-axis direction definitions and a declared-relationship exemption so hedges are not cancelled; rebalancing bands and a naive-benchmark hurdle added. *Process:* phase and verification method on every requirement. |
| 0.1 | 12 Aug 2026 | Initial specification. Seeded from two research streams: an options-hypothesis catalogue (24 candidates across 9 families) and a regime-detection review. |

---

## 1. Why this subsystem exists

The platform's other subsystems answer *"is this signal real?"*. This one answers the questions upstream and downstream: **"what should I test at all?"** and **"of the things that survived, which should be live right now?"**

Neither is answered today. The HLD names a Signal Registry and a portfolio risk budget but designs no mechanism for selecting among hypotheses, no regime model, and no allocator. §2.3 assigns the missing components to containers.

### 1.1 The finding that should change your priors — and the care its transfer requires

**Dew-Becker & Giglio (2025)** find that equity index options historically displayed sharply negative returns and CAPM alphas, but **over roughly the past fifteen years option alphas have become statistically indistinguishable from zero** — while their *synthetic* options, constructed to strip out option-market frictions, have **never** shown negative alpha across 1926–2022.

The implication is structural: the variance risk premium underpinning the entire short-volatility complex was substantially an **intermediation rent** — compensation for frictions and a demand imbalance — rather than a deep preference-based risk premium. It eroded as frictions fell.

*Status caveat:* this is a **2025 working paper**, not peer-reviewed. Its direction is corroborated by the authors' earlier synthetic-options work, but the VRP-decline literature is not unanimous. The document rests a great deal on it; that weight is stated deliberately so a reader can discount it.

**Where the India transfer must be careful.** Their model's friction is that **retail investors are structurally unable to sell options**, so equilibrium prices are set by whoever has the greatest demand. **That constraint does not exist in India.** Indian retail can and demonstrably does write options at scale; SEBI's own studies discuss retail writers. The v0.1 claim that the friction is "more binding in India than anywhere" was **false as stated** and is withdrawn.

What India plausibly has is a **large net retail demand imbalance in short-dated index options** — a behavioural fact, not a binding constraint. The argument therefore runs through the **demand-pressure and limits-to-arbitrage channel** (H4's mechanism) rather than through DBG's structural friction: if one side of the market persistently demands and capacity-constrained intermediaries must absorb it, the absorber earns a rent that shrinks as the imbalance shrinks or as absorbing capital grows.

That yields a weaker but still falsifiable prediction:

> **If Indian option premia are substantially an imbalance rent, then (a) the measured Indian variance risk premium should exceed the current US premium, and (b) it should decline as the net retail demand imbalance declines.**

**Critically, (b) requires measuring the imbalance, not assuming it.** H12 — NSE's participant-wise open interest — is the only available data that can identify the net sign and magnitude, and it is therefore the **identification input for H23**, not an unrelated catalogue entry. Its granularity ceiling (daily, EOD, aggregated by instrument class) caps the precision of any such test.

**On the SEBI interventions as natural experiments.** v0.1 described them as a sequence. They are not. **Three of them land on the same day** — 20 November 2024 carries the weekly-expiry cull, the contract-size increase and the 2% expiry-day extreme-loss margin together — so that date is one confounded bundle, not three experiments. Two later events (10 Feb 2025, 1 Apr 2025) are separable from each other but confounded with market conditions. And measuring the premium either side of any of them requires **chain history from before November 2024**, which prospective capture cannot produce and which depends entirely on the vendor-backfill decision the HLD lists as its highest-value unresolved item. v0.1's claim that this is "measurable from data you will already hold" was wrong and is withdrawn.

**Design consequence, unchanged.** The platform must not treat the variance risk premium as a constant to be harvested. It must **measure it continuously by epoch and regime, and instrument its own erosion** — see DEC-FR-01. A short-volatility book resting on an unmeasured assumption is exposed to a clock it cannot see.

### 1.2 Three positions this document argues

1. **The regime layer must justify its own existence before it is built** (§6.1). The likeliest outcome is that it should not be.
2. **The allocator starts deliberately dumb** (§9) — it sits downstream of every anti-overfitting control, where nothing is watching it.
3. **Significance for option strategies cannot be assessed with t-statistics** (§8.4).

---

## 2. Position within the document set

### 2.1 Vocabulary

| Term | Meaning |
|---|---|
| **Hypothesis** | A falsifiable claim about why a trade should pay, with a stated mechanism and a null. Not a strategy, not code |
| **Mechanism** | *Who is on the other side and what are they compensated for.* The field distinguishing an edge from a pattern |
| **Signal** | Versioned code implementing a decision rule from a hypothesis, per the FR-SIG-02 contract |
| **Conditioner** | A hypothesis with no independent P&L expression, modulating another trade's sizing or direction |
| **Risk input** | A computed quantity consumed by other hypotheses or by risk management; never traded and never promoted |
| **Regime** | A parameter vector (drift, volatility, downside deviation) governing the return process — not a narrative label |
| **Epoch** | A period of stable *market structure*. See §6.6 — the definition now includes participation shocks, not only rule changes |
| **Trial** | Any evaluation of any variant, kept or not. The denominator of every significance statistic (FR-VAL-03) |
| **Episode** | One contiguous occupancy of a regime. The honest unit of sample size for regime-conditional claims |

**Epoch and regime are different and must never be conflated.** A regime is a statistical state the market moves between. An epoch is a change in the market's structure or participant set, invisible to any return-based detector.

### 2.2 Lifecycle mapping

Four vocabularies existed across the document set with nothing mapping them. This table is now authoritative; the HLD's Lifecycle State Machine implements the FR-DEP-01 column, and the others are views onto it.

| FR-DEP-01 state | FR-RES-03 status | This spec's gate | Registry `status` |
|---|---|---|---|
| hypothesis | open | G0 registered | `proposed` / `blocked_on_data` |
| experiments | open | G1–G2 | `testing` |
| candidate | open | G2 shortlist | `testing` |
| validated | supported | G3 (+G4 if regime-conditional) | `supported` |
| forward test | supported | G5 | `supported` |
| production | promoted | G6→G7 | `promoted` |
| monitored | promoted | live | `promoted` |
| improved \| retired | rejected \| — | new linked record \| retirement | `rejected` / `retired` |

### 2.3 Container assignment

None of the HLD's 13 containers owned this subsystem's components. Assigned here, for the HLD to absorb at its next revision:

| Component | HLD container | Plane / slice | Note |
|---|---|---|---|
| Hypothesis registry, seed catalogue | Registries & Ledgers | data | Extends the existing registry set |
| Regime detector (training) | Backtest & Validation Workers | research | Batch, retrained on cadence |
| Regime detector (inference) | Signal Runtime | production / capture | Must be causal and low-latency; shares the artefact with training per FR-SIG-04 |
| Allocator | **Lifecycle Controller** | production / capture | **It gates live emission, so it cannot live in the research slice** — the same trust-boundary argument that placed the gate evaluator there (HLD AD-22) |
| Conflict veto, concentration enforcement | Lifecycle Controller + xman Webhook Gateway | production | Split per §3 |
| Naive-benchmark harness | Backtest & Validation Workers | research | |

### 2.4 Requirements convention and the FRD revision this implies

Requirements owned by the FRD are **referenced by ID, never restated**. Where v0.1 restated an FRD requirement, this revision cites it instead:

| v0.1 requirement | Owned by | Disposition |
|---|---|---|
| HYP-FR-02, GATE-FR-10 (threshold locking) | **FR-VAL-09** | Withdrawn; cited |
| HYP-FR-03 (trial count not self-reported) | **FR-VAL-03** | Withdrawn; cited |
| GATE-FR-11 (Tier-2 only as evidence) | **FR-VAL-05** + HLD AD-17 | Withdrawn; cited |
| GATE-FR-12 (minimum backtest length) | **FR-VAL-11** | Withdrawn; cited |
| DEC-FR-03 (retirement post-mortem) | **FR-FB-04** | Withdrawn; cited |
| EXP-FR-03 (machine candidates ledgered) | **FR-AI-06** | Withdrawn; cited |
| ALLOC-FR-03 (concentration limits) | **FR-CAP-03**, **FR-SIG-06** | Withdrawn; cited |
| REG-FR-12 (epoch registry) | **FR-DATA-16** | Reduced to the training-window refusal only |

**This spec introduces new runtime scope** — the allocator's weighting, the conflict veto, the regime exposure multiplier — which FRD §1.2.1 says requires a new FRD revision. **That revision is requested, not assumed.** Until it exists, §9's requirements are proposals with no FRD module owner, and are marked *Pending-FRD* in §12.

---

## 3. The runtime-enforcement boundary *(the critical gap in v0.1)*

The FRD is explicit: runtime enforcement lives in xman; this platform researches and emits. v0.1 introduced four runtime controls and never said where any of them takes effect. Each is now assigned.

| Control | Computed by | Enforced where | Rationale |
|---|---|---|---|
| **Regime exposure multiplier** | Signal Runtime (inference) | **Emitted** — scales the size hint in the FR-EXE-01 payload | It is a research output about sizing, not a safety limit. If it fails, position size is wrong, not unbounded |
| **Per-signal enable/disable and size cap** | Lifecycle Controller | **Emission interface (FR-EXE-03)**, *and* independently in xman | Belt and braces; the FRD already specifies caps at the interface layer independent of xman-side controls |
| **Conflict veto** | Lifecycle Controller | **Emission — suppression means no emission is sent** | A veto is the absence of an instruction; it needs no downstream enforcement and cannot fail open |
| **Concentration limits** (per underlying, expiry, direction, moneyness) | Lifecycle Controller, checked at G6 and at emission | **Both** — advisory at emission, authoritative in xman | Book-relative and safety-relevant. This platform cannot see xman's true live book with certainty, so it must not be the sole enforcer |
| **Gross short-gamma cap** | — | **xman only** | A hard risk limit protecting capital. **It must not depend on this platform being correct, reachable, or running.** REG-FR-08's requirement that limits sit *beneath* the regime layer means exactly this |

**ENF-FR-01** *(Must, Phase 2, verification: demonstration)* — Every control this subsystem introduces shall declare its enforcement point in the table above; no control shall be introduced without one.

**ENF-FR-02** *(Must, Phase 2, verification: test)* — Controls classified as protecting capital rather than shaping research output shall be enforced in xman and shall remain effective when this platform is stopped, unreachable, or emitting incorrectly. A fail-safe test shall demonstrate this.

**ENF-FR-03** *(Should, Phase 2, verification: inspection)* — Where a control is enforced in both places, the platform-side value shall be recorded on every emission so a divergence between intended and enforced limits is reconstructable.

---

## 4. The hypothesis record

### 4.1 Schema

Fields marked **locked** become immutable once the first gated result exists, per **FR-VAL-09**.

| Field | Purpose | Locked |
|---|---|---|
| `id`, `title` | Identity | — |
| **`mechanism`** | Who is on the other side; what they are compensated for; why they cannot avoid paying | ✔ |
| `claim` | The falsifiable statement | ✔ |
| `rejected_mechanisms` | Channels considered and ruled out, with reasons. Prevents a hypothesis silently carrying a mechanism its own evidence contradicts — the defect H1 carried in v0.1 | ✔ |
| `predictors` | Named features; missing ones become data prerequisites | ✔ |
| `universe`, `sample` | Instruments, liquidity floor, date range **and epochs spanned** | ✔ |
| **`null`** | The result that abandons this hypothesis | ✔ |
| `role` | `signal` \| `conditioner` \| `risk_input` \| `benchmark` | ✔ |
| `horizon` | The horizon at which the effect is claimed | ✔ |
| **`data_frequency`** | Sampling granularity required to *compute* the signal. Distinct from latency — see §5.7 | ✔ |
| **`latency_sensitivity`** | `none` \| `moderate` \| `high` — how fast the edge decays after the signal fires | ✔ |
| **`expected_mean_holding_period`** | The *mean*, not the minimum. Gated at G1 (§5.7) | ✔ |
| `evaluation_plan` | CV scheme, purge, embargo, metric, hurdle preset | ✔ |
| **`thresholds`** | Per **FR-VAL-09**. Includes DSR minimum, PBO maximum, cost-breakeven floor, tail floor, **the naive-benchmark increment (§8.5)**, **the decay haircut (§10.2)**, and if regime-conditional the minimum-episode requirement | ✔ |
| `identification_inputs` | For hypotheses whose test depends on another hypothesis's data — e.g. H23 depends on H12 | ✔ |
| `provenance` | `original` \| `literature` \| `vendor` \| `machine_generated`, with citation and date | — |
| `data_prerequisites` | Granularity, history, derived analytics. Blocks the hypothesis if unmet | — |
| `status` | Per §2.2 | — |
| `trial_count` | Derived from the ledger per **FR-VAL-03** | — |

### 4.2 Requirements

- **HYP-FR-01** *(Must, Phase 1, test)* — Reject any record whose `mechanism`, `null`, `rejected_mechanisms` or `thresholds` are empty.
- **HYP-FR-04** *(Must, Phase 1, test)* — Where `data_prerequisites` are unmet, status is `blocked_on_data` and gated evaluation is refused.
- **HYP-FR-05** *(Must, Phase 1, test)* — Refuse promotion of a `conditioner` or `risk_input` to standalone live emission.
- **HYP-FR-06** *(Should, Phase 2, demonstration)* — Searchable by mechanism family, predictor, status and epoch, so a proposal can be checked against prior art before testing.
- **HYP-FR-07** *(Must, Phase 1, inspection)* — Where a hypothesis declares `identification_inputs`, the platform shall block gated evaluation until those inputs are themselves available at the stated granularity.

---

## 5. The seed catalogue

Twenty-seven candidates surveyed; eighteen seeded. **Evidence grades:** **A** replicated peer-reviewed with at least partial Indian evidence · **B** strong peer-reviewed, US/EU only, transfer is an assumption · **C** contested, or practitioner/vendor tier · **D** mechanism plausible, evidence absent.

### 5.1 The anchor hypotheses

**H1 — Index variance risk premium.** *Grade A. Role: signal.*
*Claim:* implied variance on the index systematically exceeds subsequently realised variance; selling variance earns a premium.

***Mechanism (corrected in v0.2):*** the premium is substantially an **intermediation rent**. One side of the market — in India, predominantly retail buyers of short-dated index options — persistently demands convexity; capacity-constrained intermediaries absorb that demand and are compensated for inventory risk they cannot fully hedge, for jump exposure that dynamic hedging cannot replicate, and for margin that binds precisely when the payout occurs.

***Rejected mechanism:*** the deep preference-based story — *buyers purchase insurance against a wealth-destroying state, so it prices above actuarial value*. v0.1 carried this as H1's mechanism, which **contradicted §1.1's central finding**: if synthetic frictionless options never showed negative alpha across a century, the preference channel is approximately zero and cannot be the source. Recording it as rejected is what makes H23 a *test of* H1's mechanism rather than a refutation of it.

*India evidence:* Sankar, Ramachandran & Lukose (2020) test and **reject** the prior that variance risk is unpriced in retail-heavy markets, using Indian data, robust across model-dependent and model-free approaches.
*Critical refinement:* they find only past **continuous** variance forecasts variance-swap returns — **realised jumps have no predictive power**. A jump-loaded realised-variance estimator degrades the signal; separate the components. This is also why H25 exists.
*Data:* full chain, ≥2 expiries, intraday underlying for realised variance, 8–10 years.
*Decay:* live, on a clock set by the imbalance and by regulation.

**H23 — Imbalance rent as the source of the Indian premium.** *Grade C (downgraded from B in v0.1). Role: research question. Identification input: H12.*
The India test of §1.1's mechanism, restated through demand-pressure rather than DBG's structural friction. Downgraded because the identification is weaker than v0.1 implied: it needs the net imbalance measured (H12, daily EOD aggregate only) and premium history spanning epoch boundaries that prospective capture cannot supply.

**H2 — VRP as a return predictor.** *Grade B. Role: conditioner.* Strongest at roughly quarterly horizon — **not** a weekly-expiry timing signal.

### 5.2 Newly seeded in v0.2

**H25 — Jump/tail risk premium, distinct from the diffusive premium.** *Grade B. Role: signal.*
*Mechanism:* far-OTM options cannot be replicated by dynamic hedging when jumps exist, so their seller bears genuinely unhedgeable jump risk and must be paid a premium *separate* from the diffusive variance premium. Supported by evidence of a significant price-jump component in variance swap rates.
*Why it belongs:* H1 already forces continuous/jump separation in estimation but v0.1 had no hypothesis about the jump component's premium — the natural companion, and the one most relevant to a crash-exposed book. Expect it to be untestable at conventional significance on Indian samples (too few jumps); its value is as a **risk input that prices what the tail costs**, and it is graded accordingly.

**H26 — Overnight versus intraday variance premium.** *Grade B. Role: signal.*
*Mechanism:* variance accrues over trading time while option decay accrues over calendar time. Whoever holds short options across a non-trading period collects decay without bearing variance — but also bears unhedgeable gap risk, and the two are not equally priced.
*Why it belongs:* well documented, directly relevant to Indian expiry structure, and computable from data the platform will already hold. Cheap to test.

**H27 — Underlying trend as a short-volatility conditioner.** *Grade C. Role: conditioner.*
*Mechanism:* short-gamma positions lose in sustained directional moves regardless of realised-volatility level; a trend measure conditions exposure on the environment that actually hurts them.
*Why it belongs:* the most common practitioner overlay, and **the obvious continuous-conditioning rival to the entire §6 regime layer**. Its absence from v0.1 was conspicuous precisely because §6.1 predicts continuous conditioning wins — so this is the natural comparator in that experiment.

### 5.3 The remainder

| ID | Hypothesis | Grade | Role | The thing to know |
|---|---|---|---|---|
| **H4** | Put overpricing / net buying-pressure skew premium | B | signal | Demand-pressure and limits-to-arbitrage, not preference. **No Indian equivalent study exists.** Its mechanism is the one H1 and H23 now borrow |
| **H7** | Term-structure SLOPE predicts variance-asset returns | B | conditioner | SLOPE is the **second principal component**, not front-minus-back, and predicts *variance-asset* returns, not equity returns. India has no liquid VIX futures — build the curve synthetically |
| **H8** | Contango/backwardation carry; inversion as stress flag | C | mixed | The **inversion flag is more robust than the carry trade**. Calendar-spread margin relief was removed on expiry day (10 Feb 2025) |
| **H9** | Scheduled-event IV run-up and crush | B | signal | **Union Budget (1 Feb)** has no US analogue in magnitude. **No systematic academic treatment of the Indian index-level event set exists** — a genuine opportunity |
| **H10** | Implied vs realised event move | C | signal | The conditioned version of H9 |
| **H11** | Dealer gamma → realised volatility | C | conditioner | US literature is **genuinely split** on sign; the reconciliation is that the *sign of dealer gamma* is the state variable. India has **no signed order flow**, so every implementation rests on an assumed dealer sign |
| **H12** | Participant-category positioning | D | conditioner | **Daily EOD, aggregated by instrument class** — that ceiling is permanent. Now also the **identification input for H23** (§1.1) |
| **H14** | Pinning at expiry | C | research question | Indian index options settle on the **last-30-minute time-average of the index** (corrected from v0.1's "VWAP"), which plausibly neutralises close-clustering. Indian evidence is mixed-to-null |
| **H15a** | 0DTE intraday gamma regime | C | — | **Out of scope (§5.7)** — holds minutes to hours with high latency sensitivity. Retained in the catalogue so the exclusion is explicit rather than an omission |
| **H15b** | 1DTE, entered T-1 and held through expiry | C | signal | The in-scope half of the former H15: ~24-hour hold, no latency sensitivity. Arguably the world's most extreme short-dated market with **essentially no published microstructure work**. Most affected by the §7.6 participation shock |
| **H17** | Dispersion / correlation risk premium | B | signal | Cleanest mechanism in the catalogue. But liquidity is concentrated in a handful of names — full-index dispersion is probably not executable; reduced-basket only |
| **H18** | Cross-sectional IV−RV and delta-hedged option returns | B | signal | Needs a broad liquid single-stock cross-section India lacks. Expect non-replication for **data** reasons, not economic ones |
| **H20** | HAR-RV | A | risk_input | **Not a trade — the denominator of nearly everything above.** Build first. Carry HAR-J given H1's jump finding |
| **H21** | IV momentum and mean reversion | C | signal | Horizon-dependent sign flip makes single-horizon fits unstable |
| **H22** | India VIX informational content | C | risk_input | Literature is low-tier with at least one internal contradiction. **Re-derive on your own data** — history is free from NSE |

### 5.4 Role taxonomy

`conditioner` and `risk_input` are **distinct roles with different consequences** (HYP-FR-05 blocks promotion of both, but only conditioners modulate another trade's sizing). v0.1's §4.3 miscounted by pooling them.

- **Conditioners:** H2, H7, H8 (inversion), H11, H12, H27 — six.
- **Risk inputs:** H20, H22, H25 — three.
- **Signals:** H1, H4, H9, H10, H15b, H17, H18, H21, H26 — nine.
- **Research questions:** H14, H23.
- **Out of scope on frequency grounds (§5.7):** H15a, H19.

The discriminator: **does the predictor have its own P&L expression, or does it only modulate another trade?** Second cut: **anything whose Sharpe comes from a crash-exposed short-volatility payoff enters as an exposure conditioner, not an entry trigger** — otherwise the backtest Sharpe misrepresents the risk.

### 5.5 Backlog

H3 (VRP term structure — needs multi-expiry), H5 (risk-neutral skewness — **the literature's sign conventions are genuinely split and the two common measures move in opposite directions**; any implementation must store the definition with the series), H6 (tail-hedging cost — subsumed by H25), H13 (PCR and max pain — **max pain has no independent mechanism**; carry only as a benchmark), H16 (expiry-week theta — re-indexed by the Sep 2025 migration), H24 (expiry-day migration as a natural experiment — **the best available way to validate the gamma and expiry families causally**). *H19 was in this backlog in v0.2 and is now withdrawn entirely on frequency grounds (§5.7).*

### 5.6 Two inference errors the catalogue must actively prevent

**"Retail loses money" does not imply "fading retail pays."** SEBI's FY25 study reports ~91% of individual F&O traders losing money and aggregate net losses of ₹1,05,603 crore. *(v0.1 conflated the study's ~96 lakh top-13-broker sample with the ~1.05 crore trader population; corrected.)* But those losses are substantially **transaction costs, STT, spreads and adverse selection** — symmetric frictions a systematic fader also pays, not transfers to whoever takes the other side. **No study was found demonstrating a strategy profiting by fading retail positioning.** Any hypothesis invoking this must address the frictions objection in its `mechanism` field.

**High IV rank does not imply cheap-to-sell.** The evidence is vendor-tier and measures win rate and premium collected — the wrong denominators. The discriminating question is P&L **per unit of realised gamma risk or maximum adverse excursion**. And the variance risk premium *compresses* after volatility spikes, exactly when IV rank peaks, because realised volatility catches up. Prefer VRP, which has peer-reviewed forward-predictive support, over IV rank, which does not.

### 5.7 Frequency scoping — three axes, not one

**Owner constraint:** the platform is mid-frequency. Mean holding period is measured in **hours or longer**; individual positions held for minutes are acceptable, but not as the average case.

Applying that constraint requires separating three properties that are routinely conflated:

| Axis | Question | Why it is independent |
|---|---|---|
| **Data frequency** | What sampling granularity is needed to *compute* the signal? | Computed offline; says nothing about how fast you must act |
| **Holding period** | How long is the resulting position held? | The axis the owner constraint actually governs |
| **Latency sensitivity** | How fast must you act once the signal fires, before the edge decays? | The axis that makes something HFT-like |

**This distinction is load-bearing, not pedantic.** H1 — the anchor hypothesis — requires 5-minute underlying bars to compute realised variance honestly, yet it is computed at end of day and held to expiry: zero latency sensitivity, multi-day hold. Reading "we are not HFT" as "no intraday data" would eliminate H1, H20, H25 and H26 — the core of the catalogue — for no reason. **Intraday *sampling* is not intraday *trading*.**

| Hypothesis | Data frequency | Mean hold | Latency sensitivity | Scope |
|---|---|---|---|---|
| H1 VRP | 5-min underlying (offline) | days–weeks | none | **In** |
| H2 VRP as predictor | daily | quarterly | none | **In** |
| H4 Skew premium | chain, EOD adequate | weeks | none | **In** |
| H7 Term-structure SLOPE | multi-expiry, EOD | weeks | none | **In** |
| H8 Calendar / inversion | multi-expiry, EOD | days–weeks | none | **In** |
| H9 / H10 Event crush | multi-expiry daily; intraday helps | hours–days | moderate, **exit only** | **In** |
| H12 Participant OI | daily EOD (capped) | conditioner | none | **In** |
| H18 Cross-sectional | daily, broad cross-section | monthly | none | **In** |
| H20 HAR-RV | intraday (offline) | risk input | none | **In** |
| H21 IV momentum / reversion | daily | days–weeks | none | **In** |
| H22 India VIX | daily | risk input | none | **In** |
| H25 Jump premium | intraday, bipower (offline) | weeks | none | **In** |
| H26 Overnight vs intraday | intraday session split | overnight by construction | none | **In** |
| H27 Trend conditioner | daily | conditioner | none | **In** |
| H11 Dealer gamma | **intraday per-strike OI** | conditioner | moderate | **Conditioner only** |
| H14 Pinning | intraday, expiry day | hours, final session | **high in the tail** | **Borderline** |
| H17 Dispersion | simultaneous index + constituent chains | weeks | **execution, not signal** | **Borderline** |
| **H15a** 0DTE intraday gamma | intraday multi-strike multi-expiry | **hours or less** | **high** | **Out** |
| **H15b** 1DTE overnight | multi-expiry daily | **~24 h** | none | **In** |
| ~~H19~~ Surface relative value | intraday | minutes–hours | **high** | **Withdrawn** |

**Withdrawn: H19.** The catalogue already characterised it as closer to market-making than mid-frequency. Intraday data, minutes-to-hours holds, fast-decaying edge — the definition of what this constraint excludes.

**Split: H15.** One name covered two different trades. **H15a** — intraday 0DTE gamma — holds minutes to hours with high latency sensitivity and is out of scope. **H15b** — entered at T-1 and held through expiry, roughly a 24-hour hold with no latency sensitivity — is in scope, and is attractive given India's expiry structure. They carry different data prerequisites and must not share a record.

**H11 survives only because it is a conditioner.** Traded directly it is an intraday momentum play. Conditioning another trade's exposure on the dealer-gamma sign does not inherit that holding period. Note the cost though: it still needs **intraday per-strike open interest**, because end-of-day OI misses same-day-opened positions entirely — most of the volume in India — so this is real data expenditure for a conditioner.

**H14 and H17 are borderline for different reasons.** H14's hold is hours and confined to the final session, with the edge concentrated in the settlement window — it satisfies the holding rule but has a latency-sensitive tail. H17's holding period is fine at weeks; its problem is that legging a multi-name basket carries execution risk that behaves like a latency constraint even though the signal is slow.

- **SCOPE-FR-01** *(Must, Phase 1, test)* — G1 shall reject any hypothesis whose `expected_mean_holding_period` is under one hour, or whose `latency_sensitivity` is `high`, unless an explicit recorded exemption is granted at registration.
- **SCOPE-FR-02** *(Must, Phase 2, test)* — The platform shall monitor the **live book's realised** mean holding period and alert when it falls below the configured floor. **This matters more than the per-hypothesis gate:** individually acceptable short-hold signals can aggregate into a book that is de facto intraday, which is the drift the constraint exists to prevent.
- **SCOPE-FR-03** *(Should, Phase 2, inspection)* — Where a hypothesis requires intraday data purely as *offline sampling*, that shall be recorded distinctly from a requirement for intraday *execution*, so data-acquisition decisions are not made against the wrong justification.

---

## 6. Exploration

### 6.1 Intake

Four paths — seeded, human, literature-derived, machine-generated — all entering the same registry, completing the same schema, traversing the same gates. Provenance changes the decay prior (§10.2) and nothing else.

### 6.2 Breadth is priced, not forbidden

Every variant tested raises the deflated-Sharpe hurdle every survivor must clear (**FR-VAL-03**). That is what lets the platform permit unlimited exploration without permitting self-deception.

**Machine-scale search strains it.** No published method reconciles machine-scale search with DSR/PBO-style corrections — the corrections assume a countable, honest trial family. **FR-AI-06** takes the conservative position; this spec records it as a position taken absent established practice.

**Regime slicing is also search.** Testing *s* strategies × *r* regime definitions × *t* thresholds is closer to *s·r·t* effective trials than to *s+r+t*; 5×3×3 = 45 moves the required t-statistic from ~2.0 to ~3.2 under Bonferroni. *(v0.1 cited Novy-Marx here; that result concerns **combining** signals into one strategy and applies to selecting a best (strategy, regime) **pair**, not to plain grid counting. Citation narrowed accordingly.)*

- **EXP-FR-01** *(Must, Phase 1, test)* — Every hypothesis, regardless of intake path, completes the §4.1 schema before any evaluation runs.
- **EXP-FR-02** *(Must, Phase 1, test)* — Each distinct regime definition and threshold value evaluated increments the trial count for the hypothesis under test.
- **EXP-FR-04** *(Should, Phase 2, demonstration)* — Before testing, report similarity to existing entries by predictor overlap and mechanism family.
- **EXP-FR-06** *(Must, Phase 1, test)* — **Detector hyperparameter tuning is search.** Sweeping a persistence penalty, feature set or state count increments the trial count of every hypothesis subsequently evaluated against that detector.

---

## 7. Regime

### 7.1 The gating experiment — corrected, and still run first

v0.1's experiment compared a smooth function of the conditioning variable against **the discrete label derived from it** — but §7.4 mandates the layer never emit a discrete label. It emits **filtered probability as a continuous weight**, which is a *different* smooth function of history, embedding persistence and multi-feature inference. The v0.1 test was therefore aimed at a strawman.

**REG-FR-01** *(Must, Phase 1, test)* — Before the regime subsystem is built, run and record a horse race on identical forward P&L, comparing:
  (a) a smooth function of the continuous conditioning variable (India VIX level; VRP);
  (b) **the filtered-probability weight the design actually specifies**;
  (c) the discrete label, as a reference point only;
  (d) **H27's trend conditioner**, as the practitioner-standard rival.
**If (b) does not beat (a) and (d) out of sample after costs, the regime layer shall not be built** and the platform implements continuous conditioning instead.

**REG-FR-01a** *(Must, Phase 1, inspection)* — The forward-P&L series for REG-FR-01 shall be the backtest P&L of a **pre-registered, fixed set of naive benchmark strategies** (§8.5) — not candidate signals, whose selection would contaminate the comparison. Running the experiment increments those benchmarks' trial counts, not any hypothesis's.

### 7.2 If built: two states, never four

At persistence settings that avoid whipsaw, five years contains roughly **two to three regime episodes in total** — not per regime. At settings producing many episodes, turnover destroys the edge. **Persistence and statistical power are in direct opposition and five years cannot supply both.**

*(v0.1 attributed 0.5 shifts/year to the tuned model that produced the cost-aware gains. The tuned model ran ~0.9 shifts/year; 0.5 was the most-penalised column of a frequency sweep. The conclusion is unchanged at ~0.9.)*

A four-state univariate Gaussian HMM carries 20 free parameters; if the rarest state occupies 5% of a 1250-day sample, several of its parameters rest on ~2 effective observations.

- **REG-FR-02** *(Must, Phase 2, test)* — Cap state count at 3; default 2.
- **REG-FR-03** *(Must, Phase 2, demonstration)* — Report **episode-count n**, never day-count n, and visually suppress any per-regime statistic backed by fewer than 5 episodes.
- **REG-FR-04** *(Must, Phase 2, test)* — Resample with a stationary or block bootstrap at block length comparable to dwell time. IID day-level resampling produces intervals roughly √(dwell) too narrow.

### 7.3 Causality

Filtering uses data to time *t*; smoothing uses the entire sample. **The default plot after fitting an HMM to history is the smoothed one.**

**Evidence grade and provenance.** The figures below come from a **practitioner-tier source** — a published open-source replication and an accompanying write-up, not peer-reviewed work. They are directionally corroborated by the standard filtering/smoothing distinction but the magnitudes are **unverified**. Two requirements derive from them and are marked accordingly.

| Variant | Sharpe *(practitioner source, unverified)* |
|---|---|
| Buy and hold | 0.67 |
| Causal (filtered) | 0.78 |
| Parameter look-ahead only | 0.77 |
| Smoothed (full look-ahead) | 1.74 |

The decomposition is the usable finding: **parameter look-ahead was nearly free; probability look-ahead more than doubled the Sharpe.** The audit should target the state-inference path.

- **REG-FR-05** *(Must, Phase 1, test)* — **The prefix-property test.** Compute the regime series through *T*, recompute through *T+k*, assert element-wise equality on the overlapping prefix. A failing detector is barred from every backtest path. Catches smoothed decoding, full-sample scalers, full-sample quantile thresholds and forward-filled features in one assertion. **Checked at G1** (§8.1) — it is a property of the detector, not of any hypothesis's results.
- **REG-FR-06** *(Must, Phase 2, test)* — Thresholds computed from trailing windows only, never full-sample quantiles.
- **REG-FR-07** *(Should, Phase 2, demonstration)* — Alert when a regime-conditional strategy's Sharpe exceeds buy-and-hold by more than ~2×. *Derived from the unverified table above; the ratio is a heuristic tripwire, not a validated threshold.*

### 7.4 Latency

Reported lag between a true state change and filtered probability crossing 0.5 is **median 2–3 days, 90th percentile ~7 days** *(same practitioner source; unverified)*. **For Indian weekly options that is most of a contract's life.**

- **REG-FR-08** *(Must, Phase 2, test)* — Hard position limits and defined-risk structures sit **beneath** the regime layer, enforced per §3 in xman. A regime signal shall never be the primary tail control for a short-gamma position.
- **REG-FR-09** *(Should, Phase 3, inspection)* — The operator-facing threshold control displays its measured false-positive rate at selection time.

### 7.5 Detection method

Recommended: a **statistical jump model with an explicit persistence penalty**, or **Bayesian online change-point detection**, whose causality is structural — there is no smoothed variant to use by accident. **Avoid Markov-switching GARCH as a first build**: its path-dependence problem makes exact likelihood computation infeasible, so you inherit an estimation research problem rather than a library call.

Features: 3–5 return-derived exponentially-weighted measures at mixed halflives, plus VRP. No macro, correlation or liquidity inputs in v1 — every added feature multiplies the trial count (EXP-FR-06).

- **REG-FR-10** *(Must, Phase 2, demonstration)* — Persistence is an explicit tunable hyperparameter; switches-per-year is a first-class diagnostic on every run.
- **REG-FR-11** *(Should, Phase 2, test)* — After every retrain, re-map state indices to a canonical ordering and log a diff of the trailing 250 days' labels. A large diff means the detector changed, not the market.
- **REG-FR-13** *(Must, Phase 2, inspection)* — Declare and record the detector's retrain cadence, training window, and whether training windows may span epoch boundaries (they may not, per REG-FR-12).

### 7.6 Epochs

**The v0.1 definition was too narrow.** It admitted only changes "knowable in advance from a circular", which excludes the most consequential recent break: the **July 2025 SEBI interim order against a dominant expiry-day participant**, which altered expiry-day microstructure at least as much as any margin change — and was neither a rule change nor knowable in advance.

**An epoch is any change in market structure *or participant composition* that breaks the comparability of data across it.** Three kinds:

| Kind | Example | Knowable in advance |
|---|---|---|
| Rule change | Contract size, margin, expiry weekday, STT | Yes, from a circular |
| **Enforcement / participation shock** | **A dominant participant removed or restricted** | **No** |
| Product change | Weekly expiry cull removing four of five products | Yes |

Known boundaries: **1 Oct 2024 (STT on option sales raised — named by FR-DATA-16 and omitted from v0.1)**, 20 Nov 2024 (weekly cull + 2% expiry-day ELM + contract size, **one confounded bundle**), 10 Feb 2025 (calendar-spread relief removed on expiry day), 1 Apr 2025 (intraday position-limit monitoring), **July 2025 (participation shock)**, 1 Sep 2025 (NSE expiry to Tuesday, BSE to Thursday).

*Dates from broker and exchange summaries; **verify against the SEBI circulars before entry**, per FR-DATA-16's own requirement.*

- **REG-FR-12** *(Must, Phase 1, test)* — Epoch data is owned by the **FR-DATA-16 epoch registry** — verified registry data, **not a hard-coded calendar** *(v0.1 contradicted its own parents here)*. This spec adds only the behaviour: **refuse training windows spanning an epoch boundary** for any expiry-day or short-gamma hypothesis, or for the regime detector, without recorded justification.

The Sep 2025 migration is a **day-of-week identity change** — any day-of-week or DTE feature estimated before it is actively misleading after it.

---

## 8. The gate ladder

### 8.1 Stages

| Gate | Entry requires | Checks | Failure |
|---|---|---|---|
| **G0 Registration** | Complete schema (HYP-FR-01) | Prior-art similarity; identification inputs available (HYP-FR-07); thresholds locked per FR-VAL-09 | Reject |
| **G1 Feasibility** | G0 | Features exist at required granularity and history; liquidity floor met; **prefix-property compliance of any detector to be used (REG-FR-05)** | `blocked_on_data` |
| **G2 Triage** | G1 | Tier-1 evaluation across variants; every variant ledgered | Shortlist or abandon |
| **G3 Validation** | G2 shortlist | Tier-2 per FR-VAL-05; DSR, PBO, family corrections, FR-VAL-11 minimum length; **simulated null (§8.4)**; cost-breakeven; tail metrics; **naive-benchmark increment (§8.5)** | Reject |
| **G4 Regime qualification** | G3, only if regime-conditional | Minimum episodes; label-corruption sensitivity | **Demote to unconditional — see §8.3** |
| **G5 Forward test** | G3/G4 | Pre-registered duration and criteria (FR-FWD-03); paper-vs-backtest divergence | Reject |
| **G6 Promotion** | G5 | **Book-relative checks — see §8.6** | Reject or resize |
| **G7 Live** | G6 | Kill criteria registered (FR-MON-09) | — |

*(v0.1 placed the prefix-property check at G4, two gates after the regime series had already been consumed. Corrected to G1.)*

### 8.2 Two structural properties

**Thresholds are read, never supplied** (FR-VAL-09) — with the G6 exception named in §8.6. **The evaluator is not the computer**: workers compute and publish; the Lifecycle Controller judges (HLD AD-22).

### 8.3 G4 is a demotion gate, not a qualification gate

Compose this document's own numbers: ~2–3 episodes per five years at deployable persistence (§7.2), against REG-FR-03's five-episode floor. **No regime-conditional hypothesis reaches five episodes for roughly a decade of live history.**

v0.1 specified G4 as if passable. The honest statement:

> **Regime-conditional claims are not testable on available Indian history at deployable persistence. G4's function is therefore to demote hypotheses to unconditional form — which will be its outcome in essentially every case for years.**

- **GATE-FR-15** *(Must, Phase 2, inspection)* — G4 shall default to demotion. Passing it requires the episode floor **and** the §8.7 corruption test, and the platform shall display the projected date at which the episode floor could first be met, so the operator sees the wait rather than discovering it.

This makes most of §7's machinery **explicitly contingent**, which §12 now marks.

### 8.4 Significance for option returns

Option returns are non-linear and severely non-normal. The canonical caution — that large out-of-the-money put returns are not even inconsistent with Black-Scholes, and that stochastic-volatility models with **no** risk premia generate put returns not inconsistent with observed data — means significance must be assessed against **simulated model-generated returns**, not t-statistics. *(Stated for long put returns; the write-side rendering is symmetric. Paraphrase, not quotation.)*

- **GATE-FR-13** *(Must, Phase 2, test)* — For any hypothesis whose P&L expression is a non-linear option payoff, G3 shall assess significance against a simulated null. **Scope, so this is a build and not a research programme:** a **single named model family** (Heston, or Bates where jumps matter for H25), a **fixed, versioned parameter set** calibrated once per epoch to index data, **index underlyings only**, and a **fixed path count**. Single-stock and multi-asset nulls are out of scope. Compute cost is budgeted against the research slice's Tier-2 window alongside corruption curves and regime retrains.
- **GATE-FR-14** *(Must, Phase 1, test)* — The deflated Sharpe ratio is the headline metric, not raw Sharpe. For short-gamma strategies its skew/kurtosis haircut will be substantially larger than for an equity strategy at the same raw Sharpe — that is the correction working.

### 8.5 The naive-benchmark hurdle *(new in v0.2)*

Without this, the platform will validate signals whose entire edge is the unconditioned premium they sit on. DSR against zero is a far weaker hurdle than DSR of the **increment over the dumb version of the same trade**.

- **GATE-FR-16** *(Must, Phase 1, test)* — A fixed, pre-registered, versioned set of naive benchmarks shall exist — minimally a systematic fixed-delta short strangle for VRP-flavoured hypotheses and a systematic short straddle for event hypotheses — run under the same cost model and the same data.
- **GATE-FR-17** *(Must, Phase 1, test)* — G3 shall evaluate the candidate's **increment over its declared benchmark**, net of costs, against a threshold locked at G0. A candidate that does not beat its naive benchmark does not pass, regardless of standalone metrics.

### 8.6 G6's structural exception to threshold locking *(new in v0.2)*

G6's checks — incremental correlation contribution, concentration headroom, capacity — are **inherently book-relative**: they depend on what is live at promotion time and therefore **cannot** be pre-registered per hypothesis at G0. v0.1 asserted "read, never supplied" covered every gate. It does not cover G6, and G6 is precisely where the HLD threat model's named adversary — the operator's future self — has room.

- **GATE-FR-18** *(Must, Phase 2, test)* — G6 rules shall be **globally locked and versioned** rather than per-hypothesis: one rule set, applied to every promotion, changed only by opening a versioned amendment that is ledgered and takes effect prospectively.
- **GATE-FR-19** *(Must, Phase 2, inspection)* — Every G6 evaluation shall record the rule-set version, the live book it was evaluated against, and the computed values — so a promotion can be re-checked against the rules in force at the time.

### 8.7 Misclassification sensitivity, with a defined threshold

v0.1 said the design is not viable if performance "collapses" at 10% corrupted labels — **undefined**, and therefore exactly the post-hoc discretion this platform exists to remove.

- **GATE-FR-05** *(Must, Phase 2, test)* — Before any regime-conditional allocation deploys, produce a label-corruption sensitivity curve. **Defined criterion:** if randomly corrupting **10%** of regime labels reduces the strategy's **deflated Sharpe by more than 25% relative to the uncorrupted case**, or drives it below the hypothesis's locked DSR minimum, the design is not viable and shall not deploy. Both numbers are locked at G0 with the other thresholds.

---

## 9. Regime gating and the allocator

### 9.1 What regime switching is for

Maximum drawdown improving from −55% to −27% while annual return moves 10.2%→11.2% is a **drawdown-control technology**. And the documented edge is **de-risking toward flat, not rotating between strategies**.

- **GATE-FR-01** *(Must, Phase 2, inspection)* — The regime layer's primary action is exposure reduction toward flat. Strategy rotation requires its own evidence and its own gate.
- **GATE-FR-02** *(Must, Phase 2, test)* — Regime-conditional claims are evaluated on drawdown and tail metrics, not return.

### 9.2 Continuous weight

- **GATE-FR-03** *(Must, Phase 2, test)* — Emit **filtered probability as a continuous weight**, not an argmax label.
- **GATE-FR-04** *(Must, Phase 2, test)* — Halving a short-option position does not halve gap risk. Gross short-gamma exposure is capped independently of the regime weight, **enforced in xman per §3**.

### 9.3 The multiplier is not uniform *(corrected in v0.2)*

v0.1 applied the regime weight "uniformly as an exposure multiplier" across all live signals. That de-risks defensive positions exactly when they should be held or increased: a rising bear probability would scale *down* a long-vol or tail-hedge signal. Uniformity is coherent only while the book is 100% short-premium.

- **ALLOC-FR-06** *(Must, Phase 2, test)* — The regime exposure multiplier shall apply **by exposure class, not uniformly**: it scales **short-volatility / short-gamma** exposure toward flat, leaves **long-volatility and declared hedge** exposure unscaled, and never scales any exposure *up*. Each signal declares its exposure class at registration.

### 9.4 v1 allocator: deliberately dumb, but specified

An allocator sits downstream of every anti-overfitting control, where nothing is watching it. The evidence for sophistication is weak — the disagreement in the volatility-managed-portfolio literature is not about whether volatility is forecastable but about whether **the conditioning-to-weight mapping is stable enough to estimate in real time**.

Dumb, however, is not the same as vague. v0.1 said "equal weight" without a unit; for an options book the unit is the whole question.

| Element | v1 rule |
|---|---|
| **Budget** | A stated **margin budget** — the capital the book may consume, margin being the binding constraint of an Indian short-option book (FR-CAP-01) |
| **Weighting unit** | **Equal risk contribution**, measured as each signal's contribution to portfolio expected shortfall at a stated confidence — *not* equal notional or equal premium, which would give an 0DTE short-gamma signal and a quarterly VRP harvest wildly unequal risk |
| **Regime scaling** | Per ALLOC-FR-06, by exposure class |
| **Concentration** | Per **FR-CAP-03** — per underlying, expiry, direction, moneyness bucket |
| **Capacity** | Per **FR-CAP-04** participation caps |
| **Conflict** | Veto, with the definitions and exemptions of §9.5 |
| **Rebalancing** | Banded — §9.6 |

- **ALLOC-FR-01** *(Must, Pending-FRD, Phase 2, test)* — v1 shall allocate by equal risk contribution within a stated margin budget. **If REG-FR-01 concludes the regime layer is not built, the continuous conditioning variable substitutes for the regime multiplier in ALLOC-FR-06's role**, and no other part of this section changes. *(v0.1 left this precondition dangling.)*
- **ALLOC-FR-04** *(Must, Pending-FRD, Phase 3, test)* — Any allocator more sophisticated than v1 shall be estimated on a trailing window, applied forward, and reported only on that basis — never fitted on the full sample and reported in-sample.

### 9.5 Conflict resolution — corrected so it does not forbid hedging

v0.1's veto suppressed both signals when directions opposed. **"Direction" was undefined for multi-leg option structures**, and under any vega reading a long-put tail hedge permanently opposes the core short-volatility book — so the rule would have cancelled the hedge *and* the position it hedges, then flagged the deliberate pair as mis-specified.

- **ALLOC-FR-02** *(Must, Pending-FRD, Phase 2, test)* — Conflict shall be evaluated **per exposure axis** — delta, vega, gamma — not on a single undefined "direction". Two signals conflict only where they oppose on the **same axis**, over the **same underlying**, in an **overlapping window**, and are **not in a declared relationship**.
- **ALLOC-FR-07** *(Must, Pending-FRD, Phase 2, test)* — Signals may declare a **relationship** — `hedge`, `overlay`, `pair` — at registration. Declared relationships are **exempt from the veto**, and the declaration is part of the locked record so it cannot be added after a conflict surfaces.
- **ALLOC-FR-08** *(Should, Pending-FRD, Phase 3, analysis)* — G6 shall model **suppression interactions**: promoting a signal that would frequently veto an incumbent on shared underlyings is a cost to the book, and the incremental-contribution check shall account for it. Otherwise a new signal can silently silence a better incumbent.
- **ALLOC-FR-05** *(Should, Phase 3, inspection)* — Review the conflict log periodically; a persistently conflicting undeclared pair indicates at least one hypothesis is mis-specified.

### 9.6 Rebalancing *(new in v0.2)*

A continuous weight with no rebalancing policy either bleeds cost or gets silently discretised by whoever implements it — reintroducing the whipsaw continuous weighting was chosen to avoid. Every options re-weight is a close-and-reopen at spread.

- **ALLOC-FR-09** *(Must, Pending-FRD, Phase 2, test)* — Rebalancing shall be **band-triggered, not continuous**: the book re-sizes only when the target weight departs from the live weight by more than a configured band, with a minimum dwell between rebalances. Band and dwell are versioned configuration.
- **ALLOC-FR-10** *(Must, Pending-FRD, Phase 2, test)* — The cost of a rebalance shall be modelled as **unwind at prevailing spreads plus reopen at prevailing spreads**, never as a notional delta, and the backtest shall survive a 3× cost stress on that basis.

---

## 10. Decay, retirement and re-entry

### 10.1 Monitor the mechanism, not only the P&L

A premium can erode because its *source* is competed or legislated away, and that erosion is visible in the premium series long before it appears in a signal's drawdown.

- **DEC-FR-01** *(Must, Phase 2, test)* — Maintain the measured variance risk premium as a first-class series **by epoch and regime**, alerting on structural decline independently of any signal's performance.
- **DEC-FR-02** *(Should, Phase 3, analysis)* — Re-measure the premium either side of each epoch boundary. **Stated honestly:** 20 Nov 2024 is a confounded bundle of three simultaneous changes and cannot identify any of them individually; all boundaries are confounded with market conditions; and any pre-2024 measurement depends on vendor backfill that may not be obtainable (§1.1).
- **DEC-FR-05** *(Must, Phase 2, test)* — **A new epoch shall trigger a review of every live signal whose training or validation window predates it**, with the outcome recorded. *(v0.1 re-measured the premium at epoch boundaries but never revisited the live book — an omission of its own conclusion.)*

### 10.2 Decay priors

Published predictors decay after publication — 26% lower out-of-sample and 58% lower post-publication across 97 predictors. That is an **equity cross-section result**; applying it to options is an extrapolation and is labelled as one.

- **DEC-FR-06** *(Must, Phase 1, inspection)* — The decay haircut for a hypothesis is part of its **locked threshold set** (§4.1), not free-standing configuration. Revising it after results exist follows FR-VAL-09's new-hypothesis rule. *(v0.1 called it "a reviewable configuration", which opened a side door around the threshold lock.)*

### 10.3 Retirement is not deletion

Retirement post-mortems are owned by **FR-FB-04**.

- **DEC-FR-04** *(Should, Phase 3, inspection)* — A retired hypothesis may be re-proposed, but re-entry opens a new record linked to the retired one, with the original's trial history attached.

---

## 11. Open questions and build order

### 11.1 Build order

1. **The epoch registry** (FR-DATA-16) — it invalidates work silently and is cheap.
2. **HAR-RV** (H20) — the denominator of nearly everything.
3. **The measured Indian VRP by epoch and regime** — the anchor hypothesis and the live test of whether the short-volatility complex still pays.

**On the IV surface.** v0.1 declared it core infrastructure on the critical path, which **contradicts both parents** — FR-DATA-06 is a *Should* and the HLD states it never blocks the Minimal Credible Core. This spec does not overrule them. It records the conflict: five of nine hypothesis families are undefined without a fitted surface, so **either the surface rises in priority or those families are out of scope for Phase 1**. That is an owner decision and a requested FRD/HLD amendment, not something this document resolves unilaterally.

### 11.2 The most valuable unverified number

**The Indian VRP magnitude on post-2020 data.** Sankar et al. establish that variance risk *is* priced in India; the size, Sharpe and time path were not verifiable. Given US option alphas went to zero over fifteen years, this is the single most important unknown here.

### 11.3 Owner decisions required

- **Vendor backfill of pre-November-2024 chain history.** H23, DEC-FR-02 and every cross-epoch comparison depend on it. The HLD already lists this as its highest-value unresolved item; this spec adds that the hypothesis engine's anchor research question is downstream of it.
- **Intraday multi-expiry chain data** — now a narrower question than in v0.2, since H15a and H19 are out of scope (§5.7). What remains is **H11's per-strike intraday open interest**, needed for a *conditioner* rather than a trade, plus H14's expiry-day work. Judge the spend against that, not against the withdrawn intraday strategies.
- **Whether single-stock hypotheses (H5, H17, H18) are in scope**, given liquidity concentration. Honest expectation: non-replication for data reasons.
- **The IV surface priority conflict** (§11.1).
- **Whether to run REG-FR-01 before or alongside the first signal.**

### 11.4 Evidence gaps the platform must fill itself

No Indian dealer-gamma study. No Indian net-buying-pressure study. No credible modern Indian pinning study. No Indian dispersion measurement. No systematic treatment of the Indian index-level event set — despite the Union Budget being among the largest scheduled volatility events in any equity market. No Indian 0DTE literature, in arguably the world's largest short-dated options market.

**Nearly the entire catalogue is US or European evidence whose transfer to India is an explicit assumption.** The only genuinely India-based evidence verified is Sankar et al. (2020), the SEBI regulatory record, and a 2025 study of the expiry-day change.

---

## 12. Requirements index

Phase per FRD §1.4's convention — **Must means Phase 1 is not credible without it**, not "important in general". *Contingent* marks requirements specifying the regime layer, which REG-FR-01 may conclude should not be built.

| ID | Area | Priority | Phase | Verification |
|---|---|---|---|---|
| ENF-FR-01…03 | Enforcement boundary | Must / Must / Should | 2 | demonstration, test, inspection |
| HYP-FR-01, 04, 05, 07 | Hypothesis record | Must | 1 | test, test, test, inspection |
| HYP-FR-06 | Hypothesis record | Should | 2 | demonstration |
| EXP-FR-01, 02, 06 | Exploration | Must | 1 | test |
| EXP-FR-04 | Exploration | Should | 2 | demonstration |
| REG-FR-01, 01a | Gating experiment | Must | 1 | test, inspection |
| REG-FR-05 | Prefix property | Must | 1 | test |
| REG-FR-12 | Epoch training refusal | Must | 1 | test |
| REG-FR-02, 03, 04, 06, 13 | Regime | Must — **contingent** | 2 | test / demonstration |
| REG-FR-07, 09, 10, 11 | Regime | Should — **contingent** | 2–3 | demonstration, inspection, test |
| REG-FR-08 | Limits beneath regime | Must | 2 | test |
| GATE-FR-14, 16, 17 | Gate ladder | Must | 1 | test |
| GATE-FR-13, 15, 18, 19 | Gate ladder | Must | 2 | test, inspection |
| GATE-FR-01…05 | Regime gating | Must — **contingent** | 2 | inspection, test |
| ALLOC-FR-01, 02, 06, 07, 09, 10 | Allocator | Must — **Pending-FRD** | 2 | test |
| ALLOC-FR-04, 05, 08 | Allocator | Should — **Pending-FRD** | 3 | test, inspection, analysis |
| DEC-FR-01, 05, 06 | Decay | Must | 1–2 | test, inspection |
| DEC-FR-02, 04 | Decay | Should | 3 | analysis, inspection |
| SCOPE-FR-01, 02 | Frequency scoping | Must | 1–2 | test |
| SCOPE-FR-03 | Frequency scoping | Should | 2 | inspection |

**Totals:** 43 requirements (down from 46 — eight withdrawn to FRD ownership per §2.4, plus additions). **Referenced but not owned here:** FR-VAL-03, FR-VAL-05, FR-VAL-09, FR-VAL-11, FR-FB-04, FR-AI-06, FR-CAP-01, FR-CAP-03, FR-CAP-04, FR-DATA-06, FR-DATA-16, FR-DEP-01, FR-EXE-01, FR-EXE-03, FR-FWD-03, FR-MON-09, FR-RES-03, FR-SIG-02, FR-SIG-04, FR-SIG-06.

---

## 13. Bibliography

**Verified against primary sources** (this revision's review confirmed each): Dew-Becker & Giglio (2025) *The Decline of the Variance Risk Premium*, Chicago Fed WP 2025-17 — **working paper, not peer-reviewed** · Novy-Marx, NBER w21329 · Sankar, Ramachandran & Lukose P J (2020), IREF 70 · *Downside Risk Reduction Using Regime-Switching Signals: A Statistical Jump Model Approach*, arXiv:2402.05272 · Ang & Bekaert, NBER w10080 · SEBI FY25 F&O loss study · SEBI index-derivatives circular, October 2024.

**Peer-reviewed, cited from secondary sources — verify magnitudes before relying on them:** Bakshi & Kapadia (2003) · Carr & Wu (2009) · Bollen & Whaley (2004) · Broadie, Chernov & Johannes (2009) · Ni, Pearson & Poteshman (2005) · Baltussen et al. (2021) · Driessen, Maenhout & Vilkov (2009) · Goyal & Saretto (2009) · Zhan, Han, Cao & Tong (2022) · Cao & Han (2013) · Aït-Sahalia, Karaman & Mancini (2020) · Xing, Zhang & Zhao (2010) · Corsi (2009) · Bollerslev, Tauchen & Zhou (2009) · Dacco & Satchell (1999) · Cederburg, O'Doherty, Wang & Yan (2020) · Harvey & Liu · Bailey & López de Prado · McLean & Pontiff (2016) · Adams & MacKay (2007) · Moreira & Muir · Ang & Timmermann · Neuhierl, Tang, Varneskov & Zhou.

**Practitioner tier — used and labelled as such:** the filtering-versus-smoothing Sharpe ladder, latency distribution and threshold/false-positive table in §7.3–7.4, from a published open-source replication and its accompanying write-up. **Magnitudes unverified**; REG-FR-07 derives from them and is marked a heuristic.

**Regulatory record:** SEBI measures of October 2024, the expiry-day standardisation circular of 26 May 2025, and the July 2025 interim order, as rendered by exchange and broker summaries. **Circular texts must be verified before epoch-registry entry** (FR-DATA-16).
