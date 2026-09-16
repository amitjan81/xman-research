"""Search the parameter space for a configuration that reaches 12% a year.

**What this is and what it is not.** It is a coordinate search over the levers the baseline
study identified, run in parallel, with an out-of-sample tail held back. It is *not* a
verdict: a search of N configurations over one five-year corpus will find a best one whether
or not any edge exists, and the more configurations, the better the best one looks. Three
things keep that honest here:

1. **The split is fixed before the search runs.** Everything is tuned on sessions up to
   :data:`IN_SAMPLE_END` and scored again, untouched, on the tail after it. A configuration
   that reaches the target in-sample and collapses out-of-sample has told you which it was.
2. **Every configuration is reported, not only the winner** — the whole ranked table goes
   into the results file, so the spread between the best and the median is visible. A best
   that stands a long way above a flat field is a different thing from a best that is the
   top of a smooth surface.
3. **The trial count is written down.** Each configuration is one trial and the canonical
   log records it, which is what the repository's deflation machinery needs to say whether a
   Sharpe survives the number of attempts that produced it.

Runs are parallel across processes, each against its own scratch trial log because SQLite is
not the right place for forty concurrent writers; the canonical rows are written afterwards,
in order, by :func:`log_trials`.

    uv run python research/overlay/tune.py --out research/overlay/results/tuning
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import tempfile
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

from xman_research import DataWindow, open_session
from xman_research.overlay.run import DEFAULT_TRIAL_LOG, OverlayRunConfig, run_overlay
from xman_research.overlay.sizing import MarginPerLotModel

#: Everything at or before this date is the search's playground; everything after is the
#: holdout it is scored on once. Chosen as 70% of the captured window, before any run.
IN_SAMPLE_END = dt.date(2025, 3, 31)
WINDOW_START = dt.date(2021, 9, 20)
WINDOW_END = dt.date(2026, 9, 15)

#: The objective. The document's 12% a year on Portfolio Capital, with its 10% drawdown
#: objective as the constraint that stops "more gearing" from being the whole answer.
TARGET_ANNUAL_RETURN = 0.12
MAX_DRAWDOWN_OBJECTIVE = 0.10


def candidates() -> list[OverlayRunConfig]:
    """The search space, as a coordinate sweep around the baseline's best-known point.

    The baseline established that the roll destroys the edge and that the position is small,
    so the search starts from "no roll" and moves along the levers that change the *size* of
    the premium collected: how far out the short strike sits, how wide the wings are, how
    long the position is held, and how much of the credit is taken before closing.
    """
    base = OverlayRunConfig(
        start=WINDOW_START,
        end=IN_SAMPLE_END,
        wing_policy="spec",
        min_credit_ratio=0.0010,
        slippage_rupees=0.25,
        roll_trigger_delta=0.99,  # ST-20 off: the baseline showed what it costs
        margin_model=MarginPerLotModel(include_expiry_day_elm=False),
        participation_volume_pct=0.05,
        participation_oi_pct=0.02,
    )
    specs: list[OverlayRunConfig] = []

    # Lever 1 — how much premium the short strike carries. The register stops at 0.14; the
    # search goes to 0.35 because the baseline's ceiling arithmetic says nothing inside the
    # register can reach the target, and the owner asked what would.
    for target, band in (
        (0.12, (0.10, 0.14)),
        (0.16, (0.14, 0.18)),
        (0.20, (0.18, 0.23)),
        (0.25, (0.22, 0.28)),
        (0.30, (0.27, 0.33)),
    ):
        specs.append(
            replace(
                base,
                short_delta_target=target,
                delta_band=band,
                label=f"delta{target:.2f}",
            )
        )

    # Lever 2 — wing width. Narrower wings cost less to buy (more credit kept) and carry
    # less defined risk (more lots for the same margin), at the price of a thinner buffer.
    for width in (150.0, 250.0, 350.0, 500.0):
        specs.append(replace(base, wing_width=width, label=f"wing{int(width)}"))

    # Lever 3 — tenor. Shorter holds collect less premium but decay faster; ST-3's 4-7 day
    # band is the register's, and 1-3 days is outside it.
    for dte in ((1, 2), (2, 3), (3, 4), (5, 6), (6, 7)):
        specs.append(replace(base, entry_dte=dte, label=f"dte{dte[0]}{dte[1]}"))

    # Lever 4 — when to take the money. A lower target closes more often for less; a higher
    # one holds for the tail of the decay curve.
    for take, stop in ((0.40, 1.5), (0.60, 1.5), (0.80, 1.5), (0.60, 1.0), (0.60, 2.0)):
        specs.append(
            replace(base, profit_take=take, stop_multiple=stop, label=f"take{take:.2f}_stop{stop}")
        )

    # Lever 5 — size. CA-14's cap is 2.5; the search reports what the target needs, which is
    # the number the owner has to decide about rather than one this study can choose.
    for gearing in (2.5, 5.0, 10.0):
        specs.append(replace(base, max_gearing=gearing, label=f"gearing{gearing:g}"))

    # The promising corners, crossed: premium x size x tenor.
    for target, band in ((0.20, (0.18, 0.23)), (0.30, (0.27, 0.33))):
        for gearing in (2.5, 10.0):
            for dte in ((2, 3), (5, 6)):
                specs.append(
                    replace(
                        base,
                        short_delta_target=target,
                        delta_band=band,
                        max_gearing=gearing,
                        entry_dte=dte,
                        label=f"cross_d{target:.2f}_g{gearing:g}_dte{dte[0]}{dte[1]}",
                    )
                )

    seen: set[str] = set()
    unique: list[OverlayRunConfig] = []
    for spec in specs:
        if spec.label in seen:
            continue
        seen.add(spec.label)
        unique.append(spec)
    return unique


def stage_two() -> list[OverlayRunConfig]:
    """The lever the first search missed: how much margin capacity the portfolio has at all.

    Stage one swept the *trade* — delta, width, tenor, targets — and the *gearing cap*, and
    found gearing 5 and gearing 10 producing identical results. That is the tell: the cap was
    never binding. What binds is CA-9's budget, which is a share of Margin Capacity, and
    Margin Capacity under the 50% rule is at most twice the cash-equivalent collateral. The
    section 8 portfolio holds 15% of itself in cash-equivalents, so Rs 1 crore of holdings
    supports Rs 28 lakh of margin and strands Rs 52 lakh of the rest.

    Raising that fraction is not a deviation from the requirements — it is CA-R2, which the
    document instructs the platform to *recommend* whenever non-cash collateral is stranded.
    At 50% cash-equivalent nothing is stranded and capacity is Rs 84.5 lakh: three times the
    position for the same portfolio, and the same trade.
    """
    base = OverlayRunConfig(
        start=WINDOW_START,
        end=IN_SAMPLE_END,
        wing_policy="spec",
        min_credit_ratio=0.0010,
        slippage_rupees=0.25,
        roll_trigger_delta=0.99,
        margin_model=MarginPerLotModel(include_expiry_day_elm=False),
        participation_volume_pct=0.05,
        participation_oi_pct=0.02,
        max_gearing=10.0,
    )
    specs: list[OverlayRunConfig] = []

    # The lever alone, at the structure stage one liked best.
    best = replace(base, short_delta_target=0.20, delta_band=(0.18, 0.23), entry_dte=(2, 3))
    for fraction in (0.15, 0.25, 0.35, 0.50):
        specs.append(
            replace(best, cash_equivalent_fraction=fraction, label=f"ce{int(fraction * 100)}")
        )

    # CA-9's own range, on an unstranded portfolio.
    for utilisation in (0.30, 0.35):
        specs.append(
            replace(
                best,
                cash_equivalent_fraction=0.50,
                target_utilisation=utilisation,
                label=f"ce50_util{int(utilisation * 100)}",
            )
        )

    # The structures worth carrying to the larger book, at the register's maximum budget.
    for target, band in (
        (0.12, (0.10, 0.14)),
        (0.16, (0.14, 0.18)),
        (0.20, (0.18, 0.23)),
        (0.25, (0.22, 0.28)),
        (0.30, (0.27, 0.33)),
    ):
        for dte in ((1, 2), (2, 3), (5, 6)):
            specs.append(
                replace(
                    base,
                    cash_equivalent_fraction=0.50,
                    target_utilisation=0.35,
                    short_delta_target=target,
                    delta_band=band,
                    entry_dte=dte,
                    label=f"full_d{target:.2f}_dte{dte[0]}{dte[1]}",
                )
            )

    # And the widest wing, which stage one found the best of its lever.
    specs.append(
        replace(
            base,
            cash_equivalent_fraction=0.50,
            target_utilisation=0.35,
            short_delta_target=0.20,
            delta_band=(0.18, 0.23),
            entry_dte=(2, 3),
            wing_width=500.0,
            label="full_d0.20_dte23_wing500",
        )
    )
    return specs


def stage_three() -> list[OverlayRunConfig]:
    """Past the lot cap, and out to the wings.

    Stage two removed the collateral constraint and found three configurations producing the
    same number, which is the same tell as before: something else is binding. It is CA-15's
    absolute lot cap of 50, whose allowed range runs to 200. Stage three lifts it and pushes
    the two levers that were still improving when stage two stopped — wing width, which was
    the largest single jump it found, and the short delta around 0.16-0.20.

    Every configuration here reports the gearing it actually used, because past this point
    the interesting question is no longer "what return" but "at what size, and is that size
    inside the document's own cap".
    """
    base = OverlayRunConfig(
        start=WINDOW_START,
        end=IN_SAMPLE_END,
        wing_policy="spec",
        min_credit_ratio=0.0010,
        slippage_rupees=0.25,
        roll_trigger_delta=0.99,
        margin_model=MarginPerLotModel(include_expiry_day_elm=False),
        participation_volume_pct=0.05,
        participation_oi_pct=0.02,
        max_gearing=10.0,
        cash_equivalent_fraction=0.50,
        target_utilisation=0.35,
        short_delta_target=0.20,
        delta_band=(0.18, 0.23),
        entry_dte=(2, 3),
        wing_width=500.0,
    )
    specs: list[OverlayRunConfig] = []
    for lots in (50, 100, 200):
        specs.append(replace(base, max_lots_absolute=lots, label=f"lots{lots}"))
    for width in (500.0, 700.0, 1000.0):
        specs.append(
            replace(
                base,
                max_lots_absolute=200,
                wing_width=width,
                label=f"lots200_wing{int(width)}",
            )
        )
    for target, band in ((0.16, (0.14, 0.18)), (0.20, (0.18, 0.23)), (0.25, (0.22, 0.28))):
        for dte in ((2, 3), (5, 6)):
            for width in (500.0, 700.0):
                specs.append(
                    replace(
                        base,
                        max_lots_absolute=200,
                        short_delta_target=target,
                        delta_band=band,
                        entry_dte=dte,
                        wing_width=width,
                        label=f"g_d{target:.2f}_dte{dte[0]}{dte[1]}_w{int(width)}",
                    )
                )
    # And the same winners held to the document's own gearing cap, to price the constraint.
    for gearing in (2.5, 5.0):
        specs.append(
            replace(
                base,
                max_lots_absolute=200,
                wing_width=700.0,
                max_gearing=gearing,
                label=f"capped_gearing{gearing:g}",
            )
        )
    seen: set[str] = set()
    unique: list[OverlayRunConfig] = []
    for spec in specs:
        if spec.label in seen:
            continue
        seen.add(spec.label)
        unique.append(spec)
    return unique


def stage_four() -> list[OverlayRunConfig]:
    """Is the winner a peak or a plateau, and what does it cost to execute?

    Stage three produced a configuration that reaches the target: 0.25 delta, two-to-three
    days to expiry, 500-point wings, on an unstranded portfolio at 8.4x gearing. A single
    configuration out of seventy-odd is exactly what a search produces whether or not
    anything is there, so this stage does the two things that separate the cases.

    **The neighbourhood.** A result that sits alone on a spike is a fit to this corpus; one
    that sits on a smooth rise with its neighbours nearby is a property of the trade. Delta,
    wing width and tenor are each stepped either side of the winner.

    **The execution.** The winner runs at roughly 54 lots — 3,500 units a leg — under caps
    that were loosened to 5% of a minute's volume. Slippage and the caps are stepped to see
    how much of the return survives a less friendly fill, because at this size that is the
    assumption doing the most work.
    """
    winner = OverlayRunConfig(
        start=WINDOW_START,
        end=IN_SAMPLE_END,
        wing_policy="spec",
        min_credit_ratio=0.0010,
        slippage_rupees=0.25,
        roll_trigger_delta=0.99,
        margin_model=MarginPerLotModel(include_expiry_day_elm=False),
        participation_volume_pct=0.05,
        participation_oi_pct=0.02,
        max_gearing=10.0,
        max_lots_absolute=200,
        cash_equivalent_fraction=0.50,
        target_utilisation=0.35,
        short_delta_target=0.25,
        delta_band=(0.22, 0.28),
        entry_dte=(2, 3),
        wing_width=500.0,
    )
    specs: list[OverlayRunConfig] = []

    for target in (0.22, 0.25, 0.28):
        for width in (400.0, 500.0, 600.0):
            specs.append(
                replace(
                    winner,
                    short_delta_target=target,
                    delta_band=(target - 0.03, target + 0.03),
                    wing_width=width,
                    label=f"n_d{target:.2f}_w{int(width)}",
                )
            )
    for dte in ((1, 2), (2, 3), (3, 4), (4, 5)):
        specs.append(replace(winner, entry_dte=dte, label=f"n_dte{dte[0]}{dte[1]}"))
    for slippage in (0.0, 0.25, 0.50, 1.00):
        specs.append(replace(winner, slippage_rupees=slippage, label=f"n_slip{slippage:g}"))
    for volume, oi in ((0.01, 0.005), (0.05, 0.02), (0.10, 0.05)):
        specs.append(
            replace(
                winner,
                participation_volume_pct=volume,
                participation_oi_pct=oi,
                label=f"n_caps{volume:g}",
            )
        )
    # Does ST-20 still destroy the trade at this delta, or was that a 0.12-delta effect?
    specs.append(replace(winner, roll_trigger_delta=0.40, label="n_roll_on_0.40"))
    # And the document's margin rule, at the winner's structure.
    specs.append(
        replace(winner, margin_model=MarginPerLotModel(include_expiry_day_elm=True), label="n_ca12")
    )
    specs.append(replace(winner, min_credit_ratio=0.0015, label="n_credit015"))

    seen: set[str] = set()
    unique: list[OverlayRunConfig] = []
    for spec in specs:
        if spec.label in seen:
            continue
        seen.add(spec.label)
        unique.append(spec)
    return unique


def stage_five() -> list[OverlayRunConfig]:
    """The same search, with the entry window counted in sessions rather than calendar days.

    Stage four's winner turned out to be a creature of the Thursday-expiry regime: NSE moved
    the NIFTY weekly to Tuesday in mid-2025, "two to three days before expiry" became the
    weekend, and the configuration stopped trading — 163 positions to August 2025 and one
    afterwards. A five-year annualised return hid a year of not trading, because a year of
    no positions looks like a year of no losses.

    Everything here is identical except that the entry window is expressed as sessions
    before expiry, which is invariant to the change. ST-3's 5-6 calendar days is 2-3
    sessions under either regime; stage four's 2-3 days is 1-2 sessions. The holdout matters
    more than usual for this stage, because the holdout is where the new regime lives.
    """
    base = OverlayRunConfig(
        start=WINDOW_START,
        end=IN_SAMPLE_END,
        wing_policy="spec",
        min_credit_ratio=0.0010,
        slippage_rupees=0.25,
        roll_trigger_delta=0.99,
        margin_model=MarginPerLotModel(include_expiry_day_elm=False),
        participation_volume_pct=0.05,
        participation_oi_pct=0.02,
        max_gearing=10.0,
        max_lots_absolute=200,
        cash_equivalent_fraction=0.50,
        target_utilisation=0.35,
        wing_width=500.0,
    )
    specs: list[OverlayRunConfig] = []
    for sessions in ((0, 1), (1, 2), (2, 3), (3, 4)):
        for target in (0.16, 0.20, 0.25):
            specs.append(
                replace(
                    base,
                    entry_sessions_before=sessions,
                    short_delta_target=target,
                    delta_band=(target - 0.03, target + 0.03),
                    label=f"s_sb{sessions[0]}{sessions[1]}_d{target:.2f}",
                )
            )
    # The best structures again at the two wing widths that led stage four.
    for width in (500.0, 600.0):
        for sessions in ((1, 2), (2, 3)):
            specs.append(
                replace(
                    base,
                    entry_sessions_before=sessions,
                    short_delta_target=0.22,
                    delta_band=(0.19, 0.25),
                    wing_width=width,
                    label=f"s_sb{sessions[0]}{sessions[1]}_d0.22_w{int(width)}",
                )
            )
    # And the document's own entry window, in session form, for comparison.
    specs.append(
        replace(
            base,
            entry_sessions_before=(2, 3),
            short_delta_target=0.12,
            delta_band=(0.10, 0.14),
            wing_width=350.0,
            max_gearing=2.5,
            label="s_spec_window_spec_delta",
        )
    )
    seen: set[str] = set()
    unique: list[OverlayRunConfig] = []
    for spec in specs:
        if spec.label in seen:
            continue
        seen.add(spec.label)
        unique.append(spec)
    return unique


def _run_one(config: OverlayRunConfig) -> dict[str, Any]:
    """One configuration, in-sample then out-of-sample, in a worker process."""
    scratch = Path(tempfile.mkdtemp(prefix="xman_tune_")) / "trials.db"
    payload: dict[str, Any] = {"label": config.label, "params": _params_of(config)}
    try:
        in_sample = run_overlay(replace(config, trial_log=scratch, end=IN_SAMPLE_END))
        payload["in_sample"] = _summary(in_sample.metrics)
        holdout = run_overlay(
            replace(
                config,
                trial_log=scratch,
                start=IN_SAMPLE_END + dt.timedelta(days=1),
                end=WINDOW_END,
            )
        )
        payload["out_of_sample"] = _summary(holdout.metrics)
    except Exception as error:
        payload["error"] = f"{type(error).__name__}: {error}"
    return payload


def _params_of(config: OverlayRunConfig) -> dict[str, Any]:
    params = asdict(config)
    params.pop("collateral", None)
    params["margin_model"] = config.margin_model.assumptions
    params["corpus_root"] = str(config.corpus_root)
    params["trial_log"] = str(config.trial_log)
    params["start"] = config.start.isoformat()
    params["end"] = config.end.isoformat()
    return params


def _summary(metrics: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "completed_cycles",
        "cycles_traded",
        "net_pnl_rupees",
        "return_on_pc_total",
        "return_on_pc_annualised",
        "max_drawdown_pct_of_pc",
        "win_rate",
        "sharpe_annualised",
        "mean_premium_capture",
        "allocated_gearing_mean",
        "allocated_gearing_max",
        "lots_mean",
        "gross_credit_rupees",
        "cost_ratio",
        "exit_rules",
    )
    return {key: metrics.get(key) for key in keys}


def log_trials(results: list[dict[str, Any]], *, trial_log: Path) -> None:
    """Write one canonical trial row per configuration, after the parallel batch.

    The runs happened in worker processes against scratch logs; this is their record in the
    log the repository counts. Without it a forty-configuration search would be invisible to
    the deflation machinery, which is precisely the number it needs.
    """
    from xman_research.overlay.run import _HYPOTHESIS

    session = open_session(trial_log)
    try:
        for result in results:
            with session.trial(
                _HYPOTHESIS,
                data_window=DataWindow(WINDOW_START, WINDOW_END),
                params={"tuning_arm": result["label"], **result["params"]},
                notes=(
                    "Tuning search, executed in research/overlay/tune.py worker processes; "
                    "this row records the run rather than performing it."
                ),
            ) as trial:
                trial.record_metrics(
                    {
                        f"in_sample.{key}": value
                        for key, value in (result.get("in_sample") or {}).items()
                        if not isinstance(value, dict)
                    }
                )
                trial.record_metrics(
                    {
                        f"out_of_sample.{key}": value
                        for key, value in (result.get("out_of_sample") or {}).items()
                        if not isinstance(value, dict)
                    }
                )
    finally:
        session.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--only", default=None, help="comma-separated labels")
    parser.add_argument("--no-canonical-log", action="store_true")
    parser.add_argument("--stage", type=int, default=1, choices=(1, 2, 3, 4, 5))
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)

    specs = {
        1: candidates,
        2: stage_two,
        3: stage_three,
        4: stage_four,
        5: stage_five,
    }[args.stage]()
    if args.only:
        wanted = set(args.only.split(","))
        specs = [spec for spec in specs if spec.label in wanted]

    results: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for payload in pool.map(_run_one, specs):
            results.append(payload)
            (args.out / "tuning.json").write_text(json.dumps(results, indent=2, default=str))
            print(_line(payload), flush=True)

    if not args.no_canonical_log:
        log_trials(results, trial_log=DEFAULT_TRIAL_LOG)
    print(f"\n{len(results)} configurations; target {TARGET_ANNUAL_RETURN:.0%} a year")
    reached = [
        row
        for row in results
        if (row.get("in_sample") or {}).get("return_on_pc_annualised") is not None
        and row["in_sample"]["return_on_pc_annualised"] >= TARGET_ANNUAL_RETURN
    ]
    print(f"reached in-sample: {len(reached)}")
    return 0


def _line(payload: dict[str, Any]) -> str:
    if "error" in payload:
        return f"{payload['label']:28s} FAILED {payload['error'][:80]}"
    inside = payload.get("in_sample") or {}
    outside = payload.get("out_of_sample") or {}

    def pct(value: float | None) -> str:
        return "  n/a " if value is None else f"{value:6.2%}"

    return (
        f"{payload['label']:28s} IS {pct(inside.get('return_on_pc_annualised'))}/yr "
        f"dd {pct(inside.get('max_drawdown_pct_of_pc'))} n={inside.get('completed_cycles')!s:>4} "
        f"| OOS {pct(outside.get('return_on_pc_annualised'))}/yr "
        f"dd {pct(outside.get('max_drawdown_pct_of_pc'))} "
        f"| gearing {inside.get('allocated_gearing_mean') or 0:.1f}x"
    )


if __name__ == "__main__":
    raise SystemExit(main())
