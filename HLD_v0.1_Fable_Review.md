# Fable review — Options Research Platform HLD v0.1

**Reviewed:** `Options_Research_Platform_HLD_v0.1.md` against FRD v0.2
**Date:** 11 August 2026
**Method:** full read of both documents; three claims verified against primary web sources; ~16 individual requirements sampled rather than trusting the §16 coverage table.

Severity and confidence are given per finding. Findings are reported at all levels; filter as you see fit.

---

## Verdict

Strong on integrity mechanics and honest about its two known weak points (cost model, Tier-1 fidelity). The **newly added material is the weakest part**: the claim plane is incomplete as specified, §8.4 contradicts the container table in two places, and the largest unexamined risk is that the design sizes a 10-underlying corpus while the FRD demands day-one capture of the full index **and stock** derivatives universe — the one dataset the document itself calls irreplaceable.

## Status of the four previously-fixed flaws

| Fix | Status |
|---|---|
| 1. Claim plane replacing SQLite-over-NFS | Conceptually right, **incomplete** — see 1.1–1.3 |
| 2. Two-tier validation protocol | Sound protocol; arithmetic for the *adopted* design never derived (5.1); correlation guard has no locked threshold (5.2) |
| 3. Live-observed family + Redis split | Sound; write-path risk honestly spiked. Residual: second-host "read-only lake replica" has no named replication mechanism or freshness bound |
| 4. IO isolation / physical separation | **Verified accurate** against kernel docs — `io.weight` is inert under the `none` scheduler absent blk-iocost; the `memory.low`/first-faulter cache-charging description is correct. QAS-06 test broadening is a genuine improvement |
| Backup fixes | `VACUUM INTO`/backup-API rule correct; ledgers-then-lake ordering logically valid *because* the lake is append-only |

---

## CRITICAL

### C1 — The design never sizes the workload the FRD mandates
*(critical, medium-high confidence)*

§8.2's only numbers: *"a full NSE **index**-options chain … 10⁵ rows/underlying/day; a **10-underlying**, 5-year corpus lands in the low hundreds of GB."*

But FRD §1.1 and FR-DATA-01 scope the platform to *"NSE/BSE **index and stock** derivatives"*, and FR-DATA-14 requires day-one capture of *"the full live derivatives universe (all listed contracts, including those expiring)"*. NSE alone lists **180+ stock F&O underlyings** plus indices, each with thousands of listed contracts per day. The sizing note is one to two orders of magnitude short, and it silently substituted "index" for the FRD's "index and stock".

This drives everything the note was meant to answer: disk headroom (left open in §17), nightly offsite backup volume, file counts, QC/derivation compute.

Compounding it, **no capture mechanism is decided**. Is 1-minute data polled live or bulk-downloaded T+0? Diagram 3 hints at both (*"fresh: intraday / T+0 evening"*). Can a retail vendor API deliver full-universe 1-minute bars daily within rate limits at all? For the one requirement the document itself calls irreplaceable and unrecoverable if missed, there is **no feasibility analysis**.

---

## MAJOR

### Mechanisms

**1.1 — Claim plane has no liveness mechanism.** *(high)* The orphan reaper detects a dead *local* worker by PID; a dead *remote* worker is indistinguishable from a slow one without leases, heartbeats or claim expiry, and none of the three endpoints provides one. QAS-08 (reclaim < 10 min) silently fails the moment the axis-2 seam is used — which AD-20's preferred day-one second-host placement does immediately.

**1.2 — Off-host workers cannot persist run artefacts.** *(high)* The lake is mounted read-only off-host, yet workers own *"run results + artefacts written to lake/registries"* including equity curve and full trade log (FR-BT-07). The only remote write path is `submit-result-and-trial`, which nothing says carries bulk artefacts. Either that endpoint becomes an artefact-upload plane (unstated, with size and idempotency implications) or remote workers need lake write access — contradicting the design.

**1.3 — Claim plane placement is undefined and trust-mixed.** *(high)* §8.4 puts it on the Lifecycle Controller — same process as the kill switch and promotion endpoints — so the lowest-trust workloads hold credentials to the production gatekeeper, with no authn separation stated. Worse: the **Lifecycle Controller appears in no slice in Diagram 7 at all**, and Diagram 7's claim arrow terminates on the capture-daemon box rather than the LCC. The §8 container table's LCC row omits the claim plane entirely. Three views, unreconciled.

**1.4 — "As-of is what DuckDB does natively" conflates two query shapes.** *(medium)* ASOF JOIN is a nearest-preceding-*event-time* join. The load-bearing PIT query is different: per-key selection of the latest version with knowledge-time ≤ D across overlapping version files — an argmax/dedup, not an ASOF join. Snapshot-pinned runs dodge this; the SDK's *default ad-hoc* as-of query (QAS-02) does not. The §17.4 spike as worded would validate the wrong shape.

**1.5 — Tamper-evidence is defeatable, and §4 permits the hole.** *(high)* NFR-08's value under C1 is protection against the operator's future self. The chain head is anchored into each offsite backup — but §4 says of the target: *"Any dumb remote store qualifies; choice is LLD."* An operator who can rewrite the ledger can also rewrite archives on a dumb store they control and recompute the chain end-to-end. Detection depends on anchor immutability (WORM / object-lock / third-party timestamping) that the document never requires. One-line fix; as written the mechanism does not hold.

**1.6 — MonthlySqliteStore vs hash chain: unreconciled.** *(high)* A monthly-rolling file family and a continuous hash chain interact non-trivially — chain continuity across file boundaries, verification across the family, which file holds the head. Nothing addresses it.

**1.7 — QAS-09's registry RPO ≤ 1 h has no mechanism.** *(high)* §12 and Diagram 7 specify one nightly offsite push. Nothing ships ledger increments hourly. Either the RPO or the backup design is wrong.

### Coverage — requirements the design does not actually discharge

**2.1 — FR-VAL-08 (runtime leakage detector) is unowned.** *(high)* Swept under "FR-VAL-01…11 → Validation library", but that block lists walk-forward/CPCV/DSR/PBO/corrections/MinBTL — no leakage detector. §13 cites a *"leakage tripwire test suite"*, which tests the platform's own API, not the required runtime detector over researcher pipelines with its negative-control suite.

**2.2 — FR-BT-02's statutory cost stack has no data home.** *(high)* The STT/brokerage/exchange-fee/GST/stamp schedule *with effective-date history* is a dataset. It is in none of §9's six families and none of the Registries blocks. `ICostModel` is the FR-BT-03 *slippage* abstraction, not the statutory stack.

**2.3 — FR-FWD-01 paper fill simulation is unowned.** *(high)* No block in the Signal Runtime or anywhere simulates fills in paper mode. The Runtime evaluates and emits; the Gateway merely doesn't forward.

**2.4 — FR-SIG-01's online write path is unowned.** *(high)* No container computes features online: Capture's blocks don't, QC & Derivation is batch on the research queue (wrong slice and trust level for a production write), and the Signal Runtime's adapters read. Which process writes the production Redis hash every minute, in which slice, as which user? This is the feature-store half of the parity story.

### Consistency

**3.1 — The Gate Evaluator lives in two containers.** *(high)* §8 and §16 put gate evaluation in the Lifecycle Controller; §8.1 and §8.4 put a Gate Evaluator block that *"writes a pass/fail record"* in the Backtest & Validation Workers, while the LCC gets a separate Gate Orchestrator. Which container writes the record matters — it is the FR-VAL-09 integrity boundary.

**3.2 — The Universe Resolver lives in two containers.** *(high)* §8.4 lists it under PIT Lake; the §8 table and §16 put it under Registries & Ledgers.

### Scale

**6.2 — Small-file proliferation vs "no re-partitioning event exists by design".** *(medium)* dataset/underlying/day × full universe × knowledge-time versions is millions of Parquet files over five years. Compaction is the standard cure but conflicts with immutability plus content-hashed manifests, so it needs design. §11 axis 1 asserts the problem cannot occur.

### QAS

**5.1 — QAS-05b's < 12 h is asserted, never derived.** *(medium)* §7.8 shows arithmetic for the *rejected* design but none for the adopted one. 15–20 candidates × ≥45 paths = 675–900 full-resolution path-runs; at ~3 min/path across 6 workers it closes with ~2× headroom — but 3 min/path is unsupported for exactly the class the tiering exists for, and QAS-03's own budget is <5 min for *one year, one underlying*. A multi-year path at 10–20 min makes QAS-05b a 20–50 h job. **The one piece of arithmetic that justified the redesign is missing for the redesign itself.**

### Missing entirely

**7.2 — No threat model for the integrity story** *(high)* — who tamper-evidence defends against, and what the anchor target must therefore be (see 1.5).

**7.3 — The platform's own SDLC** *(medium)* — FR-DEP-02 governs signal repos; nothing states how the *platform's* code (largely AI-written per C1) is tested, reviewed, released or hotfixed while live signals run.

**7.4 — Lake schema evolution** *(medium)* — vendors add and rename fields over five years; dataset schema versioning and its interaction with byte-identical reproducibility and old manifests is unaddressed.

---

## MINOR / NIT

- **1.8** Outbox *"exactly once"* is an overclaim — outbox + retries is at-least-once dispatch; idempotency keys give effectively-once *processing*. Also the Stream→outbox handoff is a dual-write; the real guarantee rests on consumer-group ack discipline, an argument the document doesn't make. *(medium)*
- **1.9** QAS-04's async appender vs *"100% ledgered"* — a crash loses in-flight rows; the local queue's crash semantics are unstated. Diagram 5 also shows workers writing trials directly while §8.4 routes them through the appender. *(medium)*
- **1.10** *"Byte-identical"* exceeds its mechanism — the identity tuple pins engine version but not the numeric environment (dependency set, BLAS, thread count / reduction order). Needs a lockfile hash. *(medium)*
- **2.5** FR-CAP-04 live enforcement under-specified — the Gateway's cap enforcer needs volume/OI at the strike and has no market-data access in any diagram; as drawn it enforces only static caps. *(medium)*
- **2.6** NFR-05 partially discharged — lake/registries at rest, and claim-plane/dashboard transport, are unaddressed; coverage maps it to OS-user separation alone. *(medium)*
- **2.7** FR-DEP-02 CI has no infrastructure — no container runs CI, and shared-host CI contends with live trading. *(low)*
- **2.8** FR-CAP-01 (return on margin capital as *primary* metric) isn't named in the Metrics Reporter, whose list leads with CAGR/Sharpe. *(nit)*
- **3.4** Trial-logging machinery split — Registries owns the async appender, Research Workspace owns the auto-logger, Diagram 5 shows a third direct path. No boundary statement. *(medium)*
- **3.5** Production Redis contents incomplete — §11 defines it as holding the online feature store, but the SRT→Gateway emission stream must live somewhere too. *(low)*
- **3.6** Signal Registry block claims cross-signal correlation while Monitoring's Crowding Analyser computes it. Defensible store-vs-compute split, reads ambiguously. *(nit)*
- **4.1** *"Black-76 IV inversion"* fixes an algorithm the FRD deliberately left open, and Black-76-on-what-forward for spot-settled NSE index options is a methodology decision deserving the spike treatment given to margin. *(medium)*
- **4.2** "zstd" is a config detail per the document's own altitude boundary. *(nit)*
- **4.3** The claim plane's three-endpoint enumeration is LLD-grade precision that is *also wrong* — enumerating endpoints invited falsification without providing completeness. *(medium)*
- **5.2** The rank-correlation guard has no locked threshold — "weak correlation" decided by whom, when? On a platform whose thesis is thresholds locked before results, leaving this one post-hoc is self-inconsistent. *(medium)*
- **5.3** QAS-09's lake RPO ≤ 24 h means up to a full day of prospective capture — *"explicitly irreplaceable"* — sits in the loss window. Possibly acceptable; never acknowledged as a trade. *(medium)*
- **6.3** Single-operator standing load is claimed low, not shown low — 13 containers, two Redis instances, JupyterLab, cron, CI, possibly a second host, daily chain verification, restore rehearsals. No statement of daily burden or paging surface. *(medium)*
- **6.4** Alerting is required at <5 min / <1 h in four QAS and **no notification channel is named anywhere**. prometheus_client exposes metrics; nothing pages a sleeping operator during the overnight sweep. *(nit)*
- **7.5** Licensing of data sent to LLMs — the AI layer ships vendor market data to third-party APIs; NFR-10 records redistribution terms but nothing checks the AI path against them. *(medium)*
- **7.6** xman reuse *mechanism* undecided — shared packages, fork, or reimplementation, and the dependency boundary with a live trading system. An irreversible-choice-shaped question at exactly HLD altitude. *(medium)*
- **7.7** No operator-absence runbook — one human, live emissions, vacation/illness. Defensible under C1; the sentence is still expected. *(low)*
- **7.8** *"Parquet reads take no locks"* is true of finished files; write-temp-then-rename discipline for in-flight files is assumed, never stated. *(nit)*

---

## Reverse check

No container or block was found without a driving requirement. The live-observed family and claim plane are both requirement-traceable. §16's gold-plating claim stands.

## Verified accurate

The SQLite/NFS citation, the cgroup-v2 IO claims, and py-vollib as a Let's-Be-Rational implementation are all correct as stated.

**Sources consulted:** [DuckDB AsOf Join docs](https://duckdb.org/docs/current/guides/sql_features/asof_join) · [AsOf join performance #7187](https://github.com/duckdb/duckdb/issues/7187) · [hive-partitioned join discussion #9690](https://github.com/duckdb/duckdb/discussions/9690) · [Linux cgroup-v2 kernel docs](https://docs.kernel.org/admin-guide/cgroup-v2.html) · [blk-iocost / io.cost.qos (LWN)](https://lwn.net/Articles/793460/) · [NSE F&O underlyings list](https://venturasecurities.com/invest/stocks/fno-stocks-list)
