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

import importlib
import inspect
import pkgutil
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

import xman_research

# Names through which a caller could assert a count. Substring-matched against
# parameter names, so `n_trials`, `trial_count`, `num_trials` and `total_trials` all
# trip it. `trial_id` deliberately does not: an identity is not a quantity.
FORBIDDEN_SUBSTRINGS = ("count", "n_trials", "num_trials", "ntrials", "trials")


def package_modules(package: Any = xman_research) -> list[Any]:
    """Every public module in the package, at any depth, not only what ``__init__`` re-exports.

    Walking the package rather than ``__all__`` is the difference between a guard that
    keeps working and one that quietly stops: the likeliest future breach is a *new*
    module — ``xman_research.validation.deflated_sharpe(sharpe, n_trials=...)`` — that
    nobody thought to re-export. The guard has to see it on the day it is written.

    ``walk_packages``, not ``iter_modules``: the latter does not descend into
    subpackages, so the guard's own stated threat — which is written as living in a
    ``validation`` subpackage — would have walked straight past it. The guard was
    checking exactly the modules that already existed.
    ``test_the_walker_would_catch_a_nested_offender`` is the proof it now descends.
    """
    modules = [package]
    prefix = f"{package.__name__}."
    for found in pkgutil.walk_packages(package.__path__, prefix):
        # The last segment, not the dotted path: with a prefix every name contains dots,
        # so testing the whole string would stop excluding private modules.
        if any(part.startswith("_") for part in found.name.split(".")):
            continue
        modules.append(importlib.import_module(found.name))
    return modules


def public_callables(package: Any = xman_research) -> Iterator[tuple[str, Any]]:
    seen: set[tuple[str, str]] = set()
    for module in package_modules(package):
        for name, obj in inspect.getmembers(module):
            if name.startswith("_"):
                continue
            origin = getattr(obj, "__module__", "")
            if not isinstance(origin, str) or not origin.startswith(package.__name__):
                continue
            key = (origin, name)
            if key in seen:
                continue
            seen.add(key)
            if inspect.isclass(obj):
                for member_name, member in inspect.getmembers(obj):
                    if member_name.startswith("_") and member_name != "__init__":
                        continue
                    if inspect.isfunction(member) or inspect.ismethod(member):
                        yield f"{origin}.{name}.{member_name}", member
                    elif isinstance(member, property) and member.fset is not None:
                        yield f"{origin}.{name}.{member_name} (setter)", member.fset
            elif callable(obj):
                yield f"{origin}.{name}", obj


def test_the_public_surface_is_non_empty() -> None:
    """Guards the guard: a test that enumerates nothing would pass vacuously."""
    names = [name for name, _ in public_callables()]
    assert len(names) > 30
    assert any(name.endswith("TrialLog.count_trials") for name in names)
    assert any(name.endswith("evaluation.open_session") for name in names)
    # Every module in the package is represented, so a new one cannot slip the guard.
    covered = {name.split(".")[1] for name in names}
    assert {"hypothesis", "trial_log", "evaluation", "clock", "code_version"} <= covered


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
    """No `set_trial_count`, no `override_trials`, no `declare_trials`."""
    for qualified_name, _ in public_callables():
        leaf = qualified_name.split(".")[-1].lower()
        assert not (
            leaf.startswith(("set_", "override_", "assert_", "declare_", "force_"))
            and ("trial" in leaf or "count" in leaf)
        ), f"{qualified_name} looks like a way to assert a trial count"


def offending_parameters(qualified_name: str, function: Any) -> list[str]:
    """The check itself, factored out so the guard can be run against a fake package."""
    try:
        signature = inspect.signature(function)
    except (ValueError, TypeError):  # pragma: no cover - builtins without signatures
        return []
    offending = []
    for parameter_name in signature.parameters:
        lowered = parameter_name.lower()
        if any(token in lowered for token in FORBIDDEN_SUBSTRINGS):
            offending.append(f"{qualified_name}:{parameter_name}")
    return offending


def test_the_walker_would_catch_a_nested_offender(tmp_path: Path) -> None:
    """The mutation test: prove the guard fails when the thing it guards against exists.

    A guard that has only ever been observed passing is not evidence of anything — and
    this one was, until now, structurally incapable of failing in the way its own
    docstring describes. It enumerated with ``pkgutil.iter_modules``, which does not
    descend, so the breach it names — ``validation.deflated_sharpe(sharpe, n_trials=...)``
    in a *subpackage* — would have gone unseen.

    So: build that exact offender as a real, importable package, run the real
    enumeration and the real check over it, and assert they flag it. If the walker ever
    stops descending, this test fails while every other test in the file still passes.
    """
    root = tmp_path / "probe_pkg"
    (root / "validation").mkdir(parents=True)
    (root / "__init__.py").write_text("")
    (root / "validation" / "__init__.py").write_text("")
    (root / "validation" / "deflated_sharpe.py").write_text(
        "def deflated_sharpe(sharpe: float, n_trials: int = 1) -> float:\n"
        "    return sharpe / n_trials\n"
    )

    sys.path.insert(0, str(tmp_path))
    try:
        probe = importlib.import_module("probe_pkg")
        enumerated = dict(public_callables(probe))
        offenders = [
            hit
            for name, function in enumerated.items()
            for hit in offending_parameters(name, function)
        ]
    finally:
        sys.path.remove(str(tmp_path))
        for name in [n for n in sys.modules if n.startswith("probe_pkg")]:
            del sys.modules[name]

    assert any("validation.deflated_sharpe" in name for name in enumerated), (
        "the walker did not descend into the subpackage — this is the m-11 defect, and "
        "it means the guard cannot see the breach it was written to catch"
    )
    assert offenders, "the check did not flag n_trials= on a nested public callable"
    assert any("n_trials" in hit for hit in offenders)


def test_the_real_package_is_still_clean_under_the_same_check() -> None:
    """The other half of the mutation test: the same machinery, applied for real."""
    offenders = [
        hit for name, function in public_callables() for hit in offending_parameters(name, function)
    ]
    assert offenders == []
