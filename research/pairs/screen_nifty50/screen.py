"""Pair screen over a daily cash-equity panel — FRAMEWORK.md §2, phases 1 and 2.

RUN ENVIRONMENT — the research worktree's own venv (pandas, numpy, statsmodels,
scikit-learn)::

    uv run python research/pairs/screen_nifty50/screen.py

What it produces is a SCREEN: a set of pairs that satisfy pre-registered admission
inequalities on a formation window. It runs no trading rule, holds no position and
computes no return. Nothing here is evidence that any pair is profitable.

Pipeline
--------
1. Formation window: the latest ``--formation-months`` of sessions, ending
   ``--gap-sessions`` before the as-of date. Every statistic — beta, the spread mean,
   sigma, half-life, ADF — is estimated on that window alone. The gap sessions are used
   only to carry the as-of close into today's z, never to fit.
2. Pre-filter: PCA on standardised daily log returns, then density clustering (OPTICS)
   of the per-name loading vectors. With a 50-name universe density clustering commonly
   degenerates, so a degeneracy test is pre-registered as module constants below and the
   fallback is sector grouping. The branch taken is reported.
3. Candidate pairs are same-group combinations only. That count is the multiple-testing
   denominator ``m``, and every ADF p-value is deflated by it through Benjamini-Hochberg
   at ``--fdr-q``.
4. Per candidate: normalised-price distance, Engle-Granger beta and cointegration p,
   Hurst, OU half-life, spread sigma in bps of one-leg notional, mean crossings, and the
   lot-quantisation error of beta at the intended notional.

Estimation choices that matter, stated so they are not mistaken for defaults:

- **Cointegration p comes from ``statsmodels.tsa.stattools.coint``, not ``adfuller`` on
  the residual.** Beta is estimated, so Dickey-Fuller p-values computed on the residual
  as if it were an observed series are anti-conservative. ``coint`` applies MacKinnon
  critical values for the estimated-regressor case.
- **Regression direction is pre-registered as alphabetical**: A is the alphabetically
  first symbol and log P_A is regressed on log P_B. Running both directions and keeping
  the better p-value would silently double the trial count.
- **The spread is in log space**: e = log P_A - alpha - beta * log P_B. A pair holding
  leg-A notional N is then exposed to N * de, so sigma(e) * 1e4 is sigma_spread in bps
  of leg-A notional, and leg B's notional is beta * N — equal only when beta is 1.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass
from datetime import date
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.cluster import OPTICS
from sklearn.decomposition import PCA
from statsmodels.tsa.stattools import coint

DEFAULT_DATA = Path("/home/qa/runtime/data/research/pairs/nifty50_daily.parquet")
SCRIP_MASTER_DIR = Path("/home/qa/runtime/data/backtest/dhan/scrip_master")

# The framework's two admission inequalities (FRAMEWORK.md §0).
SIGMA_BPS_MIN = 50.0  # sigma_spread as bps of one-leg notional; 50-60 is the stated band
HALF_LIFE_MAX_SESSIONS = 5.0  # the mandate's maximum hold, not a minimum
HURST_MAX = 0.5
LOT_ERROR_MAX = 0.10  # nearest-lot portfolio may distort beta by at most ~10 %
FDR_Q = 0.10

# Hard round-trip cost of a two-leg futures trade, bps of one-leg notional (RESEARCH.md
# §B): STT 10.0 + txn 0.73 + brokerage 0.80 + stamp 0.40 + SEBI 0.04 + GST 0.28.
COST_HARD_BPS = 12.3
COST_ALLIN_BPS = (17.0, 27.0)

# Pre-registered degeneracy test for the density-clustering branch. Declared here, before
# any data is seen, so that falling back to sectors is not a post-hoc choice.
DEGENERACY_MIN_CLUSTERS = 2
DEGENERACY_MAX_LARGEST_SHARE = 0.60
DEGENERACY_MAX_NOISE_SHARE = 0.70

CAS_BREAK = pd.Timestamp("2026-08-03").date()
STT_BREAK = pd.Timestamp("2026-04-01").date()


# ---------------------------------------------------------------- gate arithmetic


def half_life_sessions(spread: np.ndarray) -> float:
    """OU half-life in sessions from an AR(1) fit of the spread's first difference.

    Regresses d_e_t on e_{t-1}: a negative slope b gives mean reversion with speed
    theta = -b and half-life ln(2)/theta. A non-negative slope means the fit found no
    reversion at all, reported as infinity so the horizon gate rejects it.

    This is the continuous-time convention, ln(2)/theta. The exact half-life of the
    fitted discrete AR(1) is ln(2) / -ln(1+b), which is the shorter of the two: near a
    6.5-session estimate the two differ by about 5 %. The continuous form is the
    conservative choice against an upper-bound horizon gate, and a pair whose reported
    half-life sits within a few percent of the bar is inside that convention difference
    rather than cleanly on one side of it.
    """
    e = np.asarray(spread, dtype=float)
    lag, delta = e[:-1], np.diff(e)
    design = np.column_stack([np.ones_like(lag), lag])
    slope = np.linalg.lstsq(design, delta, rcond=None)[0][1]
    if slope >= 0:
        return math.inf
    return math.log(2.0) / -slope


def hurst_exponent(spread: np.ndarray, max_lag: int = 20) -> float:
    """Hurst exponent from the scaling of lagged-difference dispersion.

    H < 0.5 is mean-reverting, 0.5 a random walk. On a ~250-session window the estimator
    is noisy — its standard error is wide enough that the < 0.5 gate rejects some pairs
    for sampling noise alone, which is why the framework calls it belt-and-braces.
    """
    e = np.asarray(spread, dtype=float)
    lags = np.arange(2, min(max_lag, len(e) // 2) + 1)
    taus = np.array([np.std(e[lag:] - e[:-lag]) for lag in lags])
    if np.any(taus <= 0):
        return float("nan")
    return float(np.polyfit(np.log(lags), np.log(taus), 1)[0])


def mean_crossings(spread: np.ndarray) -> int:
    """Number of times the spread crosses its own window mean."""
    centred = np.asarray(spread, dtype=float) - float(np.mean(spread))
    signs = np.sign(centred)
    signs = signs[signs != 0]
    return int(np.sum(signs[1:] != signs[:-1]))


def benjamini_hochberg(pvalues: list[float], q: float = FDR_Q) -> tuple[list[bool], list[float]]:
    """Benjamini-Hochberg step-up at level ``q``.

    Returns the rejection flags in the input order, and each hypothesis's BH bar
    ``q * rank / m`` (the value its p-value is compared against at its own rank). The
    step-up finds the largest rank k with p_(k) <= q*k/m and rejects every hypothesis at
    rank k or below — not a per-hypothesis comparison, which would reject too few in the
    middle of the ranking and too many at the top.
    """
    m = len(pvalues)
    if m == 0:
        return [], []
    order = np.argsort(np.asarray(pvalues, dtype=float), kind="stable")
    bars = np.empty(m, dtype=float)
    cutoff_rank = 0
    for rank, idx in enumerate(order, start=1):
        bars[idx] = q * rank / m
        if pvalues[idx] <= q * rank / m:
            cutoff_rank = rank
    rejected = [False] * m
    for rank, idx in enumerate(order, start=1):
        if rank <= cutoff_rank:
            rejected[idx] = True
    return rejected, bars.tolist()


def lot_quantisation(
    *, price_a: float, price_b: float, beta: float, lot_a: int, lot_b: int, notional: float
) -> dict[str, float]:
    """Nearest-lot futures portfolio for a leg-A notional, and the beta it realises.

    The target portfolio is leg-A notional N and leg-B notional beta * N (the log-space
    hedge: N * d log A = beta * N * d log B). Rounding each leg to whole lots realises
    beta_eff = notional_B / notional_A; the relative distance from beta is the
    quantisation error the framework caps at ~10 %. A leg that rounds to zero lots is
    floored at one, which is itself a large error and shows up as such.

    Lot counts are sized on |beta|: the sign of beta selects which leg is bought and
    which is sold, not how many lots each carries, and it is carried back onto
    beta_eff so the comparison against beta stays like-for-like.
    """
    sign = -1.0 if beta < 0 else 1.0
    lots_a = max(1, round(notional / (price_a * lot_a)))
    lots_b = max(1, round(abs(beta) * notional / (price_b * lot_b)))
    notional_a = lots_a * lot_a * price_a
    notional_b = lots_b * lot_b * price_b
    beta_eff = sign * notional_b / notional_a
    return {
        "lots_a": float(lots_a),
        "lots_b": float(lots_b),
        "notional_a": notional_a,
        "notional_b": notional_b,
        "beta_effective": beta_eff,
        "lot_error": abs(beta_eff - beta) / abs(beta),
    }


def min_notional_for_lot_gate(
    *,
    price_a: float,
    price_b: float,
    beta: float,
    lot_a: int,
    lot_b: int,
    max_notional: float = 50_000_000.0,
) -> float:
    """Smallest leg-A notional at which the nearest-lot portfolio realises beta to 10 %.

    One lot is the finest granularity available, so a small notional cannot express an
    arbitrary beta: the error shrinks as the notional grows and more lots fit into each
    leg. This reports where the gate would first be met, which is the capital fact behind
    a lot-error rejection — the pair is not disqualified, the size is.
    """
    notional = 100_000.0
    while notional <= max_notional:
        if lot_quantisation(
            price_a=price_a, price_b=price_b, beta=beta, lot_a=lot_a, lot_b=lot_b,
            notional=notional,
        )["lot_error"] <= LOT_ERROR_MAX:
            return notional
        notional += 100_000.0
    return math.inf


def round_trip_cost_bps(beta: float) -> dict[str, float]:
    """Two-leg round-trip cost in bps of leg-A notional, scaled for an unequal leg B.

    The framework's 12.3 bps hard cost assumes both legs carry notional N. Every cost
    component is proportional to its own leg's notional, so a leg B carrying beta * N
    scales the total by (1 + |beta|) / 2.

    Pass the **realised** leg ratio, not the fitted one: whole lots are what actually
    trade, and a small fitted beta whose leg B still rounds up to one lot pays for that
    lot in full. Scaling on the fitted beta would understate the cost of exactly the
    low-beta pairs whose quantisation error is largest.

    This is an approximation: the brokerage component is a per-order min(0.03 %, Rs 20)
    and so does not scale strictly linearly.
    """
    scale = (1.0 + abs(beta)) / 2.0
    return {
        "cost_hard_bps": COST_HARD_BPS * scale,
        "cost_allin_low_bps": COST_ALLIN_BPS[0] * scale,
        "cost_allin_high_bps": COST_ALLIN_BPS[1] * scale,
    }


# ---------------------------------------------------------------- pipeline


@dataclass
class PairResult:
    symbol_a: str
    symbol_b: str
    group: str
    distance: float
    beta: float
    alpha: float
    coint_p: float
    bh_bar: float
    bh_pass: bool
    hurst: float
    half_life: float
    sigma_bps: float
    crossings: int
    lots_a: float
    lots_b: float
    notional_a: float
    notional_b: float
    beta_effective: float
    lot_error: float
    lot_size_known: bool
    min_notional_for_lot_gate: float
    cost_hard_bps: float
    cost_allin_low_bps: float
    cost_allin_high_bps: float
    cost_coverage: float
    z_today: float
    gate_sigma: bool
    gate_half_life: bool
    gate_hurst: bool
    gate_lot: bool
    admitted: bool
    mwpl_ban_screen: str = "unchecked"
    event_screen: str = "unchecked"


def load_panel(path: Path) -> tuple[pd.DataFrame, list[str]]:
    """Close panel of names present on every session, and the names that were dropped.

    A name missing any session in the fetched span is dropped entirely rather than
    interpolated, so every pair is fitted on genuinely aligned observations. That is
    stricter than the fetch's own minimum-row rule, so the dropped names are returned
    and reported: a shrinking universe must be visible, not inferred from a count.
    """
    frame = pd.read_parquet(path)
    frame["date"] = pd.to_datetime(frame["date"]).dt.date
    closes = frame.pivot(index="date", columns="symbol", values="close").sort_index()
    complete = closes.dropna(axis=1, how="any")
    dropped = sorted(set(closes.columns) - set(complete.columns))
    return complete.dropna(axis=0, how="any"), dropped


def futures_lot_sizes() -> dict[str, int]:
    """Underlying -> F&O lot size, from the newest scrip master's FUTSTK rows."""
    files = sorted(SCRIP_MASTER_DIR.glob("api-scrip-master-*.csv"))
    master = pd.read_csv(files[-1], low_memory=False)
    fut = master[
        (master["SEM_EXM_EXCH_ID"] == "NSE") & (master["SEM_INSTRUMENT_NAME"] == "FUTSTK")
    ].copy()
    # The contract symbol is <UNDERLYING>-<MonYYYY>-FUT, and underlyings may themselves
    # contain a hyphen (BAJAJ-AUTO), so only the expiry suffix is stripped.
    fut["underlying"] = (
        fut["SEM_TRADING_SYMBOL"].astype(str).str.replace(r"-\w{3}\d{4}-FUT$", "", regex=True)
    )
    fut = fut.dropna(subset=["SEM_LOT_UNITS"])
    fut = fut.sort_values("SEM_EXPIRY_DATE")
    return {
        str(u): int(g["SEM_LOT_UNITS"].iloc[0])
        for u, g in fut.groupby("underlying")
        if g["SEM_LOT_UNITS"].iloc[0] > 0
    }


def group_universe(returns: pd.DataFrame, sectors: dict[str, str]) -> tuple[dict[str, str], dict]:
    """Cluster PCA residual loadings; fall back to sectors when clustering degenerates."""
    standardised = (returns - returns.mean()) / returns.std(ddof=1)
    n_components = int(min(15, standardised.shape[1] - 1, standardised.shape[0] - 1))
    pca = PCA(n_components=n_components).fit(standardised.values)
    loadings = pca.components_.T  # names x components
    norms = np.linalg.norm(loadings, axis=1, keepdims=True)
    loadings = loadings / np.where(norms == 0, 1.0, norms)

    optics = OPTICS(min_samples=3, min_cluster_size=2, metric="euclidean")
    labels = optics.fit_predict(loadings)
    names = list(returns.columns)
    sizes = pd.Series(labels).value_counts()
    clustered = sizes.drop(index=-1, errors="ignore")
    noise_share = float((labels == -1).sum()) / len(labels)
    largest_share = float(clustered.max()) / len(labels) if len(clustered) else 0.0
    degenerate = (
        len(clustered) < DEGENERACY_MIN_CLUSTERS
        or largest_share > DEGENERACY_MAX_LARGEST_SHARE
        or noise_share > DEGENERACY_MAX_NOISE_SHARE
    )
    diagnostics = {
        "pca_components": n_components,
        "pca_explained_variance_top5": [
            round(float(v), 4) for v in pca.explained_variance_ratio_[:5]
        ],
        "optics_clusters": len(clustered),
        "optics_noise_share": round(noise_share, 3),
        "optics_largest_share": round(largest_share, 3),
        "degenerate": bool(degenerate),
        "branch": "sector-fallback" if degenerate else "optics",
    }
    if degenerate:
        return {name: sectors.get(name, "Unclassified") for name in names}, diagnostics
    grouped = {
        name: f"optics-{label}"
        for name, label in zip(names, labels, strict=True)
        if label != -1
    }
    return grouped, diagnostics


def fit_pair(
    log_a: pd.Series, log_b: pd.Series
) -> tuple[float, float, np.ndarray, float]:
    """Engle-Granger fit: beta, alpha, the spread, and the cointegration p-value."""
    design = np.column_stack([np.ones(len(log_b)), log_b.values])
    alpha, beta = np.linalg.lstsq(design, log_a.values, rcond=None)[0]
    spread = log_a.values - alpha - beta * log_b.values
    p_value = float(coint(log_a.values, log_b.values, trend="c", autolag="AIC")[1])
    return float(beta), float(alpha), spread, p_value


def screen(
    closes: pd.DataFrame,
    *,
    sectors: dict[str, str],
    lots: dict[str, int],
    formation_months: int,
    gap_sessions: int,
    notional: float,
    fdr_q: float,
) -> tuple[list[PairResult], dict]:
    dates = list(closes.index)
    asof = dates[-1]
    formation_end_idx = len(dates) - 1 - gap_sessions
    formation_end = dates[formation_end_idx]
    offset_start = formation_end - pd.DateOffset(months=formation_months)
    formation_start = offset_start.date() if hasattr(offset_start, "date") else offset_start
    window = closes.loc[(closes.index > formation_start) & (closes.index <= formation_end)]

    log_prices = np.log(window)
    returns = log_prices.diff().dropna()
    groups, cluster_diag = group_universe(returns, sectors)

    candidates = [
        tuple(sorted(pair))
        for pair in combinations(sorted(groups), 2)
        if groups[pair[0]] == groups[pair[1]]
    ]

    normalised = window / window.iloc[0]
    raw: list[dict] = []
    for sym_a, sym_b in candidates:
        beta, alpha, spread, p_value = fit_pair(log_prices[sym_a], log_prices[sym_b])
        z_denominator = float(np.std(spread, ddof=1))
        spread_today = (
            math.log(closes.loc[asof, sym_a]) - alpha - beta * math.log(closes.loc[asof, sym_b])
        )
        lot_size_known = sym_a in lots and sym_b in lots
        quant = lot_quantisation(
            price_a=float(closes.loc[asof, sym_a]),
            price_b=float(closes.loc[asof, sym_b]),
            beta=beta,
            lot_a=lots.get(sym_a, 1),
            lot_b=lots.get(sym_b, 1),
            notional=notional,
        )
        # Costs scale on the lot-quantised ratio that actually trades, not the fitted one.
        costs = round_trip_cost_bps(quant["beta_effective"])
        sigma_bps = z_denominator * 1e4
        raw.append(
            {
                "symbol_a": sym_a,
                "symbol_b": sym_b,
                "group": groups[sym_a],
                "distance": float(np.sum((normalised[sym_a] - normalised[sym_b]) ** 2)),
                "beta": beta,
                "alpha": alpha,
                "coint_p": p_value,
                "hurst": hurst_exponent(spread),
                "half_life": half_life_sessions(spread),
                "sigma_bps": sigma_bps,
                "crossings": mean_crossings(spread),
                "z_today": (spread_today - float(np.mean(spread))) / z_denominator,
                "cost_coverage": 2.0 * sigma_bps / costs["cost_allin_high_bps"],
                "lot_size_known": lot_size_known,
                "min_notional_for_lot_gate": min_notional_for_lot_gate(
                    price_a=float(closes.loc[asof, sym_a]),
                    price_b=float(closes.loc[asof, sym_b]),
                    beta=beta,
                    lot_a=lots.get(sym_a, 1),
                    lot_b=lots.get(sym_b, 1),
                ),
                **quant,
                **costs,
            }
        )

    rejected, bars = benjamini_hochberg([r["coint_p"] for r in raw], q=fdr_q)
    results: list[PairResult] = []
    for row, reject, bar in zip(raw, rejected, bars, strict=True):
        gates = {
            "bh_pass": bool(reject),
            "gate_sigma": row["sigma_bps"] >= SIGMA_BPS_MIN,
            "gate_half_life": 0 < row["half_life"] <= HALF_LIFE_MAX_SESSIONS,
            "gate_hurst": bool(row["hurst"] < HURST_MAX),
            # An unknown F&O lot size cannot be quantised against, so the pair fails
            # the gate rather than passing on an assumed lot of one.
            "gate_lot": bool(row["lot_size_known"] and row["lot_error"] <= LOT_ERROR_MAX),
        }
        results.append(
            PairResult(
                **row,
                bh_bar=bar,
                **gates,
                admitted=all(gates.values()),
            )
        )

    meta = {
        "asof": str(asof),
        "formation_start": str(window.index[0]),
        "formation_end": str(formation_end),
        "formation_sessions": len(window),
        "gap_sessions": gap_sessions,
        "gap_dates": [str(d) for d in dates[formation_end_idx + 1 :]],
        "universe": int(closes.shape[1]),
        "candidates": len(candidates),
        "fdr_q": fdr_q,
        "notional": notional,
        "cluster": cluster_diag,
        "names_missing_lot_size": sorted(set(closes.columns) - set(lots)),
        "cas_break_in_window": bool(window.index[0] <= CAS_BREAK <= formation_end),
        "stt_break_in_window": bool(window.index[0] <= STT_BREAK <= formation_end),
    }
    return results, meta


def refit_pre_cas(
    closes: pd.DataFrame, pairs: list[tuple[str, str]], *, formation_start: date
) -> pd.DataFrame:
    """Refit a set of pairs on the same window truncated the session before the CAS change.

    The 2026-08-03 closing-auction change sits inside the formation window, so the window
    mixes continuous-trade closes with auction closes. Refitting on the pre-break segment
    alone shows how much of each pair's admission rests on the mixed series.
    """
    window = closes.loc[(closes.index >= formation_start) & (closes.index < CAS_BREAK)]
    log_prices = np.log(window)
    rows = []
    for sym_a, sym_b in pairs:
        beta, _alpha, spread, p_value = fit_pair(log_prices[sym_a], log_prices[sym_b])
        rows.append(
            {
                "pair": f"{sym_a}/{sym_b}",
                "sessions": len(window),
                "beta_pre_cas": beta,
                "coint_p_pre_cas": p_value,
                "half_life_pre_cas": half_life_sessions(spread),
                "sigma_bps_pre_cas": float(np.std(spread, ddof=1)) * 1e4,
                "hurst_pre_cas": hurst_exponent(spread),
            }
        )
    return pd.DataFrame(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Pair screen, FRAMEWORK.md §2 phases 1-2")
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--formation-months", type=int, default=12)
    parser.add_argument("--gap-sessions", type=int, default=5)
    parser.add_argument("--notional", type=float, default=1_000_000.0)
    parser.add_argument("--fdr-q", type=float, default=FDR_Q)
    parser.add_argument("--entry-z", type=float, default=2.0)
    parser.add_argument(
        "--out-dir", type=Path, default=Path(__file__).parent / "_output", help="per-pair dumps"
    )
    args = parser.parse_args()

    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from nifty50_members import NIFTY50

    closes, incomplete_names = load_panel(args.data)
    lots = futures_lot_sizes()
    results, meta = screen(
        closes,
        sectors=NIFTY50,
        lots=lots,
        formation_months=args.formation_months,
        gap_sessions=args.gap_sessions,
        notional=args.notional,
        fdr_q=args.fdr_q,
    )
    frame = pd.DataFrame([asdict(r) for r in results])
    args.out_dir.mkdir(parents=True, exist_ok=True)
    frame.to_csv(args.out_dir / "all_candidates.csv", index=False)

    admitted = frame[frame["admitted"]].copy()
    admitted.to_csv(args.out_dir / "admitted.csv", index=False)

    # Entry candidates require admission. The divergent set — candidates at or beyond the
    # entry threshold that were NOT admitted — is emitted separately and named for what it
    # is, so a large z on an unqualified pair can never be read as a signal.
    entry_candidates = admitted[admitted["z_today"].abs() >= args.entry_z]
    entry_candidates.to_csv(args.out_dir / "entry_candidates.csv", index=False)
    watchlist = admitted[admitted["z_today"].abs() < args.entry_z]
    watchlist.sort_values("z_today", key=abs, ascending=False).to_csv(
        args.out_dir / "watchlist.csv", index=False
    )
    divergent = frame[(frame["z_today"].abs() >= args.entry_z) & ~frame["admitted"]]
    divergent.sort_values("z_today", key=abs, ascending=False).to_csv(
        args.out_dir / "divergent_not_admitted.csv", index=False
    )

    # The CAS refit measures the closing-price break rather than merely flagging it. It
    # runs on the admitted set when there is one, and otherwise on the strongest
    # candidates by cointegration p — a set that is explicitly NOT admitted, labelled as
    # such in the output so the refit is never read as an admission.
    refit_source = admitted if not admitted.empty else frame.nsmallest(10, "coint_p")
    meta["cas_refit_set"] = "admitted" if not admitted.empty else "nearest-miss-top10-by-coint-p"
    if not refit_source.empty:
        pre_cas = refit_pre_cas(
            closes,
            list(zip(refit_source["symbol_a"], refit_source["symbol_b"], strict=True)),
            formation_start=pd.Timestamp(meta["formation_start"]).date(),
        )
        merged = refit_source[
            ["symbol_a", "symbol_b", "beta", "coint_p", "half_life", "sigma_bps", "hurst"]
        ].copy()
        merged["pair"] = merged["symbol_a"] + "/" + merged["symbol_b"]
        pre_cas = merged.merge(pre_cas, on="pair")
        pre_cas.to_csv(args.out_dir / "pre_cas_refit.csv", index=False)

    funnel = {
        "universe_names": meta["universe"],
        "candidate_pairs": meta["candidates"],
        "pass_bh": int(frame["bh_pass"].sum()) if len(frame) else 0,
        "pass_bh_and_half_life": int((frame["bh_pass"] & frame["gate_half_life"]).sum()),
        "pass_bh_hl_hurst": int(
            (frame["bh_pass"] & frame["gate_half_life"] & frame["gate_hurst"]).sum()
        ),
        "pass_bh_hl_hurst_sigma": int(
            (
                frame["bh_pass"]
                & frame["gate_half_life"]
                & frame["gate_hurst"]
                & frame["gate_sigma"]
            ).sum()
        ),
        "admitted": int(frame["admitted"].sum()),
        "solo_pass_bh": int(frame["bh_pass"].sum()),
        "solo_pass_half_life": int(frame["gate_half_life"].sum()),
        "solo_pass_hurst": int(frame["gate_hurst"].sum()),
        "solo_pass_sigma": int(frame["gate_sigma"].sum()),
        "solo_pass_lot": int(frame["gate_lot"].sum()),
        # Sensitivities, reported for reading only: they admit nothing. They say how far
        # the binding gate is from being met, which a bare zero cannot.
        "min_half_life": float(frame["half_life"].min()),
        "min_coint_p": float(frame["coint_p"].min()),
        "bh_bar_at_rank_1": float(args.fdr_q / len(frame)) if len(frame) else float("nan"),
        "n_half_life_le_10": int((frame["half_life"] <= 10).sum()),
        "n_coint_p_le_0p05_unadjusted": int((frame["coint_p"] <= 0.05).sum()),
        "n_pass_all_but_half_life": int(
            (frame["bh_pass"] & frame["gate_hurst"] & frame["gate_sigma"] & frame["gate_lot"]).sum()
        ),
        "n_pass_all_but_bh": int(
            (
                frame["gate_half_life"]
                & frame["gate_hurst"]
                & frame["gate_sigma"]
                & frame["gate_lot"]
            ).sum()
        ),
    }
    meta["funnel"] = funnel
    meta["entry_z"] = args.entry_z
    meta["names_dropped_for_incomplete_series"] = incomplete_names
    meta["entry_candidates"] = len(entry_candidates)
    meta["watchlist"] = len(watchlist)
    meta["divergent_not_admitted"] = len(divergent)
    (args.out_dir / "meta.json").write_text(json.dumps(meta, indent=2))

    print(json.dumps({k: v for k, v in meta.items() if k != "gap_dates"}, indent=2)[:2000])
    print(f"\nadmitted {len(admitted)} of {len(frame)} candidates")
    print(
        f"entry candidates (|z| >= {args.entry_z}): {len(entry_candidates)}; "
        f"watchlist: {len(watchlist)}; "
        f"divergent but NOT admitted (not trades): {len(divergent)}"
    )
    if not admitted.empty:
        cols = ["symbol_a", "symbol_b", "beta", "half_life", "sigma_bps", "coint_p", "bh_bar",
                "hurst", "crossings", "lot_error", "z_today"]
        ranked = admitted.sort_values("z_today", key=abs, ascending=False)
        print(ranked[cols].to_string(index=False))
    print(f"\ndumps -> {args.out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
