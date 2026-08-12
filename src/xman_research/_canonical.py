"""Canonical JSON encoding.

Two callers, one reason each:

* :mod:`xman_research.hypothesis` hashes a record to derive its id, so the encoding
  must be stable across processes and across insertion order. Anything order-dependent
  (``set`` iteration, ``dict`` insertion order) would make the "same record, same id"
  property quietly false.
* :mod:`xman_research.trial_log` persists caller-supplied params and metrics, which
  may contain objects JSON does not know. Those degrade to ``repr`` rather than raising
  — a trial that fails to log because a param was exotic is a worse outcome than a
  trial logged with an approximate param value.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence, Set
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

__all__ = ["canonical_json", "json_safe"]


def json_safe(value: Any) -> Any:
    """Convert ``value`` into something ``json.dumps`` accepts, deterministically."""
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, Enum):
        return json_safe(value.value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(k): json_safe(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, Set):
        return sorted((json_safe(v) for v in value), key=repr)
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [json_safe(v) for v in value]
    # Numeric wrappers — numpy scalars and anything else following the ``.item()``
    # convention — unwrap to a plain Python number. This matters most in the metrics
    # column: `np.float64` happens to be a `float` subclass and survives above, but
    # `np.int64` and `np.float32` are not, and a metric silently stored as the string
    # "np.int64(412)" is the kind of degradation nobody notices until the number is
    # needed. `df["qty"].sum()` is the ordinary way a backtest metric arrives.
    unwrap = getattr(value, "item", None)
    if callable(unwrap):
        try:
            unwrapped = unwrap()
        # Broad on purpose: a hostile .item() must not cost us the trial row.
        except Exception:
            pass
        else:
            if unwrapped is not value:
                return json_safe(unwrapped)
    return repr(value)


def canonical_json(value: Any) -> str:
    """Encode ``value`` as JSON with sorted keys and no incidental whitespace."""
    return json.dumps(
        json_safe(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
