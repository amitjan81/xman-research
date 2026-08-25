# The BANKNIFTY corpus, measured

What the published BANKNIFTY corpus contains, what it is missing, and what its bars say
about the facts the engine has to get right before any BANKNIFTY result means anything.
Everything below is measured over the **in-sample** window only. Nothing in the sealed
holdout was opened; where a holdout figure appears it is a count taken from the manifest,
never from a bar.

Corpus root `/home/qa/runtime/data/backtest/datasets/dhan/BANKNIFTY/`, manifest
`/home/qa/runtime/data/backtest/dhan/manifest.sqlite`, calendar `NSE`, derivation version
`session-store/2`.

## Holdout declaration

| | Range | Sessions | Read? |
|---|---|---|---|
| In-sample | 2024-08-01 .. 2026-05-29 | 392 published, 56 quarantined | yes |
| **Sealed holdout** | **2026-06-01 .. 2026-08-25** | **60 published, 1 quarantined** | **no** |

The holdout counts come from `SELECT ... FROM sessions` in the manifest. No parquet dated
2026-06-01 or later has been opened by any measurement in this document, and none may be
until a pre-registered decision spends it. `research/banknifty/README.md` states the split
that every BANKNIFTY run is expected to honour.

The corpus holds **509** BANKNIFTY sessions in total, 2024-08-01 .. 2026-08-25: 452
published, 57 quarantined.

## Sessions and gaps

Resolved over the full in-sample window, `SessionStore.resolve("BANKNIFTY", 2024-08-01,
2026-05-29)`:

| | |
|---|---|
| Expected by the NSE calendar | 449 |
| Found on disk | 392 |
| Missing | 57 |
| Unexpected (on disk, not expected) | 0 |
| Completeness | 87.31% |

**56 of the 57 gaps are quarantines, not losses.** The producer captured those sessions,
judged them, and published no parquet — so from the store's side they are simply absent.
The 57th, **2024-11-20**, appears in no manifest row at all: NSE did not hold a session
(Maharashtra state election) and the calendar this store uses expects one. It is a
calendar/producer disagreement, not missing data.

A second such disagreement exists and does *not* show up as a gap: **2026-01-15** has no
session on either side, and the calendar does not expect one, so nothing is reported.

Missing runs over the in-sample window (a run is consecutive expected sessions):

```
2024-08-28  2024-09-11  2024-09-18  2024-10-09  2024-11-13  2024-11-20
2025-01-30  2025-02-27  2025-04-01  2025-04-09  2025-04-24..2025-04-30 (5)
2025-05-05..2025-05-08 (4)  2025-05-12  2025-05-22  2025-05-29..2025-06-03 (4)
2025-06-05  2025-06-09..2025-06-11 (3)  2025-06-18  2025-06-30..2025-07-15 (12)
2025-07-17  2025-07-21..2025-07-22 (2)  2025-08-25  2025-08-28..2025-09-02 (4)
2025-10-08  2025-10-30  2025-11-04  2025-12-30  2026-03-09  2026-03-30  2026-05-26
```

The 12-session run 2025-06-30..2025-07-15 is the largest hole in the corpus and sits inside
the April-July 2025 quarantine cluster below.

## Quarantine, by reason

The manifest's `reason` strings embed per-session numbers, so they are grouped here by
their shape rather than quoted verbatim.

| Reason | In-sample | Holdout | What it means |
|---|---|---|---|
| `N candles with premium below intrinsic by more than 1.0% of spot; rolling-spot vs index divergence X% > 0.5%` | 42 | 0 | The option premium and the rolling spot disagree with the index. Clustered Apr-Jul 2025; worst divergence 11% on 2025-05-30. |
| `expiry-day convergence failed: ATM straddle (strike K) residual time value V INR > threshold at close — derived expiry suspect` | 13 | 1 | The ATM straddle still carried time value at the expiry close, so the derived expiry date is suspect. |
| `N candles with premium below intrinsic by more than 1.0% of spot` | 1 | 0 | The premium check alone (2026-03-09); no divergence component. |
| **Total** | **56** | **1** | |

**The 14 convergence-failure sessions are almost all expiry days themselves** —
2024-08-28, 2024-09-11, 2024-09-18, 2024-10-09, 2024-11-13, 2025-01-30, 2025-02-27,
2025-04-24, 2025-05-29, 2025-08-28, 2025-12-30, 2026-03-30, 2026-05-26 and (in the
holdout) 2026-06-30, plus 2026-03-09 which is not. That is the single most consequential
fact in this document for a hold-to-expiry strategy: see "What this does to a
hold-to-expiry position" below.

## Contract conflicts

Summed over the in-sample published sessions, from the manifest's own columns:

| | |
|---|---|
| `overlapping_contract_minutes` | 254 |
| `resolved_conflicts` | 247 |
| `unresolvable_conflicts` | **0** |

254 minutes across 392 sessions is 0.65 minutes per session, and none of it is left
unresolved.

## Lot size: declared 30 everywhere, four regimes in the bars

Measured over all 392 published in-sample sessions — 5,792,875 positive-volume option rows
— grouped by the session's **front expiry**, which on this corpus is the same thing as
grouping by contract: every one of the 392 sessions carries positive volume under exactly
one expiry, zero exceptions.

| Regime | Expiries | Expiries covered | Sessions | Volume rows | ÷15 | ÷30 | ÷35 | ÷45 |
|---|---|---|---|---|---|---|---|---|
| **15** | 2024-08-07 .. 2025-01-30 | 18 | 119 | 1,844,651 | **100.00%** | 49.75% | 13.97% | 32.93% |
| **30** | 2025-02-27 .. 2025-06-26 | 5 | 75 | 1,119,017 | 100.00% | **100.00%** | 13.42% | 32.45% |
| **35** | 2025-07-31 .. 2025-12-30 | 6 | 102 | 1,469,277 | 32.11% | 15.51% | **100.00%** | 9.97% |
| **30** | 2026-01-27 .. 2026-06-30 | 6 | 96 | 1,359,930 | 100.00% | **100.00%** | 12.87% | 31.87% |

Read the shares as bounds, not as votes: divisibility establishes only a *lower* bound on
a lot size, so 100% by 15 in the first regime is consistent with 15 and the 49.75% by 30 is
the chance rate for even multiples. The coarsest candidate that explains essentially every
row is the estimate the evidence supports. 45 was tested and explains at most a third of
any regime, which is chance, so it is not carried as a candidate.

**Every one of the 392 published in-sample sessions declares `LotSize: 30` in its
refdata.** The corpus holds 509 sessions, but the 61 from 2026-06-01 are sealed and no
bundle of theirs was opened, so this claim is made over what was read and not over the
corpus as a whole. Nothing in the
corpus ever declares 15 or 35. This is the publish-time-dependence defect the NIFTY table
already records: the corpus was published in one batch against the then-current scrip
master, so one value is stamped onto four regimes. The refdata belongs to the producer
repository (`xman`) and must be regenerated there; nothing in this package rewrites the
corpus.

Encoded as `BANKNIFTY_LOT_SIZE_EPOCHS` in `xman_research.backtest.lot_size`, keyed on
expiry, `CORROBORATED` — measurement, not citation; no NSE circular has been read.
The table closes at the 2026-06-30 expiry rather than running open-ended, because
extending it past the last measured expiry would claim a regime over the sealed holdout.

**The 35 regime was undetectable before this change.** `CANDIDATE_LOT_SIZES` did not
contain 35, so on those 102 sessions the declared 30 explained 15.51% (below the floor)
while the best available alternative, 15, explained 32.11% (below the ceiling) — and
`LotSizeAudit.contradicts_declared` returned False. A session whose declared lot size is
flatly wrong ran with no stamp at all. 30 and 35 are now candidates; NIFTY's verdicts are
unchanged, because ties break to the coarsest value and a 75-lot session still reads 75.

### A pre-existing defect that BANKNIFTY makes more visible

`epoch_for` takes a parameter named `expiry`, and its only production caller,
`LotSizeAudit.contradiction_message`, passes `self.session_date`. This is documented in
`lot_size.py` and deferred to the owner; it is **not** fixed here. BANKNIFTY widens the
window in which it can be observed, because the post-2024 cycle is monthly and a session
can sit 30 days before its front expiry rather than NIFTY's 7.

Measured over all 392 in-sample sessions: the session-keyed lookup falls in the gap
between two epochs and returns `None` on **48** of them, but a contradiction message is
only produced where the declared lot size is actually contradicted, which narrows the
consequence to **13**:

| Sessions | Front contract | Effect |
|---|---|---|
| 2024-08-01 .. 2024-08-06 (4) | 2024-08-07, lot 15 | message loses its corroboration line |
| 2025-06-27, 2025-07-16 .. 2025-07-30 (9) | 2025-07-31, lot 35 | message loses its corroboration line |
| the other 35 | a 30-lot expiry | no effect — declared 30 is correct, so no message exists |

It never attaches the *wrong* epoch anywhere in the corpus: checked on all 392 sessions by
comparing the expiry-keyed answer against the session-keyed one, zero mismatches. The
consequence is a weaker message, not a wrong number.

## Expiry regimes

35 distinct front expiries appear in the in-sample corpus: 15 Wednesdays, 11 Tuesdays, 8
Thursdays and 1 Monday.

| Regime | Cadence | Expiry weekday |
|---|---|---|
| .. 2024-11-13 | weekly | Wednesday |
| 2024-11-27 .. 2024-12-24 | monthly | last Wednesday |
| 2025-01-30 .. 2025-08-28 | monthly | last Thursday |
| 2025-09-30 .. | monthly | last Tuesday |

The weekly-to-monthly change at 2024-11-13 is the SEBI weekly-expiry cull, and it is
inside the in-sample window rather than at its edge. A hold-to-expiry position goes from a
roughly four-session hold to a roughly twenty-session hold across it.

## Strike ladder and staleness

Every one of the 392 sessions has a strike step of exactly **100**, with no exceptions and
no mixed steps within a session. Dhan's capture is capped at ATM±10 strikes, so a position
opened at the money can be marked only while spot stays within **±1000 points** — about 2%
at a 2024-2026 BANKNIFTY level of 47,886 .. 61,520.

Absolute spot move over N sessions, from the in-sample session closes:

| Horizon | Observations | > 1000 pts | Median | p95 | Max |
|---|---|---|---|---|---|
| 1 session | 391 | 26 (6.6%) | 286 | 1,110 | 3,052 |
| 3 sessions | 389 | 95 (24.4%) | 517 | 1,932 | 4,194 |
| 5 sessions | 387 | 130 (33.6%) | 658 | 2,726 | 5,199 |

So a one-session hold leaves the ladder about 7% of the time and a five-session hold about
a third of the time — and in the monthly regime the hold is four times longer than that.
Stale marks are not an edge case on this underlying; they are the expected condition of any
multi-week hold, and the engine stamps them (`max_stale_fraction` is the gate that reads
it). The BN-M1 benchmark measured a stale-mark fraction of **13.3%** of sessions — lower
than this table implies, because it only holds a position on the cycles the corpus can
settle.

## What this does to a hold-to-expiry position

The 14 convergence-failure quarantines land on expiry days, and an expiry session that was
never published is a settlement the run cannot perform. Over the BN-M1 benchmark window
(2024-10-01 .. 2026-05-29) there are **27** expiry cycles and **10** of their expiry
sessions are absent: 2024-10-09, 2024-11-13, 2025-01-30, 2025-02-27, 2025-04-24,
2025-05-29, 2025-08-28, 2025-12-30, 2026-03-30, 2026-05-26.

The engine refuses to open a position it can prove it cannot close, so those cycles are
declined at entry and counted `UNSETTLEABLE`. That refusal is correct and was not softened.
Two consequences a reader must carry:

1. **The tradeable population is at most 17 of 27 cycles**, not 27 — and fewer in
   practice: the last of the 17 expires past the window edge, so BN-M1 opened 16 straddles
   and settled 15.
2. **It is quarantine-selected, not random.** Expiry-day convergence failure is most likely
   on expiries where the ATM straddle retained the most residual value at the close — which
   is not independent of what a short straddle earns on that expiry. Any BANKNIFTY result
   over this corpus inherits that selection, and no amount of statistics inside this
   package can remove it. The fix is producer-side.

## Reproducing these numbers

The lot-size, staleness and conflict figures come from a one-off scan of the published
in-sample parquet files plus the manifest; the session, gap and quarantine figures come
from `SessionStore.resolve` and the manifest directly. The benchmark's own copies of the
gap and lot-size figures travel inside `research/banknifty/bn_m1_benchmark.json`, under
`data_provenance` and `lot_size_audit`, so a reader can check this document against the run
rather than against a promise.
