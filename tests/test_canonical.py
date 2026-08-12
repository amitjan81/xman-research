"""The canonical encoder, which must be total.

Every test here is a way the encoder used to raise. That matters more than it looks:
the encoder runs inside the ``finally`` that appends the trial row, so an exception
raised here does not fail an evaluation — it erases one that already ran. An
approximate value in a params column is a small loss; a missing row is the loss the
whole package exists to prevent.
"""

from __future__ import annotations

import json

import pytest

from xman_research._canonical import (
    MAX_DEPTH,
    canonical_json,
    json_safe,
    safe_json_dumps,
    safe_repr,
)


def test_ordinary_values_are_unchanged() -> None:
    assert json_safe({"b": 1, "a": [1, 2.5, "x", True, None]}) == {
        "a": [1, 2.5, "x", True, None],
        "b": 1,
    }


def test_a_self_referencing_dict_degrades_instead_of_recursing() -> None:
    """``d = {}; d["self"] = d`` — a config dict with a back-reference is ordinary."""
    d: dict = {"tenor": "30d"}
    d["self"] = d

    converted = json_safe(d)

    assert converted["tenor"] == "30d"
    assert "circular" in converted["self"]
    json.dumps(converted)


def test_a_self_referencing_list_degrades_too() -> None:
    items: list = [1]
    items.append(items)
    converted = json_safe(items)
    assert converted[0] == 1
    assert "circular" in converted[1]


def test_a_repeated_sibling_is_not_mistaken_for_a_cycle() -> None:
    """Only containers on the current path are cycles; a shared value is not one."""
    shared = {"k": 1}
    converted = json_safe({"a": shared, "b": shared})
    assert converted == {"a": {"k": 1}, "b": {"k": 1}}


def test_deep_non_cyclic_nesting_is_truncated_not_fatal() -> None:
    """A cycle guard alone does not save you: 3000 distinct dicts blow the stack."""
    deep: object = {"leaf": 1}
    for _ in range(3000):
        deep = {"nested": deep}

    converted = json_safe(deep)

    assert "truncated" in json.dumps(converted)


def test_the_depth_limit_is_where_it_says_it_is() -> None:
    shallow: object = "leaf"
    for _ in range(MAX_DEPTH - 2):
        shallow = {"n": shallow}
    assert "truncated" not in json.dumps(json_safe(shallow))


class _HostileRepr:
    def __repr__(self) -> str:
        raise RuntimeError("no repr for you")


class _HostileItems(dict):
    def items(self):  # type: ignore[no-untyped-def]
        raise RuntimeError("no items for you")


class _HostileItem:
    def item(self):  # type: ignore[no-untyped-def]
        raise RuntimeError("no item for you")


def test_an_object_whose_repr_raises_still_encodes() -> None:
    """The terminal degradation is ``repr``, so ``repr`` itself needs a fallback."""
    assert "unrepresentable" in safe_repr(_HostileRepr())
    json.dumps(json_safe({"model": _HostileRepr()}))


def test_a_mapping_whose_items_raises_still_encodes() -> None:
    hostile = _HostileItems()
    hostile["a"] = 1
    json.dumps(json_safe({"cfg": hostile}))


def test_a_hostile_item_method_does_not_cost_the_value() -> None:
    """The numpy ``.item()`` unwrap must not become a new way to raise."""
    json.dumps(json_safe({"metric": _HostileItem()}))


def test_unhashable_and_mixed_keys_are_stringified_deterministically() -> None:
    converted = json_safe({1: "a", "1": "b", (2, 3): "c"})
    assert set(converted) == {"1", "(2, 3)"}
    json.dumps(converted)


def test_safe_json_dumps_never_raises() -> None:
    for value in ({"a": 1}, _HostileRepr(), object(), [{"x": _HostileRepr()}]):
        assert isinstance(safe_json_dumps(value), str)


def test_canonical_json_is_order_independent() -> None:
    """The id derivation depends on this: same content, same bytes, same id."""
    assert canonical_json({"b": 1, "a": 2}) == canonical_json({"a": 2, "b": 1})


@pytest.mark.parametrize(
    "value",
    [
        {"nested": {"deep": [1, {"deeper": (2, 3)}]}},
        [set(), frozenset({1}), {}],
        {"mixed": [None, True, 1.5, "s"]},
    ],
)
def test_output_is_always_json_encodable(value: object) -> None:
    json.dumps(json_safe(value))
