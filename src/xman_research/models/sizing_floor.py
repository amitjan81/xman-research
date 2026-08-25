"""M1 §12.1 — the sizing-floor check, which the spec requires to be RUN, not assumed.

The rule under test is::

    min_t  N* / (S_t,tau * L_t)  >=  0.5

Because ``floor(x + 1/2) >= 1 <=> x >= 0.5``, a passing check means no session reaches
M1 §5's ``n_t = 0`` branch and M1 §4's corresponding suppression never fires on the
window. That is what makes the two clauses belt-and-braces rather than contradictory, and
it is what removes the one channel by which *which sessions trade* could still depend on
the contract multiplier.

**Two lot sizes are reported, and that is not redundancy.**

M1 §12.1 names ``LotSizeAudit.reference_lot_size`` — the bars-supported multiplier — and
explains why: the declared value is contradicted by the session's own volume on 1,077 of
the corpus's 1,233 sessions, and running the check on the declared value would verify the
wrong quantity on precisely the sessions that motivated the rule.

But ``engine.py`` sizes on the **declared** value. Its own comment says so, citing the
owner decision of 2026-08-13 that turned an unoverridable refusal into a stamp, and
``Contract.lot_size`` is read verbatim from the refdata ``LotSize`` column. Since ``n_t``
falls as ``L`` rises, on any session where declared exceeds reference the engine computes
a *smaller* ``n_t`` than the quantity §12.1 verifies. The spec's check can therefore pass
while the engine still reaches the zero branch.

So both minima are computed and both are reported. The spec's check is the one that
grades — it is what §12.1 names — and the declared-value minimum is reported beside it as
the check that actually protects the run. A discrepancy between them is a finding about
the spec, not a licence to substitute one for the other.

**This reads prices.** ``S_t,tau`` is a spot close, so unlike H26's gap census — which was
date arithmetic and bar *presence* only — this check opens the envelope. It is run over
the graded in-sample window alone and never over the sealed holdout; if the holdout is
ever spent, §12.1 re-executes over the holdout window at that moment and not before.

Run: ``uv run python -m xman_research.models.sizing_floor``
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
from dataclasses import dataclass
from pathlib import Path

from xman_research.backtest.lot_size import audit_lot_size
from xman_research.backtest.market import SessionView
from xman_research.session_store import SessionStore

__all__ = [
    "DECISION_TIME",
    "REQUIRED_RATIO",
    "SessionSizing",
    "SizingFloorReport",
    "check_sizing_floor",
]

#: M1 §12: the decision minute, post-open and pre-drift.
DECISION_TIME = dt.time(9, 20)

#: M1 §12.1: ``floor(x + 1/2) >= 1`` exactly when ``x >= 0.5``.
REQUIRED_RATIO = 0.5


@dataclass(frozen=True, slots=True)
class SessionSizing:
    """One session's contribution to the check, on both lot-size readings."""

    session_date: dt.date
    spot: float
    reference_lot_size: int
    declared_lot_size: int
    contradicts_declared: bool
    #: Kept on the row, not only in the report header, so a serialised row is
    #: self-describing rather than needing its header read alongside it.
    target_notional: float

    def ratio(self, lot_size: int) -> float:
        return self.target_notional / (self.spot * lot_size)

    @property
    def reference_ratio(self) -> float:
        return self.ratio(self.reference_lot_size)

    @property
    def declared_ratio(self) -> float:
        return self.ratio(self.declared_lot_size)

    @property
    def reference_lots(self) -> int:
        return math.floor(self.reference_ratio + 0.5)

    @property
    def declared_lots(self) -> int:
        return math.floor(self.declared_ratio + 0.5)

    def as_dict(self) -> dict[str, object]:
        return {
            "session_date": self.session_date.isoformat(),
            "spot": self.spot,
            "reference_lot_size": self.reference_lot_size,
            "declared_lot_size": self.declared_lot_size,
            "contradicts_declared": self.contradicts_declared,
            "reference_ratio": self.reference_ratio,
            "declared_ratio": self.declared_ratio,
            "reference_lots": self.reference_lots,
            "declared_lots": self.declared_lots,
        }


@dataclass(frozen=True, slots=True)
class SizingFloorReport:
    """The check's verdict over a window, with the binding session named."""

    underlying: str
    start: dt.date
    end: dt.date
    target_notional: float
    rows: tuple[SessionSizing, ...]
    sessions_without_spot: tuple[dt.date, ...]

    @property
    def minimum_reference(self) -> SessionSizing:
        return min(self.rows, key=lambda row: row.reference_ratio)

    @property
    def minimum_declared(self) -> SessionSizing:
        return min(self.rows, key=lambda row: row.declared_ratio)

    @property
    def passed(self) -> bool:
        """M1 §12.1 as written: the check is over ``reference_lot_size``."""
        return bool(self.rows) and self.minimum_reference.reference_ratio >= REQUIRED_RATIO

    @property
    def passed_on_declared(self) -> bool:
        """The same arithmetic on the multiplier the engine actually sizes with."""
        return bool(self.rows) and self.minimum_declared.declared_ratio >= REQUIRED_RATIO

    @property
    def zero_sized_sessions_declared(self) -> tuple[dt.date, ...]:
        return tuple(row.session_date for row in self.rows if row.declared_lots == 0)

    def as_dict(self) -> dict[str, object]:
        minimum_reference = self.minimum_reference
        minimum_declared = self.minimum_declared
        return {
            "check": "M1 §12.1 sizing floor",
            "underlying": self.underlying,
            "window": f"{self.start.isoformat()}..{self.end.isoformat()}",
            "decision_time": DECISION_TIME.isoformat(),
            "target_notional": self.target_notional,
            "required_ratio": REQUIRED_RATIO,
            "sessions_checked": len(self.rows),
            "sessions_without_spot": [day.isoformat() for day in self.sessions_without_spot],
            "passed": self.passed,
            "minimum_reference_ratio": minimum_reference.reference_ratio,
            "minimum_reference_session": minimum_reference.session_date.isoformat(),
            "minimum_reference_detail": minimum_reference.as_dict(),
            "passed_on_declared": self.passed_on_declared,
            "minimum_declared_ratio": minimum_declared.declared_ratio,
            "minimum_declared_session": minimum_declared.session_date.isoformat(),
            "minimum_declared_detail": minimum_declared.as_dict(),
            "zero_sized_sessions_declared": [
                day.isoformat() for day in self.zero_sized_sessions_declared
            ],
        }

    def summary(self) -> str:
        minimum_reference = self.minimum_reference
        minimum_declared = self.minimum_declared
        lines = [
            f"M1 §12.1 sizing floor — {self.underlying} "
            f"{self.start.isoformat()}..{self.end.isoformat()}",
            f"  N* = {self.target_notional:,.0f}   required ratio >= {REQUIRED_RATIO}",
            f"  sessions checked: {len(self.rows)}",
            f"  AS SPECIFIED (reference_lot_size): "
            f"{'PASS' if self.passed else 'FAIL'}  min ratio "
            f"{minimum_reference.reference_ratio:.4f} on "
            f"{minimum_reference.session_date.isoformat()} "
            f"(spot {minimum_reference.spot:,.2f}, L={minimum_reference.reference_lot_size})",
            f"  AS EXECUTED  (declared lot size): "
            f"{'PASS' if self.passed_on_declared else 'FAIL'}  min ratio "
            f"{minimum_declared.declared_ratio:.4f} on "
            f"{minimum_declared.session_date.isoformat()} "
            f"(spot {minimum_declared.spot:,.2f}, L={minimum_declared.declared_lot_size})",
        ]
        if self.sessions_without_spot:
            lines.append(
                f"  sessions the index printed no bar on: {len(self.sessions_without_spot)}"
            )
        zeroed = self.zero_sized_sessions_declared
        if zeroed:
            lines.append(f"  sessions the ENGINE would size to zero: {len(zeroed)}")
        return "\n".join(lines)


def check_sizing_floor(
    *,
    store: SessionStore,
    underlying: str,
    start: dt.date,
    end: dt.date,
    target_notional: float,
    gap_reason: str,
) -> SizingFloorReport:
    """Run M1 §12.1 over every resolvable session in ``[start, end]``.

    ``gap_reason`` is required rather than optional: the window this check must cover has
    known holes, and the store's rule is that proceeding over them costs a written reason.
    Defaulting it would make the check quietly weaker than the run it gates.
    """
    resolution = store.resolve(underlying, start, end)
    refs = resolution.sessions() if resolution.is_complete else resolution.accept_gaps(gap_reason)

    rows: list[SessionSizing] = []
    without_spot: list[dt.date] = []
    for ref in refs:
        frame = store.load_session(ref)
        refdata = store.load_refdata(ref)
        audit = audit_lot_size(
            session_date=ref.session_date,
            underlying=underlying,
            frame=frame,
            refdata=refdata,
        )
        session = SessionView.from_frame(ref.session_date, underlying, frame, refdata)
        minute = session.minute_at_or_after(DECISION_TIME)
        spot = session.spot_at(minute) if minute is not None else None
        if spot is None or spot <= 0.0:
            without_spot.append(ref.session_date)
            continue
        declared = audit.declared_lot_sizes[0] if audit.declared_lot_sizes else 0
        if declared <= 0 or audit.reference_lot_size <= 0:
            without_spot.append(ref.session_date)
            continue
        rows.append(
            SessionSizing(
                session_date=ref.session_date,
                spot=float(spot),
                reference_lot_size=audit.reference_lot_size,
                declared_lot_size=declared,
                contradicts_declared=audit.contradicts_declared,
                target_notional=target_notional,
            )
        )
    return SizingFloorReport(
        underlying=underlying,
        start=start,
        end=end,
        target_notional=target_notional,
        rows=tuple(rows),
        sessions_without_spot=tuple(without_spot),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run M1 §12.1 over a window.")
    parser.add_argument("--start", default="2024-10-01")
    parser.add_argument("--end", default="2026-04-30")
    parser.add_argument("--underlying", default="NIFTY")
    parser.add_argument("--target-notional", type=float, default=1_500_000.0)
    parser.add_argument("--json-out", default=None)
    parser.add_argument(
        "--gap-reason",
        default=(
            "M1 §12.1 pre-registration check over the graded window. The window has three "
            "known holes — 2024-11-20, 2025-04-30 and 2025-05-08 — and the check is run "
            "over the sessions that exist rather than narrowed to avoid them."
        ),
    )
    arguments = parser.parse_args()
    report = check_sizing_floor(
        store=SessionStore(),
        underlying=arguments.underlying,
        start=dt.date.fromisoformat(arguments.start),
        end=dt.date.fromisoformat(arguments.end),
        target_notional=arguments.target_notional,
        gap_reason=arguments.gap_reason,
    )
    print(report.summary())
    if arguments.json_out:
        Path(arguments.json_out).write_text(
            json.dumps(report.as_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    main()
