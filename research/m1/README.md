# M1 — which record is current

M1 was graded twice against the **same** pre-registered gate (`gate.toml`) over the **same**
window. Both runs are real and both are in the trial log; the second exists because the first
exposed an engine defect.

| record | run | verdict | status |
|---|---|---|---|
| [`DECISION_RERUN.md`](DECISION_RERUN.md) + `decision_rerun.json` | after the wedged-book fix (issue #26) | **FAILS_THRESHOLD** — DSR 0.3423, max drawdown 12.03%, 1.82% stale marks | **STANDING — read this one** |
| [`DECISION.md`](DECISION.md) + `decision.json` | before the fix; book wedged from 2025-04-24 | NOT_EVALUABLE — 64.7% stale marks, gate refused to grade | **SUPERSEDED** — retained as the evidence for #26 |

The superseded record is kept unedited (a banner was prepended, nothing below it altered)
because it is why the fix exists and why the family's trial count went 8 -> 9. Deleting it
would hide that the correction was needed.

`gate.toml` and `validation.toml` are the frozen pre-registration and are shared by both runs
— registered before either result existed, never rewritten between them.

**Preserved commits** (both records cite SHAs; the PRs were squash-merged, so these tags are
what keep the citations resolvable): `prereg/m1-m2-1921a5b` — the pre-registration as
registered; `record/m1-wedged-bcb8bd9` — the superseded record as originally written.
