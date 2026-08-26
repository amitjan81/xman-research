# BANKNIFTY stage-two gate — BLOCKED by an engine defect

**Outcome: no verdict of any kind was produced** — no pass, no failure, and no NOT_EVALUABLE
decision record, though NOT_EVALUABLE is what the pre-registration expected and what the
feasibility counts say all four runs would have returned (see *What the gate would have said*
below). The stage-two gate could not be run at all, on any of the four pre-registered ranks,
because two guards in `xman_research.validation.gate` contradict each other and the BANKNIFTY
hypothesis record sits exactly in the gap between them.

## The invocations

Every run took this form, from the branch worktree, with only `--rank` and `--out` varying
over 1, 2, 8, 11:

```
uv run python -m xman_research.alpha.cli gate \
  --sheet research/banknifty/screen_v1.json --rank <R> \
  --gate research/banknifty/gate_v1.toml \
  --out research/banknifty/gates/rank<R> \
  --holdout-end 2026-05-31 --seal-override "<reason below>"
```

`--seal-override` was required on every run and its reason was recorded verbatim:

> alpha/holdout.py guards on the single constant 2026-05-01, which is research/h1 NIFTY seal,
> not BANKNIFTY 2026-06-01 seal. The screened window ends 2026-05-29 and a holdout must follow
> it, so every reachable window trips that guard. The window passed, 2026-05-30..2026-05-31, is
> a Saturday and a Sunday: it holds zero NSE sessions and ends before the BANKNIFTY seal. No
> sealed BANKNIFTY bar is opened. A genuine BANKNIFTY holdout from 2026-06-01 is deferred, not
> spent.

**The holdout was not read, and the failure points are the evidence.** The holdout window is
measured only inside `if in_sample_verdict.status is GateStatus.PASSED` (`alpha/gate.py:291`).
Every run died at `:261` or `:264`, before `_measure` at `:272` produced any in-sample series
at all, so no verdict existed to be PASSED and no session in any window — sealed or not — was
opened. `holdout_spent` would have been false in every record had a record been written.

**The trial family is intact.** `research/banknifty/screen_v1.db` held 107 trials before the
first attempt and holds 107 after the eighth. Nothing was appended, nothing was deflated
against, and no verdict was produced and then discarded. This document costs the family
nothing, which is the one thing that matters about a blocked run.

## The contradiction

The stage-one screen registered a criterion on its hypothesis record. `research/banknifty/screen_v1.toml`:

```toml
thresholds = {alpha_to_advance = 0.5}
```

That number is now in the log, on hypothesis `h_a2c7cc855f6f06b2581afb7f2079121d`, and it is
immutable. Two guards then disagree about what a gate for that hypothesis must say.

**Guard 1 — `DecisionGate.check_binding`, `validation/gate.py:568`.** The gate MUST carry it:

```
xman_research.validation.gate.GateBindingError: the hypothesis registered a threshold on
'alpha_to_advance' and research/banknifty/gate_v1.toml [thresholds] does not carry it. The
gate must grade every criterion the hypothesis was registered with.
```

**Guard 2 — `DecisionGate.__post_init__`, `validation/gate.py:426`.** The gate MUST NOT carry it:

```
xman_research.validation.gate.GateVocabularyError: research/banknifty/gate_v1.toml
[thresholds] names alpha_to_advance, which this component does not compute. The metrics it
does are: annualised_adjusted_sharpe, annualised_sharpe, cost_breakeven_multiple,
deflated_sharpe, expected_shortfall, max_drawdown, pbo, probabilistic_sharpe,
risk_matched_increment, sharpe_difference. Caught here rather than at grade time, where it
would have been reported as the run failing to measure something — which blames the run for
the gate's typo.
```

Both are correct in isolation and each states a rule worth keeping. Together they mean:
**any hypothesis registered with `alpha_to_advance` can never be stage-two gated.** There is
no gate file that satisfies both, because the set of criteria the gate must carry and the
set it may carry have empty intersection on this metric.

## Where each attempt died

Eight runs, four ranks, twice.

| Attempt | Gate file said | Died at | Reached a measurement? |
|---|---|---|---|
| 1 (ranks 1, 2, 8, 11) | no `alpha_to_advance` | `gate.py:264` `check_binding` | no |
| 2 (ranks 1, 2, 8, 11) | `alpha_to_advance = { at_least = 0.5 }` | `gate.py:261` gate load, via `validation/gate.py:475` → `426` | no |

The second attempt died EARLIER than the first. `DecisionGate.from_file` validates its own
vocabulary in `__post_init__`, so the gate is refused while it is being read — before
`check_binding` at `alpha/gate.py:264`, and well before `_measure` at `272`. No backtest ran
on any rank in either attempt. That is why the trial count did not move.

## Why the criterion is unusable by construction, not merely unimplemented

`alpha/screen.py` never reads `thresholds`. The spec's `thresholds` table is written straight
onto the hypothesis record at registration and nothing in the screen consumes it, so
`alpha_to_advance` is not a stage-one gate that stage two happens not to reimplement — it is
a criterion that no component has ever computed, at either stage, while being binding on
every future gate for that hypothesis.

**Worse: the criterion has no definition, and the two available readings disagree about the
answer.** Nothing records which quantity `alpha_to_advance` means, and the sheet carries two
candidates that are not the same number:

- The screen's **`alpha`** is the annualised Sharpe of the *difference series* — candidate
  minus benchmark per session, zero-padded on either side's sat-out sessions — which is what
  `provenance.alpha_definition` states.
- `MEASURED_METRICS` carries **`sharpe_difference`**, which is the plain subtraction of the two
  annualised Sharpes. (`risk_matched`, the block it sits in, is the repository's
  volatility-matched comparison; `sharpe_difference` itself is the scale-invariant subtraction.)

For rank 1 those are −0.656 and +0.054 respectively. Against a 0.5 bar the two readings give
opposite verdicts: under `alpha` every one of the 89 measured candidates misses, while under
`sharpe_difference` **ranks 2 and 3 clear it**, at 0.942 and 0.791 — both on 5 round trips.

So this is not a case of a gate file needing to pick the right metric name. There is nothing to
pick *from*: an undefined criterion was registered as binding on every future gate for this
hypothesis, and which way it points depends on a choice nobody recorded. That ambiguity is part
of the defect and not a detail beside it.

## What was NOT done, and why

**The code was not changed.** Under the Issue Response Protocol a defect gets a postmortem
first, presented and approved, before any fix. Beyond the process: the fix is a genuine design
choice with at least three candidate shapes — resolve `alpha_to_advance` against the screen's
`alpha` and add it to `MEASURED_METRICS`; exempt stage-one-only criteria from `check_binding`;
or refuse at screen time to register a criterion the validator cannot compute. They differ in
blast radius and picking one silently inside a research deliverable is worse than reporting
the defect.

**The hypothesis was not re-registered.** Minting a fresh record without the offending
criterion would produce a gate that runs, and it would deflate against a family of one
instead of 107. That trades a blocked run for a flattering one, which is the move this
apparatus exists to prevent.

## What the gate would have said anyway

Recorded because it matters to how this blockage is read: the four runs were underpowered
before the defect stopped them, and the calibration says so at the sample this screen has.
At n=352 observations against N=109 logged trials, graded through this package's own
`deflated_sharpe_ratio`, 40 seeds per point:

| true annualised Sharpe | 0.0 | 0.5 | 1.0 | 1.5 | 2.0 | 2.5 | 3.0 |
|---|---|---|---|---|---|---|---|
| median DSR | 0.025 | 0.082 | 0.206 | 0.406 | 0.634 | 0.822 | 0.933 |
| share ≥ 0.90 | 0.0% | 0.0% | 0.0% | 7.5% | 15.0% | 35.0% | 55.0% |

Reproduce: `uv run python -m xman_research.h1.calibrate_thresholds --case 352:109 --bar 0.90`

These are **true** Sharpes. The sheet's best *observed* Sharpe of 1.59 is the maximum of 89
measured instances and is therefore an overestimate of any underlying true Sharpe, so the row
that applies to it sits at or below the 1.5 line: a 7.5% chance of clearing the bar, three
draws in forty. The calibration is 40 synthetic **iid Gaussian** seeds per point and reads no
corpus. A real short-straddle series has a fat left tail, roughly 43% exposure with zero-padded
sessions, and overlapping hold-3 returns; the deflated Sharpe carries skew and kurtosis terms,
so a Gaussian calibration **understates** the deflation. The table is an optimistic bound.

`N = 109` is the 107 logged trials plus the two rows a run appends for itself before the count
is read.

## What the gate would have said

**NOT_EVALUABLE on all four — not a threshold failure.** `validation/decision.py:552` returns
`NOT_EVALUABLE` ahead of any pass/fail outcome, and the pre-registered
`max_infeasible_fraction = 0.10` is missed by an order of magnitude. `validation/series.py:263`
counts `unsettleable`, `capped_to_zero`, `no_bar`, `no_liquidity` and `group_incomplete` as
infeasible; for the benchmark that is 258 + 71 + 34 + 5 + 18 = 386 against 44 fillable, an
infeasible fraction of **≈0.90** against a 0.10 bar. Rank 1 is ≥0.86.

`research/banknifty/gate_v1.toml` pre-committed to exactly this, before any of it was run:
*"`max_infeasible_fraction = 0.10` is therefore expected to bite, and NOT_EVALUABLE is expected
to be a live outcome for some or all four runs … the finding is 'this corpus cannot evaluate
this family at the pre-registered feasibility bar', and that is a result about the corpus. It
is not a result about the strategy, and it will not be reported as one."*

So the counterfactual is four NOT_EVALUABLE decisions, and what they would have established is
a fact about the corpus — that ten quarantined expiry sessions leave too few settleable cycles
to grade anything — not a fact about the variance premium.

**The sample-size point stands separately and is not conditional on the feasibility bar.** Even
a fully evaluable run of this family would clear 0.90 in 7.5% of draws at a true Sharpe of 1.5.
A 102-instance screen over 352 observations cannot separate any one of its instances from its
own breadth.

The blockage therefore costs one thing and not another: it costs the four decision records, and
it does not cost a finding.
