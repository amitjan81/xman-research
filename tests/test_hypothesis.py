"""Acceptance criterion 1: a record without a mechanism, a null or written thresholds
is refused at construction."""

from __future__ import annotations

import dataclasses

import pytest

from xman_research import HypothesisRecord, HypothesisValidationError

VALID = {
    "name": "H1",
    "mechanism": "Hedgers pay up for protection, so implied exceeds realised variance.",
    "null_hypothesis": "The implied-minus-realised mean is not positive after costs.",
    "thresholds": {"deflated_sharpe": 0.0},
}


def make(**overrides: object) -> HypothesisRecord:
    return HypothesisRecord(**{**VALID, **overrides})  # type: ignore[arg-type]


@pytest.mark.parametrize("missing", ["mechanism", "null_hypothesis"])
@pytest.mark.parametrize("blank", ["", "   ", "\n\t ", None])
def test_refuses_blank_prose_field(missing: str, blank: object) -> None:
    with pytest.raises(HypothesisValidationError, match=missing):
        make(**{missing: blank})


@pytest.mark.parametrize("empty", [{}, None])
def test_refuses_missing_thresholds(empty: object) -> None:
    with pytest.raises(HypothesisValidationError, match="thresholds"):
        make(thresholds=empty)


@pytest.mark.parametrize("bad", [{"dsr": None}, {"dsr": "  "}, {"  ": 1.0}])
def test_refuses_blank_threshold_entries(bad: dict) -> None:
    with pytest.raises(HypothesisValidationError):
        make(thresholds=bad)


def test_refuses_blank_name() -> None:
    with pytest.raises(HypothesisValidationError, match="name"):
        make(name="  ")


def test_refuses_blank_predictor_names() -> None:
    with pytest.raises(HypothesisValidationError, match="predictor"):
        make(predictors=["iv_30d", " "])


def test_accepts_a_complete_record() -> None:
    record = make()
    assert record.id.startswith("h_")
    assert record.mechanism == VALID["mechanism"]
    assert record.parent_id is None


# The BANKNIFTY stage-one record's own content, transcribed from the screen it
# registered. Assembled line by line so the source stays readable at any width: the
# prose is hashed into the id, so a rewrap here is a different record.
BANKNIFTY_MECHANISM = "\n".join(
    [
        "BANKNIFTY index-option implied variance sits above subsequently realised variance",
        "for the same reason NIFTY's does: index hedgers and structured-product desks buy",
        "convexity with price insensitivity and somebody must warehouse it. BANKNIFTY",
        "prices that warehousing differently — its constituents are one sector, its",
        "realised volatility is higher, and since 2024-11-13 its front contract expires",
        "monthly rather than weekly, which lengthens the decay window a short-variance",
        "book sits inside. Whether the premium is best collected at the money, across a",
        "band of strikes, with a bought tail, or only on sessions a conditioner selects,",
        "is an empirical question about this corpus and not about the mechanism.",
    ]
)

BANKNIFTY_NULL = "\n".join(
    [
        "No screened structure or conditioner produces a positive risk-matched spread over",
        "the unconditional short at-the-money BANKNIFTY straddle held for the same number",
        "of sessions.",
    ]
)

BANKNIFTY_NOTES = "\n".join(
    [
        "Holds are capped at five sessions by the owner's 1-5 day mandate. The corpus",
        "window is entirely in-sample: BANKNIFTY sessions from 2026-06-01 are sealed and",
        "no instance here may read one.",
    ]
)

BANKNIFTY_PREDICTORS = (
    "atm_iv_minus_rv20",
    "day_of_week",
    "ema20_z_abs",
    "overnight_gap_sigmas",
    "sessions_to_nearest_expiry",
)


# ------------------------------------------------------------------ identity


def test_same_content_is_the_same_id() -> None:
    assert make().id == make().id


def test_predictor_order_does_not_change_the_id() -> None:
    assert make(predictors=["a", "b"]).id == make(predictors=["b", "a"]).id


def test_threshold_insertion_order_does_not_change_the_id() -> None:
    first = make(thresholds={"max_drawdown": 1.0, "pbo": 2.0})
    second = make(thresholds={"pbo": 2.0, "max_drawdown": 1.0})
    assert first.id == second.id


def test_changed_threshold_is_a_different_id() -> None:
    assert make(thresholds={"deflated_sharpe": 0.5}).id != make().id


def test_id_is_stable_across_processes() -> None:
    """Guards against set/dict iteration order leaking into the hash via PYTHONHASHSEED."""
    import subprocess
    import sys

    program = (
        "from xman_research import HypothesisRecord;"
        "print(HypothesisRecord(name='H1',"
        "mechanism='m', null_hypothesis='n',"
        "thresholds={'pbo': 2.0, 'max_drawdown': 1.0}, predictors=['z', 'a', 'm']).id)"
    )
    ids = set()
    for seed in ("0", "1", "12345"):
        completed = subprocess.run(
            [sys.executable, "-c", program],
            capture_output=True,
            text=True,
            check=True,
            env={"PYTHONHASHSEED": seed, "PATH": "/usr/bin:/bin"},
        )
        ids.add(completed.stdout.strip())
    assert len(ids) == 1


# --------------------------------------------------------------- immutability


def test_record_is_frozen() -> None:
    record = make()
    with pytest.raises(dataclasses.FrozenInstanceError):
        record.thresholds = {"deflated_sharpe": 9.9}  # type: ignore[misc]


def test_thresholds_mapping_cannot_be_mutated_in_place() -> None:
    record = make()
    with pytest.raises(TypeError):
        record.thresholds["deflated_sharpe"] = 9.9  # type: ignore[index]


def test_mutating_the_source_dict_does_not_change_the_record() -> None:
    source = {"deflated_sharpe": 0.0}
    record = make(thresholds=source)
    source["deflated_sharpe"] = 9.9
    assert record.thresholds["deflated_sharpe"] == 0.0


# ------------------------------------------------------------------ amendment


def test_amend_returns_a_new_record_pointing_at_its_parent() -> None:
    original = make()
    amended = original.amend(thresholds={"deflated_sharpe": 0.5})

    assert amended.id != original.id
    assert amended.parent_id == original.id
    assert original.parent_id is None
    assert amended.mechanism == original.mechanism


def test_amend_rejects_unknown_fields() -> None:
    with pytest.raises(HypothesisValidationError, match="unknown field"):
        make().amend(sharpe=1.0)


def test_amend_still_validates() -> None:
    with pytest.raises(HypothesisValidationError, match="mechanism"):
        make().amend(mechanism="   ")


def test_equality_and_hashing_are_by_id() -> None:
    assert make() == make()
    assert len({make(), make(), make(thresholds={"deflated_sharpe": 1.0})}) == 2
    assert make() != "h_not_a_record"


# ----------------------------------------------- deep immutability (finding M-4)


def test_nested_mappings_are_frozen_too() -> None:
    """Freezing only the top level is not freezing.

    ``_freeze_mapping`` took a shallow copy, so a nested dict stayed the caller's own
    object: mutating it afterwards changed the record's content while ``id`` — derived
    from that content at construction — stayed put. The record then no longer hashed to
    the id it was persisted under, which is the drift the content-addressed id exists to
    make impossible.
    """
    inner = {"lower": 0.0, "upper": 1.0}
    record = make(thresholds={"deflated_sharpe": 0.0, "bands": inner})

    with pytest.raises(TypeError):
        record.thresholds["bands"]["lower"] = 9.9  # type: ignore[index]


def test_mutating_a_nested_source_dict_cannot_drift_the_id() -> None:
    inner = {"lower": 0.0}
    record = make(thresholds={"deflated_sharpe": 0.0, "bands": inner})
    original_id = record.id

    inner["lower"] = 99.0

    assert record.thresholds["bands"] == {"lower": 0.0}
    assert record.id == original_id
    assert record._derive_id() == record.id, "content must still hash to the stored id"


def test_nested_lists_are_frozen_as_tuples() -> None:
    strikes = [100, 200]
    record = make(thresholds={"deflated_sharpe": 0.0}, entry_rule={"strikes": strikes})
    strikes.append(300)

    assert record.entry_rule["strikes"] == (100, 200)
    assert record._derive_id() == record.id


def test_freezing_refuses_a_cyclic_threshold() -> None:
    """Refused at construction, where nothing is at stake — no trial has run yet."""
    cyclic: dict = {"lower": 0.0}
    cyclic["self"] = cyclic
    with pytest.raises(HypothesisValidationError, match=r"nests deeper|cycle"):
        make(thresholds={"deflated_sharpe": 0.0, "bands": cyclic})


# -------------------------------------------------------- ids and amendment nits


def test_the_id_is_128_bits_wide() -> None:
    """The id is the join key between a record and its trials; width is free."""
    record = make()
    assert record.id.startswith("h_")
    assert len(record.id) == len("h_") + 32
    int(record.id[2:], 16)


def test_amend_refuses_a_parent_id_rather_than_discarding_it() -> None:
    """It used to be dropped in silence, while every other unknown field raised.

    The parent chain is what makes the family count span a campaign, so a caller who
    believes they re-parented an amendment and has not is left with a count that is
    wrong in the direction that flatters them.
    """
    record = make()
    with pytest.raises(HypothesisValidationError, match="parent_id"):
        record.amend(parent_id="h_somewhere_else", notes="v2")

    amended = record.amend(notes="v2")
    assert amended.parent_id == record.id


# ------------------------------------------------------- the gradeable vocabulary


def test_a_threshold_no_component_measures_is_refused_at_registration() -> None:
    with pytest.raises(HypothesisValidationError, match="alpha_to_advance"):
        make(thresholds={"deflated_sharpe": 0.9, "alpha_to_advance": 0.5})


def test_the_refusal_names_the_vocabulary_and_where_a_screen_bar_belongs() -> None:
    with pytest.raises(HypothesisValidationError) as raised:
        make(thresholds={"alpha_to_advance": 0.5})
    message = str(raised.value)
    assert "deflated_sharpe" in message
    assert "screen_criteria" in message


def test_a_holdout_prefixed_threshold_is_read_against_the_same_vocabulary() -> None:
    assert make(thresholds={"holdout.deflated_sharpe": 0.5}).id
    with pytest.raises(HypothesisValidationError, match=r"holdout\.alpha_to_advance"):
        make(thresholds={"holdout.alpha_to_advance": 0.5})


def test_a_non_numeric_threshold_is_recorded_rather_than_graded() -> None:
    """Binding reconciles numeric thresholds only, so only those must be measurable."""
    record = make(thresholds={"deflated_sharpe": 0.9, "policy": "documented in the spec"})
    assert record.thresholds["policy"] == "documented in the spec"


def test_a_record_that_carries_no_screen_criteria_hashes_as_it_did_without_the_field() -> None:
    """Ids are quoted in committed gate files and every trial row; adding a field to the
    record must leave every id already minted where it is."""
    record = make()
    assert "screen_criteria" not in record.content()
    assert record.id == make(screen_criteria={}).id


def test_screen_criteria_are_id_bearing_and_frozen() -> None:
    record = make(screen_criteria={"alpha_to_advance": 0.5})
    assert record.id != make().id
    assert record.screen_criteria["alpha_to_advance"] == 0.5
    with pytest.raises(TypeError):
        record.screen_criteria["alpha_to_advance"] = 9.9  # type: ignore[index]


def test_a_screen_bar_is_not_held_to_the_gate_vocabulary() -> None:
    assert make(screen_criteria={"alpha_to_advance": 0.5}).screen_criteria


def test_a_stored_record_is_readable_after_the_vocabulary_narrows() -> None:
    """A log is append-only evidence: a record registered under an older rule must still
    be readable, including by the amendment that brings it into line."""
    stored = HypothesisRecord.from_stored(
        name="H1",
        mechanism="Hedgers pay up for protection.",
        null_hypothesis="No positive mean after costs.",
        thresholds={"alpha_to_advance": 0.5},
    )
    assert stored.thresholds["alpha_to_advance"] == 0.5
    amended = stored.amend(
        thresholds={"deflated_sharpe": 0.9}, screen_criteria={"alpha_to_advance": 0.5}
    )
    assert amended.parent_id == stored.id


def test_a_record_minted_before_screen_criteria_existed_still_hashes_to_its_id() -> None:
    """A literal id, pinned. The relational test above cannot catch a change to the hashed
    content that moves every record equally; this one can. The value is the BANKNIFTY
    stage-one record, quoted in research/banknifty/gate_v1.toml and carried by every trial
    row of that screen — if this fails, that log's join key has moved."""
    record = HypothesisRecord.from_stored(
        name=(
            "BANKNIFTY stage-1 screen: does a wider structure or a conditioner beat the "
            "short ATM straddle"
        ),
        mechanism=BANKNIFTY_MECHANISM,
        null_hypothesis=BANKNIFTY_NULL,
        thresholds={"alpha_to_advance": 0.5},
        predictors=BANKNIFTY_PREDICTORS,
        notes=BANKNIFTY_NOTES,
    )
    assert record.id == "h_a2c7cc855f6f06b2581afb7f2079121d"
