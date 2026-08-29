# Indian equity market sessions and the Closing Auction Session (CAS)

Knowledge base for anyone analysing the last hour of trading. Every statement here is a
present-tense constraint on how the market runs; the sources are secondary press and broker
explainers (listed at the end) — none is a primary exchange circular, so treat the exact
minute boundaries as corroborated, not confirmed, until a circular is read.

## 1. Session timetable (effective 2026-08-03)

| Segment | Continuous trading | Close mechanism | After |
|---|---|---|---|
| Cash, **Category I** (stocks in the F&O segment, >200 names; whether the criterion is F&O on *both* exchanges is unverified) | 09:15–**15:15** | **CAS 15:15–15:35** (single-price call auction) | post-close 15:50–16:00 at the CAS close |
| Cash, **Category II** (all other stocks) | 09:15–15:30 | VWAP close | post-close 15:50–16:00 at the closing price (unverified for this category) |
| Equity derivatives, index and stock F&O | 09:15–**15:40** | continuous to the bell; no auction | — |

Some brokers (Zerodha among them) auto-square-off intraday (MIS) positions in CAS stocks at
15:26 — a broker RMS policy, not an exchange rule; check your own broker's cut-off.

### CAS phases

| Window | Phase | What is allowed |
|---|---|---|
| 15:15–15:20 | Reference price | reference = VWAP of trades 15:00–15:15 |
| 15:20–15:25 | Order entry I | market and limit orders; nothing executes |
| 15:25–15:30 | Order entry II | limit orders only; resting market orders are locked (no modify/cancel); entry closes at a **random moment between 15:28 and 15:30** |
| 15:30–15:35 | Matching | one equilibrium price per stock — the price at which the maximum quantity executes; official close published ≈15:35 |

**Unresolved between sources — do not build on either until a circular settles it:** the
two-stage order entry (market+limit, then limit-only with market orders locked) is reported
by one explainer (Zerodha); the other explainers describe a single entry window running from
15:15 to the random close. Bloomberg times the 27 Aug indicative low at **15:18–15:23**, which
is only possible if orders and indicative dissemination exist before 15:20 — so the 15:15–
15:20 window is *not* an order-free period, or the timestamp refers to a different clock.

Rules that bind every order:

- **Price band ±3 % around the reference price**; orders outside are rejected or cancelled.
  The equilibrium may sit anywhere inside the band. The same ±3 % band is reported to apply
  to **stock futures** over 15:15–15:40 (single source; index derivatives unverified).
- Matching priority (unverified — no source states the tie-break): market-vs-market (time),
  market-vs-limit, limit-vs-limit (price-time).
- Stop-loss and iceberg orders are cancelled at 15:15; open continuous-session limit orders
  carry into the auction unless they lie outside the band; unmatched market orders may be
  cancelled. Treatment of pending market orders and broker-side triggers (GTT, baskets) at
  15:15: unverified.
- No equilibrium → the reference price is the close, and that fallback propagates into the
  index and into every derivative settled on it.

### What the exchange publishes during order entry

Per stock: indicative equilibrium price, indicative match quantity, cumulative buy and sell
quantity, imbalance quantity and side. Per index: an **indicative index value** computed from
constituents' indicative prices — BSE demonstrably disseminates one for the Sensex (the 27 Aug
path was reported minute by minute); whether NSE publishes an indicative Nifty is unverified.
Between 15:15 and 15:35 the index has **no traded value**; the official close is the index
computed on the constituents' CAS closes.

## 2. How derivatives interact with CAS

- Spot is frozen from 15:15 while F&O keeps trading to 15:40. A hedger has only the
  indicative to hedge against; on expiry, moneyness is known only after ≈15:35.
- Stock derivatives settle on the underlying's CAS close. How the NSE and BSE CAS closes of
  the same stock are reconciled for a derivative's settlement is **unverified** (a cross-
  exchange VWAP is asserted by some explainers and by no circular read here). Index options'
  final settlement price is the index closing value computed from the constituents' CAS
  closes. A position that is OTM at 15:15 can finish ITM at 15:35: the band allows ±3 %.
- The derivatives' 15:30–15:39 bars are its last ten minutes of continuous trading *while
  matching runs*; they are not the cash auction.

## 3. The 2026-08-27 Sensex auction flash crash (first monthly expiry under CAS)

| | |
|---|---|
| Continuous close 15:15 | 77,182.91 |
| Indicative low (15:18–15:23, >2,200 pts down) | 74,983.19 (−2.9 %) |
| Official close | 76,933.59 (−539.35, −0.70 %) |
| Nifty the same session | closed −0.48 % (−116.90) at 24,090.85; auction-window move ≈ −0.31 % (single press figure, unverified). That the dislocation was BSE-specific is an inference from these two numbers |
| Reported cause | orders in an index-heavy stock reaching the −3 % band; thin BSE auction liquidity plus heavy expiry positioning; Reliance, HDFC Bank, ITC, Bharti swung sharply |
| Derivatives | a Sensex 75,000 PE rose ≈4,800 % during the auction and gave it back by the close |
| Regulator | SEBI chair, 2026-08-27: no changes to CAS. Exchange-level tweaks after that date (band width, dissemination): unverified as of 2026-08-29 |

## 4. What the vendor feed (Dhan) can and cannot see

Measured on the 2026-08-27 session by `research/expiry_cas/` (PR #37) and the read-only
probe whose raw responses it cites; numbers below are those measurements.

- Index minute bars are frozen from 15:25 (identical bars) and the official close is
  stamped into the 15:29 bar (SENSEX, 2026-08-27); the indicative path is never published
  as OHLC.
- Equity minute bars end at 15:14 on every day and interval — the last 15 minutes of
  continuous trading in constituents are absent, as is the auction.
- Daily candles: low equals close (minute-derived, auction-blind); the daily volume does
  include auction trades, so **daily volume minus summed minute volume** is the only auction
  trace (Reliance BSE ≈33 % of day volume on 27 Aug vs a 1–6 % baseline; NSE control 7 %).
- Option bars run to 15:39 but the capture ladder is ATM±10, so deep-OTM strikes that carry
  the auction "lottery" (75,000 with spot 77,200) are outside the corpus.
- No historical tick, quote, or indicative-price endpoint exists; the websocket feeds are
  live-only. Analysing the auction path needs the exchange's CAS dissemination captured live.

## 5. Consequences for strategy work

- A call auction executes at one price. The indicative path is order-book information and
  cannot be traded; "capturing the swing" reduces to (a) auction limit orders at a discount
  that fill only if the equilibrium clears there, (b) the cash–derivatives basis while F&O
  trades to 15:40 against a frozen spot, (c) the divergence between the option-implied index
  and the indicative index during 15:15–15:35 — on 27 Aug the **ATM-implied** index moved
  ~100 pts while the indicative moved 2,200 and the close proved the ATM market right; the
  deep-OTM tail (the 75,000 put) did reprice violently, so the divergence is between the
  liquid core and the wings, not a uniform calm.
- Any report about "the close" must name the segment and window it observed. An absence in a
  window the feed does not cover is not a finding.

## Sources (secondary)

Zerodha Z-Connect, "Everything you need to know about Closing Auction Session (CAS)";
indmoney, "Stock market timings change from 3 August 2026"; sahi.com, "Closing Auction
Session (CAS) explained: 2026 guide"; Bloomberg, "India's Sensex hit by 'flash crash' during
unpopular closing auction" (2026-08-27); Business Standard, "Sensex sees sharpest late-session
fall since closing auction rollout"; FreePressJournal, "Sensex swings over 2,200 points during
BSE closing auction session"; cryptobriefing, "Flash crash sends India's Sensex down 3 % during
closing auction"; NSE, Closing Auction Session product page (not readable from this host).
