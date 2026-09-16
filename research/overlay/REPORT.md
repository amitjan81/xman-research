# Backtest — pledge-funded index option overlay (requirements v1.0, sections 3–4)

| Field | Value |
|---|---|
| Question | What return would the document's Nifty weekly iron-condor overlay have produced on ₹1 crore of Portfolio Capital? |
| Underlyings asked for | NIFTY and SENSEX |
| Underlyings answered | **NIFTY only.** SENSEX is not evaluable on the corpus we hold — [§6](#6-sensex-not-evaluable). |
| Data | Dhan 1-minute option chains, `/home/qa/runtime/data/backtest/datasets/dhan/NIFTY`, 1,250 sessions, 2021-06-01 → 2026-09-15 |
| Window run | 2021-09-20 → 2026-09-15 (starts after the corpus's 45-day 2021 capture hole) |
| Costs | The platform's dated statutory stack: STT, exchange transaction charge, SEBI turnover fee, stamp duty, GST, per-order brokerage, plus exercise STT where an option settles |
| Report status | In-sample description of what the rules would have done. No out-of-sample claim is made and no holdout was spent. |

<!-- RESULTS -->

---

## 5. What the corpus can and cannot answer

Everything in this section is produced by `research/overlay/coverage.py` and stored in
`research/overlay/results/coverage_NIFTY.json`.

**The capture is a band around spot, not a chain.** Each session carries the nearest weekly
expiry only, about 21–29 strikes, roughly ±2.3% of spot. That is ample for the intraday
strategies this corpus was built for and tight for this one, which needs a 0.12-delta strike
(1.5–2% out of the money at 5–6 days) *and* a 350-point wing beyond it (another ~1.5%).

| Fact | NIFTY |
|---|---|
| Sessions captured | 1,250 (2021-06-01 → 2026-09-15) |
| Trading days missing inside that range | 56 |
| Entry windows (nearest expiry 5 or 6 days out) | 295 |
| …with **both** 0.12-delta shorts inside the captured band at 10:00 | 198 (67%) |
| …with 300–400pt wings on both sides inside the band | **0** |
| …with at least 100pt of room beyond both shorts | 97 |
| Median room beyond the short strike | 150pt call side, 100pt put side |

Two consequences, and they shape every number in this report:

1. **The specified 350-point wing is never observable.** Not rarely — never, in 295 entry
   windows. Arm A prices it with the model described in `xman_research.overlay.greeks`,
   whose error was measured by holdout before it was used: median ₹1.42 per unit against a
   median true price of ₹14.35, biased ₹1.48 **low**. A cheap long wing flatters the entry
   credit and depresses the exit proceeds, so the two ends partly cancel.
2. **The short strikes are observable about two-thirds of the time**, and the third that is
   not is not random: the 0.12-delta strike leaves the band precisely when implied
   volatility is high, because that is when it sits further out. The weeks this study can
   measure are therefore tilted towards calmer ones. The direction of the resulting bias is
   not obvious — calm weeks pay less premium *and* lose less — but its existence is a fact
   about the sample, not a caveat about the method.

**A five-session hold needs prices for strikes that have since left the band.** The captured
band follows spot, so a wing bought on Monday can be outside the band by Wednesday — and not
merely unpriced: the session's instrument master does not list it either. A run without the
modelled extension cannot close its own positions. That was measured, not assumed: the first
fully observed five-year attempt failed on 2022-11-02 with an exit leg unlisted, and the
position ran to cash settlement. Both arms therefore read modelled prices *after* entry.
What "observed" honestly means for this strategy is **arm B**: every price the entry decision
rested on was a real print.

---

## 6. SENSEX: not evaluable

`research/overlay/results/coverage_SENSEX.json`.

| Fact | SENSEX |
|---|---|
| Sessions captured | 32 (2026-07-13 → 2026-08-27) |
| Trading days missing inside that range | 2 |
| Entry windows at 5–6 days to expiry | **6** |
| …with both 0.12-delta shorts inside the captured band | **0** |
| Smallest \|delta\| available at those windows (median) | 0.19 call side, 0.24 put side |

Six entry windows is not a sample, and in none of them does the captured band even reach the
0.14 delta the requirement's band tops out at — the *short* strike is unattainable, never
mind the wing. Running the strategy on SENSEX would not produce a weak result; it would
produce a different strategy's result on six observations.

What would unblock it: a Dhan backfill of SENSEX weeklies over a multi-year window with a
wider strike band (the present capture's band is the binding constraint as much as its
length). Whether Dhan serves expired BSE option chains that far back is not established
here; it is the first thing to check before committing to the work.

---

## 7. What is implemented, substituted and absent

| Requirement | Status |
|---|---|
| ST-3 entry window (5–6 DTE, 09:20–14:30) | Implemented. Driven off days-to-expiry read from the contract, not off the weekday — the corpus spans the Thursday→Tuesday expiry change. |
| ST-4 exit before expiry day | Implemented, and attempted from 14:00 rather than only at 15:15. Misses are counted, not absorbed. |
| ST-5–ST-7 structure | Implemented. Arm A uses the specified 350pt wing; arm B uses the widest wing that printed, per side. |
| ST-8 minimum credit | Implemented; the default is the study's main filter finding — [§4](#4-sensitivities). |
| ST-10 volatility filter | **Substituted.** No India VIX series exists in the corpus. The IV-percentile limb is evaluated against this corpus's own weekly at-the-money implied volatility over a trailing 252 sessions; the VIX-floor limb is recorded as inapplicable. |
| ST-11 VRP filter, ST-12 trend, ST-13 gap | Implemented from the corpus's own spot series. |
| ST-14–ST-16 event calendar | **Absent by configuration.** The mechanism is implemented and takes a calendar; no event source exists here, so every week is treated as a normal week. The document's fallback (missing calendar → HALF) is not applied: halving five years of positions would be a different strategy rather than a conservative version of this one. |
| ST-17/ST-19 profit target and stop | Implemented, evaluated every 15 minutes. |
| ST-20/ST-21 roll and second touch | Implemented. |
| ST-22 no naked short | Implemented structurally: entry, roll and exit are atomic leg groups, and a book that stops matching the structure is unwound. |
| ST-24–ST-27 Tail Hedge | **Absent.** A 9%-out-of-the-money *monthly* put exists in no captured session. Sized separately in [§3](#3-the-tail-hedge-is-not-in-these-numbers). |
| ST-30/ST-31 intraday margin monitoring | **Absent.** Both are driven by broker-reported blocked margin and collateral value, neither of which exists historically. Their effect would be to reduce positions in stressed weeks, so their absence flatters drawdown. |
| ST-32/ST-33 risk budget and drawdown scaling | Implemented, gated on the strategy's own mark-based estimate (pre-cost). |
| CA-2–CA-18 allocation | Implemented. Reproduces the document's section 8 worked example exactly (`tests/test_overlay_sizing.py`). |
| CA-19 stress test | Implemented and not disableable. |
| ST-37–ST-39 order requirements | Partly: leg role, rule ID and atomicity are carried; a per-day client order reference is not modelled. |

---

## 8. Reproducing this

```bash
# the corpus-coverage evidence (§5, §6)
uv run python research/overlay/coverage.py --underlying NIFTY \
    --out research/overlay/results/coverage_NIFTY.json
uv run python research/overlay/coverage.py --underlying SENSEX \
    --out research/overlay/results/coverage_SENSEX.json

# every arm of the study (§1, §4); writes one JSON per arm plus summary.json
uv run python research/overlay/sweep.py --out research/overlay/results

# the tail-hedge sizing (§3)
uv run python research/overlay/hedge_drag.py --out research/overlay/results/hedge_drag.json

# the tables in this document
uv run python research/overlay/report_tables.py --results research/overlay/results
```

Each arm files a trial in the canonical research log
(`/home/qa/runtime/data/research/trial_log.db`) with its parameters, its metrics and the
code version that produced it. Seven arms is seven trials, and the log says so — which is
the only honest way to present a sweep.
