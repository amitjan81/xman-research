# Fable review — FRD v0.4 (against HLD v0.5)

**Date:** 12 August 2026 · ~40 findings, 3 critical
**Verification status:** every mechanically checkable claim independently confirmed by the author before circulation — **6 for 6**. All six web-fact-checked empirical claims confirmed against primary sources.

---

## The headline

**The sealed holdout was promoted to "the platform's strongest control" and is the least-specified thing in the document.** It is unspecified at every point that matters: construction, consumption semantics, gate wiring, and — fatally — the operator adversary its own threat model names.

---

## CRITICAL

**H-1 — The holdout does not defend against the platform's own named primary adversary.** *(high)* The HLD threat model names "the operator's future self" as primary and answers it for ledgers with hash-chaining plus an offsite write-once anchor. The holdout gets no analogue: the operator owns the machine, the capture user and root, and **a peek leaves no trace** — no tamper-evident read audit, no offsite-anchored access log, no encryption under an externally held key. FR-VAL-12's claim that the holdout "depends on no accounting at all" is inverted: it depends entirely on the unaudited restraint of the one person the threat model says not to trust. **The document's own standard — "a rule they are asked to respect is not a control" — condemns its own strongest control as specified.**

**H-2 — "Evaluated once per candidate" is defeatable by candidate multiplication.** *(high)* FR-VAL-14 never defines *candidate*. Submit ten near-identical siblings, receive ten holdout verdicts, condition the eleventh on them — which is exactly the adaptive selection FR-EXP-08 describes, now running **on the holdout**. There is no aggregate multiplicity correction across looks, no family-level cap on submissions, and no requirement that verdicts be withheld from the processes generating the next candidate (FR-AI-03's information boundaries never mention holdout verdicts). "Consumes a fresh segment" covers only *re*-evaluation of the same candidate; a new sibling is evaluated against — the same segment (free looks) or a fresh one (trivially exhausted by machine generation, with no burn-rate budget anywhere). Both readings are bad.

**H-3 — The holdout never appears in the gate ladder.** *(high)* §19's G0–G7 table enumerates every check at every stage. FR-VAL-12/14 appear at **none of them** (G6 checks only FR-GATE-18/19). Under the ladder's own convention, **the operative promotion procedure never runs the platform's self-described strongest control.** Nothing states which gate consumes a segment, or that a candidate cannot reach G7 without a verdict.

---

## MAJOR — the holdout, continued

**H-4 — Construction entirely unspecified.** *(high)* Which window, how much, carved from what? A temporal holdout on ~5 years of vendor history collides with the document's own epoch logic — any recent window sits post-Nov-2024 / post-Sep-2025 while training data straddles the breaks, and FR-BT-12 bars silent pooling, yet FR-VAL-12/13/14 never mention epochs. Segment sizing is absent: FR-VAL-11's own MinBTL logic says short windows cannot support significance, but nothing requires a minimum segment length — months of data evaluating a negatively-skewed short-gamma strategy is noise. Replenishment and post-consumption disposition are unaddressed in both documents.

**H-5 — Failed-evaluation semantics undefined.** *(high)* If the evaluation crashes, or is later invalidated by a data-quality error in a zone whose QC status is itself unclear, **is the look consumed?** Neither answer is stated. "Operator decides afterwards" recreates the post-hoc discretion FR-VAL-09 exists to remove.

**H-6 — Parametric look-ahead pierces the seal.** *(high)* FR-AI-08 correctly observes that a model already knows history preceding its training cutoff. **A historical holdout window before the cutoff of any model in a candidate's lineage is therefore not unseen by that candidate — the model's weights contain the holdout period.** FR-VAL-12's claim to survive an adaptive research process fails *exactly for the machine-generated candidates it was added to police*, unless the holdout is constrained to post-cutoff data — which no requirement states. **FR-VAL-12/13/14 and FR-AI-08 never reference each other**, despite being in the same document and about the same failure.

## MAJOR — the other new controls

**C-1 — The adaptive-search annotation is cosmetic.** *(high)* FR-EXP-08 mandates that adaptive-lineage DSRs be reported "indicative, not dispositive" — but **nothing downstream changes**. G3 still gates on the locked DSR minimum; nothing says such a candidate cannot pass, must substitute another control, or must clear a stiffer preset. An annotation with no gate consequence is documentation, not a control — *the identical criticism the previous round levelled at trial counting.*

**C-2 — Campaign records miss the payload; the stopping rule is unenforced.** *(medium)* FR-EXP-07 records which candidates were conditioned on which results but not **what result content the generator actually received** — without it the lineage is a topology with no payload, and no future correction method can be applied retrospectively. Nothing requires a campaign to *stop* at its declared stopping rule, or to be closed before a member enters the ladder.

**F-1 — "Mechanism family" has no definition, no assignment authority, and no anti-relabelling control.** *(high)* `mechanism` is free text; family assignment is made by the same process being budgeted; FR-EXP-04's similarity check is "by mechanism family" — circular. **The two-hundredth variant of a dead idea escapes quarantine by declaring itself a new family.** This is the exact failure mode FR-DEC-07 was added to stop.

**F-2 — The budgets are unquantified, unlocked and unenforced.** *(high)* Four quantities named, no thresholds, no fit criterion, no locking rule — a budget the operator can raise when nearly exhausted is not a budget. And **no gate checks quarantine membership**: G0 checks schema, prior art, inputs and thresholds, not "is this family quarantined?"

## MAJOR — consolidation contradictions inside an "Approved baseline"

**I-2 — FR-ALLOC-10 mandates the arbitrary multiplier FR-BT-15 abolished.** *(high)* FR-BT-15: "a fixed 2× or 3× stress is a guess about uncertainty the model can measure directly", promotion must survive the credible-interval upper bound. FR-ALLOC-10: rebalance cost "survives a 3× cost stress". Two Musts in direct contradiction; the v0.4 fix was never propagated into §20.

**I-3 — The haircut lives in two incompatible places.** *(medium)* v0.4 moved it "from the gate to sizing" (FR-SIG-08), yet FR-VAL-09's locked **gate threshold set** still enumerates "haircuts" and FR-DEC-06 locks it as part of that set.

**I-1 — G3 is built on Should requirements.** *(high)* G3 checks family corrections (FR-VAL-10), minimum length (FR-VAL-11), cost-breakeven (FR-BT-13) and tail metrics (FR-BT-14) — **all four are Should**. Under §1.4's own MoSCoW semantics they can be dropped from Phase 1, leaving a Must-path gate unexecutable.

**I-4 — Trial-count semantics are gameable and unimplementable.** *(high)* (a) FR-VAL-03 counts variants "for the hypothesis" — splitting a search across linked records keeps each N small, and FR-VAL-09's new-hypothesis rule *institutionalises* record-splitting; nothing consolidates counts across a lineage. (b) FR-EXP-06 and FR-REG-01b create forward-propagating counts with no aggregation rule, no decay and no bound — read literally, a 50-configuration detector sweep **permanently inflates N for every future hypothesis, platform-wide, forever**.

**I-5 — The horse race decides on evidence the document rules insufficient.** *(high)* FR-GATE-15 states regime-conditional claims are not testable at deployable persistence (2–3 episodes). Yet FR-REG-01 makes the build/no-build decision on tail metrics over that same history — **which FR-REG-03's own display rule would suppress** as backed by fewer than five episodes. FR-ALLOC-12 then adopts that underpowered result as the multiplier's evidence standard.

**I-6 — "Roughly a decade" is likely two.** *(medium)* §18 gives 2–3 episodes *in total* per five years; FR-REG-03's floor is five episodes *per regime*. Composing them gives ~17–25 years, not a decade — the claim mixes total-episode arithmetic against a per-regime floor.

**I-10 — FR-BT-15 has no mechanism under C3 branch (a).** *(medium)* Its interval derives from FR-BT-03(b)'s shrinkage machinery. If quotes are available and branch (a) applies, no calibration dispersion is defined and the Must has no output. The requirement is unconditional; its mechanism is conditional.

**M-1 — The MCC's "one honest experiment" violates its own Musts.** *(high)* The MCC excludes data QC (FR-DATA-08) and the epoch registry (FR-DATA-16, FR-BT-12) — yet FR-BT-12 bars cross-epoch pooling, and any first experiment on 2023–2026 history **necessarily spans the Oct/Nov-2024 and Sep-2025 breaks**. The membership test conflates "the loop closes" with "the experiment is honest"; QC and epoch annotation are on the honesty path.

**M-2 — MCC locks thresholds without the thing that makes locking real.** *(high)* C1 says self-attestation is made honest by tamper-evidence. The MCC defers hash-chaining as retrofittable while keeping locked thresholds — so during the MCC, thresholds are "locked" in a mutable store fully controlled by the primary adversary. **Retrofitted chaining protects future rows, not rows edited before chaining began.**

**A-1 / A-3 — Cross-document:** FR-DATA-14 (Must, full universe day one) is contradicted by AD-21 and the FRD was never amended — a compliant build fails its own requirement on day one. And the holdout cannot be QC'd or derived under the HLD's placement of the derivation workers in the research slice.

## Minor / nit (selected)

Cross-reference rot from the consolidation renumbering — §1.4 cites §25 for the MCC (it is §24), C1 cites §17 for effort (now §25), Appendix A cites §16/§17/§19 at pre-consolidation numbers, sending a verifier to the wrong section of an "authoritative" document · Appendix B carries six role values outside the FR-HYP enum ("research question", "mixed", "—") · FR-ALLOC-13's review cadence is "each epoch", an irregular structural event potentially years apart, leaving the control dormant · "Tier-1"/"Tier-2" gate normatively in G2/G3 but are defined only in the HLD · FR-GATE-16 defines benchmarks for two families while FR-GATE-17 requires every candidate to beat one · FR-DEP-01's state machine and G0–G7 are unreconciled automata, and G4's "demote to unconditional" has no corresponding state · FR-SIG-09's "reproduce exactly" has no float-tolerance policy for the very precision effects FR-SIG-04 enumerates.

## Feasibility

**FE-1 — FR-GATE-13 is a research programme wearing a Must.** *(high)* A physical-measure-calibrated stochastic-vol/jump null with bootstrap propagation is a build-and-validate-a-pricing-engine project. **No requirement validates the null model itself** — a misspecified null silently rejects or accepts with the same no-error-no-diagnostic failure the requirement warns about for price calibration. No fit criterion, no fallback.

**FE-2 — Standing operational load is never totalled.** *(medium)* Daily chain verification, hourly backups, restore rehearsals, notebook self-audits, monthly review packs per signal, epoch-triggered review of every live signal, conflict-log review, multiplier accounting, two negative-control suites, capture-gap triage within an hour of close. Individually reasonable; collectively a part-time SRE job for the person also doing the research. The document bands *build* effort carefully and is silent on *run* effort.

**FE-4 — The compensating second human is an unspecified LLM.** *(medium)* FR-AI-10 is *the* substitute for the missing approver, with no fit criterion, no independence definition and no diversity requirement — under C1 the adversarial reviewer will plausibly be the same model family that proposed and implemented the candidate, with correlated blind spots.

## Missing entirely

**X-1 — No production timeliness requirement.** *(high)* NFR-03 bounds backtest speed only. Nothing bounds bar-close-to-emission latency, evaluation-cycle deadlines, or online-feature staleness at decision time — **the Signal Runtime has no performance requirement at all** — yet emissions carry validity windows.

**X-2 / X-3 — No LLM data-egress or licensing control.** *(high)* Prompts built from market data go to external APIs; vendor licences commonly prohibit redistribution, and the proprietary edge leaves the machine. FR-AI-09's masking exists for look-ahead, not confidentiality — and nothing requires the mask be tested against period re-identification. **A one-minute NIFTY price path identifies its own period**, so masking symbols and dates is likely a fig leaf.

**X-4 — The baseline is "Approved" with its most consequential inputs open.** *(high)* C3 (self-described "single most design-consequential open item"), C4 history depth and C6 budget are all TBC, and nothing forces resolution by a date or names an owner.

**X-5 — No cross-system contract validation with xman.** *(high)* FR-EXE verification is "test against a webhook stub"; nothing validates that xman *interprets* size hints, validity windows or veto-as-absence as intended. §21's enforcement table rests on semantic agreement no requirement tests.

**X-6 / X-7:** epochs don't trigger review of in-flight candidates · no dead-man or maximum-unattended-emission control for a single-operator live system.

## The science — the document's strongest axis

All six spot-checked claims **confirmed against primary sources**: McLean & Pontiff's 26%/58% across 97 predictors (exact); SEBI FY25's 91% and ₹1,05,603 crore (exact); the regulatory dates including 20 Nov 2024 as precisely a three-change bundle, STT 1 Oct 2024, calendar-spread relief 10 Feb 2025, Tue/Thu standardisation 1 Sep 2025 (all exact); Dew-Becker & Giglio's abstract matching the characterisation nearly verbatim with the working-paper label accurate; Sankar et al. on continuous-versus-jump variance (exact); Bollerslev-Tauchen-Zhou's quarterly horizon (exact). The 4-state/20-parameter count and the √dwell CI claim also check out analytically.

**Remaining uncited numbers inside Musts:** FR-GATE-02's −55%→−27% and 10.2%→11.2%, FR-REG-08's detection-latency distribution, FR-REG-07's ~2× tripwire (self-labelled heuristic). Load-bearing numbers inside Musts need sources.

## Bottom line

The statistics, market facts and regulatory record are solid — every externally checkable claim survived. The failures are structural: the self-declared strongest control is unspecified at every point that matters; the new family and campaign controls lack the definitions and enforcement points that would make them act; and the consolidation left live contradictions inside an "Approved baseline" whose three most consequential inputs remain TBC.
