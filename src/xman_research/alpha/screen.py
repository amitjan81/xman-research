"""Stage one of the two-stage alpha protocol: screen many candidates, rank, hand off.

**What this automates and what it deliberately does not.** The owner's protocol has two
stages. Stage one runs a wide set of template-and-parameter instances over an in-sample
window and orders them by how much they beat an unconditional benchmark. Stage two takes a
handful of survivors to a pre-registered gate with a sealed holdout — the machinery in
:mod:`xman_research.validation` — and only that stage produces a verdict. This module is
stage one, entirely. It computes point estimates, ranks them, and stops. It grades nothing.

**Why a screen is honest only if it counts itself.** Ranking a hundred instances by
in-sample Sharpe and taking the best is exactly the procedure a deflated Sharpe exists to
discount, and the discount is a function of how many instances were tried. So every run
here is appended to the trial log against the screening hypothesis before its number is
read, and :attr:`ScreenSheet.n_trials_logged` reports the total on the face of the sheet. A
stage-two gate filed against the same hypothesis family therefore deflates against the
whole screen automatically — which is the intended arrangement, and the reason a family
trial count in the hundreds is a working screen rather than a bug.

**Alpha here is a spread over a benchmark, not a profit.** ``alpha`` is the annualised
Sharpe of the candidate's per-session return series minus the benchmark's, aligned session
by session. Costs are inside both series and are stamped on every row, but they are not the
gate: the question stage one asks is whether the conditioner or the structure adds anything
over trading unconditionally, and a cost model that shifts both series equally cannot
change that answer.

**A session the candidate sat out is a zero, not a missing observation.** A conditional
instance that declines to enter still carries a daily record with flat equity, so it is
present in its own return series as a real zero. That is what keeps the comparison honest:
measuring a conditional candidate only on the days it chose to trade would flatter every
conditioner by the same amount, and a bias that survives comparison is worse than noise.
Because of it the two series cover identical sessions by construction, and
:func:`_excess_series` refuses a pair that does not rather than filling the difference.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import itertools
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from xman_research.adapter import evidence_from_result
from xman_research.alpha.features import (
    AsOfNotASessionError,
    FeatureBuilder,
    InsufficientHistoryError,
)
from xman_research.alpha.library import EvidenceCard
from xman_research.alpha.templates import (
    HOLD_SESSIONS,
    StrategyTemplate,
    TemplateRegistry,
    parameter_key,
)
from xman_research.backtest.engine import BacktestConfig, BacktestResult, run_backtest
from xman_research.clock import Clock, SystemClock
from xman_research.code_version import CodeVersionProvider, GitCodeVersion
from xman_research.evaluation import ResearchSession
from xman_research.hypothesis import HypothesisRecord
from xman_research.session_store import SessionStore, SessionStoreError
from xman_research.trial_log import DataWindow, TrialLog
from xman_research.validation.series import ReturnSeries, RunEvidence, SeriesError
from xman_research.validation.statistics import (
    BenchmarkMismatchError,
    annualised_sharpe_ratio,
    drawdown,
    risk_matched_increment,
)

__all__ = [
    "SCREEN_SHEET_SCHEMA_VERSION",
    "CandidateInstance",
    "CandidateSpec",
    "ScreenSheet",
    "ScreenedInstance",
    "ScreeningRun",
    "ScreeningRunError",
    "evidence_card_from_screen",
    "feature_pass",
    "load_screen_sheet",
    "replace_gap_reason",
]

SCREEN_SHEET_SCHEMA_VERSION = 1

#: The outcome recorded on a screened instance the run could measure. Not a verdict — no
#: threshold was applied and none was pre-registered. The word a stage-two gate uses for a
#: pass is deliberately not this one.
SCREENED = "screened"

#: The outcome of an instance whose entry rules refused every session in the window. Its own
#: return series is flat, but its *spread* over a benchmark that moved is not, so without its
#: own outcome it would rank as a measured row at minus the benchmark's Sharpe — and outrank
#: every real candidate on any window the benchmark lost money over.
NEVER_ENTERED = "never_entered"

#: A backtest reports one daily record per session and no starting point, and a return series
#: is the differences between them, so three sessions is the shortest run that can carry the
#: two observations a dispersion needs. Derived from that chain rather than written down, so
#: the trial log's outcome and the sheet's row cannot disagree about which runs are judgeable.
MIN_SESSIONS_FOR_A_RETURN_SERIES = 3


class ScreeningRunError(ValueError):
    """A screen that cannot be run as specified, refused before any trial is appended."""


@dataclass(frozen=True, slots=True)
class CandidateSpec:
    """One template and the explicit grid of parameter points to screen it at.

    The grid holds **listed values, not ranges**, and that is the difference between a
    screen and a search. A range invites an optimiser, and an optimiser's trial count is
    whatever it decided to spend; a written list is a number a reader can check against the
    sheet's own ``n_trials_logged``.

    Every point is validated against the template's declared
    :class:`~xman_research.alpha.templates.ParameterRange` at expansion time, which is also
    what bounds the hold: ``hold_sessions`` is a declared parameter, so a grid naming six
    sessions is refused there rather than by a second check here that could disagree with it.
    """

    template_id: str
    grid: Mapping[str, Sequence[float]] = field(default_factory=dict)
    underlying: str = "NIFTY"

    def __post_init__(self) -> None:
        for name, values in self.grid.items():
            if not values:
                raise ScreeningRunError(
                    f"{self.template_id}: parameter {name!r} lists no values. An empty axis "
                    "expands to no instances at all, so the whole spec would silently "
                    "screen nothing."
                )

    def expand(self, registry: TemplateRegistry) -> tuple[CandidateInstance, ...]:
        """Every point on the grid, in a deterministic order.

        Parameter names are sorted and the product is taken in that order, so two runs of
        the same spec produce the same instances in the same sequence — which is what makes
        two sheets comparable row by row.
        """
        template = registry.get(self.template_id)
        names = sorted(self.grid)
        axes = [tuple(float(value) for value in self.grid[name]) for name in names]
        instances: list[CandidateInstance] = []
        for point in itertools.product(*axes) if axes else [()]:
            params = dict(zip(names, point, strict=True))
            # Raises on an undeclared name or a value outside its declared range, including
            # a hold outside one-to-five sessions. The strategy is then built and thrown
            # away: a conditioner refuses some combinations its parameters each satisfy
            # individually — a band whose edges are the wrong way round — and only the built
            # object can see it. Discovering that inside the run would leave the log holding
            # trials for a screen that never produced a sheet.
            template.resolve(params)
            template.build(params, self.underlying, feature_series={})
            instances.append(
                CandidateInstance(
                    template_id=self.template_id,
                    underlying=self.underlying,
                    params=params,
                    hold_sessions=template.hold_for(params),
                )
            )
        return tuple(instances)

    def as_dict(self) -> dict[str, Any]:
        return {
            "template_id": self.template_id,
            "underlying": self.underlying,
            "grid": {name: list(values) for name, values in sorted(self.grid.items())},
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> CandidateSpec:
        return cls(
            template_id=str(payload["template_id"]),
            grid={
                str(name): tuple(float(value) for value in values)
                for name, values in (payload.get("grid") or {}).items()
            },
            underlying=str(payload["underlying"]),
        )


@dataclass(frozen=True, slots=True)
class CandidateInstance:
    """One template at one point of its parameter space, for one underlying."""

    template_id: str
    underlying: str
    params: Mapping[str, float]
    hold_sessions: int

    @property
    def instance_id(self) -> str:
        """A stable name for this point, unique within a sheet.

        Built from the sorted parameters rather than from a position in the grid, so the
        same instance carries the same name in a later screen whose grid was reordered or
        extended around it.
        """
        return f"{self.template_id}@{self.underlying}[{parameter_key(self.params)}]"

    def as_dict(self) -> dict[str, Any]:
        return {
            "instance_id": self.instance_id,
            "template_id": self.template_id,
            "underlying": self.underlying,
            "params": {name: value for name, value in sorted(self.params.items())},
            "hold_sessions": self.hold_sessions,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> CandidateInstance:
        return cls(
            template_id=str(payload["template_id"]),
            underlying=str(payload["underlying"]),
            params={str(name): float(value) for name, value in payload["params"].items()},
            hold_sessions=int(payload["hold_sessions"]),
        )


@dataclass(frozen=True, slots=True)
class ScreenedInstance:
    """What one instance measured, and its spread over the benchmark.

    Every headline number is ``None`` when the run could not produce it, with
    :attr:`reason` saying which of the several possible causes applied — a window too short
    to have a dispersion, a candidate that never entered, a benchmark comparison the
    statistics layer refused. A zero in place of any of them would rank an instance that
    measured nothing alongside one that measured no edge.
    """

    instance: CandidateInstance
    trial_id: str
    outcome: str
    strategy_name: str
    strategy_parameters: Mapping[str, Any]
    fingerprint: str
    alpha: float | None
    annualised_sharpe: float | None
    mean_return_per_session: float | None
    mean_return_at_hold: float | None
    max_drawdown: float | None
    n_observations: int | None
    sessions_entered: int
    feasibility: Mapping[str, int]
    cost_stamps: tuple[str, ...]
    risk_matched: Mapping[str, Any] | None
    regime_breakdown: Mapping[str, Mapping[str, Any]]
    reason: str | None = None

    @property
    def measured(self) -> bool:
        """Whether this row carries an alpha a ranking can order on."""
        return self.alpha is not None

    def as_dict(self) -> dict[str, Any]:
        return {
            "instance": self.instance.as_dict(),
            "trial_id": self.trial_id,
            "outcome": self.outcome,
            "strategy_name": self.strategy_name,
            "strategy_parameters": dict(self.strategy_parameters),
            "fingerprint": self.fingerprint,
            "alpha": self.alpha,
            "annualised_sharpe": self.annualised_sharpe,
            "mean_return_per_session": self.mean_return_per_session,
            "mean_return_at_hold": self.mean_return_at_hold,
            "max_drawdown": self.max_drawdown,
            "n_observations": self.n_observations,
            "sessions_entered": self.sessions_entered,
            "feasibility": dict(self.feasibility),
            "cost_stamps": list(self.cost_stamps),
            "risk_matched": dict(self.risk_matched) if self.risk_matched else None,
            "regime_breakdown": {
                regime: dict(facts) for regime, facts in sorted(self.regime_breakdown.items())
            },
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ScreenedInstance:
        return cls(
            instance=CandidateInstance.from_dict(payload["instance"]),
            trial_id=str(payload["trial_id"]),
            outcome=str(payload["outcome"]),
            strategy_name=str(payload["strategy_name"]),
            strategy_parameters=dict(payload["strategy_parameters"]),
            fingerprint=str(payload["fingerprint"]),
            alpha=_optional_float(payload.get("alpha")),
            annualised_sharpe=_optional_float(payload.get("annualised_sharpe")),
            mean_return_per_session=_optional_float(payload.get("mean_return_per_session")),
            mean_return_at_hold=_optional_float(payload.get("mean_return_at_hold")),
            max_drawdown=_optional_float(payload.get("max_drawdown")),
            n_observations=(
                None if payload.get("n_observations") is None else int(payload["n_observations"])
            ),
            sessions_entered=int(payload["sessions_entered"]),
            feasibility={str(k): int(v) for k, v in (payload.get("feasibility") or {}).items()},
            cost_stamps=tuple(str(stamp) for stamp in payload.get("cost_stamps") or ()),
            risk_matched=(dict(payload["risk_matched"]) if payload.get("risk_matched") else None),
            regime_breakdown={
                str(regime): dict(facts)
                for regime, facts in (payload.get("regime_breakdown") or {}).items()
            },
            reason=(None if payload.get("reason") is None else str(payload["reason"])),
        )


def _optional_float(value: Any) -> float | None:
    return None if value is None else float(value)


@dataclass(frozen=True, slots=True)
class ScreenSheet:
    """One screening run's ranked output, and everything needed to reproduce it.

    :attr:`instances` is ranked by :attr:`ScreenedInstance.alpha` descending, ties broken by
    the shallower maximum drawdown. Rows the run could not measure sort last, in the order
    they were run: an unmeasurable instance has no place in the ordering and hiding it would
    understate what the screen cost in trials.
    """

    underlying: str
    window: DataWindow
    benchmark: ScreenedInstance
    instances: tuple[ScreenedInstance, ...]
    specs: tuple[CandidateSpec, ...]
    gaps_reason: str | None
    sessions_without_features: tuple[dt.date, ...]
    provenance: Mapping[str, Any]
    generated_at: str
    schema_version: int = SCREEN_SHEET_SCHEMA_VERSION

    @property
    def trial_ids(self) -> tuple[str, ...]:
        """Every trial this screen appended, benchmark first."""
        return (self.benchmark.trial_id, *(row.trial_id for row in self.instances))

    @property
    def n_trials_logged(self) -> int:
        """How many trials the screen spent, derived from the ids it collected.

        A derived property and **not** a constructor field, for the reason
        ``tests/test_no_caller_supplied_count.py`` enforces across this package: a count
        passed in beside the evidence it describes is a count that can disagree with it, and
        this is the one number a researcher must never supply. A stage-two gate reads it to
        know how wide a selection its survivor came out of.
        """
        return len(self.trial_ids)

    def row(self, instance_id: str) -> ScreenedInstance:
        """The row naming ``instance_id``, benchmark included."""
        for row in (self.benchmark, *self.instances):
            if row.instance.instance_id == instance_id:
                return row
        raise KeyError(
            f"this sheet holds no instance {instance_id!r}; it screened "
            f"{[row.instance.instance_id for row in self.instances]}"
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "underlying": self.underlying,
            "window": str(self.window),
            "generated_at": self.generated_at,
            "benchmark": self.benchmark.as_dict(),
            "instances": [row.as_dict() for row in self.instances],
            "specs": [spec.as_dict() for spec in self.specs],
            "gaps_reason": self.gaps_reason,
            "sessions_without_features": [
                day.isoformat() for day in self.sessions_without_features
            ],
            "trial_ids": list(self.trial_ids),
            "n_trials_logged": self.n_trials_logged,
            "provenance": dict(self.provenance),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ScreenSheet:
        """Read a sheet back, refusing a schema this reader does not understand.

        ``trial_ids`` and ``n_trials_logged`` in the document are **not** read back into
        fields: both are derived from the rows, so reading them would create a second copy
        of a count that could disagree with the rows it describes.
        """
        version = payload.get("schema_version")
        if version != SCREEN_SHEET_SCHEMA_VERSION:
            raise ScreeningRunError(
                f"screen sheet declares schema_version {version!r}; this reader understands "
                f"{SCREEN_SHEET_SCHEMA_VERSION}"
            )
        start, _, end = str(payload["window"]).partition("..")
        return cls(
            underlying=str(payload["underlying"]),
            window=DataWindow(dt.date.fromisoformat(start), dt.date.fromisoformat(end)),
            benchmark=ScreenedInstance.from_dict(payload["benchmark"]),
            instances=tuple(ScreenedInstance.from_dict(row) for row in payload["instances"]),
            specs=tuple(CandidateSpec.from_dict(spec) for spec in payload.get("specs") or ()),
            gaps_reason=(
                None if payload.get("gaps_reason") is None else str(payload["gaps_reason"])
            ),
            sessions_without_features=tuple(
                dt.date.fromisoformat(day) for day in payload.get("sessions_without_features") or ()
            ),
            provenance=dict(payload.get("provenance") or {}),
            generated_at=str(payload["generated_at"]),
            schema_version=int(version),
        )


def load_screen_sheet(path: Path | str) -> ScreenSheet:
    """Read a screen sheet from disk."""
    source = Path(path)
    if not source.exists():
        raise ScreeningRunError(f"no screen sheet at {source}")
    try:
        payload = json.loads(source.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ScreeningRunError(f"screen sheet at {source} does not parse: {error}") from error
    if not isinstance(payload, Mapping):
        raise ScreeningRunError(f"screen sheet at {source} is not a JSON object")
    return ScreenSheet.from_dict(payload)


class ScreeningRun:
    """Runs one screen: a benchmark, a set of candidates, one ranked sheet.

    Everything the run needs is supplied rather than discovered — the store, the registry,
    the log to append to, and the hypothesis every trial is filed against. The hypothesis is
    the seam to stage two: it is what makes the screen's trials countable against the
    survivor that later faces a gate.
    """

    def __init__(
        self,
        *,
        store: SessionStore,
        registry: TemplateRegistry,
        trial_log: TrialLog,
        hypothesis: HypothesisRecord,
        window: DataWindow,
        benchmark: CandidateSpec,
        candidates: Sequence[CandidateSpec],
        config: BacktestConfig | None = None,
        gaps_reason: str | None = None,
        feature_builder: FeatureBuilder | None = None,
        clock: Clock | None = None,
        code_version: CodeVersionProvider | None = None,
    ) -> None:
        self._store = store
        self._registry = registry
        self._session = ResearchSession(trial_log)
        self._hypothesis = hypothesis
        self._window = window
        self._benchmark_spec = benchmark
        self._specs = tuple(candidates)
        base = config if config is not None else BacktestConfig()
        # The gap policy is the caller's research decision and travels into the engine, so
        # the run and the sheet cannot disagree about whether a holey window was accepted.
        self._config = replace_gap_reason(base, gaps_reason)
        self._gaps_reason = gaps_reason
        if feature_builder is not None and (
            feature_builder.decision_time != self._config.decision_time
        ):
            raise ScreeningRunError(
                f"the feature builder reads its features at "
                f"{feature_builder.decision_time.isoformat()} and the engine acts at "
                f"{self._config.decision_time.isoformat()}. Features are truncated at the "
                "builder's minute, so a later one puts prints the strategy had not seen into "
                "every conditioner and every strike rule — look-ahead, in the flattering "
                "direction, on every instance in the sheet equally."
            )
        self._features = (
            feature_builder
            if feature_builder is not None
            else FeatureBuilder(store, decision_time=self._config.decision_time)
        )
        self._clock = clock if clock is not None else SystemClock()
        self._code_version = code_version if code_version is not None else GitCodeVersion()

    def run(self) -> ScreenSheet:
        """Run the benchmark and every candidate, and return the ranked sheet."""
        benchmark_instances = self._benchmark_spec.expand(self._registry)
        if len(benchmark_instances) != 1:
            raise ScreeningRunError(
                f"the benchmark spec expands to {len(benchmark_instances)} instances. A "
                "benchmark is the single unconditional run every candidate's alpha is a "
                "spread over; a family of them is not a benchmark."
            )
        instances = [instance for spec in self._specs for instance in spec.expand(self._registry)]
        if not instances:
            raise ScreeningRunError(
                "the screen names no candidates. A sheet holding only its own benchmark "
                "ranks nothing and would still spend a trial."
            )
        underlying = self._config.underlying
        for instance in (*benchmark_instances, *instances):
            if instance.underlying != underlying:
                raise ScreeningRunError(
                    f"instance {instance.instance_id} names underlying "
                    f"{instance.underlying!r} and the run is configured for {underlying!r}. "
                    "Alpha is a spread over a benchmark measured on one product; mixing "
                    "products would compare two different markets."
                )

        series, regimes, featureless = self._feature_pass(underlying)

        benchmark_result, benchmark_evidence = self._backtest(benchmark_instances[0], series)
        benchmark_row = self._row(
            benchmark_instances[0],
            benchmark_result,
            benchmark_evidence,
            benchmark=benchmark_evidence,
            regimes=regimes,
        )
        rows = []
        for instance in instances:
            result, evidence = self._backtest(instance, series)
            rows.append(
                self._row(instance, result, evidence, benchmark=benchmark_evidence, regimes=regimes)
            )

        return ScreenSheet(
            underlying=underlying,
            window=self._window,
            benchmark=benchmark_row,
            instances=_ranked(rows),
            specs=(self._benchmark_spec, *self._specs),
            gaps_reason=self._gaps_reason,
            sessions_without_features=featureless,
            provenance=self._provenance(benchmark_result),
            generated_at=self._clock.now().isoformat(),
        )

    # ------------------------------------------------------------------ internals

    def _feature_pass(
        self, underlying: str
    ) -> tuple[dict[str, dict[dt.date, float]], dict[dt.date, str | None], tuple[dt.date, ...]]:
        """Every feature, for every session in the window, computed once for the whole run.

        One pass rather than one per instance: the conditioners and the strike rules between
        them read most of the feature layer, and a frame costs a window of parquet reads.
        Sharing the pass also means every instance in a sheet is conditioned on numerically
        the same series, so a difference between two rows is a difference between the
        strategies rather than between two computations of one feature.

        A session whose frame cannot be built is reported rather than filled. Its features
        are absent, so every conditioned instance declines to enter on it — the safe
        direction :class:`~xman_research.alpha.templates.HoldNSpread` documents.
        """
        return feature_pass(
            store=self._store,
            features=self._features,
            underlying=underlying,
            window=self._window,
            gaps_reason=self._gaps_reason,
        )

    def _backtest(
        self, instance: CandidateInstance, series: Mapping[str, Mapping[dt.date, float]]
    ) -> tuple[BacktestResult, RunEvidence | None]:
        """One instance, run inside its own logged trial.

        The trial row is appended when the context exits, which is why the evidence is
        adapted afterwards: :func:`~xman_research.adapter.evidence_from_result` reads the
        run's timestamp from the log row rather than from the wall clock, and the row does
        not exist until then.
        """
        template = self._registry.get(instance.template_id)
        strategy = template.build(instance.params, instance.underlying, feature_series=series)
        notes = (
            f"Screening stage 1: {instance.instance_id} over {self._window}. Point estimate "
            "only — no threshold was applied and none was pre-registered for this run."
        )
        with self._session.trial(
            self._hypothesis,
            data_window=self._window,
            params={
                "instance_id": instance.instance_id,
                "template_id": instance.template_id,
                "underlying": instance.underlying,
                HOLD_SESSIONS: instance.hold_sessions,
                **dict(instance.params),
            },
            notes=notes,
        ) as trial:
            result = run_backtest(trial, store=self._store, strategy=strategy, config=self._config)
            trial.record_metrics(result.metrics())
            trial.record_params(strategy_name=result.strategy_name)
            if len(result.daily) < MIN_SESSIONS_FOR_A_RETURN_SERIES:
                trial.mark_not_evaluable(
                    f"the run produced {len(result.daily)} daily record(s) and a judgeable "
                    f"return series needs {MIN_SESSIONS_FOR_A_RETURN_SERIES}"
                )
        try:
            evidence = evidence_from_result(
                result,
                session=self._session,
                hypothesis_id=self._hypothesis.id,
                label=instance.instance_id,
            )
        except SeriesError:
            # A window too short to carry a dispersion. The trial is already logged and the
            # row will say why the numbers are absent — see `_row`.
            return result, None
        return result, evidence

    def _row(
        self,
        instance: CandidateInstance,
        result: BacktestResult,
        evidence: RunEvidence | None,
        *,
        benchmark: RunEvidence | None,
        regimes: Mapping[dt.date, str | None],
    ) -> ScreenedInstance:
        entries = sum(1 for fill in result.fills if fill.tag == "entry" and fill.filled)
        common = {
            "instance": instance,
            "trial_id": result.trial_id,
            "strategy_name": result.strategy_name,
            "strategy_parameters": dict(result.strategy_parameters),
            "fingerprint": result.fingerprint(),
            "sessions_entered": entries,
            "feasibility": result.feasibility_counts(),
            "cost_stamps": tuple(result.unverified_inputs),
        }
        if evidence is None:
            return ScreenedInstance(
                outcome="not_evaluable",
                alpha=None,
                annualised_sharpe=None,
                mean_return_per_session=None,
                mean_return_at_hold=None,
                max_drawdown=None,
                n_observations=len(result.daily),
                risk_matched=None,
                regime_breakdown={},
                reason=(
                    f"the run covered {len(result.daily)} session(s) of {self._window} and a "
                    f"judgeable return series needs {MIN_SESSIONS_FOR_A_RETURN_SERIES}"
                ),
                **common,
            )

        returns = evidence.returns
        if entries == 0:
            refusals = {verdict: n for verdict, n in result.feasibility_counts().items() if n}
            return ScreenedInstance(
                outcome=NEVER_ENTERED,
                alpha=None,
                annualised_sharpe=None,
                mean_return_per_session=0.0,
                mean_return_at_hold=0.0,
                max_drawdown=0.0,
                n_observations=len(returns),
                risk_matched=None,
                regime_breakdown={},
                reason=(
                    "the instance's entry rules refused every session in the window, so it "
                    "measured nothing. Its spread over a benchmark that did trade is not "
                    "flat, and reporting that spread as an alpha would rank a strategy that "
                    "never traded above every one that did, on any window the benchmark lost "
                    f"money over. What the engine recorded: {refusals or 'no intents at all'}."
                ),
                **common,
            )
        mean_per_session = math.fsum(returns.net) / len(returns)
        facts = drawdown(returns)
        excess = _excess_series(returns, benchmark.returns) if benchmark is not None else None
        if benchmark is None:
            alpha, reason = (
                None,
                ("no benchmark series was measurable, so there is no spread to take"),
            )
        else:
            alpha, reason = _sharpe_or_none(
                excess,
                undefined=(
                    "the spread over the benchmark is identically flat, so it has no "
                    "dispersion to form a ratio from. This is what an instance that "
                    "reproduces the benchmark exactly looks like, and it is not an alpha "
                    "of zero: there is no number here at all."
                ),
            )
        own_sharpe, own_reason = _sharpe_or_none(
            returns,
            undefined=(
                "the run's own return series never moved, so its Sharpe is undefined "
                "rather than zero"
            ),
        )
        if own_reason is not None:
            reason = own_reason if reason is None else f"{reason}; {own_reason}"
        return ScreenedInstance(
            outcome=SCREENED,
            alpha=alpha,
            annualised_sharpe=own_sharpe,
            mean_return_per_session=mean_per_session,
            mean_return_at_hold=mean_per_session * instance.hold_sessions,
            max_drawdown=facts.max_drawdown,
            n_observations=len(returns),
            risk_matched=_risk_matched(evidence, benchmark),
            regime_breakdown=_regime_breakdown(excess, regimes),
            reason=reason,
            **common,
        )

    def _provenance(self, benchmark_result: BacktestResult) -> dict[str, Any]:
        version = self._code_version()
        return {
            "code_version": str(version),
            "code_version_dirty": version.dirty,
            "generated_by": "xman_research.alpha.screen.ScreeningRun",
            "hypothesis_id": self._hypothesis.id,
            "hypothesis_name": self._hypothesis.name,
            "trial_log_path": str(self._session.log.db_path),
            "decision_time": self._config.decision_time.isoformat(),
            "corpus": dict(benchmark_result.data_provenance),
            "config": dict(benchmark_result.config_provenance),
            "alpha_definition": (
                "annualised Sharpe of the candidate's per-session net return series minus "
                "the benchmark's, aligned on the union of their session dates with a zero "
                "for a session either side sat out. Distinct from `risk_matched`, which is "
                "this repository's volatility-matched comparison and scales the benchmark "
                "to the candidate's volatility before differencing."
            ),
            "trial_count_note": (
                "every instance in this sheet was appended to the trial log against "
                f"hypothesis {self._hypothesis.id} before its number was read, so a "
                "stage-two gate filed against the same family deflates against the whole "
                "screen. A large family count is the screen working, not a fault."
            ),
            "stage": (
                "screening (stage 1). Point estimates and a ranking, no pre-registered "
                "threshold and no holdout. Nothing here is a verdict."
            ),
        }


def feature_pass(
    *,
    store: SessionStore,
    features: FeatureBuilder,
    underlying: str,
    window: DataWindow,
    gaps_reason: str | None,
) -> tuple[dict[str, dict[dt.date, float]], dict[dt.date, str | None], tuple[dt.date, ...]]:
    """Every feature, for every session in ``window``, and the sessions that have none.

    Shared by the screen and by the stage-two gate runner so that an instance graded at a
    gate is conditioned on numerically the same series it was screened on. Two computations
    of one feature would make a stage-two verdict a statement about a different strategy
    from the one the sheet ranked.
    """
    resolution = store.resolve(underlying, window.start, window.end)
    refs = resolution.accept_gaps(gaps_reason) if gaps_reason is not None else resolution.sessions()
    series: dict[str, dict[dt.date, float]] = {}
    regimes: dict[dt.date, str | None] = {}
    featureless: list[dt.date] = []
    for ref in refs:
        try:
            frame = features.build(underlying, ref.session_date)
        except (AsOfNotASessionError, InsufficientHistoryError, SessionStoreError):
            featureless.append(ref.session_date)
            continue
        regimes[ref.session_date] = frame.regime.tag
        for name, feature in frame.features.items():
            if feature.value is not None:
                series.setdefault(name, {})[ref.session_date] = feature.value
    return series, regimes, tuple(featureless)


def replace_gap_reason(config: BacktestConfig, gaps_reason: str | None) -> BacktestConfig:
    """``config`` with its gap policy set to ``gaps_reason``, and every other field kept."""
    if config.gap_reason == gaps_reason:
        return config
    return dataclasses.replace(config, gap_reason=gaps_reason)


def _excess_series(candidate: ReturnSeries, benchmark: ReturnSeries) -> ReturnSeries | None:
    """The candidate's per-session return minus the benchmark's, aligned on both.

    **Both series must cover the identical sessions, and a mismatch is refused rather than
    filled.** Every instance in a screen runs the same window against the same store, and a
    session an instance sat out already carries a flat daily record, so the two date sets
    agree by construction — a disagreement means the two runs were not comparable, and
    zero-filling would credit the candidate with a flat return on sessions nothing measured
    it over. ``None`` is returned so the row carries a stated reason instead of a number.

    The excess carries **no cost drag of its own**: both inputs are already net, so the
    difference has no separable cost component, and reporting one would invite a
    cost-multiple counterfactual that means nothing on a spread.
    """
    if set(candidate.dates) != set(benchmark.dates):
        return None
    if candidate.periods_per_year != benchmark.periods_per_year:
        return None
    days = sorted(candidate.dates)
    left = dict(zip(candidate.dates, candidate.net, strict=True))
    right = dict(zip(benchmark.dates, benchmark.net, strict=True))
    return ReturnSeries(
        dates=tuple(days),
        net=tuple(left.get(day, 0.0) - right.get(day, 0.0) for day in days),
        drag=tuple(0.0 for _ in days),
        label=f"{candidate.label} minus {benchmark.label}",
        periods_per_year=candidate.periods_per_year,
    )


def _sharpe_or_none(series: ReturnSeries, *, undefined: str) -> tuple[float | None, str | None]:
    """The annualised Sharpe of ``series``, or ``None`` with the reason there is not one.

    A series with no dispersion has no Sharpe — the ratio is zero over zero, not zero — and
    :mod:`xman_research.validation.statistics` refuses it rather than returning a number.
    A screen meets that case routinely: an instance that reproduces its benchmark exactly
    has an identically flat spread. Reporting ``None`` keeps such a row out of the ranking
    instead of seating it in the middle at a fabricated zero.
    """
    # Checked rather than caught: `annualised_sharpe_ratio` raises `ValueError` for zero
    # dispersion today, and catching that would also swallow any future `ValueError` from the
    # moment calculation and report it under this reason — a wrong explanation attached to a
    # missing number, which is worse than either alone.
    if len(set(series.net)) == 1:
        return None, undefined
    return annualised_sharpe_ratio(series), None


def _risk_matched(candidate: RunEvidence, benchmark: RunEvidence | None) -> dict[str, Any] | None:
    """This repository's volatility-matched comparison, or ``None`` with the refusal on it.

    Reported alongside ``alpha`` rather than instead of it. The two answer different
    questions — a plain spread asks what the candidate added, a matched one asks what it
    added at the benchmark's risk — and a screen that quietly shipped one under the other's
    name would make its sheets incomparable with the decision records that gate stage two.
    """
    if benchmark is None:
        return None
    try:
        return risk_matched_increment(candidate, benchmark=benchmark).as_dict()
    except BenchmarkMismatchError as error:
        return {"refused": str(error)}


def _regime_breakdown(
    excess: ReturnSeries | None, regimes: Mapping[dt.date, str | None]
) -> dict[str, dict[str, Any]]:
    """The excess return, split by the feature layer's volatility-regime tag.

    **Descriptive and ungraded.** The tag is a tercile of the implied-minus-realised spread
    measured over its own trailing distribution, so the three buckets are not independent
    samples and their means are not three separate pieces of evidence. A reader uses this to
    see whether an edge is concentrated in one kind of market, and a stage-two gate reads
    nothing from it.

    Sessions the feature pass could not tag land under ``untagged`` rather than being
    dropped, so the bucket sizes always sum to the series length.
    """
    if excess is None:
        return {}
    buckets: dict[str, list[float]] = {}
    for day, value in zip(excess.dates, excess.net, strict=True):
        tag = regimes.get(day) or "untagged"
        buckets.setdefault(tag, []).append(value)
    return {
        tag: {
            "observations": len(values),
            "mean_excess_return": math.fsum(values) / len(values),
        }
        for tag, values in sorted(buckets.items())
    }


def _ranked(rows: Sequence[ScreenedInstance]) -> tuple[ScreenedInstance, ...]:
    """Measured rows by alpha descending, ties by the shallower drawdown; the rest last.

    The tie-break is a real preference and not a convenience: two instances with the same
    spread over the benchmark are not equally good, and the one that reached it through a
    shallower trough is the one an operator can hold through.

    ``max_drawdown`` is a non-negative depth, so ascending is shallowest-first.
    """
    measured = [row for row in rows if row.measured]
    unmeasured = [row for row in rows if not row.measured]
    measured.sort(
        key=lambda row: (
            -(row.alpha if row.alpha is not None else 0.0),
            row.max_drawdown if row.max_drawdown is not None else math.inf,
            row.instance.instance_id,
        )
    )
    return (*measured, *unmeasured)


def evidence_card_from_screen(
    sheet: ScreenSheet, instance_id: str, *, source: str, template: StrategyTemplate
) -> EvidenceCard:
    """A library evidence card for one screened instance, pointing back at its sheet.

    **The card is stage-one evidence and says so on every field that could be mistaken for
    a verdict.** ``gate_status`` is ``None`` because no gate was applied, and ``outcome`` is
    the screen's own word rather than any of the four a decision record can carry. A card
    built here is fit to file a template as a CANDIDATE and is not fit to admit one:
    :meth:`~xman_research.alpha.library.TemplateLibrary.admit` reads ``gate_status`` and
    refuses an admission this card cannot justify.

    ``deflated_sharpe`` is ``None`` and not computed here even though the sheet knows its
    own trial count. Deflating requires the *family* count from the log, which includes
    trials this sheet never saw, and a deflation against the screen alone would understate
    the discount in the flattering direction.
    """
    row = sheet.row(instance_id)
    # Resolved rather than the grid point as written: the card is compared against an
    # admission's point, and only a resolved pair is comparable — see `parameter_key`.
    point = template.resolve(row.instance.params)
    return EvidenceCard(
        parameters=point,
        n_observations=row.n_observations,
        annualised_sharpe=row.annualised_sharpe,
        deflated_sharpe=None,
        max_drawdown=row.max_drawdown,
        hit_rate=None,
        mean_return_per_session=row.mean_return_per_session,
        mean_return_at_hold=row.mean_return_at_hold,
        hold_sessions=row.instance.hold_sessions,
        gate_status=None,
        outcome=row.outcome,
        window=str(sheet.window),
        measured_strategy=row.strategy_name,
        measured_strategy_parameters=dict(row.strategy_parameters),
        cost_stamps=row.cost_stamps,
        regime_table=None,
        provenance={
            "n_observations": f"{source}:instances[{instance_id}].n_observations",
            "annualised_sharpe": f"{source}:instances[{instance_id}].annualised_sharpe",
            "deflated_sharpe": (
                "not computed: deflation needs the trial log's family count, which is wider "
                f"than this sheet's {sheet.n_trials_logged} screening trials"
            ),
            "max_drawdown": f"{source}:instances[{instance_id}].max_drawdown",
            "hit_rate": "not reported by a screening sheet",
            "mean_return_per_session": (
                f"{source}:instances[{instance_id}].mean_return_per_session, net of costs"
            ),
            "mean_return_at_hold": (
                f"derived: mean_return_per_session x hold_sessions "
                f"({row.instance.hold_sessions}); the screened run held exactly that many "
                "sessions, so this is a restatement rather than an extrapolation"
            ),
            "gate_status": (
                "absent: a screening sheet applies no threshold and pre-registers none, so "
                "there is no gate for this instance to have passed or failed"
            ),
            "outcome": f"{source}:instances[{instance_id}].outcome",
            "window": f"{source}:window",
            "measured_strategy": f"{source}:instances[{instance_id}].strategy_name",
            "measured_strategy_parameters": (
                f"{source}:instances[{instance_id}].strategy_parameters"
            ),
            "cost_stamps": f"{source}:instances[{instance_id}].cost_stamps",
            "regime_table": (
                "absent: the sheet's regime breakdown is a descriptive split of the excess "
                "return, not a measured multiplier the ranker may scale an edge by"
            ),
            "alpha": (
                f"{source}:instances[{instance_id}].alpha — the ranking statistic, an "
                "annualised Sharpe of the spread over the sheet's benchmark"
            ),
            "parameters": (
                f"{source}:instances[{instance_id}].instance.params, filled out with "
                f"{row.instance.template_id}'s declared defaults [{parameter_key(point)}]"
            ),
        },
    )
