# Pair-trading research base — India, 1–5 day horizon (2026-08-31)

Deep-research report backing `FRAMEWORK.md`. Evidence policy: Parts A and C cite only
peer-reviewed journals and widely-cited working papers; Part B is market mechanics from
exchange/broker documentation, labelled as such. Citation counts are OpenAlex
(`cited_by_count`; runs lower than Google Scholar, which was unfetchable); counts not
retrieved are marked rather than estimated.

## A. Models, ranked for the India context

Ranking criterion: estimation risk per unit of available data (a ~208-name universe with
1–5 day holds gives few independent observations per parameter), not headline Sharpe.

1. **Distance method** — Gatev, Goetzmann & Rouwenhorst 2006, *RFS* 19(3):797–827
   (OpenAlex 818). Normalise prices, minimise squared deviation over a 12-month formation
   window, trade 2σ divergences. US 1962–2002: up to ~11–12 % annualised excess (sources
   differ on window). Decay: Do & Faff 2010 *FAJ* 66(4) — downward trend, strong in
   turbulence, +22 bps/mo from refinements; Do & Faff 2012 *JFR* 35(2) — after full costs,
   ~30 bps/mo for well-matched within-industry pairs, ~24 bps/mo alpha on large caps.
   Failure: fundamental divergences never reconverge. Verdict: lowest estimation risk;
   re-specify around a short-half-life filter for the 1–5 day horizon.
2. **Cointegration (EG / Johansen)** — framing Vidyamurthy 2004 (Wiley); horse race Rad,
   Low & Faff 2016 *QF* 16(10): 1962–2014 with time-varying costs — monthly net 38 bps
   distance, 33 cointegration, 5 copula. Needs ≥ ~250 obs per window, monthly re-fit; low
   test power at short windows; multiple-testing across ~21.5k pairs. Verdict: second, kept
   for the explicit hedge ratio the lot-quantised SSF legs require.
3. **OU spread / half-life** — Elliott, van der Hoek & Malcolm 2005 *QF* 5(3). Not a
   competing model: the layer on top of any selection method; half-life = ln2/θ is the
   horizon gate.
4. **Kalman dynamic hedge** — no standalone cost-aware evidence gathered; an upgrade to the
   ratio inside 1–2, not a model. Failure: process noise Q fitted; too high chases the
   divergence.
5. **Copula** — Rad, Low & Faff 2016: 43 bps gross / 5 net, worst by far; opportunity
   frequency stays stable post-2009 (the one redeeming finding). Liew & Wu 2013 (73).
   Rejected for a limited-capital first build.
6. **PCA/clustering selection** — Avellaneda & Lee 2010 *QF* 10(7):761–782 (342): factor
   residuals as OU, Sharpe 1.44 after costs 1997–2007, 0.90 for 2003–07. Sarmento & Horta
   2020 *ESWA* 158: PCA→OPTICS→EG + Hurst<0.5 + half-life; reported Sharpe 3.79 — not
   comparable to A&L (different universe/costs). Use for candidate shrinkage.
7. **Hurst / variance-ratio** — screens beside the half-life gate, not strategies.

Top 3: distance (re-specified, half-life-gated) → rolling EG for the hedge ratio →
PCA/clustering as pre-filter. Not ranked: copula, DL forecasting, stochastic control.

## B. India constraints (mechanics)

| Constraint | Detail |
|---|---|
| Shorting | Naked shorting prohibited; institutions deliver gross; FPIs short only via SLB. SLB thin: first-Tuesday expiries, 100 % + VAR/ELM borrower margin. ⇒ short leg = single-stock future |
| Universe | ~208 F&O stocks (6 added 2026-04-01); list reviewed periodically |
| Lots | Jan-2026 series: Nifty 65, BankNifty 30, Next50 25, Sensex 20, FinNifty 60; stock lots per circular |
| Expiries | NSE Tuesday (monthly last Tuesday), BSE Thursday, since 2025-09-01 |
| STT | 0.05 % futures sell-side (hiked from 0.02 % on 2026-04-01 — the level verified on a broker sheet, the prior from snippets) |
| Other costs | NSE txn 0.00183 %; stamp 0.002 % buy; SEBI ₹10/cr; GST 18 % on (brokerage+SEBI+txn); brokerage min(0.03 %, ₹20)/order |
| Margin | Price scan 14.2 % + ELM 3.5 % = 17.7 %/leg; no cross-underlying offset ⇒ 35.4 % of N per pair at the base scan range, up to ~44 % on volatile names with higher scan ranges (~40–50 % with MTM buffer); delivery margins escalate over the last ~4 sessions before physical-settlement expiry |
| Sessions | Derivatives 09:15–15:40 (since 2026-08-03); cash CAS stocks stop 15:15, auction to 15:35; F&O intraday auto-square-off 15:12 (broker) |
| Circuits | F&O stocks: dynamic ±10 %; cash bands 2/5/10/20 %; CAS stock-futures band ±3 % of fresh reference |
| Tax | F&O = non-speculative business income, slab rates, STT deductible, 8-yr carry-forward |

Cost arithmetic (denominator N = one-leg notional): STT 10.0 bps (two sell events) + txn
0.73 + brokerage 0.80 (at N=₹10L) + stamp 0.40 + SEBI 0.04 + GST 0.28 ≈ **12.3 bps hard**;
**17–27 bps all-in** with slippage. STT ≈ 82 % of hard cost; the 2026-04 hike roughly
doubled friction.

Universe candidates: stock–stock SSF pairs (the design); index pairs second-choice
(Nifty–BankNifty = sector beta; Nifty–Sensex = two exchanges, two expiry calendars); ETF
pairs illiquid beyond the largest; ADR/dual-listed untradeable domestically; commodity-
linked pairs are macro bets.

## C. India evidence (thin — justifies building a backtest, not skipping one)

1. Aggarwal & Aggarwal 2021, *Asia-Pacific Financial Markets* — pairs on **Indian stock
   futures**, up to 34 % annualised including costs, Fama–French-adjusted. Full text
   unread (paywall); pre-dates the STT hike. Upper bound, not a forecast. Quality: high.
2. Mahajan & Chandra 2019, arXiv:1907.08397 — MCX commodities, Johansen: 12/136 pairs
   cointegrate (~9 % hit-rate prior); Sharpe >1.4 in backtest, no costs. Quality: medium.
3. Sen et al. 2022, arXiv:2211.07080 — five NSE sectors, one out-of-sample year, no costs;
   demonstrates sector dispersion, not profitability. Quality: medium-low.

Practitioner colour (NOT evidence): QuantInsti EPAT conventions (ADF selection, z-entry
1.5–2, exit 0); typical parameters match Sarmento & Horta — cite the paper instead. Cat-III
AIF is the hedge-fund wrapper; AlphaGrep/Estee run systematic strategies (aggregator
sources). `nseindiagov.com` is not NSE; several SEO farms excluded.

## Synthesis for a 1–5 day system

The two admission inequalities (σ_spread ≥ 50–60 bps of N; half-life ≈1–5 days) are the
spec; the model ranking is secondary. Signals computed on closes cannot be executed at
those closes since 2026-08-03 (auction close, discovered 15:30–15:35, continuous cash stops
15:15, futures run to 15:40) — pre-register either a pre-15:15 snapshot-and-fire or
next-open execution. Backtests spanning 2026-08-03 carry a structural break in the close
series; spanning 2026-04-01 carry a cost break. Capital ~40–50 % of N per pair ⇒ tens of
pairs; roll around NSE last-Tuesday.

Full source URLs: see the PR description (research report of 2026-08-31, 58 tool calls,
OpenAlex for counts; Semantic Scholar rate-limited; Google Scholar unfetchable; NSE/BSE/SEBI
not fetched by policy).
