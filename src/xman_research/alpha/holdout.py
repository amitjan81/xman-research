"""The corpus-wide seal, and the one check that enforces it.

The alpha loop screens, gates and settles over the same captured corpus that
``research/h1`` reserves its unseen months in. Those months are a pre-registration: reading
them under a different hypothesis, in a different log, spends them just as surely, and
``H1``'s own :func:`~xman_research.validation.gate.inspect_holdout` cannot see it happen
because it queries one trial log's families and the alpha loop files elsewhere.

So the seal lives here as a date rather than as a convention held in each caller's choice of
window, and both entry points that can read past it — the stage-two gate and the idea
ledger's settlement — go through :func:`require_unsealed`. An override is available and it
is a written one: the reason travels into the artefact the run produces, so a window past
the seal is answerable afterwards rather than merely possible.
"""

from __future__ import annotations

import datetime as dt

__all__ = ["HOLDOUT_FIRST_DATE", "SealedWindowError", "require_unsealed"]

#: The first sealed session. Sessions on or after it are H1's unseen months, and the value
#: is the ``holdout_first_date`` recorded in ``research/h1/validation.toml``. Spelled once so
#: that the gate and the ledger cannot come to hold two different opinions about where the
#: corpus stops being readable.
HOLDOUT_FIRST_DATE = dt.date(2026, 5, 1)


class SealedWindowError(ValueError):
    """A window that would read sessions the corpus has reserved, with no written override."""


def require_unsealed(end: dt.date, *, what: str, override_reason: str | None = None) -> str | None:
    """Refuse a window ending on or after :data:`HOLDOUT_FIRST_DATE`, or record why not.

    Returns the override reason where one was given, so a caller can put it in the record it
    writes; returns ``None`` for a window that never needed one. A blank override is not an
    override — an empty string is what an automated caller passes when it has nothing to say.
    """
    if end < HOLDOUT_FIRST_DATE:
        return None
    if override_reason is not None and override_reason.strip():
        return override_reason.strip()
    raise SealedWindowError(
        f"{what} ends {end}, on or after {HOLDOUT_FIRST_DATE}, which research/h1 has sealed "
        "as its unseen months. Reading them here spends them there, and H1's own holdout "
        "check cannot see a read filed in another log. Move the window, or pass a written "
        "override saying why these months may be read."
    )
