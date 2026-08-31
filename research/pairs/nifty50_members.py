"""Nifty 50 membership used by the pair-trading screen, with its sector labels.

HONESTY HEADER — read before trusting this list.

- **Source: the authoring model's own knowledge, as-of 2026-08-31.** No index-provider
  file was fetched: this host has no web access and no NSE/NSE-Indices feed, so the list
  is unverifiable from here. It is a *plausible* Nifty 50, not a confirmed one.
- **Known-uncertain entries.** Index reconstitution runs twice a year, and the following
  are the memberships this list is least sure of: `TATAMOTORS` (the scrip master carries
  no EQ row under that symbol — the commercial-vehicle / passenger-vehicle demerger
  leaves two listed lines, `TMCV` (TATA MOTORS LIMITED) and `TMPV` (TATA MOTORS PASS VEH
  LTD); which of them the index holds is not verifiable from this host, so neither is
  substituted in and the name simply drops out of the screen), `INDUSINDBK`,
  `ETERNAL`, `JIOFIN`, `SHRIRAMFIN`, `TRENT` and `BEL` (all recent joiners or
  churn-prone). Names that joined the index after the author's knowledge cutoff are
  missing altogether and there is no way to detect that from this host.
- **Consequence for the screen.** A wrong member list changes the *universe*, therefore
  the candidate count, therefore the multiple-testing denominator. It does not bias any
  individual pair's statistics. Treat the screen as "a screen over these 50 liquid large
  caps", not "a screen over the Nifty 50".
- **Resolution against the scrip master.** `fetch_daily.py` resolves each symbol to an
  NSE / segment `E` / series `EQ` row. Symbols with no such row are dropped and listed
  explicitly in the run output and in the screen document — never silently.

`SECTOR` exists because the pre-filter needs a fallback: with a 50-name universe,
density clustering on PCA residual loadings frequently degenerates (one giant cluster or
mostly noise), and the framework's stated fallback is sector grouping. The labels are
coarse GICS-style buckets chosen so that a same-bucket pair is economically plausible.
"""

from __future__ import annotations

# symbol -> coarse sector bucket (fallback grouping for the pre-filter)
NIFTY50: dict[str, str] = {
    "ADANIENT": "Conglomerate",
    "ADANIPORTS": "Infrastructure",
    "APOLLOHOSP": "Healthcare",
    "ASIANPAINT": "ConsumerDiscretionary",
    "AXISBANK": "Bank",
    "BAJAJ-AUTO": "Auto",
    "BAJFINANCE": "NBFC",
    "BAJAJFINSV": "NBFC",
    "BEL": "CapitalGoods",
    "BHARTIARTL": "Telecom",
    "CIPLA": "Pharma",
    "COALINDIA": "Energy",
    "DRREDDY": "Pharma",
    "EICHERMOT": "Auto",
    "ETERNAL": "Internet",
    "GRASIM": "Materials",
    "HCLTECH": "IT",
    "HDFCBANK": "Bank",
    "HDFCLIFE": "Insurance",
    "HEROMOTOCO": "Auto",
    "HINDALCO": "Metals",
    "HINDUNILVR": "FMCG",
    "ICICIBANK": "Bank",
    "INDUSINDBK": "Bank",
    "INFY": "IT",
    "ITC": "FMCG",
    "JIOFIN": "NBFC",
    "JSWSTEEL": "Metals",
    "KOTAKBANK": "Bank",
    "LT": "CapitalGoods",
    "M&M": "Auto",
    "MARUTI": "Auto",
    "NESTLEIND": "FMCG",
    "NTPC": "Power",
    "ONGC": "Energy",
    "POWERGRID": "Power",
    "RELIANCE": "Energy",
    "SBILIFE": "Insurance",
    "SBIN": "Bank",
    "SHRIRAMFIN": "NBFC",
    "SUNPHARMA": "Pharma",
    "TCS": "IT",
    "TATACONSUM": "FMCG",
    "TATAMOTORS": "Auto",
    "TATASTEEL": "Metals",
    "TECHM": "IT",
    "TITAN": "ConsumerDiscretionary",
    "TRENT": "ConsumerDiscretionary",
    "ULTRACEMCO": "Materials",
    "WIPRO": "IT",
}

SYMBOLS: list[str] = sorted(NIFTY50)
