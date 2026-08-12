# Fable review — HLD v0.5 (against FRD v0.4)

**Date:** 12 August 2026
**Method:** full read of both documents; technical claims spot-checked against kernel documentation, DuckDB issue tracker and SQLite documentation; ~15 individual requirements sampled rather than trusting the §16 coverage table.

**Independently verified by the author before circulation** — every mechanically checkable claim below was confirmed by grep against the document. Five for five.

---

## Verified sound

The cgroup and IO claims in §11 are accurate: `io.weight` is inert under the `none` scheduler typical of NVMe, blk-iocost is the mechanism that must be modelled per device, page-cache pages are charged to the first-faulting cgroup, and `memory.low` is the correct working-set protection. The SQLite-over-NFS citation is correct. The §7.3 correction from ASOF join to knowledge-time version resolution is right, and AD-25's compaction handles the file-count consequence.

The v0.2–v0.3 fixes verified in this round — claim plane, two-tier validation, Redis split, backup ordering, hash-chain/monthly-store separation — are correct and internally coherent.

---

## CRITICAL

### C1 — The sealed holdout is defeated by its own evaluation path *(high)*

§9.1 denies the holdout to the Research Workspace, the Backtest Workers, the AI agents and any notebook, granting read access only to the promotion service. But **FR-VAL-14's evaluation is a backtest of researcher- or AI-authored candidate code over the holdout window.** Two consequences the design never faces:

**No compute path exists.** The Backtest Workers cannot read the holdout; the Lifecycle Controller is a FastAPI gatekeeper in the capture slice, not a backtest engine. Who executes the candidate over the holdout, in which slice, under which identity, is undesigned.

**Result-channel exfiltration.** Whatever process runs the evaluation executes code authored in the research slice while holding holdout read access. FR-BT-07 requires the **equity curve and full trade log persisted** for every run — over the holdout window, those artefacts *are* a projection of holdout data at 1-minute cadence, written back where research can read them. An AI agent, the exact adversary FR-VAL-13 names, can also deliberately encode holdout bytes into any output field.

**The mount seal is defeated through the front door of the evaluation itself.** The design needs a result-minimisation boundary — scalar verdict out, artefacts sealed with the zone — and a sandboxed evaluation identity. It has neither.

### C2 — The Lifecycle Controller's operator API is unauthenticated against research-slice processes *(high)*

§11's trust boundaries cover files and Redis; the claim plane received a worker identity. **Nothing stops a research-slice process — including an autonomous agent — calling the promotion, rollback, kill-switch and threshold-lock HTTP endpoints on localhost.** OS-user separation is void over HTTP.

FR-AI-02/03 require agents to act "through the SDK and registry, never around them". The Lifecycle Controller's API as designed *is* an around-path. And under C1, **distinguishing the operator from the operator's agents is exactly the hard problem the document never names.**

### C3 — An approved FRD Must is waived outside the baseline *(high)*

FRD v0.4 — status "Approved baseline" — requires at FR-DATA-14 "continuous daily capture of the **full live derivatives universe** … at platform day one". AD-21 phases capture to indices only. That may be the right decision, but **an HLD cannot waive a Must in an approved requirements document**, and §16 still maps FR-DATA-14 as covered with no flag. Either the FRD is amended, or §16 records the failure.

---

## MAJOR

### The holdout, beyond C1

**M1 — It cannot be QC'd or derived without breaking its own seal.** *(high)* The QC & Derivation Workers run on the worker fleet, which Diagram 7 places in `research.slice`. So either holdout-period data never receives QC, IV/Greeks or vol analytics — meaning the evaluation runs against raw data through a *different pipeline* than every in-sample result, invalidating the comparison the holdout exists to make — or research-slice workers read it and the seal is convention.

**M2 — No tamper-evidence against the primary named adversary.** *(high)* §11's threat model names "the operator's future self" as primary and scopes out root access. But under C1 the operator *has* root, and unlike ledger tampering — which the WORM anchor makes detectable — **reading the holdout leaves no trace at all.** The document calls this the platform's strongest control; it is the only control with zero tamper-evidence against its own named adversary. No read audit, no at-rest encryption with escrowed key, and no holdout row in the threat-model table.

**M3 — No capacity arithmetic for a depleting resource.** *(high)* §7.8 set the document's own standard: *"the rejected one got arithmetic and this owes the same."* The holdout gets none — segments consumed per evaluation, expected candidate flow, segment length needed for power on *positional* strategies (a three-month segment validates nothing multi-day), against a total span that is still TBC. Plausibly exhausted within the first year. **The strongest control is the only one whose budget was never computed.**

**M4 — Temporal definition absent; the seal is porous by date range.** *(medium)* Nothing states which dates the holdout spans, how prospective capture routes into it, or whether it replenishes. If it overlaps any period the platform was live, the **live-observed, monitoring and execution dataset families cover the same dates and are research-readable** — the seal holds on the market-data zones and leaks through every adjacent family. Backups and restores are unaddressed: the Backup Agent must read it (under which identity?), and a restore rehearsal to a research-readable path unseals it.

### Coverage failures §16 claims are covered

**M5 — NFR-05 is not discharged.** *(high)* "Encrypted data at rest and in transit": the design encrypts secrets and backup archives. The lake, every SQLite store **and the holdout** sit unencrypted at rest on a disk shared with another platform, and the claim plane is "thin **HTTP**". §16 maps NFR-05 to OS-user separation, a different property.

**M6 — FR-AI-03's information boundaries have no mechanism and contradict §5.** *(high)* The FRD's own words: *"Roles without information asymmetry are theatre."* The AI layer is agents sharing one SDK, one registry, one research OS user — and §5/C1 explicitly says **no auth or entitlement subsystem**. An implementer that "cannot see out-of-sample results" cannot be built when those results sit in registries its OS user reads freely. §16's "enforced information boundaries" is asserted, not architected. FR-AI-11 alone is genuinely discharged by the mount denial.

**M7 — The run manifest names a container image digest in a containerless architecture.** *(high)* Deployment is systemd slices, a uv workspace and bare processes; no container image exists to digest. Worse, **recording the numerical environment is not reconstructing it** — nothing can re-materialise a nine-month-old BLAS/dependency/thread environment, so QAS-01's "byte-identical, zero manual steps" is unachievable. The manifest makes irreproducibility *detectable*, which is a weaker promise than the one QAS-01 still makes. Either the design adopts containerised run environments — a §7-tier decision taken nowhere — or NFR-01 is weakened honestly.

### Architecture

**M8 — Campaign Register and Family Budget store but nothing enforces.** *(high)* A registry row is not a control. Nothing enforces FR-EXP-07's declared stopping rule, blocks G0 registration of a hypothesis in a quarantined family, or makes the Validation Library consult branching lineage to stamp FR-EXP-08's mandatory annotation. Same class: **no trial-count attribution model.** FR-EXP-06 and FR-REG-01b require a hypothesis's N to include trials cross-charged from shared infrastructure, which a per-hypothesis append-only row count cannot represent — yet DSR reads "trial count only from the ledger".

**M9 — The Lifecycle Controller has crossed from stated risk to unrecorded design problem.** *(high)* One FastAPI process now owns the kill switch, bulk artefact ingestion from the whole worker fleet, SSE dashboard fan-out, gate evaluation, threshold locking, the allocator and sole holdout read. **A wedged upload or dashboard client takes the kill switch down with it.** "Same trust boundary" justifies the same *identity domain*, not the same *process*. And §8.5's claim that "§17 records that as a risk" is **false** — §17 contains no such record.

**M10 — Replay Verifier lacks state inputs and duplicates Monitoring.** *(medium-high)* FR-SIG-04 itself lists warm-up and feature-cache state as divergence sources; replaying any window that doesn't start cold requires the runtime's state at window start, and the Live-Observed Recorder records bars and features, not checkpoints — so the assertion fails vacuously or spuriously. Separately, Monitoring's Parity Recomputer and the Replay Verifier are the same recompute-and-compare job at two altitudes, in different containers, with the batch one placed inside the production evaluation daemon where it contends with live evaluation.

**M11 — The compute budget no longer closes, and only the old parts were ever budgeted.** *(medium-high)* §7.8's arithmetic covers Tier-1 and Tier-2. Since then the nightly windows have absorbed the simulated-null generator ("the heaviest new compute in the platform", with parameter bootstrap, no numbers anywhere), FR-GATE-20's both-sides re-evaluation on every cost recalibration, corruption curves, feasibility checks, CI in the research slice, hourly ledger shipping and the nightly lake backup — on one disk, inside declared write windows that are themselves a live-trading safety control.

### Consistency

**M12 — The v0.5 manifest change was applied incompletely: four stale statements of the defining property.** *(high)* AD-32 replaces the identity tuple, but §3 Goal 2, §6 QAS-01, §13 QAS-01 and the §18 glossary all still state the superseded form — the glossary still *defines* the abolished five-element tuple as "the reproducibility key".

**M13 — §13 QAS-06 contradicts AD-20.** *(high)* The tactic column mandates "physical separation of the contended device (dedicated disk minimum; research on a second host preferred)" while AD-20 records the owner decision that exactly this is unavailable and the risk is accepted. The tactics table was not updated when the decision changed.

---

## MINOR / NIT

- **Header and §1 are stale:** "Status: Proposed — for owner review against FRD **v0.2**"; §1 "satisfies FRD **v0.2** in full — all **12** FR modules" against a v0.4 baseline with 20; header date 11 Aug versus the v0.5 revision row's 12 Aug. *(high)*
- **The simulated null can only reject the premium's *existence*.** *(medium)* A zero-risk-premia null is rejected by any short-vol variant once the real premium exists, so for hypothesis N>1 it adds little discrimination — that work falls to FR-GATE-17's benchmark increment. Yet it is "the heaviest new compute in the platform", at G3, for every non-linear payoff. Say what marginal question it answers, or scope it to premium-existence claims. *(A scoping refinement, not an error.)*
- **Two claim paths, two liveness detectors.** *(high)* Local workers reaped by PID, remote by lease expiry; QAS-08's <10 min reclaim is specified for one. A local worker wedged-but-alive defeats a PID check. Also all bulk artefacts upload through the single LCC process.
- **DuckDB dedup shape has documented IO-amplification pathologies** (`QUALIFY ROW_NUMBER() OVER (...)` over overlapping files, duckdb#21348) — the §17.4 spike is not optional and should pin the engine version in the manifest lockfile. *(medium)*
- **FR-EXP-04** (pre-test similarity, *all* intake paths): only the AI layer's Originality Regulariser does similarity, and only for AI-generated factors. No block serves human or literature proposals. *(medium)*
- **FR-GATE-05** (corruption sensitivity curve): compute-heavy, no owning block; §8.5 enumerates the workers' three gains and omits it. *(high)*
- **FR-AI-08**: the block blocking pre-cutoff out-of-sample labelling sits in the AI layer, but OOS labels are assigned by the Validation Library in the workers — enforcement in the wrong container. *(medium)*
- **Kill-path availability:** if the Lifecycle Controller is down, is the gateway fail-open or fail-closed? Unstated. *(medium)*
- **Ops Health Monitor does not watch disk headroom** on a shared disk where the irreplaceable capture stream is the first casualty of disk-full, while §17 leaves headroom an open question. *(medium)*
- **QAS-06's saturation test must run against live trading during market hours to mean anything** — the test is the incident it screens for, and no staged approach is described. *(medium)*
- **Nits:** §13 QAS-05b names a "Validation Service" container that does not exist; §16 cites nonexistent IDs (FR-EXP-03/05, FR-DEC-03); FR-DEP-05's "no shared mutable state other than the read-only data layer" is contradicted by the job queue and registries.

---

## Genuinely discharged (checked individually)

FR-BT-15/16 (Cost Envelope Estimator and Feasibility Checker — well placed, feasibility-as-result honoured) · FR-FWD-01 (Paper Fill Simulator sharing `ICostModel`) · FR-VAL-09 / AD-22 evaluator-computer separation · FR-BT-02 statutory schedule as reference data · FR-SIG-01 online writer in the capture slice · FR-ENF-05 fallback in the gateway · FR-DEC-05 epoch-triggered review. **Components with no driving requirement: none** — §16's gold-plating check holds.

---

## What is missing entirely

1. **The holdout evaluation execution design** — identity, slice, sandboxing, result minimisation. The highest-value absence in the document.
2. **Derivation and QC of sealed data** without research-slice workers, and the holdout's temporal definition, replenishment policy and cross-family date porosity.
3. **An environment-reconstruction mechanism** making the run manifest executable rather than archival — a §7-tier decision (containers or Nix versus a weakened NFR-01) taken by neither document.
4. **Authentication of the operator surface against research-slice processes** (C2).
5. **A trial-count attribution model** for cross-charged search.
6. **Read-audit or at-rest encryption for the holdout** against the operator's future self, and the backup/restore identity model around it.
7. Lesser: replay-state checkpointing, quarantine and campaign enforcement points, disk-headroom monitoring.

---

## Summary judgement

The v0.5 additions are the weak stratum. The sealed holdout — promoted by the FRD to "the platform's strongest control" — is, as architected, defeatable by the evaluation path itself, by the derivation pipeline, by the primary named adversary, and possibly by adjacent dataset families, while carrying no capacity arithmetic. The run manifest promises a reproducibility the deployment model cannot deliver. The v0.5 edit left four stale statements of the defining non-functional property and two false cross-references. The Lifecycle Controller has crossed from stated risk to unrecorded design problem.

None of it is unfixable. But **§9.1 is one design session short of being real: it currently seals the data against everyone except the process that must hand it to the researcher's own code.**
