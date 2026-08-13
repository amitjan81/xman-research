"""The refusals: pre-recorded thresholds, epoch boundaries, and the untouched holdout.

Three disciplines that a research platform normally keeps as habits, made into conditions
that code checks:

* **Thresholds are written down before the run.** Not "we intended 0.95" after seeing
  0.93. The gate is a file with a ``recorded_at`` in it, and grading is refused when that
  timestamp is not strictly before the run being graded.
* **A window that crosses a structural break is not one market.** Six dated breaks since
  October 2024 changed the cost of trading Indian options, what may be traded, and when it
  expires. A single number over a window spanning two of them describes a market that
  never existed, so grading is refused without a recorded justification.
* **The holdout is months nobody has read.** Whether that is still true is answerable —
  from the trial log, by asking which logged evaluations had a window reaching into it —
  rather than a claim the researcher makes about their own behaviour.

All three raise. **A refusal is not a verdict**: "we cannot grade this" and "this is not
evaluable" are different statements, and collapsing them would let a process failure be
recorded as a property of the strategy (see :mod:`xman_research.validation.decision`).
"""

from __future__ import annotations

import datetime as dt
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from xman_research.clock import require_aware
from xman_research.evaluation import ResearchSession
from xman_research.hypothesis import HypothesisRecord
from xman_research.trial_log import DataWindow, TrialLog

__all__ = [
    "EPOCH_BOUNDARIES",
    "EPOCH_PROVENANCE_STAMP",
    "CrossEpochWindowError",
    "DecisionGate",
    "Direction",
    "EpochAnnotation",
    "EpochBoundary",
    "GateBindingError",
    "HoldoutPolicy",
    "HoldoutStatus",
    "HoldoutTouchedError",
    "NotEvaluableRules",
    "Threshold",
    "ThresholdResult",
    "ThresholdsNotRecordedError",
    "epochs_spanned",
    "inspect_holdout",
]

# Every date here is transcribed from secondary sources — broker rate cards, exchange
# notices as reported, and the platform's own research notes. Spec §9 lists verification
# against primary circulars as an open item that gates C3, and until that is closed every
# result annotated with these dates carries the stamp below. An epoch table that is wrong
# by a week does not fail loudly: it silently pools two regimes, or splits one.
EPOCH_PROVENANCE_STAMP = "epochs.dates_not_primary_sourced"


@dataclass(frozen=True, slots=True)
class EpochBoundary:
    """A date on which the Indian F&O market stopped being the same market."""

    name: str
    effective_from: dt.date
    description: str
    source: str
    confidence: str = "secondary"

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "effective_from": self.effective_from.isoformat(),
            "description": self.description,
            "source": self.source,
            "confidence": self.confidence,
        }


EPOCH_BOUNDARIES: tuple[EpochBoundary, ...] = (
    EpochBoundary(
        name="stt_rise_2024",
        effective_from=dt.date(2024, 10, 1),
        description="Securities transaction tax on options and futures raised.",
        source="Finance (No. 2) Act 2024, as reported in broker rate cards",
    ),
    EpochBoundary(
        name="weekly_expiry_cull_2024",
        effective_from=dt.date(2024, 11, 20),
        description=(
            "Weekly expiries cut to one per exchange, contract size raised, and extra "
            "margin applied on expiry day."
        ),
        source="SEBI measures on index derivatives, October 2024, as reported",
    ),
    EpochBoundary(
        name="calendar_spread_relief_removed_2025",
        effective_from=dt.date(2025, 2, 10),
        description="Calendar-spread margin relief withdrawn on expiry-day positions.",
        source="SEBI measures on index derivatives, phase 2, as reported",
    ),
    EpochBoundary(
        name="intraday_position_limits_2025",
        effective_from=dt.date(2025, 4, 1),
        description="Intraday monitoring of index-derivative position limits began.",
        source="SEBI measures on index derivatives, phase 3, as reported",
    ),
    EpochBoundary(
        name="nse_expiry_tuesday_2025",
        effective_from=dt.date(2025, 9, 1),
        description="NSE weekly and monthly expiry moved from Thursday to Tuesday.",
        source="NSE circular on expiry-day change, as reported",
    ),
    EpochBoundary(
        name="stt_rise_2026",
        effective_from=dt.date(2026, 4, 1),
        description="Securities transaction tax on options raised again.",
        source="Finance Act 2026, as reported in broker rate cards",
    ),
)


class CrossEpochWindowError(RuntimeError):
    """Raised when a window spans a structural break with no recorded justification."""


class ThresholdsNotRecordedError(RuntimeError):
    """Raised when the decision criteria were not written down before the run."""


class GateBindingError(RuntimeError):
    """Raised when the gate file and the registered hypothesis disagree."""


class HoldoutTouchedError(RuntimeError):
    """Raised when the holdout months have already been read."""


@dataclass(frozen=True, slots=True)
class EpochAnnotation:
    """Which regimes a window spans, and whether pooling them was justified in writing."""

    window: DataWindow
    boundaries_crossed: tuple[EpochBoundary, ...]
    regimes: tuple[str, ...]
    justification: str | None = None

    @property
    def crosses_boundary(self) -> bool:
        return bool(self.boundaries_crossed)

    def require_justification(self) -> None:
        """Refuse a cross-epoch window that nobody argued for."""
        if self.crosses_boundary and not (self.justification or "").strip():
            names = ", ".join(
                f"{boundary.name} ({boundary.effective_from})"
                for boundary in self.boundaries_crossed
            )
            raise CrossEpochWindowError(
                f"the window {self.window} crosses {len(self.boundaries_crossed)} structural "
                f"break(s): {names}. A single statistic over it pools regimes that are not "
                "the same market, so it describes a market that never existed. Record a "
                "cross_epoch_justification in the gate file, or split the window."
            )

    def as_dict(self) -> dict[str, object]:
        return {
            "window": str(self.window),
            "regimes": list(self.regimes),
            "boundaries_crossed": [boundary.as_dict() for boundary in self.boundaries_crossed],
            "cross_epoch_justification": self.justification,
            "epoch_provenance": EPOCH_PROVENANCE_STAMP,
        }


def epochs_spanned(
    window: DataWindow,
    *,
    justification: str | None = None,
    boundaries: tuple[EpochBoundary, ...] = EPOCH_BOUNDARIES,
) -> EpochAnnotation:
    """Annotate ``window`` with the regimes it touches.

    A boundary is *crossed* when it takes effect after the window opens and on or before
    it closes — a window starting exactly on a boundary date sits wholly inside the new
    regime and crosses nothing.
    """
    crossed = tuple(
        boundary for boundary in boundaries if window.start < boundary.effective_from <= window.end
    )
    edges = [boundary.effective_from for boundary in boundaries]
    regimes: list[str] = []
    starts = [window.start, *[edge for edge in edges if window.start < edge <= window.end]]
    for index, start in enumerate(starts):
        end = starts[index + 1] - dt.timedelta(days=1) if index + 1 < len(starts) else window.end
        regimes.append(f"{start.isoformat()}..{end.isoformat()}")
    return EpochAnnotation(
        window=window,
        boundaries_crossed=crossed,
        regimes=tuple(regimes),
        justification=justification,
    )


class Direction(StrEnum):
    """Which way a threshold binds."""

    AT_LEAST = "at_least"
    AT_MOST = "at_most"


@dataclass(frozen=True, slots=True)
class Threshold:
    """One decision criterion, as written down before the run."""

    metric: str
    direction: Direction
    value: float

    def check(self, observed: float | None) -> ThresholdResult:
        """Compare ``observed``. A missing metric **fails** — it never passes by absence."""
        if observed is None:
            return ThresholdResult(self, None, passed=False, missing=True)
        passed = (
            observed >= self.value
            if self.direction is Direction.AT_LEAST
            else observed <= self.value
        )
        return ThresholdResult(self, float(observed), passed=passed, missing=False)

    def __str__(self) -> str:
        symbol = ">=" if self.direction is Direction.AT_LEAST else "<="
        return f"{self.metric} {symbol} {self.value:g}"


@dataclass(frozen=True, slots=True)
class ThresholdResult:
    """A threshold and what the run actually did against it."""

    threshold: Threshold
    observed: float | None
    passed: bool
    missing: bool

    def __str__(self) -> str:
        if self.missing:
            return f"{self.threshold} — NOT REPORTED (fails)"
        outcome = "pass" if self.passed else "FAIL"
        return f"{self.threshold} — observed {self.observed:.4g} ({outcome})"

    def as_dict(self) -> dict[str, object]:
        return {
            "metric": self.threshold.metric,
            "direction": str(self.threshold.direction),
            "required": self.threshold.value,
            "observed": self.observed,
            "passed": self.passed,
            "missing": self.missing,
        }


@dataclass(frozen=True, slots=True)
class NotEvaluableRules:
    """When the honest answer is about execution rather than about the edge.

    Spec §6's fourth outcome. These are checked *before* the thresholds, because a run
    whose real problem is that a tenth of its intents could not have been filled has not
    failed a threshold — it has not been measured.
    """

    max_infeasible_fraction: float = 0.10
    max_stale_fraction: float = 0.20
    optimistic_costs_below: float = 1.0
    """Cost-breakeven at or below this multiple, while cost inputs are unverified, means
    the result survives only at optimistic costs. Default 1.0 — the strategy is under
    water at the modelled rates and only a *lower* cost estimate saves it."""

    def as_dict(self) -> dict[str, object]:
        return {
            "max_infeasible_fraction": self.max_infeasible_fraction,
            "max_stale_fraction": self.max_stale_fraction,
            "optimistic_costs_below": self.optimistic_costs_below,
        }


@dataclass(frozen=True, slots=True)
class DecisionGate:
    """The thresholds, when they were recorded, and what they were recorded against.

    Constructed from a file. There is deliberately no constructor that takes thresholds
    and defaults ``recorded_at`` to now: that is the shape which lets a threshold be
    written after the number it judges.
    """

    thresholds: tuple[Threshold, ...]
    recorded_at: dt.datetime
    source: str
    hypothesis_id: str | None = None
    cross_epoch_justification: str | None = None
    rules: NotEvaluableRules = NotEvaluableRules()
    holdout_thresholds: tuple[Threshold, ...] = ()
    """Optional separate criteria for the one run against the holdout months.

    Not a loophole — a statistical necessity, and it has to be written down beforehand
    like everything else. The holdout is a *short* sample: a deflated-Sharpe bar of 0.95
    calibrated against four years of evidence needs a per-period Sharpe near 0.2 to clear
    on six months, which no plausible strategy has. Applying the in-sample bar to a sixth
    of the evidence does not make the holdout stricter, it makes it auto-fail, and an
    auto-failing holdout tells the operator nothing.

    Left empty, the in-sample thresholds are used — which is the right default only when
    the holdout is long enough to carry them."""

    def __post_init__(self) -> None:
        if not self.thresholds:
            raise ThresholdsNotRecordedError(
                f"{self.source} records no thresholds. A run with no criteria cannot be "
                "failed, and a criterion invented after the result is not a criterion."
            )
        require_aware(self.recorded_at, f"{self.source}: recorded_at")

    @classmethod
    def from_file(cls, path: Path | str) -> DecisionGate:
        """Read a gate from TOML. See the module docstring for the shape.

        ``recorded_at`` must be a TOML offset date-time — a bare local date-time is
        refused, because "09:00" without an offset is not a moment.
        """
        path = Path(path)
        if not path.exists():
            raise ThresholdsNotRecordedError(
                f"no thresholds file at {path}. Thresholds are written down before the "
                "run; there is nothing to grade against."
            )
        with path.open("rb") as handle:
            document = tomllib.load(handle)
        recorded_at = document.get("recorded_at")
        if not isinstance(recorded_at, dt.datetime):
            raise ThresholdsNotRecordedError(
                f"{path} has no recorded_at timestamp (found {recorded_at!r}). Without one "
                "there is no evidence the thresholds predate the run."
            )
        thresholds = _parse_thresholds(document.get("thresholds", {}), source=str(path))
        holdout_thresholds = _parse_thresholds(
            document.get("holdout_thresholds", {}), source=f"{path} [holdout_thresholds]"
        )
        rules_document = document.get("not_evaluable", {})
        return cls(
            thresholds=thresholds,
            recorded_at=recorded_at,
            source=str(path),
            hypothesis_id=document.get("hypothesis_id"),
            cross_epoch_justification=document.get("cross_epoch_justification"),
            holdout_thresholds=holdout_thresholds,
            rules=NotEvaluableRules(
                max_infeasible_fraction=float(rules_document.get("max_infeasible_fraction", 0.10)),
                max_stale_fraction=float(rules_document.get("max_stale_fraction", 0.20)),
                optimistic_costs_below=float(rules_document.get("optimistic_costs_below", 1.0)),
            ),
        )

    def thresholds_in_force(self, *, holdout: bool) -> tuple[Threshold, ...]:
        """The criteria this run is judged against — see :attr:`holdout_thresholds`."""
        if holdout and self.holdout_thresholds:
            return self.holdout_thresholds
        return self.thresholds

    def threshold_for(self, metric: str) -> Threshold | None:
        for threshold in self.thresholds:
            if threshold.metric == metric:
                return threshold
        return None

    def require_recorded_before(self, moment: dt.datetime | None, *, what: str) -> None:
        """Refuse to grade a run that predates its own criteria.

        ``moment`` is when the run happened — the trial's ``created_at``, for a run that
        came through the log. ``None`` is refused rather than waved through: a run that
        cannot say when it happened cannot show that it happened after the thresholds.
        """
        if moment is None:
            raise ThresholdsNotRecordedError(
                f"{what} carries no run timestamp, so the thresholds in {self.source} "
                "cannot be shown to predate it. Grade a run that came through the trial "
                "log, or record its run_at."
            )
        require_aware(moment, f"{what}: run_at")
        if self.recorded_at >= moment:
            raise ThresholdsNotRecordedError(
                f"the thresholds in {self.source} were recorded at {self.recorded_at.isoformat()}, "
                f"which is not before {what} ran at {moment.isoformat()}. Thresholds written "
                "after the run are not thresholds."
            )

    def check_binding(self, record: HypothesisRecord) -> None:
        """Refuse a gate that disagrees with the hypothesis's immutable thresholds.

        :class:`~xman_research.hypothesis.HypothesisRecord` is content-addressed and
        immutable, so the thresholds registered with it cannot be edited after the fact.
        Requiring the gate file to agree with them is what stops the file — which *is*
        editable — from being the loophole around that.
        """
        if self.hypothesis_id is not None and self.hypothesis_id != record.id:
            raise GateBindingError(
                f"{self.source} is bound to hypothesis {self.hypothesis_id!r}, but the run "
                f"being graded is filed under {record.id!r}."
            )
        for metric, expected in record.thresholds.items():
            if not isinstance(expected, int | float):
                continue
            threshold = self.threshold_for(metric)
            if threshold is None:
                raise GateBindingError(
                    f"the hypothesis registered a threshold on {metric!r} and {self.source} "
                    "does not carry it. The gate must grade every criterion the hypothesis "
                    "was registered with."
                )
            if not _close(float(expected), threshold.value):
                raise GateBindingError(
                    f"{metric}: the hypothesis was registered with {expected} and "
                    f"{self.source} says {threshold.value}. One of them was changed after "
                    "the fact; the registered record is the one that cannot have been."
                )

    def as_dict(self) -> dict[str, object]:
        return {
            "source": self.source,
            "recorded_at": self.recorded_at.isoformat(),
            "hypothesis_id": self.hypothesis_id,
            "thresholds": [str(threshold) for threshold in self.thresholds],
            "holdout_thresholds": [str(threshold) for threshold in self.holdout_thresholds],
            "cross_epoch_justification": self.cross_epoch_justification,
            "not_evaluable_rules": self.rules.as_dict(),
        }


def _parse_thresholds(document: Mapping[str, object], *, source: str) -> tuple[Threshold, ...]:
    thresholds: list[Threshold] = []
    for metric, specification in document.items():
        if not isinstance(specification, Mapping):
            raise ThresholdsNotRecordedError(
                f"{source}: threshold {metric!r} must say which way it binds, as "
                f"{{ at_least = x }} or {{ at_most = x }}; got {specification!r}"
            )
        directions = [direction for direction in Direction if str(direction) in specification]
        if len(directions) != 1:
            raise ThresholdsNotRecordedError(
                f"{source}: threshold {metric!r} must carry exactly one of at_least / "
                f"at_most, found {sorted(specification)}"
            )
        thresholds.append(
            Threshold(
                metric=metric,
                direction=directions[0],
                value=float(specification[str(directions[0])]),
            )
        )
    return tuple(thresholds)


def _close(left: float, right: float) -> bool:
    return abs(left - right) <= 1e-12 * max(1.0, abs(left), abs(right))


@dataclass(frozen=True, slots=True)
class HoldoutPolicy:
    """The months nothing reads until the end, as a date nothing may cross.

    There is no sandbox and no access control (spec §1.2 defers both). What there is: a
    boundary written down once, and a question about it that the log can answer.
    """

    first_date: dt.date
    label: str = "holdout"

    def contains(self, window: DataWindow) -> bool:
        return window.end >= self.first_date

    def as_dict(self) -> dict[str, object]:
        return {"holdout_first_date": self.first_date.isoformat(), "holdout_label": self.label}


@dataclass(frozen=True, slots=True)
class HoldoutStatus:
    """The answer to *has the holdout been touched* — evidence, not a self-report."""

    policy: HoldoutPolicy
    touched: bool
    touching_trial_ids: tuple[str, ...]
    first_touch_at: dt.datetime | None
    furthest_window_end: dt.date | None

    def require_untouched(self) -> None:
        if self.touched:
            raise HoldoutTouchedError(
                f"the holdout from {self.policy.first_date} has already been read by "
                f"{len(self.touching_trial_ids)} logged evaluation(s), the first at "
                f"{self.first_touch_at.isoformat() if self.first_touch_at else 'unknown'} "
                f"({', '.join(self.touching_trial_ids[:3])}). It cannot be unseen, and a "
                "holdout result computed after it was looked at is an in-sample result."
            )

    def as_dict(self) -> dict[str, object]:
        return {
            "holdout_touched": self.touched,
            "holdout_touching_trial_ids": list(self.touching_trial_ids),
            "holdout_first_touch_at": (
                self.first_touch_at.isoformat() if self.first_touch_at else None
            ),
            "holdout_furthest_window_end": (
                self.furthest_window_end.isoformat() if self.furthest_window_end else None
            ),
            **self.policy.as_dict(),
        }


def inspect_holdout(
    source: ResearchSession | TrialLog,
    hypothesis: HypothesisRecord | str,
    *,
    policy: HoldoutPolicy,
) -> HoldoutStatus:
    """Ask the log whether any evaluation has read into the holdout months.

    Every evaluation records the window it ran over, so *has the holdout been touched*
    reduces to *is there a logged trial whose window reaches past the boundary* — a
    question about recorded evidence rather than about anyone's memory.

    What it cannot see: an evaluation that never went through the log at all, and a run
    against a different database (which is why the database is pinned in configuration).
    A negative answer is therefore "no trace of a touch", not "definitely untouched", and
    that is the strongest statement available without the sandbox spec §1.2 defers.
    """
    log = source.log if isinstance(source, ResearchSession) else source
    hypothesis_id = hypothesis.id if isinstance(hypothesis, HypothesisRecord) else hypothesis
    touching = [
        record
        for record in log.family_trials(hypothesis_id)
        if record.data_window.end >= policy.first_date
    ]
    furthest = max(
        (record.data_window.end for record in log.family_trials(hypothesis_id)),
        default=None,
    )
    return HoldoutStatus(
        policy=policy,
        touched=bool(touching),
        touching_trial_ids=tuple(record.trial_id for record in touching),
        first_touch_at=min((record.created_at for record in touching), default=None),
        furthest_window_end=furthest,
    )
