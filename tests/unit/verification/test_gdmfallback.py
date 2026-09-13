"""The fallback evaluator reads the observer's records out of the journal and judges them."""

from __future__ import annotations

import json

from apex.verification import gdmfallback

GOOD = "sha256:" + "1" * 64
BAD = "sha256:" + "2" * 64
BOOT_1, BOOT_2, BOOT_3 = "a" * 32, "b" * 32, "c" * 32


def observation(boot: str, phase: str, digest: str, *, counter: str | None, gdm: str) -> str:
    grubenv = f"boot_success=0\ngreenboot_next_deployment_id={BAD}\n"
    if counter is not None:
        grubenv += f"boot_counter={counter}\n"
    record = {
        "boot_id": boot, "phase": phase, "digest": digest,
        "injected": phase == "gdm-start" and digest == BAD,
        "gdm": {"stdout": gdm}, "grubenv": {"stdout": grubenv},
    }
    return gdmfallback.PREFIX + json.dumps(record)


def line(boot: str, message: str) -> str:
    return json.dumps({"_BOOT_ID": boot, "MESSAGE": message})


def failed_boot(boot: str, counter: str | None) -> list[str]:
    failed = "ActiveState=failed\n"
    return [
        line(boot, observation(boot, "gdm-start", BAD, counter=counter, gdm=failed)),
        line(boot, gdmfallback.INJECTED_EXIT + "n/a"),
        line(boot, observation(boot, "health-before", BAD, counter=counter, gdm=failed)),
        line(boot, gdmfallback.HEALTH_REJECTED),
    ]


def journal(*, failures: int = 2, rollback: bool = True, recovered: bool = True) -> str:
    boots = [BOOT_1, BOOT_2, BOOT_3][:failures]
    lines: list[str] = []
    for index, boot in enumerate(boots):
        lines += failed_boot(boot, None if index == 0 else str(failures - 1 - index))
    if rollback:
        lines.append(line(boots[-1], "greenboot: " + gdmfallback.ROLLED_BACK))
    if recovered:
        active = observation(
            "d" * 32, "health-before", GOOD, counter=None, gdm="ActiveState=active\n"
        )
        lines.append(line("d" * 32, active))
        lines.append(line("d" * 32, gdmfallback.HEALTH_PASSED))
    return "\n".join(lines) + "\n"


def test_two_failed_boots_then_a_healthy_fallback_pass_the_two_failure_limit() -> None:
    found = gdmfallback.evaluate(journal(), good=GOOD, bad=BAD)

    assert found["automatic_gdm_fallback"] == "PASS" and found["two_failure_limit"] == "PASS"
    assert found["failed_boot_ids"] == [BOOT_1, BOOT_2] and found["fallback_boot_id"] == "d" * 32
    assert found["counter_before_health"] == [None, "0"]


def test_three_failures_are_a_fallback_that_fails_the_limit() -> None:
    found = gdmfallback.evaluate(journal(failures=3), good=GOOD, bad=BAD)

    assert found["automatic_gdm_fallback"] == "PASS" and found["two_failure_limit"] == "FAIL"
    assert found["counter_before_health"] == [None, "1", "0"]


def test_missing_evidence_is_blocked_with_its_reason_never_judged() -> None:
    no_rollback = gdmfallback.evaluate(journal(rollback=False), good=GOOD, bad=BAD)
    no_recovery = gdmfallback.evaluate(journal(recovered=False), good=GOOD, bad=BAD)
    empty = gdmfallback.evaluate("", good=GOOD, bad=BAD)
    malformed = gdmfallback.evaluate("not json\n", good=GOOD, bad=BAD)

    assert no_rollback["status"] == "BLOCKED" and "rollback" in str(no_rollback["reason"])
    assert no_recovery["status"] == "BLOCKED" and "fallback boots" in str(no_recovery["reason"])
    assert empty["status"] == "BLOCKED"
    assert malformed["status"] == "BLOCKED"


def test_the_journal_must_have_been_read_by_the_collection() -> None:
    import pytest  # noqa: PLC0415

    from apex.kernel import errors  # noqa: PLC0415

    read = {"programs": {"journal": {"returncode": 0, "stdout": "x"}}}
    assert gdmfallback.require_journal(read) == "x"
    with pytest.raises(errors.Refusal):
        gdmfallback.require_journal({"programs": {"journal": {"returncode": 1}}})
