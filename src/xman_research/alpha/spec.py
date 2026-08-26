"""A screen written down before it is run, as TOML.

**A screen's grid is a research decision, and a research decision belongs in a file.** The
alternative — a grid assembled from command-line flags — makes the set of instances a
property of a shell history nobody keeps, which is exactly the state that leaves a trial
count unreconstructable. A spec file is committable, diffable, and quotable in the sheet it
produced.

**The hypothesis is written here too, in full.** A screen's trials are appended against it,
and a stage-two gate filed against the same record deflates against every one of them, so
the record is the seam between the two stages rather than a label on the run. Its
``thresholds`` are the screen's *own* — what a survivor must clear before it is worth taking
to a gate — and nothing in :mod:`xman_research.alpha.screen` reads them: they are recorded
so a later reader can see what the screen was looking for, not applied.
"""

from __future__ import annotations

import datetime as dt
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from xman_research.alpha.features import DEFAULT_DECISION_TIME
from xman_research.alpha.screen import ALPHA_DEFINITION, CandidateSpec
from xman_research.hypothesis import HypothesisRecord
from xman_research.trial_log import DataWindow

__all__ = ["ScreenSpec", "ScreenSpecError", "load_screen_spec"]


class ScreenSpecError(ValueError):
    """A spec file that is missing, unreadable, or does not describe a runnable screen."""


@dataclass(frozen=True, slots=True)
class ScreenSpec:
    """Everything one screening run needs, read from one file."""

    hypothesis: HypothesisRecord
    window: DataWindow
    underlying: str
    benchmark: CandidateSpec
    candidates: tuple[CandidateSpec, ...]
    trial_log_path: Path
    decision_time: dt.time
    gaps_reason: str | None
    source: Path


def load_screen_spec(path: Path | str) -> ScreenSpec:
    """Read and validate the spec at ``path``.

    Every refusal here happens before a trial is appended, which is the property that
    matters: a spec rejected halfway through would leave the log holding trials for a screen
    that never produced a sheet, and a later deflation would count them against nothing.
    """
    source = Path(path)
    if not source.exists():
        raise ScreenSpecError(f"no screen spec at {source}")
    try:
        payload = tomllib.loads(source.read_text())
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ScreenSpecError(f"screen spec at {source} does not parse: {error}") from error

    window = _window(payload, source)
    underlying = str(payload.get("underlying") or "NIFTY")
    benchmark = _candidate(payload.get("benchmark"), underlying, source, "benchmark")
    rows = payload.get("candidates")
    if not isinstance(rows, list) or not rows:
        raise ScreenSpecError(
            f"{source} names no `[[candidates]]`. A screen with only a benchmark ranks "
            "nothing and would still spend a trial."
        )
    candidates = tuple(
        _candidate(row, underlying, source, f"candidates[{index}]")
        for index, row in enumerate(rows)
    )

    log_path = payload.get("trial_log")
    if not isinstance(log_path, str) or not log_path.strip():
        raise ScreenSpecError(
            f"{source} names no `trial_log`. Every screened instance is appended to a log "
            "before its number is read, and a screen with nowhere to append is a search."
        )

    return ScreenSpec(
        hypothesis=_hypothesis(payload, source),
        window=window,
        underlying=underlying,
        benchmark=benchmark,
        candidates=candidates,
        trial_log_path=Path(log_path),
        decision_time=_decision_time(payload, source),
        gaps_reason=_gaps_reason(payload),
        source=source,
    )


def _window(payload: Mapping[str, Any], source: Path) -> DataWindow:
    section = payload.get("window")
    if not isinstance(section, Mapping):
        raise ScreenSpecError(f"{source} has no `[window]` table with a start and an end")
    try:
        return DataWindow(_date(section, "start", source), _date(section, "end", source))
    except ValueError as error:
        raise ScreenSpecError(f"{source}: {error}") from error


def _date(section: Mapping[str, Any], key: str, source: Path) -> dt.date:
    value = section.get(key)
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        try:
            return dt.date.fromisoformat(value)
        except ValueError as error:
            raise ScreenSpecError(f"{source}: window.{key} {value!r} is not a date") from error
    raise ScreenSpecError(f"{source}: `[window]` names no {key}")


def _decision_time(payload: Mapping[str, Any], source: Path) -> dt.time:
    value = payload.get("decision_time")
    if value is None:
        return DEFAULT_DECISION_TIME
    if isinstance(value, dt.time):
        return value
    if isinstance(value, str):
        try:
            return dt.time.fromisoformat(value)
        except ValueError as error:
            raise ScreenSpecError(f"{source}: decision_time {value!r} is not a time") from error
    raise ScreenSpecError(f"{source}: decision_time must be a time of day")


def _gaps_reason(payload: Mapping[str, Any]) -> str | None:
    value = payload.get("gaps_reason")
    if value is None:
        return None
    text = str(value).strip()
    # An empty string is not a reason, and letting it through would accept a holey window
    # under a policy that says nothing — the one shape the store's `accept_gaps` exists to
    # refuse. Absent and empty therefore mean the same thing here: no gaps are accepted.
    return text or None


def _candidate(row: Any, underlying: str, source: Path, where: str) -> CandidateSpec:
    if not isinstance(row, Mapping):
        raise ScreenSpecError(f"{source}: `{where}` is not a table")
    template_id = row.get("template")
    if not isinstance(template_id, str) or not template_id.strip():
        raise ScreenSpecError(f"{source}: `{where}` names no `template`")
    grid_section = row.get("grid", {})
    if not isinstance(grid_section, Mapping):
        raise ScreenSpecError(f"{source}: `{where}.grid` is not a table")
    grid: dict[str, tuple[float, ...]] = {}
    for name, values in grid_section.items():
        listed = values if isinstance(values, list) else [values]
        try:
            grid[str(name)] = tuple(float(value) for value in listed)
        except (TypeError, ValueError) as error:
            raise ScreenSpecError(
                f"{source}: `{where}.grid.{name}` holds a value that is not a number"
            ) from error
    return CandidateSpec(
        template_id=template_id,
        grid=grid,
        underlying=str(row.get("underlying") or underlying),
    )


def _hypothesis(payload: Mapping[str, Any], source: Path) -> HypothesisRecord:
    section = payload.get("hypothesis")
    if not isinstance(section, Mapping):
        raise ScreenSpecError(
            f"{source} has no `[hypothesis]` table. Every screened instance is filed against "
            "one, and it is what lets a stage-two gate deflate against the whole screen."
        )
    predictors = section.get("predictors", [])
    if isinstance(predictors, str) or not isinstance(predictors, list):
        raise ScreenSpecError(
            f"{source}: `hypothesis.predictors` must be a list of names. A bare string "
            "iterates as its own characters, which would register a hypothesis predicting "
            "on single letters."
        )
    thresholds = section.get("thresholds")
    if not isinstance(thresholds, Mapping) or not thresholds:
        raise ScreenSpecError(
            f"{source}: `[hypothesis.thresholds]` is empty. A screen that states nothing a "
            "survivor must clear is a search dressed as a hypothesis."
        )
    screen_criteria = _screen_criteria(section, source)
    try:
        return HypothesisRecord(
            name=str(section.get("name", "")),
            mechanism=str(section.get("mechanism", "")),
            null_hypothesis=str(section.get("null_hypothesis", "")),
            thresholds=dict(thresholds),
            screen_criteria=screen_criteria,
            predictors=tuple(str(name) for name in predictors),
            notes=str(section.get("notes", "")),
            parent_id=(str(section["parent_id"]) if section.get("parent_id") is not None else None),
        )
    except ValueError as error:
        raise ScreenSpecError(f"{source}: `[hypothesis]` is not a valid record: {error}") from error


ALPHA_TO_ADVANCE = "alpha_to_advance"
"""The screen's own bar: how much alpha an instance must show to be worth gating."""

ALPHA_TO_ADVANCE_DEFINITION_KEY = f"{ALPHA_TO_ADVANCE}_definition"


def _screen_criteria(section: Mapping[str, Any], source: Path) -> dict[str, Any]:
    """The screen-stage bars, with the definition of `alpha_to_advance` attached.

    These go on the record under ``screen_criteria`` rather than ``thresholds``: a
    stage-two gate must carry every numeric threshold a record registered and may only
    name metrics :mod:`xman_research.validation` measures, so a screen bar recorded as a
    threshold is one no gate can satisfy and none can omit.

    ``alpha_to_advance`` is measured against the sheet's `alpha` column, and the two
    quantities that word can mean rank the sheet differently, so the bar is recorded with
    :data:`~xman_research.alpha.screen.ALPHA_DEFINITION` beside it. A spec that states its
    own definition keeps it; the reader is then told which quantity was meant by whoever
    wrote the screen, which is the point either way.
    """
    stated = section.get("screen_criteria", {})
    if not isinstance(stated, Mapping):
        raise ScreenSpecError(
            f"{source}: `[hypothesis.screen_criteria]` is not a table. A screen's own bars "
            "are named criteria with values, or they are not criteria."
        )
    criteria = {str(key): value for key, value in stated.items()}
    if ALPHA_TO_ADVANCE in criteria:
        criteria.setdefault(ALPHA_TO_ADVANCE_DEFINITION_KEY, ALPHA_DEFINITION)
    return criteria
