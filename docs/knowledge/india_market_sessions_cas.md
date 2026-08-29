# Indian equity market sessions and the Closing Auction Session (CAS)

Knowledge base for anyone analysing the last hour of trading. Every statement here is a
present-tense constraint on how the market runs; the sources are secondary press and broker
explainers (listed at the end) — none is a primary exchange circular, so treat the exact
minute boundaries as corroborated, not confirmed, until a circular is read.

## 1. Session timetable (effective 2026-08-03)

| Segment | Continuous trading | Close mechanism | After |
|---|---|---|---|
| Cash, **Category I** (stocks with F&O on both NSE and BSE, ≈200 names) | 09:15–**15:15** | **CAS 15:15–15:35** (single-price call auction) | post-close 15:50–16:00 at the CAS close |
| Cash, **Category II** (all other stocks) | 09:15–15:30 | VWAP close (unchanged) | — |
| Equity derivatives, index and stock F&O | 09:15–**15:40** | continuous to the bell; no auction | — |

MIS auto-square-off for CAS stocks moves to 15:26.

### CAS phases

| Window | Phase | What is allowed |
|---|---|---|
| 15:15–15:20 | Reference price | reference = VWAP of trades 15:00–15:15; no order entry |
| 15:20–15:25 | Order entry I | market and limit orders; nothing executes |
| 15:25–15:30 | Order entry II | limit orders only; resting market orders are locked (no modify/cancel); entry closes at a **random moment between 15:28 and 15:30** |
| 15:30–15:35 | Matching | one equilibrium price per stock — the price at which the maximum quantity executes; official close published ≈15:35 |

Rules that bind every order:

- **Price band ±3 % around the reference price**; orders outside are rejected or cancelled.
  The equilibrium may sit anywhere inside the band.
- Matching priority: market-vs-market (time), market-vs-limit, limit-vs-limit (price-time).
- Stop-loss and iceberg orders are cancelled at 15:15; open continuous-session orders carry
  into the auction unless they lie outside the band; unmatched market orders may be cancelled.
- No equilibrium → the reference price is the close.

### What the exchange publishes during 15:20–15:30

Per stock: indicative equilibrium price, indicative match quantity, cumulative buy and sell
quantity, imbalance quantity and side. Per index: an **indicative index value** computed from
constituents' indicative prices. Between 15:15 and 15:35 the index has **no traded value**;
the official close is the index computed on the constituents' CAS closes.

## 2. How derivatives interact with CAS

- Spot is frozen from 15:15 while F&O keeps trading to 15:40. A hedger has only the
  indicative to hedge against; on expiry, moneyness is known only after ≈15:35.
- Stock derivatives settle on the underlying's CAS close (reported as the cross-exchange VWAP
  of NSE and BSE CAS closes). Index derivatives settle on the index computed from constituent
  CAS closes. A position that is OTM at 15:15 can finish ITM at 15:35: the band allows ±3 %.
- The derivatives' 15:30–15:39 bars are its last ten minutes of continuous trading *while
  matching runs*; they are not the cash auction.

## 3. The 2026-08-27 Sensex auction flash crash (first monthly expiry under CAS)

| | |
|---|---|
| Continuous close 15:15 | 77,182.91 |
| Indicative low (15:18–15:23, >2,200 pts down) | 74,983.19 (−2.9 %) |
| Official close | 76,933.59 (−539.35, −0.70 %) |
| Nifty the same session | −0.31 % in its auction; close 24,090.85 — the dislocation was BSE-specific |
| Reported cause | orders in an index-heavy stock reaching the −3 % band; thin BSE auction liquidity plus heavy expiry positioning; Reliance, HDFC Bank, ITC, Bharti swung sharply |
| Derivatives | a Sensex 75,000 PE rose ≈4,800 % during the auction and gave it back by the close |
| Regulator | SEBI chair: no changes to CAS |

## 4. What the vendor feed (Dhan) can and cannot see

- Index minute bars are frozen from 15:25 (identical bars) and the official close is
  stamped into the 15:29 bar; the indicative path is never published as OHLC.
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
  and the indicative index during 15:15–15:35 — on 27 Aug the options market implied a far
  smaller move than the indicative and was right.
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
