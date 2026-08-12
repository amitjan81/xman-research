# Fable review — Hypothesis Engine Spec v0.1

**Reviewed:** `Hypothesis_Engine_Spec.md` v0.1 against FRD v0.2 and HLD v0.3
**Date:** 12 August 2026
**Method:** full read of the spec and both parents; **7 empirical claims verified against primary sources** (Dew-Becker & Giglio WP 2025-17 including the author copy and the model's friction description; Novy-Marx NBER w21329; Sankar/Ramachandran/Lukose IREF 2020; the jump-model paper arXiv 2402.05272 with the full PDF extracted; SEBI's FY25 loss study; the SEBI Oct-2024 circular effective dates; the Ang–Bekaert quote).

**Verdict.** The scholarship survived verification — every citation spot-checked against primary sources held, including the load-bearing one. The failures are elsewhere: the central §1.1 claim is accurately cited but its India transfer is mischaracterised; the anchor hypothesis contradicts the document's own reframing finding; the spec cites **zero** FRD requirement IDs while restating at least six; the gate ladder contains a gate its own arithmetic proves unpassable for a decade; and the allocator's three core rules are each underspecified or wrong for an options book in ways the spec's own catalogue predicts.

---

## What verification confirmed

Stated so it is not re-checked. §1.1's rendering of Dew-Becker & Giglio is accurate in every particular: option alphas indistinguishable from zero over ~15 years (break ~2010); synthetic options never showed negative alpha across 1926–2022; and the model friction is genuinely *"when retail investors are unable to sell options, the equilibrium price will be driven by the investors with the greatest demand."* Novy-Marx is quoted essentially verbatim. Sankar et al. is real and the continuous-vs-jump refinement in H1 is exactly what the paper finds. §7.1's numbers match the jump-model paper's Table 4 for the S&P 500 (−55.2%→−26.6%; 10bp one-way costs); the threefold turnover reduction matches (141% vs 44%); 9.7 unpenalised shifts/year matches Table 3. The Ang–Bekaert quote and cash-switching characterisation are correct. McLean–Pontiff 26%/58% is correct and correctly labelled an equity extrapolation. The Bonferroni arithmetic, the 20-parameter 4-state HMM count, and the √dwell CI factor are internally sound.

---

## CRITICAL

**F27 — The runtime-enforcement boundary with xman is entirely unaddressed.** *(high)*
REG-FR-08 requires hard position limits to sit *beneath* the regime layer — sitting **where**, enforced by **whom**? The FRD scope line is explicit that runtime enforcement lives in xman and this platform researches and emits. The spec introduces four runtime controls — the allocator's concentration caps, the conflict veto, the regime multiplier, and GATE-FR-04's gross short-gamma cap — and maps **none** of them onto the emission interface (FR-EXE-03 size caps) versus xman-side enforcement. For the subsystem that "decides what to trade and when," the absence of any statement of where its decisions become enforceable is the largest hole in the document.

---

## MAJOR

### Science and its transfer

**F1 — §1.1's India-transfer step mischaracterises the friction.** *(high)* The Dew-Becker & Giglio friction is a **structural constraint on option writing**. No such constraint exists in India — retail can and demonstrably does write options at scale, and SEBI's own studies discuss retail writers. What India has is (allegedly) a large *net* demand imbalance: a behavioural fact, not a binding constraint. The document's single strongest rhetorical sentence — *"more binding in India than anywhere"* — is asserted, false as literally stated, and unmarked as an assumption. Compounding it: H12 (participant-wise OI) is the only data that could measure the net imbalance, and the spec never links H12 to H23 as its identification input. The H23 prediction may still be derivable through the demand-pressure and limits-to-arbitrage channel — but that is a different argument and must be made.

**F2 — The SEBI "natural experiments" are confounded, and the data to run them may not exist.** *(med-high)* Three interventions land on the **same day** (20 Nov 2024: weekly cull + contract size + 2% ELM), as §6.6's own list shows — so "each SEBI intervention" is not a sequence of separable experiments but one confounded bundle plus two later events, all confounded with market conditions. Worse, measuring the premium either side of the boundary requires intraday chain history from *before* Nov 2024; the interventions are already in the past, prospective capture starts at platform day one, and vendor history depth is TBC. *"Measurable from data you will already hold"* is unsupported, and H23 silently depends on a vendor-backfill decision the HLD lists as its highest-value unresolved item.

**F3 — §6.3/§6.4's load-bearing tables have no provenance.** *(high)* The Sharpe ladder (0.67 / 0.78 / 0.77 / 1.74), the decomposition claim, the latency figures, and the threshold/false-positive table are presented as "measured" with no citation anywhere, including the bibliography. They are not in the jump-model paper. **Two Must requirements derive directly from them** (REG-FR-07's ~2× alert ratio; the composition argument behind GATE-FR-05). A document this scrupulous about provenance elsewhere cannot carry its most-quoted table unattributed.

**F5 — H1's stated mechanism contradicts §1.1.** *(high)* H1's mechanism field reads *"the buyer purchases insurance against a state that coincides with wealth destruction, so it prices above actuarial value"* — precisely the deep preference-based risk premium that §1.1's central finding says is **not** the source. Under the spec's own rule that mechanism is "the field that distinguishes an edge from a pattern," H1 should carry the intermediation-rent/demand-imbalance mechanism with the preference channel as the *rejected* alternative. Otherwise H23 is not a refinement of H1, it is a refutation of it, and the registry begins life with its Grade-A entry mis-mechanised.

**F8 — Three canonical hypotheses are missing.** *(medium)* The **jump/tail risk premium as distinct from the diffusive VRP** — the natural companion to H1's own continuous/jump separation, and the one most relevant to a crash-exposed short book. **Overnight vs intraday variance decomposition** — well documented, directly relevant to Indian expiry structure, cheap from data the platform will hold. **Underlying trend as a short-vol conditioner** — the most common practitioner overlay and the obvious continuous-conditioning rival to the entire §6 regime layer; conspicuous by absence given §6.1 predicts continuous conditioning wins.

**F9 — The epoch definition excludes the most important recent structural event.** *(med-high)* §2 defines an epoch as "knowable in advance from a circular," and §6.6 stops at 1 Sep 2025. The **SEBI Jane Street interim order (July 2025)** removed or restricted the dominant expiry-day participant — a structural break in expiry-day microstructure at least as consequential for H14/H15/H9 as the margin changes, *not* knowable in advance and not a rule change. The epoch concept must admit **enforcement and participation shocks** or the calendar will systematically miss the breaks that matter for exactly the family the spec says has no literature. Separately, §6.6 **omits the October 2024 STT change that FRD FR-DATA-16 explicitly names** as an epoch example.

### Consistency with the parents

**F11 — The spec cites zero FRD requirement IDs.** *(high)* A document naming FRD v0.2 as its requirements baseline references no `FR-*` anywhere, while restating at least: HYP-FR-02/GATE-FR-10 ≈ FR-VAL-09 · HYP-FR-03 ≈ FR-VAL-03 · GATE-FR-12 ≈ FR-VAL-11 · GATE-FR-11 ≈ FR-VAL-05 · DEC-FR-03 ≈ FR-FB-04 · EXP-FR-03 ≈ FR-AI-06 · ALLOC-FR-03 ≈ FR-CAP-03 + FR-SIG-06 · REG-FR-12 ≈ FR-DATA-16. The HLD's own rule is *reference by ID, do not restate — the FRD owns the text*. Every restatement is a drift surface with no cross-reference to detect drift. The 46 new IDs also invert the FRD's naming convention. And per FRD §1.2.1, new scope requires a new FRD revision: the allocator's runtime behaviour is new runtime scope with no FRD revision and no module assignment.

**F12 — Three lifecycle vocabularies, no mapping.** *(high)* The spec's `status` enum, FR-DEP-01's state machine, FR-RES-03's status set, and the G0–G7 ladder are four structures with nothing mapping them — and the HLD's Lifecycle State Machine must implement exactly one. Equally unmapped: **which HLD container owns the regime detector, the allocator, and the veto logic?** None of the HLD's 13 containers is any of these. The allocator gates live emission, so it belongs on the production plane, a placement with trust-boundary consequences the spec never engages.

**F13 — §6.1's gating experiment tests a strawman.** *(high)* REG-FR-01 compares a smooth function of the continuous variable against **the discrete regime label derived from it**. But GATE-FR-03 mandates the layer never emit a discrete label — it emits **filtered probability as a continuous weight**, which is a *different* smooth function of history embedding persistence and multi-feature inference, not a discretisation. If the label adds nothing over smooth-VRP, that says nothing about whether filtered-probability weighting adds anything. The right regression is **smooth(VRP) vs the filtered-probability weight**. The single gating experiment the document calls position #1 is aimed at the wrong target.

**F15 — The IV surface is promoted to the critical path against both parents.** *(high)* §11.1 calls it core infrastructure without which five of nine families are undefined; FRD FR-DATA-06 is a **Should** and HLD §17 says it "never blocks the MCC." One of the three documents is wrong about priority, and the spec neither flags the conflict nor requests the change it implies.

**F16 — "Hard-coded epoch calendar" contradicts the parents' epoch *registry*.** *(high)* REG-FR-12 mandates hard-coding while FR-DATA-16 and the HLD's Epoch Registry make epochs verified registry *data*. The only new content in REG-FR-12 is the refuse-training-windows behaviour.

### Implementability

**F17 — No phasing, no MoSCoW timebox, no MCC mapping, no verification methods.** *(high)* 46 requirements, mostly Must, with nothing marking Phase 1 versus contingent. The FRD went to unusual lengths to make "Must" mean *Phase 1 is not credible without it*; the spec discards that discipline. Twenty-one of the 46 specify a layer §6.1 expects not to build, and nothing marks them conditional.

**F18 — GATE-FR-05's acceptance criterion is unfalsifiable.** *(high)* *"If performance collapses by X = 10%"* — "collapses" is undefined: no metric, no threshold. A Must gate whose pass/fail is a judgement call at evaluation time is exactly the post-hoc discretion the platform exists to remove. The HLD makes this same point about "weak correlation" and then locks a number; the spec should copy its own parent.

**F19 — REG-FR-01's regression has no P&L to regress at the time it must run.** *(medium)* Forward strategy P&L requires strategies. Which ones? Does running it increment their trial counts? Billed as *"one regression, it is cheap"* — underspecified enough that two implementers would build two different experiments.

**F20 — GATE-FR-13's simulated null is a research programme wearing a checkbox.** *(medium)* A stochastic-volatility null for arbitrary multi-leg structures requires calibrating an SV model to Indian index dynamics and simulating internally consistent chains per path. Right idea, materially underscoped for one operator — needs a named model family, fixed parameter sets, index-only scope. Also unpriced compute: corruption curves, simulation nulls and regime retrains all land in a research slice whose Tier-2 window the HLD already calls tight.

### The gate ladder

**F21 — G4 is a gate the spec's own arithmetic says cannot be passed.** *(high)* Compose the spec's own numbers: recommended persistence gives 2–3 episodes per 5 years (§6.2); REG-FR-03 suppresses any statistic under 5 episodes; G4 requires a minimum episode count. **No regime-conditional hypothesis reaches 5 episodes for roughly a decade of live history.** The spec calls this "the hardest constraint in this document" and then specifies G4 as if passable. The honest statement is that regime-conditional *claims* are untestable on available Indian history at deployable persistence, and G4's real function is to demote to unconditional, essentially always. Say that, and much of §6's remaining machinery becomes explicitly contingent.

**F22 — The prefix-property check is placed two gates too late.** *(high)* The G4 row lists it, after G2 and G3 have already consumed the regime series. REG-FR-05 says a failing detector "shall be barred from every backtest path" — it is a property of the *detector*, not of the hypothesis's results, so it belongs at G1/G2 entry. The ladder table contradicts the requirement.

**F23 — G6's checks are the one place thresholds cannot be locked at G0, and the spec pretends otherwise.** *(high)* §3.1's locked threshold set contains no correlation-contribution, concentration or capacity threshold — the G6 checks. Those are inherently book-relative and cannot be pre-registered per hypothesis. Fine — but then "read, never supplied" does not cover G6, and G6 is precisely where the HLD threat model's named adversary (the operator's future self) will exercise discretion. The exception must be named and given its own discipline: G6 rules locked globally, versioned, changes ledgered.

### The allocator

**F24 — "Equal weight" has no unit, and for options the unit is the whole question.** *(high)* Equal *what* — notional, premium, margin, expected shortfall? An 0DTE short-gamma signal and a quarterly VRP harvest at equal notional produce wildly unequal risk contributions, and the spec's own tail-awareness requirements argue for risk-based units. Missing entirely: the allocation **budget**. FR-CAP-01 makes return on margin capital the primary metric because margin is the binding constraint of an Indian short-option book — the v1 allocator never mentions margin. Equal weight without a margin budget is not executable.

**F25 — Veto-on-conflict structurally forbids hedges.** *(high)* "Direction" is undefined for multi-leg structures — delta? vega? both? Under any vega reading, a long-put tail hedge or a long-vol event signal permanently opposes the core short-vol book on the same underlying and window, so ALLOC-FR-02 suppresses **both** — cancelling the hedge and the position it hedges — and ALLOC-FR-05 then flags the deliberate pair as "mis-specified." Needs a per-axis direction definition and a declared-relationship exemption for hedge/overlay roles. Secondary perverse incentive: promoting a new signal can silence an incumbent via suppression windows, and G6's incremental-contribution check does not model suppression interactions.

**F26 — The uniform regime multiplier de-risks the hedges too.** *(high)* GATE-FR-01's evidence base is about long-equity/short-premium exposure. Applied uniformly, a rising bear probability scales *down* any long-vol or defensive signal exactly when it should scale up. Uniformity is coherent only while the book is 100% short-premium — which the catalogue makes likely but the spec nowhere requires.

### Omissions

**F28 — No rebalancing policy anywhere.** *(high)* GATE-FR-03 emits a continuous weight; nothing states when the book re-sizes as it drifts. For options every re-weight is a close-and-reopen at spread. Without a banding rule at the *allocator* level, this either bleeds costs or is silently discretised by the implementer, reintroducing the whipsaw continuous weighting was chosen to avoid.

**F29 — No naive-benchmark hurdle.** *(medium)* The `benchmark` role exists and is used once. The canonical discipline — every promoted signal must beat the *dumb* version of itself (fixed-delta systematic short strangle for VRP-flavoured work, straight short straddle for event trades) net of costs — appears nowhere in the ladder. DSR against zero is a much weaker hurdle than DSR of the increment over the naive harvest; without it the platform will validate signals whose entire edge is the unconditioned premium.

---

## MINOR / NIT

- **F4** — "0.5 shifts/year" is misattributed. The tuned model that produced the cost-aware results ran ~30 shifts over 1990–2023 (~0.9/yr); 0.5/yr is the most-penalised column of the frequency sweep. The episode-arithmetic conclusion survives; the attribution is wrong. *(med-high)*
- **F6a** — §4.5 conflates the SEBI study's top-13-broker sample (~96 lakh) with the loss population (1.05 crore FY25 traders). The ₹1.06 lakh crore and 91% figures are correct. *(high)*
- **F6b** — Novy-Marx is invoked for a 5×3×3 grid, but the n^k result concerns *combining* signals into one strategy; a grid product is plain multiple-testing counting. Decorative citation. *(medium)*
- **F6c** — NSE final settlement is the last-30-minute *time*-average of the index, not a VWAP. *(medium)*
- **F6d** — §8.4 paraphrases Broadie-Chernov-Johannes as if verbatim; they state it for long put returns, the write-side rendering is symmetric but should not use quotation marks. *(medium)*
- **F6e** — §1.1 rests the document's entire posture on a 2025 **working paper**. Direction is corroborated by the authors' earlier work, but "the single most consequential result" deserves the caveat that it has not passed peer review. *(medium)*
- **F7** — §4.3's conditioner count includes H20 and H22, which §4.2 labels `risk_input`; §3.1 defines these as distinct roles with different promotion consequences. *(high)*
- **F10** — "~182 optionable NSE names" is likely stale; the F&O list expanded in 2024–25. *(low)*
- **F14** — ALLOC-FR-01 (Must) depends on a layer REG-FR-01 may forbid building, with no stated fallback for the outcome the spec itself calls likeliest. *(high)*
- **F30** — The decay haircut is "a reviewable configuration, not a constant" while gate evaluation applies it. If it sits outside the locked threshold set, revising it after results changes effective hurdles without opening a new hypothesis — a side door through HYP-FR-02. *(medium)*
- **F31** — DEC-FR-02 re-measures the premium at epoch boundaries, but nothing requires an epoch event to trigger re-validation or demotion review of *live* signals whose evidence predates it. An omission of the document's own conclusion. *(medium)*
- **F32** — The regime detector's own training hygiene is unaddressed: no retrain cadence or window, and detector hyperparameter tuning (sweeping a persistence penalty is search, as §5.2 itself argues) is unledgered. *(medium)*

---

## What is fine

The mechanism discipline is mostly genuine — H4, H11 and H17 name who is on the other side. Evidence grades are internally consistent with their definitions. §4.5's two inference errors are the best content in the document. §8.2's evaluator/computer separation correctly matches HLD AD-22. The dumb-allocator *position* is defensible and honestly argued, and veto-not-net is reasonable as a default once F25's definition hole is fixed. The gate order G0→G3→G5→G6→G7 is sensible and consistent with the HLD's tiering.
