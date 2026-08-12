# Shared Data Layer — Analysis and Recommendation

| | |
|---|---|
| **Version** | 0.1 |
| **Date** | 12 August 2026 |
| **Question** | Should the Dhan data pipeline be extracted into `xman-data-platform` so the execution and research platforms share one normalised, enriched corpus? |
| **Basis** | Source map of `/home/qa/xman/backtest/src/xman_backtest/dhan/` (3,125 LOC, 13 modules) and the 119-session corpus on disk |

---

## 1. Recommendation, up front

**Yes to sharing. Yes to extraction eventually. No to extracting first — and the repo is the least important part of this decision.**

The pipeline as it stands **cannot serve the research platform regardless of which repository it lives in**, for four reasons that are all about data semantics rather than code location. Moving it would feel like progress and deliver none of what research needs.

The sequence that actually works:

| Phase | What | Why this order |
|---|---|---|
| **0 — now, days** | Widen and harden capture *in place* | POC milestone 0: a day not captured is permanently lost. A repo move captures nothing |
| **1 — weeks** | Add point-in-time semantics *in place* | This is the real work, it is additive, and the execution backtester never notices |
| **2 — when two consumers actually exist** | Extract the ingest tier to `xman-data-platform` | Cheap by then (~2,000 LOC leaf), and the contract will have been proven by use |

The extraction is genuinely cheap — that is precisely why it should not be done first. **The cheap thing does not unblock anything; the expensive thing does.**

---

## 2. What exists today

A working, well-tested pipeline. This is not a rewrite candidate.

**Flow:** `sync-master` → `download` → `publish`, orchestrated by `Pipeline.publish_session()`, driven nightly by cron at 18:30 with a weekly Saturday sweep.

**Output:** one parquet per session at `datasets/dhan/NIFTY/YYYY-MM-DD.parquet`, columns `minute_ts, symbol, open, high, low, close, iv, oi, volume, spot, delta, gamma, theta, vega`, plus a sibling `.refdata/` directory the backtester loads through the same `RefDataCache` used live.

**Provenance:** a SQLite manifest with `raw_downloads` and `sessions` tables, content sha256 per artefact, download-level skip so an already-fetched window is never re-requested.

**Quality:** four hard-fail schema and OHLC checks, four quarantine thresholds (spot coverage &lt;95%, premium-below-intrinsic, rolling-spot divergence &gt;0.5%, expiry-day straddle time value &gt;₹60), and a **canary backtest** that runs a reference strategy over the published artefact.

**Tests:** 2,588 lines across 13 test modules, hermetic against fake payloads.

**Provenance of the enrichment matters for what follows:** `iv`, `oi`, `volume` and `spot` are **vendor-supplied**; the **Greeks are computed by us** at publish time via Black-76, using spot-as-forward, a hardcoded 7% risk-free rate, and always against the **front weekly expiry**.

---

## 3. The four things that block sharing — none of them topological

### 3.1 No knowledge-time, no versioning, no restatement handling

Both manifest tables use `INSERT OR REPLACE`. **No history is retained.** A re-publish overwrites the parquet in place and silently replaces the recorded sha256 and timestamp; the only drift signal is a `logger.warning` line in a cron log.

Research requires bitemporal point-in-time storage (FR-DATA-03/10), immutable content-hashed snapshots (FR-DATA-09), and the ability to answer *"what did we believe on date D"*. That is not a feature bolted onto this design — **it is a different data model**, and it is the single largest piece of work in this analysis.

The redeeming detail: **it is additive.** Adding a knowledge-time dimension and version history does not break the execution backtester, which continues reading the latest version and never notices. This is why it can be done in place, before any extraction.

### 3.2 Front weekly expiry only — structurally, not by configuration

`download_expired_options` hardcodes `expiry_flag="WEEK"` and `expiry_code=1`. There is **no monthly or back-week ingestion at all**.

That is not a gap in coverage; it is a gap in what the corpus can ever answer. Term structure (H7), calendar spreads and the inversion flag (H8), the VRP term structure (H3), and the 1DTE-overnight hypothesis (H15b) are all undefined on a single-expiry corpus. **Roughly half the seed catalogue is untestable against this data as captured**, and no amount of repository restructuring changes that.

### 3.3 The expiry rule is hardcoded to Tuesday, and the code says so

`expiry.py` implements `_TUESDAY = 1` with an explicit docstring warning:

> *"Valid only for the post-Tuesday-transition window. Extending the backfill into the pre-2025 Thursday era requires a new decision — do NOT silently generalize this rule."*

There is no data-driven expiry table and no date-conditional branch. **Backfilling before 1 September 2025 would produce wrong expiries, and therefore wrong refdata and wrong Greeks.**

The safety net does not catch it. `_check_expiry_convergence` only fires on sessions that *are* the derived expiry day — so a systematically wrong weekday shifts most sessions without tripping anything. It is precisely the failure mode that looks fine until someone checks.

This matters immediately: the research platform needs pre-November-2024 history for epoch comparison and holdout span, and that is exactly the era this rule gets wrong.

### 3.4 Greeks carry the execution platform's approximations

Computed against the **front expiry only**, with **spot as the forward** and a **hardcoded 7% RFR** — chosen deliberately to match the backtest runner's own convention, which is the right call for that consumer.

For research it is not. Multi-expiry work needs per-expiry Greeks; the forward should come from put-call parity rather than spot; and the rate belongs in data, not a module constant. **If the shared layer bakes in one consumer's approximations, the other inherits them silently** — see §6.

---

## 4. Coupling — the extraction is cheap, and cleanly tiered

The map produced the fact that decides the shape of any extraction. The subtree splits into two tiers with different dependency profiles:

| Tier | Modules | Depends on | Extractable? |
|---|---|---|---|
| **Ingest** | auth, client, instruments, expiry, manifest, download, normalize, report, email, pipeline | Three `xman_core` symbols (`EngineTime`, `NSEHolidayCalendar`, `compute_greeks_black76`, 612 LOC total, no internal deps of their own) plus two trivial helpers — a 10-line path resolver and one pure function | **Yes — a genuine leaf** |
| **Verification** | `validate.run_canary_backtest`, `backtest_validate.py` | The entire execution engine: `BacktestRunner`, the scan kernel, `report.metrics` | **No — and it should not be** |

The verification tier's imports are function-local and lazy, so the ingest tier imports cleanly without them.

**Nothing outside `backtest/` imports the dhan package** — zero references from `btp`, `xman_strategy` or `xman_brokers`. Reverse dependencies are the cron script, its own tests, and two prose comments.

**`data/datasets.py` is the seam.** Unlike `dhan/`, it is *not* a leaf — the workflow executor, composite runner and period orchestrator all import it. It is already the boundary between the execution platform and the data layer, which makes it the natural published contract.

---

## 5. What to extract, and what not to

When Phase 2 arrives:

**Extract — the producer.** The ingest tier, roughly 2,000 LOC: acquire, normalise, structurally validate, publish versioned. Plus either the three `xman_core` symbols or small reimplementations.

**Do not extract — the consumers' own acceptance tests.** The canary backtest is *xman's* check that the data is fit for *its* engine. Research will want entirely different checks — leakage tripwires, epoch-boundary refusal, holdout seal verification. Forcing both into a shared validator produces a validator serving neither. **Each consumer keeps its own acceptance layer.**

That yields a clean producer/consumer split:

```
xman-data-platform  →  publishes versioned, normalised sessions + manifest + refdata
        ├── xman/backtest        reads; runs its canary
        └── xman-research        reads; runs leakage tripwires, epoch checks, seals the holdout
```

**The contract is the file layout, the schema and the manifest — not a Python API.** That distinction matters more than the repository does: research reading parquet has *no code dependency on a live trading repo*, which is the coupling actually worth avoiding. Research only needs to import the producer if it must *run* the pipeline — and under this split it does not, because capture is owned by one side and consumed by both.

---

## 6. The caution I would not skip

The brief says "share the same normalised enriched data". The word doing the work is **enriched**, and it is where a shared layer most easily goes wrong.

**Raw and vendor fields are unambiguously shared.** Bars, IV, OI, volume, spot — one acquisition, one normalisation, one quarantine rule. That is where the duplication risk genuinely lives and where sharing pays.

**Derived enrichment is not automatically shared**, because the two consumers legitimately want different derivations. Greeks are the worked example: xman's front-expiry, spot-as-forward, fixed-RFR convention is *correct for xman* and *wrong for research*.

Two workable resolutions, and I would take the first:

1. **The shared layer publishes raw plus vendor fields plus a minimal documented derivation; consumer-specific enrichment stays with the consumer.** Greeks move out of the shared publish step, or are published under an explicit **method version** recorded per row, so a reader always knows which convention it received.
2. The shared layer publishes every variant both consumers need — more compute, more storage, one source of truth.

Getting this wrong is subtle and expensive: research would silently inherit a forward approximation it would never have chosen, and the resulting IV surface, term structure and skew analytics would all be quietly conditioned on it.

---

## 7. Landmines found in passing

Worth fixing regardless of what is decided about repositories.

| Finding | Consequence |
|---|---|
| **53 orphan quarantine parquets** on disk while the manifest reports `quarantined=0` | Sessions quarantined then republished leave artefacts with no record. The quality report is not reflecting the corpus |
| **Authored option tokens restart at 9,000,000 every session** | Deterministic within a session, **not stable across sessions** — the same contract carries different ids in different files. Anything joining across sessions on token is wrong |
| **NIFTY hardcoded in two places** (`instruments._INDEX_SECURITY`, `download._SPOT_SPEC`) | Adding an underlying means finding both. A duplicated onboarding point is a latent bug |
| **No configuration file of any kind** | Strike range, expiry scope, quality thresholds and the RFR are all module constants. Every scope change is a code change |
| **Cron continues past failures** (`\|\| echo ... >&2` on each step) and alerting is email-only and success-shaped | If cron never fires, or the Gmail credential file is missing, nothing notifies anyone. No dead-man's switch |
| **The crontab is an example, not installed** by anything in the repo | The nightly job's existence depends on a manual step no code enforces |
| Docstring claims `oi`/`volume` are `int64`; they are `float64` | NaN on spot rows forces the widening. Minor, but the schema doc is wrong |
| README says 18:30 UTC while the script computes in `Asia/Kolkata` | Documented-versus-code inconsistency in the one job that must not silently skip |

---

## 8. What I would do next

1. **Fix the expiry rule before any backfill.** Data-driven expiry table with historical validity intervals, replacing the hardcoded Tuesday. This blocks pre-September-2025 backfill, which blocks holdout span and epoch comparison. It is also the highest-risk item here, because it fails silently.
2. **Introduce a config surface.** There is none. Widening expiry scope, strike range or underlyings should not require editing module constants.
3. **Widen capture** — full expiry ladder first, since it unlocks the largest share of the catalogue. Storage is not a constraint: current NIFTY front-weekly runs 1.06 MB per session, so a full chain projects to roughly 7–9 GB per year against 591 GB free.
4. **Then the PIT upgrade** — knowledge-time, immutable versions, append-only manifest history, epoch registry. Additive; the backtester is unaffected.
5. **Then extract**, once research is a real consumer and the contract has been proven by use.

**Items 1–3 are days. Item 4 is weeks and includes migrating 119 existing sessions. Item 5 is a day or two of mechanical work.** That ordering is the whole recommendation: the repository question is the cheapest and least consequential part, and doing it first would deliver the appearance of progress while the actual blockers remained exactly where they are.
