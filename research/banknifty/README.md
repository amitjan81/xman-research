# BANKNIFTY research

Two things every BANKNIFTY run in this repository is expected to honour: the in-sample /
holdout split, and the gap-acceptance reason. Both are written down here so a run does not
get to choose them while looking at a result.

## The split

| | Range | Sessions |
|---|---|---|
| In-sample | 2024-08-01 .. 2026-05-29 | 392 published (56 quarantined) |
| **Holdout — sealed** | **2026-06-01 .. 2026-08-25** | **60 published (1 quarantined)** |

**The holdout is unread.** Counting its sessions in the manifest is allowed and is how the
numbers above were obtained; loading a bar from it is not. It is spent once, by a
pre-registered decision, and it is spent by nothing else — not by a benchmark, not by a
sanity check, not by "just looking".

The boundary is 2026-06-01 rather than a round quarter because the corpus was published on
2026-08-25 with sessions running to that date, and the last three months are the only
material never used to build anything. It is drawn before any BANKNIFTY strategy has been
written, which is the property that makes it worth anything.

`BANKNIFTY_LOT_SIZE_EPOCHS` respects it: the table closes at the 2026-06-30 expiry, the
last one evidenced by in-sample sessions, instead of running open-ended into unmeasured
data.

## The window a run actually gets

The in-sample corpus starts 2024-08-01, but a **costed** run starts **2024-10-01**, the
first date the securities-transaction-tax schedule is in force. Earlier sessions are
runnable — rate schedules extrapolate rather than refuse — but extrapolating STT
undercharges, because STT has only ever been revised upward, and the run carries
`costs.rate_extrapolated:stt.*` to say so. A number another run has to beat must not be
flattered by construction, so BN-M1 gives up the two months. A run that has a reason to
want them may take them, and must report the stamp.

Measurement is different from grading and is not bound by that floor: reading bars charges
nothing, so the lot-size epochs are measured over the full 2024-08-01 .. 2026-05-29 window.

## The gap-acceptance reason

The in-sample window is 87.31% complete: 57 of 449 expected sessions are absent, 56 of them
quarantined by the producer and one (2024-11-20) a session NSE did not hold. A BANKNIFTY
run therefore cannot use `Resolution.sessions()`; it must call `accept_gaps` with a written
reason.

**The reason to use is `xman_research.models.bn_benchmark.GAP_REASON`**, or one derived
from it for a different window. Import it rather than retyping it — a reason that drifts
from the run it describes is worse than none. What it has to say, and what that constant
says:

1. How many sessions are expected, present and absent for that exact window.
2. That 43 of the absences are the premium-below-intrinsic / spot-divergence quarantines
   clustered April-July 2025, and that the rest are expiry-day convergence failures.
3. **That ten of the absences are front-contract expiry sessions**, named, so a
   hold-to-expiry strategy cannot silently lose ten cycles. The engine declines those
   cycles as `UNSETTLEABLE`; the reason says so and the result counts them.
4. That the window is not narrowed to dodge the holes, and why: narrowing fragments one
   trial into many and discards the 2024-11-13 weekly-to-monthly change and the lot-size
   boundaries, which are exactly the conditions a real BANKNIFTY strategy traded through.
5. That `include_quarantined` is **not** passed. Quarantined sessions are excluded, never
   read into a P&L. "Carry on across a gap" and "compute on data the producer says is bad"
   are different decisions and this is only the first.

## What is here

| File | What it is |
|---|---|
| `CORPUS.md` | The corpus measured: sessions, gaps, quarantine reasons, conflicts, lot-size regimes, expiry cadence, ladder staleness. |
| `BN_M1.md` | The BN-M1 benchmark read honestly. |
| `bn_m1_benchmark.json` | That run's metrics, provenance, lot-size audit and fingerprint. |

The runner is `xman_research.models.bn_benchmark`
(`uv run python -m xman_research.models.bn_benchmark`). BN-M1 is a **benchmark and an
engine proof**, not a candidate: nothing grades it, and it spends no holdout.
