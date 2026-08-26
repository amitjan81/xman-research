# BANKNIFTY stage-two gate — BLOCKED by an engine defect

**Outcome: no verdict.** Not a failure, not a pass, not NOT_EVALUABLE. The stage-two gate
could not be run at all, on any of the four pre-registered ranks, because two guards in
`xman_research.validation.gate` contradict each other and the BANKNIFTY hypothesis record
sits exactly in the gap between them.

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

The metric it names is nonetheless real and is on the sheet: the screen's `alpha` is exactly
"candidate annualised Sharpe minus benchmark annualised Sharpe". `MEASURED_METRICS` carries a
`sharpe_difference`, but the sheet's own `alpha_definition` says that is the repository's
volatility-matched comparison, which scales the benchmark before differencing. The two are
different numbers and substituting one for the other in a gate file would be a silent change
to a pre-registered criterion.

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

A true annualised Sharpe of 1.5 — about what the best instance on this sheet shows — clears
the pre-registered 0.90 bar in 7.5% of draws. Even a true 3.0 clears it barely more than half
the time. **Fixing the defect would not have produced a pass.** It would have produced four
`FAILS_THRESHOLD` verdicts whose informative content is "a 102-instance screen over 352
observations cannot separate any one instance from its own breadth", which is what the
pre-registration in `research/banknifty/gate_v1.toml` said in advance it would mean.

The blockage therefore costs one thing and not another: it costs the four verdicts on the
record, and it does not cost a finding.
