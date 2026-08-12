"""The two injected providers."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from xman_research import CodeVersion, GitCodeVersion, ManualClock, SystemClock
from xman_research.clock import require_aware
from xman_research.code_version import UNKNOWN_SHA, StaticCodeVersion


def test_system_clock_is_timezone_aware() -> None:
    assert SystemClock().now().tzinfo is not None


def test_manual_clock_is_pinned_by_default() -> None:
    pinned = datetime(2024, 1, 1, tzinfo=UTC)
    clock = ManualClock(pinned)
    assert clock.now() == pinned
    assert clock.now() == pinned


def test_manual_clock_steps_when_asked() -> None:
    clock = ManualClock(datetime(2024, 1, 1, tzinfo=UTC), step=timedelta(seconds=30))
    first, second = clock.now(), clock.now()
    assert second - first == timedelta(seconds=30)


def test_manual_clock_advance_and_set() -> None:
    clock = ManualClock(datetime(2024, 1, 1, tzinfo=UTC))
    clock.advance(timedelta(days=1))
    assert clock.now() == datetime(2024, 1, 2, tzinfo=UTC)
    clock.set(datetime(2030, 5, 5, tzinfo=UTC))
    assert clock.now() == datetime(2030, 5, 5, tzinfo=UTC)


def test_manual_clock_refuses_naive_time() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        ManualClock(datetime(2024, 1, 1))


def test_require_aware_passes_aware_time_through() -> None:
    moment = datetime(2024, 1, 1, tzinfo=UTC)
    assert require_aware(moment) is moment


# ------------------------------------------------------------- code version


def test_static_code_version_is_what_it_says() -> None:
    assert StaticCodeVersion("abc", dirty=False)() == CodeVersion("abc", False)


def test_code_version_renders_dirtiness_visibly() -> None:
    assert str(CodeVersion("abc", True)) == "abc-dirty"
    assert str(CodeVersion("abc", False)) == "abc"


def test_git_version_degrades_instead_of_raising(tmp_path: Path) -> None:
    """A missing checkout must not cost the researcher an evaluation."""
    version = GitCodeVersion(tmp_path)()
    assert version == CodeVersion(UNKNOWN_SHA, True)


def test_git_version_reads_a_real_tree(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    run = lambda *args: subprocess.run(  # noqa: E731
        ["git", "-C", str(repo), *args], check=True, capture_output=True
    )
    run("init", "-q")
    run("config", "user.email", "test@example.invalid")
    run("config", "user.name", "Test")
    (repo / "a.txt").write_text("one\n")
    run("add", "a.txt")
    run("commit", "-qm", "first")

    clean = GitCodeVersion(repo)()
    assert len(clean.sha) == 40
    assert clean.dirty is False

    (repo / "a.txt").write_text("two\n")
    dirty = GitCodeVersion(repo)()
    assert dirty.sha == clean.sha
    assert dirty.dirty is True


def test_an_untracked_file_counts_as_dirty(tmp_path: Path) -> None:
    """The least recoverable case of all: code the sha says nothing about."""
    repo = tmp_path / "repo"
    repo.mkdir()

    def run(*args: str) -> None:
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)

    run("init", "-q")
    run("config", "user.email", "test@example.invalid")
    run("config", "user.name", "Test")
    (repo / "a.txt").write_text("one\n")
    run("add", "a.txt")
    run("commit", "-qm", "first")
    assert GitCodeVersion(repo)().dirty is False

    (repo / "scratch_helper.py").write_text("SIZING = 2\n")
    assert GitCodeVersion(repo)().dirty is True


def test_git_version_is_cached_per_instance(tmp_path: Path) -> None:
    provider = GitCodeVersion(tmp_path)
    assert provider() is provider()
