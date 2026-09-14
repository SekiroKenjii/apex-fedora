"""A refusal has an identity, so tests match a code and never English."""

from __future__ import annotations

from apex.kernel import refusals


def test_every_reason_has_a_stable_lowercase_dotted_code() -> None:
    for reason in refusals.RefusalReason:
        assert reason.value == reason.value.lower()
        assert " " not in reason.value


def test_reason_codes_are_unique() -> None:
    values = [reason.value for reason in refusals.RefusalReason]

    assert len(values) == len(set(values))


def test_the_reasons_the_current_tools_already_express_are_present() -> None:
    required = {
        "malformed.digest",
        "malformed.identifier",
        "evidence.no-verified-result",
        "evidence.hardware-requires-physical",
        "evidence.pass-requires-proof",
        "path.outside-runtime-root",
        "path.not-a-regular-file",
    }

    assert required <= {reason.value for reason in refusals.RefusalReason}
