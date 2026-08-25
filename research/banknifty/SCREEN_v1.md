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
binding case is the 35-lot epoch at the in-sample spot peak — roughly 21.7 lakh
of exposure per lot — which at 50 lakh still buys 2.3 lots.

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
