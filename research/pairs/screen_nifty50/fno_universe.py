"""The NSE F&O stock universe, read from a Dhan scrip master.

One definition of "which names have single-stock futures, and at what lot size", shared
by the fetcher (which needs the symbol list) and the screen (which needs the lot sizes).
A second copy of the underlying-extraction rule in either caller would be free to drift
from this one, and the two answers must agree for the lot gate to mean anything.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

SCRIP_MASTER_DIR = Path("/home/qa/runtime/data/backtest/dhan/scrip_master")

# The master carries exchange test scrips (011NSETEST … ) that have FUTSTK rows and no
# tradeable history. They are excluded by name and the exclusions are reported.
TEST_SCRIP_MARKER = "NSETEST"

# The contract symbol is <UNDERLYING>-<MonYYYY>-FUT, and underlyings may themselves
# contain a hyphen (BAJAJ-AUTO), so only the expiry suffix is stripped.
EXPIRY_SUFFIX = r"-\w{3}\d{4}-FUT$"


def newest_scrip_master(directory: Path = SCRIP_MASTER_DIR) -> Path:
    """The most recent scrip-master CSV, by filename date."""
    files = sorted(directory.glob("api-scrip-master-*.csv"))
    if not files:
        raise FileNotFoundError(f"no scrip master under {directory}")
    return files[-1]


def futures_underlyings(master_csv: Path) -> tuple[dict[str, int], list[str]]:
    """Underlying -> F&O lot size over NSE FUTSTK rows, and the test scrips excluded.

    The lot size is taken from the nearest expiry, which is the contract a position opened
    today trades; NSE revises lot sizes at contract introduction, so a far-month row can
    carry a different one.
    """
    master = pd.read_csv(master_csv, low_memory=False)
    fut = master[
        (master["SEM_EXM_EXCH_ID"] == "NSE") & (master["SEM_INSTRUMENT_NAME"] == "FUTSTK")
    ].copy()
    fut["underlying"] = (
        fut["SEM_TRADING_SYMBOL"].astype(str).str.replace(EXPIRY_SUFFIX, "", regex=True)
    )
    excluded = sorted({u for u in fut["underlying"] if TEST_SCRIP_MARKER in u})
    fut = fut[~fut["underlying"].isin(excluded)]
    fut = fut.dropna(subset=["SEM_LOT_UNITS"]).sort_values("SEM_EXPIRY_DATE")
    lots = {
        str(u): int(g["SEM_LOT_UNITS"].iloc[0])
        for u, g in fut.groupby("underlying")
        if g["SEM_LOT_UNITS"].iloc[0] > 0
    }
    return lots, excluded
