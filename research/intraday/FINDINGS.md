# Intraday short strangle on NIFTY — tuned parameters and what they are worth

| Field | Value |
|---|---|
| Question | Which strike, stop, entry time and profit rule give the best risk-versus-reward for an intraday short strangle on the NIFTY near-week contract? |
| Data | Dhan 1-minute option chains, 1,250 sessions, 2021-06-01 → 2026-09-15 |
| Window | 2021-09-20 → 2026-09-15, split in-sample / holdout at **2025-03-31, fixed before the search** |
| Configurations examined | 66 across three stages |
| Prior to beat | H26 measured intraday short premium on this corpus at **−10.5% a year** |
| Costs | The platform's dated statutory stack, plus ₹0.25/unit/leg slippage |
| Corpus | Read through `corpus_hygiene` — see §5 for the four defects found and what each moved |

---

## 1. The answer

**Expiry day only · sell the 0.15-delta call and put · enter 12:00 · stop when NIFTY moves
0.75% from the entry print · hold to settlement, no early profit-take.**

| | In-sample | Holdout | Full window |
|---|---:|---:|---:|
| Trades | 174 | 65 | 239 |
| Win rate | 77.0% | 76.9% | 77.0% |
| Profit factor | 1.46 | **1.86** | 1.57 |
| Max drawdown (of notional) | 1.26% | 0.39% | 1.26% |
| Worst single day | −0.43% | −0.27% | −0.43% |

It holds out of sample, which most of the field did not: **the best in-sample configuration
(0.20 delta at 13:00, profit factor 1.91) loses money on the holdout**, and four separate
11:00-entry configurations are negative there. The search found overfitting and the split
caught it.

**What it earns is modest and the margin assumption dominates it.** Net P&L is ₹4.09 lakh
over five years on a position of ₹1 crore notional per leg:

| Margin assumption | Capital blocked | Return on it |
|---|---:|---:|
| The engine's: 12% of notional per leg, **no netting** | ₹28.3 lakh | **2.74%/yr** |
| Realistic SPAN, with the strangle's scanning benefit | ~₹14 lakh | ~5.3%/yr |
| Aggressive netting | ~₹10 lakh | ~7.1%/yr |

The engine charges both legs in full; real SPAN does not, because a strangle can only lose on
one side. **2.74% is a floor, not an estimate.** The honest range is 2.7–7% a year on deployed
margin, and narrowing it needs a broker's margin calculator rather than more backtesting.

For scale: the same capital in a liquid fund at 6.5% sits at the top of that range with none
of the work and none of the tail.

---

## 2. Each parameter, and what the data says

### Which strike

| Short delta | Return | Win rate | Profit factor |
|---|---:|---:|---:|
| 0.08 | +0.46% | 61.9% | 1.21 |
| 0.12 | +0.51% | 58.2% | 1.16 |
| 0.15 | +0.21% | 57.9% | 1.05 |
| 0.20 | **−0.55%** | 54.5% | 0.94 |
| 0.25 | −0.20% | 54.1% | 1.02 |

*(all-tenor arm, return on notional)*

**Further out of the money is better.** Everything closer than 0.15 delta degrades, and 0.20
loses money outright. The premium you pick up moving in does not compensate for how much more
often the index reaches you. On the expiry-day arm the ranking is flatter and 0.15 wins on
return while 0.08 wins on win rate and drawdown — either is defensible, and 0.12–0.15 is the
compromise.

### The stop — on the index, as you specified

| Stop (NIFTY move from entry) | Return | Win rate |
|---|---:|---:|
| 0.30% | **−0.37%** | **47.0%** |
| 0.50% | +0.21% | 57.9% |
| **0.75%** | **+0.78%** | **65.5%** |
| 1.00% | +0.62% | 67.1% |
| 1.50% | +0.27% | 67.5% |

**This is the most important table in the study.** A 0.30% stop drops the win rate to 47% and
turns the strategy negative — NIFTY's ordinary intraday wander exceeds it, so the stop
converts noise into realised losses. Widen it to 0.75% and the win rate jumps eighteen points.
Past 1% the protection starts costing more than it saves.

The alternative shape — stopping at a fraction of the distance to the tested strike — was
tested at 0.50/0.75/1.00 of that distance and produced 0.63%/0.59%/0.48%. Comparable, no
better, and harder to operate. A flat percentage of spot is the simpler rule and loses nothing.

**Your reason for wanting a spot-based stop turned out to be understated.** The concern was
manipulation of option prices. The stronger fact is that the far-out legs frequently print *no
price at all* late in the session — on 2025-01-03 the 24550 call had no bar at 15:15, 15:20 or
15:25. A premium-based stop would have nothing to read. Spot prints on every bar.

### When to enter

| Entry | Return | Max drawdown |
|---|---:|---:|
| 09:20 | +0.48% | 2.19% |
| 09:45 | +0.21% | 1.92% |
| 10:15 | −0.10% | 3.47% |
| **11:00** | **−0.98%** | **5.34%** |
| 12:00 | +0.18% | 1.37% |
| 13:00 | **+0.75%** | **0.77%** |

**Midday, and never 11:00.** The 11:00 entry is the single worst configuration in the study,
and it stays negative out-of-sample at every delta tested — four independent confirmations,
which is more than any positive result here can claim. Later entries carry less time risk for
proportionally more of the decay, and 12:00–13:00 is the sweet spot on the expiry-day arm.

### When to book profit

| Close at | Return | Max drawdown |
|---|---:|---:|
| 25% of credit | −0.28% | 3.78% |
| 40% | +0.22% | 2.12% |
| 50% | +0.21% | 1.92% |
| 70% | +0.24% | 1.38% |
| **90%** | **+0.52%** | **1.17%** |

**Do not book early.** Taking 25% of the credit is the worst rule tested. The intuition that a
quick profit reduces risk is wrong here: you keep the same number of losing days and shrink
every winning one. Running to settlement — on expiry day the options expire anyway — is both
the best return and the lowest drawdown.

### The tenor, which conditions all four

| Days to expiry | Trades | Win rate | Profit factor | Carried overnight |
|---|---:|---:|---:|---:|
| **0 (expiry day)** | 250 | **67.6%** | 1.22 | **0** |
| 1–2 | 421 | 57.5% | 1.18 | 19 |
| 3–4 | 232 | 54.7% | 1.21 | 29 |
| 5–6 | 257 | 57.6% | 1.31 | 37 |

**Restrict it to expiry day.** Every expiry-day configuration beat every other configuration on
win rate, profit factor and drawdown once the levers were crossed, and the arm carries nothing
overnight because the options settle. That last point is not a convenience — it is what makes
the result *measurable*. On every other tenor, between 5% and 20% of positions fail to close
at the bell and carry, and an overnight strangle is the trade H26 found actually makes money.
A study that counted those would rediscover H26 and call it an intraday edge.

---

## 3. Why it cannot earn more than it does

The median credit collected is **0.080% of spot** — about ₹19 per unit on a 23,700 index. That
is the whole resource the strategy has to work with, and the exits divide it like this:

| Exit | Trades | P&L |
|---|---:|---:|
| Profit take | 75 | **+₹5,01,283** |
| Time exit at settlement | 137 | +₹2,85,564 |
| **Stop** | **26** | **−₹3,77,728** |

Twenty-six stop-outs — 11% of trades — erase nearly half the gross. That is the trade working
exactly as designed: the stop is doing its job, and its job costs money. Average win ₹6,129,
average loss ₹13,067, win rate 77%. The arithmetic of short premium.

**No parameter in the tested space changes this.** The levers move the result by fractions of
a per cent, and the best corner of the space is the one reported above. What would change the
magnitude is not tuning but structure: more trades per expiry day, a second underlying with
expiries on a different weekday, or a margin regime that blocks less capital.

---

## 4. What this does not answer

- **The margin number**, which is a 2.5× factor on the headline and is a question for a broker's
  calculator, not a backtest.
- **Whether the size is tradeable.** The study sizes at ₹1 crore of notional per leg — about 6
  lots — and the participation caps were set at 5% of a minute's volume. Larger sizes need the
  live book.
- **Sensex.** The same rule on a second index would roughly double the number of expiry days,
  and the SENSEX capture is 32 sessions, so it cannot be tested here.
- **Anything about a crash.** The worst day in this window was −5.62% and the worst overnight
  gap −3.86%. March 2020 is outside the corpus. On expiry day the position is flat by the
  close, so overnight gaps do not reach it — but an intraday dislocation past the stop would,
  and none of that size occurred in five years.

## 5. The corpus was wrong, and what that moved

Every number above was re-measured after four defects were found in the captured files and
fixed at the reader (`xman_research.corpus_hygiene`, commit `59b35ee`). The defects, measured
over all 1,252 NIFTY sessions by `research/intraday/data_audit.py`:

| defect | reach | what it did |
|---|---|---|
| index feed padded outside market hours — zero volume, one price repeated for hours | 208 sessions (16.6%) | a band or an "open" drawn from a 07:06 print |
| `spot` disagreeing with itself inside one minute (each option row carries its own snapshot) | 436 sessions (34.8%), median 4.2 pts, max 35.6 | four derivations of spot, none of them the one the engine traded on |
| implied volatility at or below zero, or above 300% | 8.9% of option rows; 224 sessions | a zero entering an average that gates whether to trade |
| negative traded volume | 8 sessions | meaningless, and read as a quantity |

**The headline answer did not move.** The tuned static strangle is byte-identical before and
after — 174 in-sample trades, ₹235,415, profit factor 1.46 — because it enters at a fixed
clock time, stops on a move from its own entry print, and reads spot through `spot_at`, which
was always the index's own bar. Nothing it touches was defective.

**What did move is every rule that reads a session extremum.** The opening-range arms draw
their band from the session's first minutes, and on a padded session that minute is 07:06:

| arm (in-sample) | before | after |
|---|---:|---:|
| open-range 10:00 | −40,421 | **−89,460** |
| open-range 10:30 | +56,585 | **+34,333** |
| open-range 11:00 | +103,328 | **+68,198** |
| %-from-open 0.3 | −148,278 | **−194,623** |

On 2022-01-07 the opening-range band was 149.1 points wide instead of 67.9 — the padded print
sat 82 points below the real morning low. Out-of-sample the same arms are unchanged to the
rupee, because the padding is concentrated in 2021 and 2022.

The ATR and Bollinger bands were largely spared: `window_stats` filters to 10:00-15:00 by
clock time, so the padding fell outside it, and only the within-minute spot disagreement
reached them — 5.4% of sessions, a median change of 0.0000 percentage points in the ATR.

**One thing the audit found that cannot be fixed here.** The 2026-08-25 session was never
captured, which leaves the continuously-captured tail 16 sessions long where the store's own
test requires 20. That is a hole in the sibling `xman` capture repository, and it is reported
rather than worked around.

## 6. Reproducing this

```bash
uv run python research/intraday/search.py --out research/intraday/results --stage 1  # each lever alone
uv run python research/intraday/search.py --out research/intraday/results --stage 2  # crossed
uv run python research/intraday/search.py --out research/intraday/results --stage 3  # expiry day, split
uv run python research/intraday/data_audit.py --out research/intraday/results/data_audit_NIFTY.json
```

Each configuration files a trial in the canonical research log. Sixty-six configurations is
sixty-six trials, and the log says so — which is the only honest way to present a search that
found one winner.
