"""The coefficient decoder, checked against the outputs the older command recorded."""

from __future__ import annotations

import pytest

from apex.kernel import errors, refusals
from apex.verification import hdacoefficient


@pytest.mark.parametrize(
    ("nid", "verb", "parameter", "word", "canonical", "effective"),
    [
        (0x20, 0x500, 0x0, "0x20050000", "0x500", "0x0000"),
        (0x20, 0x400, 0xFF, "0x200400ff", "0x400", "0x00ff"),
        (0x20, 0xC00, 0x11, "0x200c0011", "0xc00", "0x0011"),
    ],
)
def test_the_word_the_verb_and_the_parameter_are_what_the_older_command_printed(
    nid: int, verb: int, parameter: int, word: str, canonical: str, effective: str
) -> None:
    assert hdacoefficient.decode(nid, verb, parameter) == {
        "nid": "0x20",
        "hwdep_word": word,
        "canonical_verb": canonical,
        "effective_parameter": effective,
        "parameter_changed_by_overlap": False,
        "device_access": False,
    }


def test_a_verb_that_is_not_a_coefficient_access_and_an_operand_out_of_range_are_refused() -> None:
    with pytest.raises(errors.Refusal) as verb:
        hdacoefficient.decode(0x14, 0x3, 0x80)
    with pytest.raises(errors.Refusal) as too_wide:
        hdacoefficient.decode(0x100, 0x500, 0x0)
    with pytest.raises(errors.Refusal) as text:
        hdacoefficient.operand("twenty", "nid")

    assert verb.value.reason is refusals.RefusalReason.REQUEST_MALFORMED
    assert "coefficient read/write verbs" in str(verb.value)
    assert too_wide.value.reason is refusals.RefusalReason.REQUEST_MALFORMED
    assert text.value.reason is refusals.RefusalReason.REQUEST_MALFORMED
    assert hdacoefficient.operand("0x20", "nid") == 32 and hdacoefficient.operand("32", "nid") == 32


def test_an_overlapping_parameter_is_reported_as_changed() -> None:
    decoded = hdacoefficient.decode(0x20, 0x5FF, 0x1234)

    assert decoded["hwdep_word"] == "0x2005ff34"
    assert decoded["effective_parameter"] == "0xff34"
    assert decoded["parameter_changed_by_overlap"] is True
