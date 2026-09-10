"""Facts are typed, immutable, and record who produced them."""

from __future__ import annotations

import pytest

from apex.kernel import errors, identifiers
from apex.pipeline import facts

BUILD = facts.FactKey[str]("build_id")
DIGEST = facts.FactKey[str]("digest")


def test_a_map_returns_what_was_put_in_it() -> None:
    updated = facts.FactMap().with_fact(BUILD, "abc", produced_by=identifiers.StageId("load"))

    assert updated[BUILD] == "abc"


def test_the_original_map_is_unchanged() -> None:
    original = facts.FactMap()

    original.with_fact(BUILD, "abc", produced_by=identifiers.StageId("load"))

    assert BUILD not in original


def test_a_map_records_which_stage_produced_each_fact() -> None:
    updated = facts.FactMap().with_fact(BUILD, "abc", produced_by=identifiers.StageId("load"))

    assert str(updated.producer(BUILD)) == "load"


def test_reading_an_absent_fact_names_what_is_present() -> None:
    populated = facts.FactMap().with_fact(BUILD, "abc", produced_by=identifiers.StageId("load"))

    with pytest.raises(errors.InternalDefect) as raised:
        populated[DIGEST]

    assert "build_id" in str(raised.value)


def test_writing_a_fact_twice_is_a_defect() -> None:
    populated = facts.FactMap().with_fact(BUILD, "abc", produced_by=identifiers.StageId("load"))

    with pytest.raises(errors.InternalDefect):
        populated.with_fact(BUILD, "other", produced_by=identifiers.StageId("second"))


def test_two_keys_with_the_same_name_are_the_same_key() -> None:
    assert facts.FactKey[str]("build_id") == BUILD


def test_a_key_renders_its_name() -> None:
    assert str(BUILD) == "build_id"
