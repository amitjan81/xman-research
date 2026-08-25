"""BANKNIFTY's lot-size regimes, and the detection hole that hid one of them.

Two things are held here. The first is the epoch table itself: four regimes keyed on
contract expiry, the gap between two of them reading "not established" rather than
guessing, and NIFTY reading exactly what it read before. The second is the reason
:data:`CANDIDATE_LOT_SIZES` had to grow — a regime whose true lot size is absent from the
candidate set is not merely unnamed, it is *undetectable*: the declared value fails the
floor, no alternative clears the ceiling, and the session runs unstamped. That is held on
a synthetic frame rather than on the corpus, so it fails on a machine with no data.
"""

from __future__ import annotations

import datetime as dt
from itertools import pairwise

import pandas as pd
import pytest

from xman_research.backtest import (
    BANKNIFTY_LOT_SIZE_EPOCHS,
    NIFTY_LOT_SIZE_EPOCHS,
    audit_lot_size,
    epoch_for,
)
from xman_research.backtest.costs import Confidence
from xman_research.backtest.lot_size import CANDIDATE_LOT_SIZES
from xman_research.session_store import RefData

SESSION = dt.date(2025, 10, 1)
EXPIRY = dt.date(2025, 10, 28)


def _refdata(*, declared_lot_size: int, underlying: str = "BANKNIFTY") -> RefData:
    return RefData(
        session_date=SESSION,
        nfo_instruments=(
            {
                "TradingSymbol": f"{underlying}-28Oct2025-56000-CE",
                "LookupName": underlying,
                "OptionType": "CE",
                "StrikePrice": 56000.0,
                "ExpiryDate": EXPIRY.strftime("%d/%m/%Y"),
                "LotSize": declared_lot_size,
                "TickSize": 5.0,
            },
        ),
        underlier_instruments=(),
    )


def _frame(*, true_lot_size: int, underlying: str = "BANKNIFTY") -> pd.DataFrame:
    """Option bars whose volume is a whole number of contracts at ``true_lot_size``."""
    rows = [
        {
            "symbol": f"{underlying}-28Oct2025-56000-CE",
            "volume": float(true_lot_size * units),
            "oi": float(true_lot_size * units * 10),
        }
        for units in range(1, 201)
    ]
    rows.append({"symbol": underlying, "volume": float("nan"), "oi": float("nan")})
    return pd.DataFrame(rows)


@pytest.mark.parametrize(
    ("expiry", "expected"),
    [
        # The first expiry the measurement covers, and the last of the 15 regime.
        (dt.date(2024, 8, 7), 15),
        (dt.date(2025, 1, 30), 15),
        # Between the 30/01/2025 and 27/02/2025 expiries no contract exists, and no
        # measurement covers the interval. "Not established" is the answer.
        (dt.date(2025, 2, 10), None),
        (dt.date(2025, 2, 27), 30),
        (dt.date(2025, 6, 26), 30),
        # The regime that was invisible before 35 joined the candidate set.
        (dt.date(2025, 7, 31), 35),
        (dt.date(2025, 12, 30), 35),
        (dt.date(2026, 1, 27), 30),
        (dt.date(2026, 6, 30), 30),
        # Past the last measured expiry. The holdout is sealed, so nothing here may
        # claim a regime over it.
        (dt.date(2026, 7, 1), None),
    ],
)
def test_banknifty_epochs_across_every_regime_boundary(
    expiry: dt.date, expected: int | None
) -> None:
    epoch = epoch_for(expiry, underlying="BANKNIFTY")
    assert (epoch.lot_size if epoch else None) == expected


def test_the_banknifty_table_is_corroborated_evidence_not_assertion() -> None:
    assert BANKNIFTY_LOT_SIZE_EPOCHS
    for epoch in BANKNIFTY_LOT_SIZE_EPOCHS:
        assert epoch.underlying == "BANKNIFTY"
        assert epoch.confidence is Confidence.CORROBORATED
        assert epoch.evidence.strip()
        # A closed range on both sides: an open end would claim a regime past the last
        # expiry anyone measured, and past the holdout seal.
        assert epoch.expiries_from is not None
        assert epoch.expiries_through is not None


def test_the_regimes_do_not_overlap_and_run_forward() -> None:
    ordered = sorted(BANKNIFTY_LOT_SIZE_EPOCHS, key=lambda e: e.expiries_from or dt.date.min)
    assert ordered == list(BANKNIFTY_LOT_SIZE_EPOCHS)
    for earlier, later in pairwise(ordered):
        assert earlier.expiries_through < later.expiries_from
        assert earlier.lot_size != later.lot_size


def test_nifty_reads_exactly_what_it_read_before() -> None:
    """The default underlying is NIFTY and its answers are untouched by the new table."""
    assert epoch_for(dt.date(2025, 12, 16)).lot_size == 75
    assert epoch_for(dt.date(2025, 12, 30)).lot_size == 75
    assert epoch_for(dt.date(2026, 1, 6)).lot_size == 65
    assert epoch_for(dt.date(2026, 6, 25)).lot_size == 65
    assert epoch_for(dt.date(2025, 12, 30), underlying="NIFTY").lot_size == 75
    # An underlying nobody has measured is not silently answered from another's table.
    assert epoch_for(dt.date(2025, 12, 30), underlying="FINNIFTY") is None
    assert all(epoch.underlying == "NIFTY" for epoch in NIFTY_LOT_SIZE_EPOCHS)


def test_a_thirty_five_lot_session_is_convicted_against_its_declared_thirty() -> None:
    """The 2025-07..2025-12 regime, in miniature. Before 35 was a candidate this passed
    silently: 30 explains 15% of the rows, 15 explains 32%, and neither the floor nor the
    ceiling fires, so a session whose declared lot size is flatly wrong carried no stamp."""
    audit = audit_lot_size(
        session_date=SESSION,
        underlying="BANKNIFTY",
        frame=_frame(true_lot_size=35),
        refdata=_refdata(declared_lot_size=30),
    )
    assert audit.declared_lot_sizes == (30,)
    assert audit.best_alternative == 35
    assert audit.best_alternative_share == 1.0
    assert audit.declared_volume_share < 0.20
    assert audit.contradicts_declared
    assert audit.reference_lot_size == 35


def test_a_fifteen_lot_session_is_convicted_against_its_declared_thirty() -> None:
    """The 2024-08..2025-01 regime: half the rows divide by 30 by parity alone."""
    audit = audit_lot_size(
        session_date=SESSION,
        underlying="BANKNIFTY",
        frame=_frame(true_lot_size=15),
        refdata=_refdata(declared_lot_size=30),
    )
    assert audit.best_alternative == 15
    assert audit.best_alternative_share == 1.0
    assert 0.4 < audit.declared_volume_share < 0.6
    assert audit.contradicts_declared


def test_a_session_whose_declared_lot_size_holds_is_not_convicted() -> None:
    audit = audit_lot_size(
        session_date=SESSION,
        underlying="BANKNIFTY",
        frame=_frame(true_lot_size=30),
        refdata=_refdata(declared_lot_size=30),
    )
    assert audit.declared_volume_share == 1.0
    assert not audit.contradicts_declared
    assert audit.reference_lot_size == 30


def test_the_candidate_set_still_picks_the_coarsest_explanation_for_nifty() -> None:
    """Adding 30 and 35 must not steal NIFTY's verdict: divisibility bounds from below,
    so a 75-lot session divides by 15, 25 and 30 too, and the coarsest value consistent
    with every row is the one the evidence supports."""
    audit = audit_lot_size(
        session_date=dt.date(2025, 12, 16),
        underlying="NIFTY",
        frame=_frame(true_lot_size=75, underlying="NIFTY"),
        refdata=_refdata(declared_lot_size=65, underlying="NIFTY"),
    )
    assert audit.best_alternative == 75
    assert audit.best_alternative_share == 1.0
    assert audit.contradicts_declared


def test_every_measured_lot_size_is_a_candidate() -> None:
    """A regime the table records but the audit cannot test for is a hole by construction."""
    recorded = {epoch.lot_size for epoch in BANKNIFTY_LOT_SIZE_EPOCHS + NIFTY_LOT_SIZE_EPOCHS}
    assert recorded <= set(CANDIDATE_LOT_SIZES)
