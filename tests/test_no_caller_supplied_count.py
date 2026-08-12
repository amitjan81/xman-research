"""Acceptance criterion 3: the trial count is read from the log, never supplied by the
caller.

A behavioural test (``count_trials(h) == 3``) does not test this at all — it passes
just as happily against an API that also accepts an override. So this is an
introspective test over the whole public surface: it enumerates every public callable
reachable from ``xman_research`` and fails if any of them grows a parameter through
which a caller could assert how many trials there have been. It is written to fail on
the *addition* of such an API, which is the point at which the property would be lost.
"""

from __future__ import annotations

import inspect
from collections.abc import Iterator
from typing import Any

import pytest

import xman_research

# Names through which a caller could assert a count. Substring-matched against
# parameter names, so `n_trials`, `trial_count`, `num_trials` and `total_trials` all
# trip it. `trial_id` deliberately does not: an identity is not a quantity.
FORBIDDEN_SUBSTRINGS = ("count", "n_trials", "num_trials", "ntrials", "trials")


def public_callables() -> Iterator[tuple[str, Any]]:
    for exported in xman_research.__all__:
        obj = getattr(xman_research, exported)
        if inspect.isclass(obj):
            for member_name, member in inspect.getmembers(obj):
                if member_name.startswith("_") and member_name != "__init__":
                    continue
                if inspect.isfunction(member) or inspect.ismethod(member):
                    yield f"{exported}.{member_name}", member
                elif isinstance(member, property) and member.fset is not None:
                    yield f"{exported}.{member_name} (setter)", member.fset
        elif callable(obj):
            yield exported, obj


def test_the_public_surface_is_non_empty() -> None:
    """Guards the guard: a test that enumerates nothing would pass vacuously."""
    names = [name for name, _ in public_callables()]
    assert len(names) > 20
    assert "TrialLog.count_trials" in names
    assert "open_session" in names


@pytest.mark.parametrize("qualified_name,function", list(public_callables()))
def test_no_public_callable_accepts_a_trial_count(qualified_name: str, function: Any) -> None:
    try:
        signature = inspect.signature(function)
    except (ValueError, TypeError):  # pragma: no cover - builtins without signatures
        pytest.skip(f"{qualified_name} has no introspectable signature")

    for parameter_name in signature.parameters:
        lowered = parameter_name.lower()
        offending = [token for token in FORBIDDEN_SUBSTRINGS if token in lowered]
        assert not offending, (
            f"{qualified_name} accepts parameter {parameter_name!r}, which looks like a "
            f"caller-supplied trial count ({offending}). The trial count must be read "
            "from the log."
        )


def test_counting_methods_take_only_a_hypothesis() -> None:
    """The two counters read the log and accept nothing else."""
    for owner, method_name in (
        (xman_research.TrialLog, "count_trials"),
        (xman_research.TrialLog, "count_family_trials"),
        (xman_research.ResearchSession, "count_trials"),
        (xman_research.ResearchSession, "count_family_trials"),
    ):
        parameters = list(inspect.signature(getattr(owner, method_name)).parameters)
        assert parameters == ["self", "hypothesis_id"] or parameters == ["self", "hypothesis"], (
            f"{owner.__name__}.{method_name} takes {parameters}"
        )


def test_no_public_name_offers_to_set_a_count() -> None:
    """No `set_trial_count`, no `override_trials`, no `trials = n`."""
    for exported in xman_research.__all__:
        obj = getattr(xman_research, exported)
        candidates = [exported]
        if inspect.isclass(obj):
            candidates += [n for n, _ in inspect.getmembers(obj) if not n.startswith("_")]
        for name in candidates:
            lowered = name.lower()
            assert not (
                lowered.startswith(("set_", "override_", "assert_", "declare_"))
                and ("trial" in lowered or "count" in lowered)
            ), f"{exported}.{name} looks like a way to assert a trial count"
