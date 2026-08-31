# Pair trading — research framework for the Indian market

Owner mandate: non-HFT, 1–5 session holds, limited capital. Evidence policy: model claims
cite peer-reviewed or widely-cited work only; market mechanics cite exchange/broker
documentation, labelled as mechanics. The evidence base behind every claim here is the
2026-08-31 research report (sources listed at the end); citation counts are OpenAlex.

## 0. The two inequalities that define admission

Everything else in this document exists to find pairs that satisfy both, honestly:

1. **Cost coverage.** The short leg must be a single-stock future (naked shorting is
   prohibited and institutions settle gross; SLB is thin — mechanics). A two-leg futures
   round trip costs **≈12.3 bps of one-leg notional N in hard costs (~82 % of it STT at
   0.05 % on each sell), ≈17–27 bps all-in with slippage**. A 2σ-entry/0-exit rule captures
   ≈2σ_spread, so admission requires **σ_spread ≥ 50–60 bps of N** (≥4–5× cost coverage).
2. **Horizon.** The spread's **Ornstein–Uhlenbeck half-life must sit in ≈1–5 trading
   days** (Elliott, van der Hoek & Malcolm 2005, *Quantitative Finance*), or the 1–5 day
   mandate turns winners into timeouts.

Capital is the third constraint, not a gate: SPAN+ELM ≈18 % of N per leg with **no
cross-underlying offset** (mechanics) → **≈40–50 % of N per pair** with an MTM buffer. A
small book runs tens of pairs; prefer fewer, higher-σ pairs over breadth.

## 1. Model choices (ranked by estimation risk per unit of data, from the evidence)

| Layer | Choice | Why (evidence) |
|---|---|---|
| Trading rule | **Distance method**, re-specified for short horizon | Zero estimated selection parameters; only method with net-of-cost survival through 2009 (Do & Faff 2012, *JFR*: ~30 bps/mo; Rad, Low & Faff 2016, *QF*: 38 bps/mo net vs 33 cointegration, 5 copula) |
| Hedge ratio | **Rolling Engle–Granger** (monthly re-fit); Kalman as an upgrade to evaluate, not a default | The SSF legs are lot-quantised, so an explicit ratio is operationally required; Kalman has no cost-aware evidence of its own |
| Pre-selection | **PCA factor residuals + clustering** within sectors | Avellaneda & Lee 2010 (*QF*, 342 cites, Sharpe 1.44 after costs 1997–2007); attacks the ~21,500-pair multiple-testing problem in a ~208-name universe |
| Gates | ADF on the spread, **Hurst < 0.5**, half-life bounds, ≥1 mean-crossing/month | Sarmento & Horta 2020 (*ESWA*) pipeline; Hurst/variance-ratio as screens, not strategies |
| Rejected | Copula (5 bps/mo net in the horse race), DL spread forecasting (no cost-aware evidence at this scale), ADR/dual-listing pairs (untradeable from a domestic account) | |

India-specific prior: Aggarwal & Aggarwal 2021 (*Asia-Pacific Financial Markets*) reports
pairs on **Indian stock futures** profitable up to 34 % annualised including costs — full
text unread (paywall) and pre-dating the 2026 STT hike, so an upper bound, not a forecast.
Johansen hit rate prior: ~9 % of candidate combinations cointegrate (Mahajan & Chandra 2019,
arXiv, commodities).

## 2. The workflow

**Phase 0 — data (prerequisite, not yet in the corpus).** The corpus holds index options
only. Stock pairs need: single-stock futures minute/EOD bars and cash closes for the ~208
F&O names. Extend the Dhan `capture-chain` pattern: FUTSTK by security id from the scrip
master, nightly, plus a one-time back-capture of as much history as contract listings
allow; EOD continuous series (front-month, roll-adjusted) built with the roll on the NSE
last-Tuesday cadence. Two structural breaks any history must stamp: the 2026-04-01 STT
change (cost model is date-effective — `costs.py` pattern) and the 2026-08-03 CAS change
(closing prices before/after are different statistical objects; never mix them in one
formation window without a flag).

**Phase 1 — universe and pre-filter (monthly).**
F&O list (~208) → drop illiquid futures (volume/OI floor, spread proxy) → PCA on daily
returns (≤15 components) → cluster residuals (DBSCAN/OPTICS) within and across sectors →
candidate pairs = same-cluster combinations only. Record the candidate count — it is the
denominator every later "significance" claim must be deflated by (trial-log family, as the
alpha framework already enforces).

**Phase 2 — pair admission (monthly, on the formation window).**
Per candidate: normalised-price distance rank; EG hedge ratio β and ADF p on the spread;
Hurst; OU fit → half-life and σ_spread; mean-crossings; **the two inequalities of §0**;
lot-quantisation error of β at the intended N (reject if the nearest-lot portfolio distorts
β by more than ~10 %); margin cost. Survivors become **CANDIDATE pair templates** in the
alpha framework's library (`template = pair(A,B,β,params)`, underlying = the pair), with
the ScreenSheet as evidence — the existing screen → gate → admit machinery applies
unchanged, including the sealed holdout and DSR deflation by the family's trial count.

**Phase 3 — trading rule (daily, per admitted pair).**
Signal at a **pre-15:10 snapshot**; orders in futures **before 15:15** (after that the cash
legs are in auction and the futures reference degrades) or at next open, chosen once and
pre-registered — never "the close", which is discovered at 15:30–15:35 and cannot be traded
(mechanics). Entry |z| ≥ 2, exit z = 0, hard stop |z| ≥ 3, **time stop = 2× half-life**
(caps the hold inside the mandate), structural-break exit if the rolling ADF p degrades past
a pre-set bound. Roll policy: positions opened within 2 sessions of the NSE last-Tuesday
expiry open in the next month; open positions roll with the calendar (partial ELM relief on
the far leg — mechanics).

**Phase 4 — evaluation (the platform's existing discipline).**
Every backtest run is a trial in the family log; formation/trading windows walk forward;
the last ~3 months stay sealed as holdout; stage-2 gate on the pre-registered thresholds;
paper-trade ledger (the tracking/demotion machinery) before any capital. The nightly ranker
surfaces admitted pairs' signals on the research panel like any other template.

## 3. What phase 1 can start on today

Index pairs from data already captured (NIFTY/BANKNIFTY via options-implied series, SENSEX
with its BSE Thursday calendar) are **explicitly second-choice**: Nifty–BankNifty is a
sector-beta bet, and Nifty–Sensex straddles two exchanges and two expiry calendars — a
structural roll mismatch. They are useful only to exercise the pipeline end-to-end while
Phase 0 capture accumulates stock-futures history. The decision to spend capital waits for
stock pairs.

## 4. Risks the design carries knowingly

Distance-method profitability decays secularly (Do & Faff 2010) and concentrates in
turbulence; cointegration can break without warning (low test power at short windows);
the India evidence base is thin (one strong paywalled study, two preprints) — it justifies
building the backtest, not skipping it; the STT hike roughly doubled friction, so published
profitability from any pre-2026 sample overstates today's; and lot quantisation puts a floor
on N per pair that concentrates the book.

## Sources

Gatev, Goetzmann & Rouwenhorst 2006 *RFS* (818 cites); Do & Faff 2010 *FAJ*, 2012 *JFR*;
Rad, Low & Faff 2016 *QF*; Krauss 2017 *J. Econ. Surveys*; Elliott, van der Hoek & Malcolm
2005 *QF*; Avellaneda & Lee 2010 *QF* (342); Sarmento & Horta 2020 *ESWA*; Liew & Wu 2013
(73); Vidyamurthy 2004 (Wiley); Aggarwal & Aggarwal 2021 *APFM*; Mahajan & Chandra 2019
arXiv:1907.08397; Sen et al. 2022 arXiv:2211.07080. Mechanics: Zerodha charge sheet and
support pages, Tradejini/Business Standard (session times), Ventura/Stocko (lots, F&O list),
5paisa (expiry days), INDmoney (SPAN/ELM), ClearTax (tax), S&R Law/Lexology (shorting/SLB).
Full URLs in the research report attached to the PR.
