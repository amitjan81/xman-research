# BANKNIFTY stage-1 screen, v1 — specified, not run

`screen_v1.toml` is written, parses, and expands to the grid described below. It
was **not launched**: every shipped strategy template refuses to build for
BANKNIFTY, so the screen cannot produce a single instance. The refusal is
recorded verbatim here and nothing about it has been softened.

## The refusal

Reproduced by expanding the spec's first candidate block through the real loader
and the real expansion path:

```
uv run python -c "
from pathlib import Path
from xman_research.alpha.spec import load_screen_spec
from xman_research.alpha.templates import default_registry
s = load_screen_spec(Path('research/banknifty/screen_v1.toml'))
s.candidates[0].expand(default_registry())"
```

```
File "src/xman_research/alpha/screen.py", line 161, in expand
    template.build(params, self.underlying, feature_series={})
File "src/xman_research/alpha/templates.py", line 840, in build
    raise ValueError(
ValueError: template short_atm_straddle_hold_n is valid for ['NIFTY'] and was
asked to build for BANKNIFTY; its admission evidence was measured on the former
and says nothing about the latter
```

### What is refusing, and why it is right

`StrategyTemplate.build` (`templates.py:838-843`) checks the requested product
against the template's declared `products` and refuses a product not in it.
`_template_for` (`templates.py:1332`, `1348`) declares `products=("NIFTY",)` for
every shipped template — all three unconditional shapes and all fifteen
conditional crossings. The guard fires before any parameter is resolved, so the
refusal is total: not one of the 103 instances in this spec can be built.

The message states the rule it is enforcing: a template's admission evidence was
measured on NIFTY and says nothing about BANKNIFTY. That is a claim about
evidence, not a configuration detail, and it is the correct thing for the engine
to refuse. Adding `"BANKNIFTY"` to the `products` tuple would assert an evidence
base that does not exist, and would do it silently — every downstream sheet,
library entry and admission record would then carry a BANKNIFTY instance whose
provenance points at NIFTY measurement. **That change is not made here.** It is a
design decision for the owner, and it is the specific thing this run was told not
to soften.

There is no legitimate path around it in the current code: `screen`'s CLI
(`cli.py:164-167`) takes `--spec`, `--out` and `--corpus-root` and offers no
product override, and `TemplateRegistry.for_product` is never called on the
screen path (the guard in `build` is the only product check, and it is
unconditional).

### This is the first wall, not provably the only one

Because the guard fires in `expand`, everything downstream of it is untested for
BANKNIFTY. `_feature_pass(underlying)` never ran, so whether
`atm_iv_minus_rv20`, `ema20_z_abs`, `overnight_gap_sigmas` and
`sessions_to_nearest_expiry` resolve on this corpus is **unknown**, as is whether
the strike ladder satisfies the strangle and condor rules at BANKNIFTY's rung
spacing. Nothing here supports reading the refusal as "one line and it runs".
Clearing the product question is what makes the next wall observable, not what
guarantees there isn't one.

### The decision this needs

Three shapes, and the choice between them is the owner's:

1. **Widen `products` on the shipped templates.** One line, and it asserts that
   NIFTY admission evidence covers BANKNIFTY — precisely what the guard exists to
   prevent.
2. **Register a BANKNIFTY template family with its own evidence base.** New code
   and its own provenance; nothing is asserted that was not measured.
3. **Rescope the guard.** It fires in `build()`, which a stage-1 screen reaches
   while still pre-admission — and screening is the activity that *generates*
   product evidence. Gating exploration on admission evidence may itself be the
   defect, in which case the fix is to move the check to the admission path and
   leave screening free.

Option 3 would be a defect fix rather than a widening, and under the Issue
Response Protocol any of the three starts with a postmortem and the owner's
approval before code is written.

### What this blocks

Steps 3 and 4 of the run: no smoke, no launch, no sheet, no PID, no timing. No
trial was appended to any log — the refusal happens in `expand`, which runs
before the first trial is written, so the trial log at
`research/banknifty/screen_v1.db` does not exist and the family's trial count is
untouched. Nothing needs unwinding.

## The spec that is ready

Verified by expanding every block through `CandidateSpec.expand(default_registry())`
with the underlying relabelled to NIFTY — a count of the cartesian product only,
which is all the product guard prevents from being read directly.

| | Instances |
|---|---|
| Benchmark — `short_atm_straddle_hold_n`, `hold_sessions = 3` | 1 |
| Unconditional: straddle 3, strangle 6, iron condor 3 | 12 |
| `iv_rv` x 3 structures | 18 |
| `ema_atr_band` x 3 structures | 18 |
| `post_gap` x 3 structures | 18 |
| `expiry_distance` x 3 structures x 2 bands | 18 |
| `day_of_week` x 3 structures | 18 |
| **Candidate total** | **102** |

Window 2024-10-01 .. 2026-05-29, decision minute 14:50, underlying BANKNIFTY.
Entirely in-sample: the sealed BANKNIFTY holdout starts 2026-06-01 and no block
reaches it.

### Decisions worth naming

**Notional is 5,000,000 in every block, benchmark included.** `load_screen_spec`
reads `grid` per row with no top-level default, so a block omitting
`target_notional` sizes at the template default of 1,500,000 and silently stops
being risk-comparable. The value is 50 lakh rather than the 15 lakh a NIFTY
screen uses because BANKNIFTY's lot quantises a 15-lakh target to one lot, and at
one lot every continuous sizing multiplier collapses to the same position. The
binding case is the largest lot size `BANKNIFTY_LOT_SIZE_EPOCHS` records, 35. As
arithmetic, a target of N buys at least two lots while spot is below N / 70: at
50 lakh that threshold is about 71,400, and at 15 lakh it is about 21,400 — an
order of magnitude under the range BANKNIFTY trades in across this window, so a
15-lakh target is pinned at one lot or none throughout. No spot series was read
to reach this; the two thresholds are the whole argument.

**Conditional strangles pin `atr_multiple = 1.0`.** Crossing k in {0.5, 1.0}
through every conditional block puts the grid at 132, past the ~110 ceiling. The
claim under test in a conditional block is about the conditioner, and it is
tested against the unconditional strangle, which does carry both k values.

**`expiry_distance` takes two blocks per structure, not two values on one axis.**
The band is a pair of parameters (`_low`, `_high`), so a single block crossing
`low = [1, 6]` with `high = [5, 15]` would also expand the incoherent `[1, 15]`
and the empty `[6, 5]`.

**`day_of_week` is Tuesday (1) and Thursday (3).** The conditioner takes a single
weekday — a `WITHIN` band whose edges are the same value — so a two-day set is
not expressible. Its shipped thesis is that "the NSE index-option cycle is
weekly, so a session's weekday and its position inside the expiry cycle are the
same fact". **That does not hold for BANKNIFTY** after the 2024-11-13 move to a
monthly front contract. The conditioner still runs and is still screenable; the
mechanism it claims is not the mechanism it would be testing here.

**`expiry_distance` `[1, 5]` crossed with `hold_sessions = 5` is kept
deliberately.** Entry demands `hold + 3` calendar days of headroom to expiry
(`_EXPIRY_HEADROOM_DAYS = 3`) while the near band fires only close to expiry, so
these cells may never enter. They are kept because BANKNIFTY's monthly cadence
makes the two constraints far less opposed than NIFTY's weekly one, and whether
they in fact bind is a fact about this corpus worth one logged trial each.

**Gaps.** `gaps_reason` is `xman_research.models.bn_benchmark.GAP_REASON`
reproduced verbatim; its counts are for exactly 2024-10-01..2026-05-29, this
spec's window. `bn_benchmark` does not exist on this branch, so the README's
"import it rather than retyping it" cannot be followed and the text is inlined
instead. Its leading clause names the BN-M1 benchmark, a different run; the
clause is left unedited rather than quietly reworded.

**Trial log.** `research/banknifty/screen_v1.db` — a committed path under this
directory, not a temp file, so the trial count persists across runs for stage-2
deflation. The file itself is untracked: `.gitignore:18` ignores `*.db`
repo-wide. The path is the durable part; the database is local state.

## The guard, rescoped

Option 3 of the three above, approved by the owner on 2026-08-25. **The
specification changed**: evidence scope is a property of an admission, not of a
template.

- `StrategyTemplate` no longer has `products`. A template is a trade *shape* and
  carries no claim about any product; `build(params, underlying)` instantiates it
  for whatever underlying the corpus can supply and refuses only an absent one.
  `TemplateRegistry.for_product` went with the field — it filtered on a claim the
  template no longer makes.
- `AdmissionRecord.underlying` names the product an admission covers, and is part
  of the entry's identity: one shape admitted on NIFTY and on BANKNIFTY is two
  admissions carrying two different sets of numbers. `history`, `current`,
  `status` and `demote` take the product as a selector, and an ambiguous selector
  is refused as it already was for parameter points.
- `EvidenceCard.underlying` is the product the *evidence* was measured on, read
  from `runs.in_sample.underlying` where the source names it. A decision record
  that does not is silent, not corroborating: the card's provenance says so, and
  the admission's product is then asserted by whoever filed it.
- `TemplateLibrary.admit` refuses on a mismatch between the two
  (`CrossProductEvidenceError`), as does `seed_from_screen`, where the sheet
  always names its product. Every other refusal is unchanged.
- The ranker's skip is now `no_admission_for_product`: a scan of a product a
  template has no ADMITTED record for is a visible skip on the sheet, not a
  silent instantiation of another product's evidence. `product_not_supported` is
  gone with the field it read.

A drift report aggregates the ideas at one (template, parameter point) whatever
product they were proposed on, so `tracking` matches the library on that pair and
demotes without naming a product; the library refuses outright once one point is
admitted on two products, which is the honest answer to a report that cannot say
which of them drifted.
