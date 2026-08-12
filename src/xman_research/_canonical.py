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

**Encoding here is total: no input makes it raise.** That is not a nicety, it is the
load-bearing property of the second caller. The trial row is appended in a ``finally``
after the evaluation body has already run, so *any* exception raised while serialising
means the researcher keeps a result that the log never recorded — an un-logged
evaluation, which is exactly what this package exists to prevent. A circular reference
in a config dict (``d["self"] = d``) is an ordinary accident and used to cost the row;
deep nesting, a hostile ``__iter__``, and a ``repr`` that raises are the same class.
Every one of them degrades to a placeholder string instead.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Mapping, Sequence, Set
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

__all__ = ["canonical_json", "json_safe", "safe_json_dumps", "safe_repr"]

# Deep *non-cyclic* nesting hits Python's recursion limit without ever repeating an
# object, so a cycle guard alone is not enough. Anything past this depth is a config
# blob nobody reads at the bottom of, not a value worth losing a trial row over.
MAX_DEPTH = 60


def safe_repr(value: Any) -> str:
    """``repr(value)`` that cannot raise — the terminal degradation for anything else."""
    try:
        return repr(value)
    except Exception:
        try:
            return f"<unrepresentable {type(value).__name__}>"
        except Exception:
            return "<unrepresentable>"


def _safe_str(value: Any) -> str:
    try:
        return str(value)
    except Exception:
        return safe_repr(value)


def json_safe(value: Any) -> Any:
    """Convert ``value`` into something ``json.dumps`` accepts, deterministically.

    Total: every failure mode degrades to a placeholder string rather than raising.
    """
    return _convert(value, 0, set())


def _convert(value: Any, depth: int, path: set[int]) -> Any:
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if depth >= MAX_DEPTH:
        return f"<truncated at depth {MAX_DEPTH}: {safe_repr(value)}>"
    # Only the containers *currently on the path* are tracked, not every object seen:
    # the same dict referenced twice side by side is not a cycle and should serialise
    # normally both times.
    marker = id(value)
    if marker in path:
        return f"<circular {type(value).__name__}>"

    if isinstance(value, Decimal):
        try:
            return float(value)
        except Exception:
            return safe_repr(value)
    if isinstance(value, Enum):
        try:
            inner = value.value
        except Exception:
            return safe_repr(value)
        return _convert(inner, depth + 1, path)
    if isinstance(value, datetime | date):
        try:
            return value.isoformat()
        except Exception:
            return safe_repr(value)

    if isinstance(value, Mapping):
        return _convert_mapping(value, depth, path, marker)
    if isinstance(value, Set):
        return _convert_set(value, depth, path, marker)
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return _convert_sequence(value, depth, path, marker)

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
                return _convert(unwrapped, depth + 1, path)
    return safe_repr(value)


def _convert_mapping(value: Mapping[Any, Any], depth: int, path: set[int], marker: int) -> Any:
    path.add(marker)
    try:
        try:
            items = list(value.items())
        # A mapping whose .items() raises is still worth logging approximately.
        except Exception:
            return safe_repr(value)
        # An unsortable mix of key types is not worth a row; unsorted output is only
        # a determinism loss, and json.dumps(sort_keys=True) re-sorts downstream anyway.
        with contextlib.suppress(Exception):
            items.sort(key=lambda kv: _safe_str(kv[0]))
        return {_safe_str(k): _convert(v, depth + 1, path) for k, v in items}
    finally:
        path.discard(marker)


def _convert_set(value: Set[Any], depth: int, path: set[int], marker: int) -> Any:
    path.add(marker)
    try:
        try:
            converted = [_convert(item, depth + 1, path) for item in value]
        except Exception:
            return safe_repr(value)
        with contextlib.suppress(Exception):
            converted.sort(key=safe_repr)
        return converted
    finally:
        path.discard(marker)


def _convert_sequence(value: Sequence[Any], depth: int, path: set[int], marker: int) -> Any:
    path.add(marker)
    try:
        try:
            return [_convert(item, depth + 1, path) for item in value]
        except Exception:
            return safe_repr(value)
    finally:
        path.discard(marker)


def canonical_json(value: Any) -> str:
    """Encode ``value`` as JSON with sorted keys and no incidental whitespace."""
    return json.dumps(
        json_safe(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def safe_json_dumps(value: Any) -> str:
    """Encode ``value`` as JSON, with no failure mode at all.

    :func:`json_safe` already degrades rather than raises, so this outer guard should
    be unreachable. It is here because "unreachable" is a claim about code, and the
    thing being protected — that an evaluation which ran is an evaluation which is
    logged — is worth a belt as well as braces at the last boundary before the row is
    written.
    """
    try:
        return json.dumps(json_safe(value), sort_keys=True, ensure_ascii=False)
    except Exception:
        try:
            return json.dumps({"__unserializable__": safe_repr(value)}, ensure_ascii=False)
        except Exception:
            return '{"__unserializable__": "<unserializable>"}'
