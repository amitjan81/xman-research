"""The property that makes a research verdict about markets rather than about NSE.

**The claim.** "Does selling index variance earn a premium" is a question about an
economic effect. The lot size is an execution-layer rounding constraint — NIFTY's has been
25, 50, 75 and 65, and it moves by exchange circular. A Sharpe, a drawdown or a
cost-breakeven multiple that changes when the multiplier changes is not measuring the
effect; it is measuring the contract specification.

**What used to fail, and how quietly.** Size was declared as ``ShortAtmStraddle(lots=1)``,
so the position — and therefore P&L, margin and every percentage-based cost — was
proportional to the multiplier. The Sharpe survived that, being scale-free, which is
exactly what made it hard to notice. The maximum drawdown did not:
:func:`~xman_research.validation.statistics.drawdown` runs on returns denominated in a
fixed capital base, so a 75->65 change moved it by 15%, and H1's gate bars drawdown at
10%. A verdict could flip on a circular about contract size, and nothing in the output
would have said so. ``test_a_one_lot_book_is_not_lot_invariant_and_that_is_the_honest_limit``
below pins that failure in its remaining form, so it cannot come back unremarked.

**What replaced it.** Sizing targets a notional exposure; the multiplier only decides the
rounding to whole contracts. See
:attr:`~xman_research.backtest.strategies.ShortAtmStraddle.target_notional`.

**Why this is a tolerance test and not an equality test.** The residual is irreducible and
its size is known in advance. The strategy wants ``target_notional / spot`` index units and
can only buy whole contracts, so realised exposure misses the target by at most half a lot.
Two runs at different multipliers can therefore differ in size by at most
``(lot_a + lot_b) / (2 * target_units)``, and every scale-free statistic inherits roughly
that. Each test below computes that bound from its own configuration, asserts the
statistics agree inside it, **and asserts the bound is itself small** — the second half is
what stops a loose tolerance passing vacuously at a size where the property is trivial.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import os
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from conftest import SyntheticContract, write_synthetic_session
from xman_research import (
    DataWindow,
    HypothesisRecord,
    ResearchSession,
    StaticCodeVersion,
    TrialLog,
)
from xman_research.adapter import costs_by_date
from xman_research.backtest import BacktestConfig, ShortAtmStraddle, run_backtest
from xman_research.clock import ManualClock
from xman_research.session_store import DEFAULT_CORPUS_ROOT, SessionStore
from xman_research.validation.series import RunEvidence
from xman_research.validation.statistics import (
    annualised_sharpe_ratio,
    cost_breakeven,
    drawdown,
)

UNDERLYING = "NIFTY"

#: The two multipliers NIFTY has actually traded at inside this corpus's lifetime. Using
#: the real pair rather than an arbitrary one keeps the test about a change that happened.
LOT_A = 65
LOT_B = 75


# --------------------------------------------------------------------------------------
# Running one configuration and reducing it to the three numbers a verdict rests on
# --------------------------------------------------------------------------------------


def statistics_for(
    store: SessionStore,
    *,
    window: DataWindow,
    target_notional: float,
    starting_cash: float,
) -> dict[str, Any]:
    """Run the straddle and return the scale-free statistics, plus the size it traded at.

    The comparison deliberately stops at :class:`RunEvidence` and the statistics functions
    rather than going through ``Validator.grade``. A graded verdict can come back
    NOT_EVALUABLE for reasons that have nothing to do with size — the counterfactual run
    below carries a lot-size contradiction stamp by construction — and two NOT_EVALUABLE
    verdicts would compare equal while telling us nothing at all.
    """
    log = TrialLog(
        Path(tempfile.mkdtemp(prefix="lot_invariance_")) / "research.db",
        clock=ManualClock(dt.datetime(2026, 8, 13, 9, 15, tzinfo=dt.UTC)),
        code_version=StaticCodeVersion("0" * 40, dirty=False),
    )
    session = ResearchSession(log)
    hypothesis = HypothesisRecord(
        name="lot-size invariance — machinery only, not a claim about markets",
        mechanism=(
            "Stands in for H1 so the same window can be run at two contract multipliers. "
            "Registering these against the real hypothesis family would inflate the "
            "selection count the real deflated Sharpe is corrected against."
        ),
        null_hypothesis="Not tested here.",
        thresholds={"deflated_sharpe": 0.0},
        predictors=["iv_30d"],
    )
    try:
        with session.trial(hypothesis, data_window=window) as trial:
            result = run_backtest(
                trial,
                store=store,
                strategy=ShortAtmStraddle(target_notional=target_notional),
                config=BacktestConfig(underlying=UNDERLYING, starting_cash=starting_cash),
            )
    finally:
        session.close()

    evidence = RunEvidence.from_equity_curve(
        result.equity_curve(),
        label="invariance",
        capital_base=starting_cash,
        cost_by_date=costs_by_date(result),
    )
    entries = [fill for fill in result.fills if fill.tag == "entry" and fill.filled_lots > 0]
    assert entries, "nothing was traded, so there is no size to be invariant about"
    settled_flow = sum(abs(record.cash_flow) for record in result.settlements)
    traded_flow = sum(abs(fill.gross_value) for fill in result.fills)
    return {
        "sharpe": annualised_sharpe_ratio(evidence.returns),
        "max_drawdown": drawdown(evidence.returns).max_drawdown,
        "cost_breakeven": cost_breakeven(evidence).multiple,
        "smallest_units": float(min(fill.filled_lots * fill.lot_size for fill in entries)),
        # Every entry's unit count, in order. Compared between the two runs to prove
        # they are different books: the *smallest* position is not enough, because
        # 12,675 units is a whole number of both 65s and 75s and the two runs can
        # legitimately coincide on one session while differing on the rest.
        "entry_units": tuple(fill.filled_lots * fill.lot_size for fill in entries),
        "resized": float(len(result.resized_fills())),
        "settlements": float(len(result.settlements)),
        # Share of gross cash movement that came through cash settlement rather than
        # through a fill. This strategy holds to expiry, so it is the dominant path and
        # the one the invariance most needs to cover — see the settlement assertions.
        "settled_share": settled_flow / (settled_flow + traded_flow),
    }


def rounding_bound(a: dict[str, Any], b: dict[str, Any]) -> float:
    """Worst-case relative size disagreement the two multipliers can produce.

    Half a contract of rounding error on each side, over the smaller of the two positions.
    Deliberately computed from what the runs actually traded rather than from the
    configured notional: if a participation cap cut the size down, the bound has to widen
    with it, and a bound derived from the target alone would understate the residual on
    precisely the sessions where it is largest.
    """
    smallest = min(a["smallest_units"], b["smallest_units"])
    return (LOT_A + LOT_B) / (2.0 * smallest)


def assert_invariant(
    a: dict[str, Any],
    b: dict[str, Any],
    *,
    bound_ceiling: float,
    slack: float = 3.0,
) -> float:
    """The two-sided assertion. Returns the bound so a caller can report it.

    ``slack`` is 3x the worst-case bound rather than 1x because the bound is a worst case
    on a *single* entry, while every statistic here aggregates over many — the residuals
    partly cancel, but nothing guarantees by how much, and pinning the tolerance to the
    observed cancellation would be fitting the test to the run.

    ``bound_ceiling`` is the half that stops this passing for the wrong reason. Without
    it, a run sized at one contract would satisfy any tolerance loose enough to admit its
    own 15% disagreement, and the test would certify the defect it exists to catch.
    """
    bound = rounding_bound(a, b)
    assert bound <= bound_ceiling, (
        f"the configured size admits {bound:.2%} of pure rounding disagreement, above the "
        f"{bound_ceiling:.2%} this test claims to hold the property to. The tolerance "
        "below would pass vacuously; make the position larger, do not loosen the bound."
    )
    for key in ("sharpe", "max_drawdown", "cost_breakeven"):
        scale = abs(a[key]) or 1.0
        relative = abs(a[key] - b[key]) / scale
        assert relative <= slack * bound, (
            f"{key} moved {relative:.2%} between lot {LOT_A} and lot {LOT_B}, beyond the "
            f"{slack * bound:.2%} that rounding to whole contracts can explain "
            f"({a[key]:.6f} vs {b[key]:.6f}). Something other than the rounding is "
            "scaling with the contract multiplier."
        )
    return bound


# --------------------------------------------------------------------------------------
# A synthetic corpus: identical bars, two declared multipliers
# --------------------------------------------------------------------------------------

#: Real NSE trading days, and every one in the span — the store resolves a range through
#: the exchange calendar, so a missing weekday would be reported as a gap and refuse the
#: run. Four weekly expiry cycles, because one entry would make the test vacuous: with a
#: single position the rounding error is a *constant* scale factor, and a constant scale
#: factor leaves the Sharpe exactly invariant for the wrong reason. The property only has
#: teeth when spot moves between entries, so the rounding lands differently each cycle.
SYNTHETIC_SESSIONS: tuple[dt.date, ...] = tuple(
    dt.date(2026, 2, day) for day in (2, 3, 4, 5, 6, 9, 10, 11, 12, 13, 16, 17, 18, 19, 20, 23, 24)
)
SYNTHETIC_EXPIRIES: tuple[dt.date, ...] = (
    dt.date(2026, 2, 3),
    dt.date(2026, 2, 10),
    dt.date(2026, 2, 17),
    dt.date(2026, 2, 24),
)

#: Spot per session. Hand-written rather than generated: the numbers have to move enough
#: that consecutive cycles round differently under the two multipliers, and a generated
#: series would make that a property of the generator rather than of the fixture.
SYNTHETIC_SPOT_SERIES: tuple[float, ...] = (
    23_000.0,
    23_140.0,
    22_880.0,
    23_310.0,
    23_055.0,
    22_760.0,
    23_420.0,
    23_190.0,
    22_930.0,
    23_505.0,
    23_260.0,
    22_845.0,
    23_610.0,
    23_080.0,
    23_390.0,
    22_915.0,
    23_720.0,
)
SYNTHETIC_SPOT: dict[dt.date, float] = dict(
    zip(SYNTHETIC_SESSIONS, SYNTHETIC_SPOT_SERIES, strict=True)
)

#: Divisible by both 65 and 75 (lcm 975), so neither multiplier is reported as
#: non-conforming and the comparison isolates the one variable it is about. Large enough
#: that the 1%-of-volume participation cap never binds at the sizes used below — a capped
#: run is answering "could this have been filled", which is a genuinely size-dependent
#: question and not this one.
SYNTHETIC_VOLUME = 19_500_000.0
SYNTHETIC_OPEN_INTEREST = 195_000_000.0

#: 200 contracts of 65 at the opening spot. Chosen from the bound, not from taste: it puts
#: the worst-case rounding disagreement at ~0.5%, an order of magnitude below the 15%
#: defect this file exists to prevent.
SYNTHETIC_TARGET_NOTIONAL = 13_000 * 23_000.0
SYNTHETIC_CAPITAL = 200_000_000.0


def _expiry_for(session_date: dt.date) -> dt.date:
    return next(expiry for expiry in SYNTHETIC_EXPIRIES if expiry >= session_date)


def _strikes_around(spot: float) -> tuple[float, ...]:
    centre = round(spot / 50.0) * 50.0
    return tuple(centre + 50.0 * step for step in (-2, -1, 0, 1, 2))


def _premium(strike: float, spot: float, days_to_expiry: int) -> float:
    """A premium that decays into expiry and rises away from the money.

    It does not need to be arbitrage-free. It needs to be deterministic, positive, and to
    vary across sessions, so the equity curve has a dispersion for a Sharpe to be about.
    """
    return 20.0 + 18.0 * days_to_expiry + 0.35 * abs(strike - spot)


def _write_corpus(root: Path, lot_size: int) -> None:
    """The same market, declared at ``lot_size``."""
    for session_date in SYNTHETIC_SESSIONS:
        spot = SYNTHETIC_SPOT[session_date]
        expiry = _expiry_for(session_date)
        days = (expiry - session_date).days
        write_synthetic_session(
            root,
            session_date,
            underlying=UNDERLYING,
            spot=spot,
            lot_size=lot_size,
            contracts=[
                SyntheticContract(
                    strike=strike,
                    option_type=option_type,
                    expiry=expiry,
                    close=_premium(strike, spot, days),
                    volume=SYNTHETIC_VOLUME,
                    open_interest=SYNTHETIC_OPEN_INTEREST,
                )
                for strike in _strikes_around(spot)
                for option_type in ("CE", "PE")
            ],
        )


@pytest.fixture
def synthetic_pair(tmp_path: Path) -> Iterator[dict[int, SessionStore]]:
    """One store per multiplier, over bars that are otherwise identical."""
    stores: dict[int, SessionStore] = {}
    for lot_size in (LOT_A, LOT_B):
        root = tmp_path / f"corpus_{lot_size}"
        root.mkdir()
        _write_corpus(root, lot_size)
        stores[lot_size] = SessionStore(root=root, manifest_path=tmp_path / "no-manifest.sqlite")
    yield stores


SYNTHETIC_WINDOW = DataWindow(SYNTHETIC_SESSIONS[0], SYNTHETIC_SESSIONS[-1])


def test_the_verdict_survives_a_change_of_contract_multiplier(synthetic_pair) -> None:
    """The deliverable: same market, two lot sizes, the same answer.

    Runs without the real corpus, so the property is held on every machine rather than
    only where the captured data happens to be mounted.
    """
    runs = {
        lot_size: statistics_for(
            store,
            window=SYNTHETIC_WINDOW,
            target_notional=SYNTHETIC_TARGET_NOTIONAL,
            starting_cash=SYNTHETIC_CAPITAL,
        )
        for lot_size, store in synthetic_pair.items()
    }

    # No cap bound, on either side. If one had, the two runs would have been cut to sizes
    # decided by liquidity rather than by the sizing rule, and agreement would say nothing
    # about the sizing rule.
    assert runs[LOT_A]["resized"] == runs[LOT_B]["resized"] == 0

    # **Settlement is the path this most needs to cover, so it is asserted rather than
    # assumed.** The straddle is held to cash settlement, so most of the money moves
    # through the exchange's expiry payout, not through a fill — and lot size enters that
    # path differently: not through a fill price and a participation cap, but through
    # `intrinsic_per_unit * units`, with exercise STT charged on the settlement notional.
    # A sizing rule could be invariant on the entry path and still leak on this one, and
    # a fixture with no expiry in it would never find out.
    assert runs[LOT_A]["settlements"] == runs[LOT_B]["settlements"] == 2 * len(SYNTHETIC_EXPIRIES)
    assert runs[LOT_A]["settled_share"] > 0.5
    assert runs[LOT_B]["settled_share"] > 0.5

    bound = assert_invariant(runs[LOT_A], runs[LOT_B], bound_ceiling=0.01)
    assert bound < 0.01

    # The runs are genuinely different books, not the same one twice: the multiplier
    # changed, so the traded unit counts must differ. Without this the assertions above
    # would pass on a fixture that silently ignored `lot_size`.
    assert runs[LOT_A]["entry_units"] != runs[LOT_B]["entry_units"]


def test_a_one_lot_book_is_not_lot_invariant_and_that_is_the_honest_limit(
    synthetic_pair,
) -> None:
    """The limitation, pinned so that nobody later "fixes" a failure by shrinking the size.

    At one contract the book's size *is* the lot, so the drawdown moves by the full ratio
    of the two multipliers — 75/65, about 15%. That is not a defect in the sizing rule; it
    is the market's own granularity, and no expression of the strategy can remove it.

    It is asserted rather than merely documented because the alternative is worse than
    silence: a future reader who saw only the passing invariance test above could
    reasonably conclude the property holds at any size, size a real study at one contract,
    and get a verdict that turns on an exchange circular. The bound in
    :func:`assert_invariant` is what refuses that, and this is the test that proves the
    refusal bites.
    """
    one_lot = 1_495_000.0  # 65 contracts... one contract of 65 at spot 23,000.
    runs = {
        lot_size: statistics_for(
            store,
            window=SYNTHETIC_WINDOW,
            target_notional=one_lot,
            starting_cash=1_000_000.0,
        )
        for lot_size, store in synthetic_pair.items()
    }

    assert runs[LOT_A]["smallest_units"] == LOT_A
    assert runs[LOT_B]["smallest_units"] == LOT_B

    # The scale-free statistic is unharmed even here — which is precisely why the defect
    # went unnoticed for as long as it did.
    assert abs(runs[LOT_A]["sharpe"] - runs[LOT_B]["sharpe"]) / abs(runs[LOT_A]["sharpe"]) < 0.02

    # The one that is not scale-free moves by the whole ratio of the multipliers.
    ratio = runs[LOT_B]["max_drawdown"] / runs[LOT_A]["max_drawdown"]
    assert ratio == pytest.approx(LOT_B / LOT_A, rel=0.02)

    # And the guard refuses to certify it.
    with pytest.raises(AssertionError, match="rounding disagreement"):
        assert_invariant(runs[LOT_A], runs[LOT_B], bound_ceiling=0.01)


# --------------------------------------------------------------------------------------
# The same property against the real corpus
# --------------------------------------------------------------------------------------

CORPUS_ROOT = Path(os.environ.get("XMAN_RESEARCH_CORPUS_ROOT") or DEFAULT_CORPUS_ROOT)

#: H1's own in-sample window, so the property is demonstrated on the run a verdict is
#: actually taken from rather than on a window chosen to be well-behaved.
H1_IN_SAMPLE = DataWindow(dt.date(2025, 12, 31), dt.date(2026, 4, 30))

#: ~1,000 index units per straddle at the corpus's spot. The ceiling is liquidity, not
#: preference: the thinnest session in this window admits 1,770 units at the 1%-of-volume
#: cap, and a size that trips the cap would be comparing feasibility, not sizing.
CORPUS_TARGET_NOTIONAL = 24_000_000.0
CORPUS_CAPITAL = 16_000_000.0


class RelotStore(SessionStore):
    """The corpus's own bars, handed back under a different declared lot size.

    A test double, and the only honest way to ask the counterfactual: the corpus is
    read-only and irreplaceable, so the multiplier is changed on the way out of the reader
    rather than on disk. Everything else — prices, volumes, open interest, the calendar —
    is the real thing, which is what makes this stronger than the synthetic pair above.

    **This test is only possible because the lot-size refusal became a stamp.** Declaring
    75 against bars that divide by 65 is exactly the contradiction that used to raise
    ``LotSizeContradictionError`` and abort the run. Under the owner's 2026-08-13 decision
    it computes and stamps instead, so the counterfactual can be run at all.
    """

    def __init__(self, *args, lot_size: int, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._lot_size = lot_size

    def load_refdata(self, ref):  # type: ignore[no-untyped-def]
        refdata = super().load_refdata(ref)
        return dataclasses.replace(
            refdata,
            nfo_instruments=tuple(
                {**row, "LotSize": self._lot_size} for row in refdata.nfo_instruments
            ),
            underlier_instruments=tuple(
                {**row, "LotSize": self._lot_size} for row in refdata.underlier_instruments
            ),
        )


@pytest.mark.skipif(
    not (CORPUS_ROOT / UNDERLYING).is_dir(),
    reason=f"real corpus not present at {CORPUS_ROOT / UNDERLYING}",
)
def test_the_h1_window_gives_the_same_answer_at_either_multiplier() -> None:
    """The property on the data a verdict is actually taken from.

    The bound is looser here than on the synthetic corpus and cannot be tightened: the
    thinnest session's participation cap puts a ceiling on the position, and the position
    is the denominator of the rounding residual. So this window supports the property to a
    few percent, not to a fraction of one — which is a fact about NIFTY's liquidity at
    09:20 rather than about the sizing rule, and is worth having on the record as such.
    """
    runs = {
        LOT_A: statistics_for(
            SessionStore(root=CORPUS_ROOT),
            window=H1_IN_SAMPLE,
            target_notional=CORPUS_TARGET_NOTIONAL,
            starting_cash=CORPUS_CAPITAL,
        ),
        LOT_B: statistics_for(
            RelotStore(root=CORPUS_ROOT, lot_size=LOT_B),
            window=H1_IN_SAMPLE,
            target_notional=CORPUS_TARGET_NOTIONAL,
            starting_cash=CORPUS_CAPITAL,
        ),
    }

    assert runs[LOT_A]["resized"] == runs[LOT_B]["resized"] == 0
    assert runs[LOT_A]["entry_units"] != runs[LOT_B]["entry_units"]

    bound = assert_invariant(runs[LOT_A], runs[LOT_B], bound_ceiling=0.10)
    # Liquidity-limited, and stated rather than left implicit.
    assert 0.01 < bound < 0.10
