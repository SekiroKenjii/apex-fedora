"""Decode a coefficient command as integers, never opening a codec device.

The same arithmetic as the older `decode-coefficient`: the hwdep word, the canonical verb it
carries, the parameter as the hardware would see it, and whether an overlap changed it.
"""

from __future__ import annotations

from apex.kernel import encoding, errors, refusals

NID_LIMIT = 0xFF
VERB_LIMIT = 0xFFF
PARAMETER_LIMIT = 0xFFFF
COEFFICIENT_VERBS = frozenset({4, 5, 12, 13})


def operand(text: str, name: str) -> int:
    try:
        return int(text, 0)
    except ValueError as error:
        raise errors.Refusal(
            refusals.RefusalReason.REQUEST_MALFORMED,
            subject=f"{name} {text!r} is not an integer",
            remedy="write the operand in decimal or as 0x hexadecimal",
        ) from error


def decode(nid: int, verb: int, parameter: int) -> encoding.Document:
    in_range = 0 <= nid <= NID_LIMIT and 0 <= verb <= VERB_LIMIT
    if not (in_range and 0 <= parameter <= PARAMETER_LIMIT):
        raise errors.Refusal(
            refusals.RefusalReason.REQUEST_MALFORMED,
            subject="operand outside the hwdep input range",
            remedy="nid up to 0xff, verb up to 0xfff, parameter up to 0xffff",
        )
    if verb >> 8 not in COEFFICIENT_VERBS:
        raise errors.Refusal(
            refusals.RefusalReason.REQUEST_MALFORMED,
            subject="this decoder only accepts coefficient read/write verbs",
            remedy="use a verb whose high nibble is 4, 5, c or d",
        )
    word = (nid << 24) | (verb << 8) | parameter
    opcode = (word >> 8) & 0xF00
    effective = word & 0xFFFF
    return {
        "nid": f"0x{nid:02x}",
        "hwdep_word": f"0x{word:08x}",
        "canonical_verb": f"0x{opcode:03x}",
        "effective_parameter": f"0x{effective:04x}",
        "parameter_changed_by_overlap": effective != parameter,
        "device_access": False,
    }
