# Review — Options Trading Research Platform, Functional Requirements Document

**Document under review:** `Options_Research_Platform_FRD.docx`, Version 0.1 (Draft for review), August 2026
**Scope of review:** completeness, correctness, prioritisation, and evidentiary standard
**Date of review:** 11 August 2026

**What this review was assessed against.** Three research streams: (1) the
methodology literature on backtest overfitting, cross-validation and
point-in-time data discipline; (2) published accounts of research-platform
practice at systematic funds and platform vendors; (3) requirements-engineering
practice — ISO/IEC/IEEE 29148:2018, the Volere template, EARS syntax patterns,
and ISO/IEC 25010:2023 for non-functional classification.

Where a claim below rests on a secondary source rather than primary text, it is
marked. Two standards (29148, 25010) are paywalled and were not read in full.

---

## Summary judgement

This is a strong document — better structured and better grounded than most
requirements drafts, and materially better than a first draft has any right to
be. The module decomposition is sound, the anti-overfitting philosophy is
correct and load-bearing rather than decorative, and several requirements
capture details that are normally learned the expensive way.

The findings below are **ten gaps** and **six disagreements**. None of them
invalidate the document's structure; all are additive or corrective. The single
most important is the first, because it is the root cause of several others.

### What the document gets right, and should not be disturbed

- **FR-VAL-03** — the Deflated Sharpe Ratio uses the platform-recorded trial
  count, and "the researcher cannot self-report a smaller number". This is the
  strongest requirement in the document. Every anti-overfitting statistic is
  uncomputable without a truthful trial count, and making the count
  non-negotiable is what separates a real gate from a ceremonial one.
- **FR-MON-04** — separating *technical* failure (the pipeline computes
  something different from research: a bug) from *statistical* failure (correct
  implementation, decayed edge) with distinct playbooks. Conflating these two is
  a classic and expensive error.
- **FR-BT-02** — the point-in-time cost stack with effective-date history,
  specifically including STT on the intrinsic value of exercised ITM options.
  That detail is normally discovered after it has already corrupted a backtest.
- **FR-SIG-04** — the same signal artefact running unmodified in backtest, paper
  and live modes. This is the structural cure for training/serving skew rather
  than a monitoring patch over it.
- **FR-DEP-06** — every production emission logged with the feature inputs that
  produced it, sufficient to replay the decision.
- **FR-FB-02** — realised execution data recalibrating the cost model as a new
  versioned configuration. This closes the loop that most platforms leave open.
- **FR-AI-07** being the only *Must* in the AI section is the right instinct:
  the accountability requirement is mandatory, the capabilities are not.

---

## Gaps — requirements not present

### G1. There is no Constraints and Assumptions section — *root cause, high severity*

The document states scope (§1.2) and design philosophy (§1.3) but never records
operating constraints. Missing: single operator; single machine, shared with the
live trading platform; data vendor, granularity and history depth; budget; and
most consequentially, **whether bid/ask quote data is available**.

This is not a documentation nicety. FR-BT-03 requires slippage modelled as a
fraction of "the observed **(or estimated)** bid-ask spread". That parenthetical
is carrying the entire question silently. If quote data is unavailable — which
materially changes the platform — then the cost model must be *learned from
realised fills*, and that approach has consequences the document never argues:

- **Circularity** — a strategy never traded has no fills to calibrate from, so
  its first deployment always runs on a prior.
- **Fills-only blindness** — it measures cost *conditional on filling*. Orders
  cancelled or expired unfilled are invisible, yet at thin strikes the
  opportunity cost of not filling is a first-order cost channel.
- **A contaminated reference price** — with no quotes, slippage is measured
  against last-trade or a model mid. At illiquid strikes the last trade is stale
  by minutes, so measurement error is largest exactly where cost is largest.
- **Selection and regime conditioning** — fills occur when existing strategies
  chose to trade, embedding their adverse selection, urgency and the prevailing
  volatility regime. The resulting curve is biased toward already-traded
  *behaviour*, not merely already-traded strikes.
- **Sample famine** — cost by moneyness × time-of-day × size on a single account
  yields single-digit cell counts for a long time. Without a minimum-sample floor
  and shrinkage toward the prior, "calibrated" means "fitted to noise".
- **Cold start** — the loop produces nothing until execution history accumulates,
  and that history cannot be reconstructed retrospectively.

FR-MON-08 and FR-FB-02 build this loop well. The gap is that nothing states what
the loop *cannot* do, so a reader will over-trust its output.

**Recommendation:** add §1.5 Constraints and Assumptions, each constraint stating
its consequence. Remove the "(or estimated)" hedge from FR-BT-03 and make the
position explicit, with a revisit clause if quote data later becomes available.

### G2. The exploration-to-trial boundary is undefined — *high severity*

FR-RES-01 provides an interactive notebook workspace. FR-RES-04 auto-logs "all
experiment runs" and asserts "nothing that was run can be unrecorded".

But a researcher eyeballing fifty parameter values inside a notebook cell has run
fifty trials that never touch the experiment pipeline. The recorded count is
therefore a **lower bound**, and every Deflated Sharpe Ratio computed from it is
optimistic. §4's preamble asserts that "even exploratory work leaves a trail",
but no requirement enforces this for ad-hoc interactive work.

This matters more than any other gap because it partially undermines FR-VAL-03,
the document's best requirement. A trial counter that can be bypassed by opening
a notebook produces false precision rather than protection.

**Recommendation:** take an explicit position — instrument the workspace,
require declared exploration sessions, or accept the undercount and state it —
and add a requirement in the FR-RES series.

### G3. Regulatory epochs are stored but never annotate results — *high severity*

FR-DATA-04 and FR-BT-02 correctly store reference data and cost rates with
effective dates, so a simulated date uses the rules in force. Good, and
necessary. What is missing is the consequence for *interpretation*.

Across 2024–2025 the Indian derivatives market changed structurally: NSE expiry
moved from Thursday to Tuesday effective 1 September 2025 (BSE taking Thursday);
November 2024 tripled contract sizes and reduced weekly expiries to one benchmark
index per exchange, and added an expiry-day margin on short options; STT on
option sales rose on 1 October 2024. SEBI's own studies report individual F&O
participants falling from 61.4 lakh to 42.7 lakh across FY25 — a change in the
counterparty mix, not merely in the rules.

Consequently, day-of-week features, expiry-day seasonality and any 0/1-DTE study
**break** across those dates. FR-BT-10 provides regime-sliced reporting, but
"regime" there means volatility and trend regime, not regulatory epoch.

*(Regulatory dates above are drawn from exchange and broker circular summaries;
the 1 September 2025 NSE transition was not verified against the primary NSE
circular and should be confirmed before the document relies on it.)*

**Recommendation:** a named regulatory-epoch registry, epoch annotation on every
result, and a default bar on pooling across epochs without recorded
justification.

### G4. Nothing captures the "capture now or lose it forever" property — *high severity*

FR-DATA-01 requires ingesting and persisting derivatives data. It does not state
that **expired option contracts fall out of vendor instrument masters and their
history generally cannot be re-requested afterwards**.

That makes continuous prospective capture urgent from day one and impossible to
satisfy in arrears — a materially different requirement from "ingest data", and
one whose cost of delay is permanent rather than recoverable. A platform that
begins capture in month six has permanently lost months one to five.

*(This is vendor-behaviour dependent and was established from developer-forum
sources rather than vendor documentation. It should be confirmed empirically
against the intended data provider before it drives a build decision — but the
asymmetry of consequences favours acting as though it is true.)*

**Recommendation:** an explicit prospective-capture requirement, a daily
instrument-master snapshot requirement, and a stated backfill-depth target.

### G5. LLM training-cutoff leakage is absent from §12 — *high severity*

§12 handles the AI failure modes it addresses well — unlogged search, reward
hacking against the backtest metric, evidence-bound claims, originality
regularisation. FR-AI-04 and FR-AI-06 are genuinely good.

What is entirely missing is **parametric look-ahead**: a language model trained
*after* the period being backtested already knows what happened. Published work
in 2025–26 shows backtested LLM-agent returns collapse once evaluation moves past
the model's knowledge window, and that mitigating the effect removes roughly
two-thirds of the apparent in-sample advantage. The bias is invisible — it
produces no error, no warning, and a better-looking result.

**Recommendation:** record model identity and training cutoff per run; prohibit
labelling any backtest window preceding that cutoff as "out-of-sample"; and
provide entity/date masking for prompts built from historical data.

### G6. Position sizing and capacity are missing — *high severity*

Sizing is treated as the execution platform's concern (§1.2 places risk
management out of scope). But *how much to trade* is a research question:
volatility targeting, per-signal capital allocation, portfolio maximum loss,
concentration limits. Sizing errors dominate outcomes at mid-frequency, and the
document validates signals while remaining silent on the decision that most
determines the result.

Separately, **capacity**: without quote data the cost model says nothing about
how much can be absorbed at a far strike. FR-BT-03 scales slippage by size
relative to volume, which *prices* the trade but never *caps* it. A
max-participation constraint against traded volume and open interest is the
standard substitute, and FR-DATA-12 already ingests the open-interest data
needed.

**Recommendation:** a new module — Capital, Sizing and Capacity — covering
return on margin capital as the primary return metric, sizing policy as a
researched and validated artefact, portfolio risk budget, per-strike
participation caps, and a per-signal capacity estimate.

### G7. Gate thresholds can be chosen after seeing results — *high severity*

FR-VAL-04 enforces "a configurable maximum" PBO; FR-VAL-05 versions the gate
configuration. Neither says *when* the configuration is chosen. If a threshold
can be adjusted once the result is visible, the gate is theatre and the
versioning merely records the adjustment.

FR-FWD-03 gets this exactly right for forward tests — promotion criteria
"recorded before the test starts, so the promotion decision is pre-registered
rather than post-hoc". The same discipline must apply to the statistical gates.

Relatedly, §7 presents significance thresholds as settled. There is a live and
serious dispute: one influential line of work argues a newly discovered factor
should clear a far higher bar than convention, while a substantial rebuttal
bounds the false-discovery rate and argues such hurdles are over-restrictive.
The platform should ship both stances as named presets and force the choice
before results are visible, rather than embed one silently.

### G8. No fit criteria and no verification section — *medium-high severity, structural*

Not one requirement states how you would know it had been met, and the document
has no verification section. Many requirements are testable as written; several
are not — FR-RES-02's "documented usage examples", FR-DATA-08's "outlier IV
detection", FR-MON-04's "structured triage flow", FR-RES-06's "options-specific
exploratory tooling".

Requirements-engineering practice is direct on this point: if a fit criterion
cannot be written, the requirement is either ambiguous or not yet understood.
And 29148 expects a verification method recorded *per requirement*, not merely
a testing intention.

**Recommendation:** add a verification method per requirement (inspection /
analysis / demonstration / test) and a fit criterion wherever the statement is
not self-evidently testable, shaped as *scale + meter + threshold + condition*.
Include a negative control wherever a detector could be over-aggressive — a
leakage detector that fires on everything passes a naive test.

### G9. No backup, durability or recovery requirement — *medium-high severity*

NFR-02 states that audit records are immutable. But the hypothesis registry and
the trial ledger are the platform's scientific conscience, and immutability on a
single machine is one accidental deletion away from being nothing at all. §14
contains no backup, disaster-recovery, or offsite-copy requirement of any kind.

**Recommendation:** durability and recovery NFRs, plus tamper-evidence
(append-only enforcement and hash-chaining) for the research record specifically.

### G10. Smaller but real gaps — *medium to low severity*

- **Survivorship control for the equities and stock-options scope.** FR-DATA-02
  covers corporate actions; index constituent history with effective dates and
  retention of delisted symbols are not required. A universe resolver that
  cannot answer "what was in the index on date D" reintroduces survivorship bias
  through the back door.
- **Multiple-testing correction across a search family.** DSR and PBO are
  present and correct. Absent: haircut Sharpe under Bonferroni / Holm /
  Benjamini-Hochberg-Yekutieli, and a data-snooping test across swept
  configurations. FR-VAL-06 compares two versions; it does not correct across a
  family of trials.
- **Minimum backtest length and minimum track-record length.** Given a recorded
  trial count, there is a computable minimum sample below which an apparent
  result is expected by chance. Neither is required.
- **Pre-registered kill criteria.** FR-FB-04 provides a retirement workflow;
  FR-MON-05 provides automated de-risking. Neither requires the kill threshold to
  be registered *at promotion time*, before decay makes the decision
  uncomfortable.
- **Decay prior for literature-sourced signals.** Published predictors decay
  substantially after publication — the best-known study finds returns 26% lower
  out-of-sample and 58% lower post-publication across 97 predictors. A default
  haircut on literature-derived signals, with provenance recorded on the signal,
  is cheap and well-evidenced. *(That figure is an equity cross-section result;
  applying it to an options volatility strategy is an extrapolation and should be
  labelled as one.)*
- **Data licensing and redistribution terms** for retained multi-year vendor
  history are not mentioned.

---

## Disagreements

### D1. MoSCoW has collapsed — roughly 51 requirements are marked Must

That is not a prioritisation; it is a wishlist with labels. This is the
documented structural failure mode of MoSCoW when applied without a fixed
timebox, not a drafting error — without a timebox, every requirement drifts to
Must because nothing forces a trade-off.

§15's phasing partly rescues this, but Phase 1 alone comprises roughly 35 Musts,
including bitemporal point-in-time storage, arbitrage-free surface fitting, a
feature store, an event-driven options backtester with margin modelling, and
combinatorial purged cross-validation.

**Recommendation:** keep MoSCoW but scope it to a named phase — the only
condition under which it behaves — and add a satisfaction / dissatisfaction pair
(1–5 each) per requirement. That separates "this would delight me" from "its
absence would infuriate me", a distinction one label collapses. Add a **Minimal
Credible Core**: the subset sufficient to run one honest experiment end to end,
which is smaller than Phase 1 and is the thing actually worth building first.

### D2. The effort estimates describe a team, not a person

"Phase 1 running within roughly two to three months, with the full lifecycle
taking six to nine months" is achievable for a small team. For a single
practitioner, point-in-time bitemporal storage plus arbitrage-free surface
calibration plus a margin-accurate event-driven options backtester is most of a
year on its own, before validation, forward testing, deployment or monitoring.

**Recommendation:** restate as effort bands with the assumed headcount named, or
remove them. As written they are the part of the document most likely to be
quoted back later.

### D3. FR-DATA-06 should be *Should*, and second-order Greeks *Could*

Arbitrage-free SVI/SSVI calibration per underlying per timestamp at one-minute
resolution is a substantial compute and failure-mode burden — fit failures,
arbitrage violations, thin-chain truncation at the wings — and the platform is
credible without it. Similarly, vanna/charm/volga (FR-DATA-05) are needed for
specific strategies, not for the platform to function.

There is also a cheaper and more valuable requirement hiding here: if the data
vendor already supplies implied volatility and Greeks, the platform should
**reconcile vendor-supplied against independently computed values and store the
residual as a data-quality metric**. That catches vendor error and model error
simultaneously, and costs far less than computing everything from scratch.

### D4. FR-DATA-01's tick-data extensibility clause is speculative generality

"The design must allow later extension to tick data without schema change"
constrains the design today for a capability that an explicitly mid-frequency
platform may never want. If tick data is genuinely anticipated, it belongs in
Constraints; if not, the clause should go.

### D5. FR-RES-05's isolation claim needs qualifying

"Research compute is isolated from production trading systems" is a
resource-partitioning promise, not a separate-hardware guarantee, if research and
live trading share a machine. NFR-03's interactive backtest target should state
what it assumes about contention, or it will be missed under load precisely when
it matters.

### D6. Verify the 2025–26 AI citations before they anchor §12

AlphaAgent (KDD '25) is sound and correctly characterised. RD-Agent(Q),
QuantaAlpha, XALPHA and FactorMiner could not all be confirmed in this review —
and one closely related paper in the same cluster, Chain-of-Alpha
(arXiv:2508.06312), has been **withdrawn by arXiv administrators**. A
requirements section that cites withdrawn or unverified work undercuts the
evidentiary standard the rest of the document sets for itself.

§12 should also record an **open problem** rather than implying settlement: no
published method reconciles machine-scale hypothesis search with
Deflated-Sharpe/PBO-style corrections. FR-AI-06 takes the conservative position
(log every candidate as a trial), which is right — but the document should say
that this is a position taken in the absence of established practice.

### D7. "Won't" is defined and never used

§1.4 defines a Won't category explicitly to bound scope, and no requirement
carries it. There is no list of deliberate exclusions, so future scope creep has
nothing to be measured against. Candidates: order-book and microstructure
capability, HFT-frequency signals, multi-user governance and approval workflow,
reinforcement-learning execution.

---

## Suggested new requirement IDs

Numbering continues each existing module.

| ID | Title |
|---|---|
| FR-DATA-14 | Prospective capture of expiring contracts |
| FR-DATA-15 | Daily historical instrument-master snapshots |
| FR-DATA-16 | Regulatory-epoch registry with effective dates |
| FR-DATA-17 | Index constituent history and delisted-symbol retention |
| FR-DATA-18 | Vendor vs computed IV/Greeks reconciliation |
| FR-RES-09 | Exploration-to-trial boundary instrumentation |
| FR-SIG-08 | Signal provenance and literature decay haircut |
| FR-BT-12 | Epoch-annotated reporting; no cross-epoch pooling by default |
| FR-BT-13 | Cost-breakeven multiple as a headline metric |
| FR-BT-14 | Tail-aware headline metrics for negatively-skewed returns |
| FR-VAL-09 | Gate thresholds locked before results are visible |
| FR-VAL-10 | Multiple-testing correction across the search family |
| FR-VAL-11 | Minimum backtest length and minimum track-record length |
| FR-CAP-01…06 | New module: Capital, Sizing and Capacity |
| FR-MON-09 | Pre-registered kill criteria recorded at promotion |
| FR-AI-08 | Model identity and training cutoff recorded per run |
| FR-AI-09 | Entity and date masking for historical prompts |
| NFR-07 | Backup, durability and recovery |
| NFR-08 | Tamper-evidence for the research record |
| NFR-09 | Resource partitioning against live trading |
| NFR-10 | Data licensing and redistribution terms |

---

## Reviewer's note on confidence

The gaps in G1, G2, G6, G7, G8 and G9 are structural and do not depend on any
external fact — they can be assessed by reading the document alone.

G3, G4, G5 and the decay figure in G10 rest on external claims. Of these, the
regulatory dates and the vendor instrument-master behaviour are the two worth
verifying before they drive design decisions, and both are flagged inline. The
LLM training-cutoff finding (G5) rests on recent published work whose direction
is not in dispute even if the precise magnitude is.

Nothing in this review requires restructuring the document. All findings are
additive or corrective within its existing shape.
