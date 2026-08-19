# M2 — near-week overnight vs intraday variance split, on the backfilled corpus

| | |
|---|---|
| Record | `h_a63a756ae984683a60176fe41e2acf7a` (amendment of H26 v2 `h_cacfc556d38a2bda25efef59eb5544cf`) |
| Gate | `research/m2/gate.toml`, committed in `1921a5b`, before this result existed |
| Window attempted | in-sample 2024-10-01 .. 2026-04-30, 385 sessions |
| Holdout | 2026-05-01 .. 2026-08-03, 64 sessions — **SEALED, not read** |
| Trial burned | `t_ba74b7d8e6694f36b43046876eacdeda`, **outcome = error** |
| **OUTCOME** | **NO VERDICT — the run could not be produced.** The engine refused. |

**Prior verdict for comparison:** H26, FAILS_THRESHOLD, 45 gaps, DSR 0.2413 vs 0.80, PSR 0.7010.

---

## 1. What happened

The candidate backtest died 128 sessions into the window:

```
KeyError: 'NIFTY-09Apr2025-22900-CE is not in the instrument master for 2025-04-07.
A strategy must choose contracts from session.universe; composing a trading symbol is
how a backtest trades an instrument that was never listed.'
```

No metrics exist. This is **not** NOT_EVALUABLE — that is a graded outcome reached from
computed evidence, and no evidence was computed. It is a refusal, and the engine is right
to refuse.

**Do not read this as a null result about the hypothesis.** It says nothing about whether
the overnight premium exists. It says M2 as specified cannot be executed over this window
on this corpus.

## 2. The cause — and it is not what H26 concluded

The strike ladder in this corpus is a **moving window around spot**, not a fixed grid.
Measured directly:

| session | spot at 15:25 | near expiry | strikes listed | is 22900 CE listed? | bars? |
|---|---:|---|---:|---|---|
| 2025-04-04 (Fri) | 22,904.50 | 2025-04-09 | 27 | **yes** | yes |
| **2025-04-07 (Mon)** | **22,232.20** | 2025-04-09 | 30 | **NO** | no |
| 2025-04-08 (Tue) | 22,537.95 | 2025-04-09 | 29 | yes | yes |

M2's overnight arm sold the ATM straddle at Friday's close, when spot was 22,904.50 and the
ATM strike was 22,900. NIFTY then gapped down 2.9% overnight. On Monday the captured strike
ladder had rolled down with the market and **22,900 was no longer in it**. The buy-back
cannot be expressed, so the engine refuses. By Tuesday the strike is back.

**H26 hit the same wall and diagnosed it wrongly.** Trial row 3 in the family log is H26
v1's crash:

```
KeyError: 'NIFTY-03Feb2026-25100-CE is not in the instrument master for 2026-02-03.'
```

`research/h26/gate.toml`'s `supersession` block attributes that to issue #23 — *"the
expiring contract is dropped from the instrument master on its expiry date, so a straddle
entered on expiry eve can never be bought back"* — and fixes it by tightening the entry
guard to `MIN_CALENDAR_DAYS_TO_EXPIRY`. Checked directly:

| session | spot at 15:25 | near expiry | strike range | is 25100 CE listed? |
|---|---:|---|---|---|
| 2026-02-02 (Mon) | 25,095.70 | 2026-02-03 | 24,200 – 25,600 | **yes** |
| **2026-02-03 (Tue)** | **25,719.95** | 2026-02-03 | 25,150 – 26,350 | **NO** |

Spot gapped **up** 2.5% and the ladder's lower bound moved from 24,200 to 25,150, dropping
25,100 off the bottom. The contract did not vanish because it was expiring — it vanished
because the ladder moved.

H26's guard removed the symptom on its 80-session window only by coincidence: 2026-02-03
*was* an expiry date, so an expiry-eve guard happened to exclude the one case that window
contained. M2's failure proves the diagnosis wrong — **2025-04-07 is not an expiry date**
(expiry is 2025-04-09), the guard passed, and the same `KeyError` occurred.

## 3. Why this matters more than a threshold would have

The failure is **selective on exactly the population M2 exists to measure.**

M2's mechanism is payment for gap risk. The larger the overnight gap, the further spot
moves, and the more likely last night's ATM strike falls outside this morning's captured
ladder. Both known instances are large gaps — −2.9% on 2025-04-07 (the global tariff
selloff) and +2.5% on 2026-02-03.

So the corpus is structurally blind to the biggest overnight moves in the sample, and it
does not fail gracefully by omitting them — it kills the run. Any future guard that skips
these sessions to make M2 runnable would be **silently conditioning the sample on the gap
being small**, which is a bias pointing directly at the hypothesis under test: it would
remove the sessions where a gap-risk seller takes its losses while keeping the sessions
where it collects. A version of M2 that runs by excluding them would produce a *flattering*
number, not a neutral one.

This compounds H26 §9's already-recorded limit that ~43% of candidate gaps are
unobservable. That was a limit on power. This is a limit on **validity**.

## 4. Threshold table

None. No metrics were computed, so there is nothing to compare against the pre-registered
bars. For the record, the bars that were registered and never reached:

| metric | required | observed |
|---|---:|---|
| `deflated_sharpe` | ≥ 0.90 (raised from H26's 0.80) | — |
| `cost_breakeven_multiple` | ≥ 3.0 | — |
| `max_drawdown` | ≤ 0.10 | — |
| `risk_matched_increment` | ≥ 0.0 | — |

The PSR/DSR spread the brief asked for — H26's most interesting number, 0.7010 against
0.2413 — **cannot be reported for M2.** M1's answer to the same question is in
`research/m1/DECISION.md` §4, and it is that H26's "the failure was almost entirely the
multiple-testing correction" does not generalise.

## 5. Descriptive analyses

All three pre-registered in `gate.toml` — the per-epoch breakdown, the calendar-day
dose-response, and the settled-P&L decomposition — are **unreportable**. Each is computed
from a return series that does not exist. They are not omitted for convenience, and none
may be quietly dropped from a future run's obligations.

## 6. Honesty stamps

The run produced no `unverified_inputs` list, because it produced no result. The stamps
that *would* have applied are M1's (`research/m1/DECISION.md` §8), plus M2's own structural
disclosures carried in the gate: the benchmark is the intraday arm rather than an always-on
straddle and is conditionally toothless; ~43% of candidate gaps are unobservable; and on
the prior run over half of P&L came from straddles that cash-settled — i.e. from M1's path,
not M2's.

One stamp *is* earned by this run and is recorded here: **`corpus.strike_ladder_is_a_moving_window`**
— the finding in §2. It has no code yet. It should.

## 7. Trial count and family

Family: H1 → {H26 v1 → H26 v2 → M2}, {M1}. M2's attempt is row 7:

| seq | hypothesis | outcome |
|---|---|---|
| 1 | H1 | completed |
| 2 | H26 v1 | error (`TypeError`, exit path) |
| 3 | H26 v1 | error (`KeyError`, 2026-02-03 — **§2**) |
| 4 | H26 v2 | completed (candidate) |
| 5 | H26 v2 | completed (benchmark) |
| 6 | M1 | completed (first run, verdict lost in reporting) |
| **7** | **M2** | **error (`KeyError`, 2025-04-07 — §2)** |
| 8 | M1 | completed (graded) |

**The row is kept.** H26's gate set the precedent and the reasoning is unchanged: deleting
a row from an append-only research log to reach a pre-registered count is the flattering
move even when it is justified, and no result was ever observed from row 7, so nothing was
selected on. It counts in the family and it makes every subsequent verdict harder.

Pre-registered inventory said M2 would grade at N=8. It never graded.

## 8. What was NOT done

- **The record was not amended to make M2 runnable.** Tightening the entry guard until the
  crash stops is available, cheap, and wrong — see §3. It would condition the sample on
  small gaps.
- **The window was not narrowed** to exclude 2025-04-07. Same objection, less disguised.
- **No threshold was moved.** The bars in `gate.toml` are the ones committed in `1921a5b`.
- **The holdout was not touched.**

## 9. What to do next

1. **Establish the strike-ladder rule empirically** — how many strikes the capture carries,
   how the window is centred, and how often an ATM strike from session *t* is absent at
   *t+1*. That frequency, over the whole 1,233-session corpus, is the real measure of how
   much of M2's population is unreachable.
2. **Correct H26's `supersession` diagnosis.** `research/h26/gate.toml` is frozen and must
   not be edited; the correction belongs in a new record that cites it. H26's verdict
   stands — its guard was still the right change for a different reason — but its stated
   cause is wrong, and the wrong cause is now propagating.
3. **Only then decide whether M2 is expressible on this corpus at all.** If the honest
   answer is that a gap-risk model cannot be tested on a spot-tracking strike ladder, that
   is a finding about the data platform, and it is worth more than a deflated Sharpe.
4. **Do not re-run M2 before 1-3.** Every attempt burns a trial and deflates the family.
