"""Which code produced a result.

A trial row that does not say which code ran is not reproducible, and a result from a
dirty working tree is not reproducible *at all* — the exact source is unrecoverable
once the tree moves on. So the dirty flag is recorded, loudly, rather than hidden.

The provider is injected for the same reason the clock is: shelling out to ``git``
inside business logic makes every test depend on the state of the developer's tree.
It also never raises — a missing ``git``, or a directory that is not a repository,
degrades to ``CodeVersion("unknown", dirty=True)``. An evaluation must not be lost
because provenance capture failed; ``unknown`` + dirty is the honest description of
"we cannot vouch for this".
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

__all__ = ["CodeVersion", "CodeVersionProvider", "GitCodeVersion", "StaticCodeVersion"]

UNKNOWN_SHA = "unknown"
_GIT_TIMEOUT_SECONDS = 10


@dataclass(frozen=True, slots=True)
class CodeVersion:
    """A commit id plus whether the working tree had uncommitted changes."""

    sha: str
    dirty: bool

    def __str__(self) -> str:
        return f"{self.sha}{'-dirty' if self.dirty else ''}"


@runtime_checkable
class CodeVersionProvider(Protocol):
    def __call__(self) -> CodeVersion: ...


class StaticCodeVersion:
    """A fixed version. For tests, and for environments with no git checkout."""

    def __init__(self, sha: str = UNKNOWN_SHA, *, dirty: bool = True) -> None:
        self._version = CodeVersion(sha=sha, dirty=dirty)

    def __call__(self) -> CodeVersion:
        return self._version


class GitCodeVersion:
    """Read HEAD and the dirty flag from a git working tree.

    The result is cached for the life of the instance: a research session is short,
    the tree does not change under it, and re-forking ``git`` on every evaluation is
    pure overhead. Construct a new provider if the tree really has moved.
    """

    def __init__(self, repo_root: Path | str | None = None) -> None:
        self._repo_root = Path(repo_root) if repo_root is not None else Path.cwd()
        self._cached: CodeVersion | None = None

    def __call__(self) -> CodeVersion:
        if self._cached is None:
            self._cached = self._read()
        return self._cached

    def _read(self) -> CodeVersion:
        sha = self._git("rev-parse", "HEAD")
        if sha is None:
            return CodeVersion(sha=UNKNOWN_SHA, dirty=True)
        status = self._git("status", "--porcelain", "--untracked-files=no")
        if status is None:
            return CodeVersion(sha=sha, dirty=True)
        return CodeVersion(sha=sha, dirty=bool(status.strip()))

    def _git(self, *args: str) -> str | None:
        try:
            completed = subprocess.run(
                ["git", "-C", str(self._repo_root), *args],
                capture_output=True,
                text=True,
                timeout=_GIT_TIMEOUT_SECONDS,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if completed.returncode != 0:
            return None
        return completed.stdout.strip()
