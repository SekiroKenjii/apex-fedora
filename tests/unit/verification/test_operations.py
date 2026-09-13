"""The judgements the guest operations make on the host, as the older tools made them."""

from __future__ import annotations

import hashlib
import json
from typing import Any

import guestoperations as ops
import pytest

from apex.kernel import errors, identifiers, refusals
from apex.verification import bootcstatus, initramfsops, recoveryops, updateops


def test_the_status_reader_finds_each_slot_s_image_and_tolerates_absence() -> None:
    status = ops.bootc(ops.IMAGE_A, rollback=ops.IMAGE_B)

    assert bootcstatus.image(status, "booted") == ops.IMAGE_A
    assert bootcstatus.image(status, "rollback") == ops.IMAGE_B
    assert bootcstatus.image(status, "staged") is None
    assert bootcstatus.image({}, "booted") is None
    assert bootcstatus.parse(ops.program(json.dumps(status))) == status
    with pytest.raises(errors.Refusal):
        bootcstatus.parse(ops.program("not json"))
    with pytest.raises(errors.Refusal):
        bootcstatus.parse(ops.program("{}", returncode=1))


def test_a_rejection_needs_the_policy_s_words_a_failure_and_no_change() -> None:
    before = ops.bootc(ops.IMAGE_A)
    refused = {"returncode": 1, "stderr": "Error: signature verification failed"}

    updateops.require_rejection("wrong-key", refused, before, before)
    updateops.require_rejection(
        "untrusted", {"returncode": 1, "stderr": "rejected by policy"}, before, before
    )
    for case, operation, after in (
        ("unsigned", {"returncode": 0, "stderr": "signature"}, before),
        ("unsigned", refused, ops.bootc(ops.IMAGE_A, staged=ops.IMAGE_B)),
        ("untrusted", refused, before),
    ):
        with pytest.raises(errors.Refusal) as raised:
            updateops.require_rejection(case, operation, before, after)
        assert raised.value.reason is refusals.RefusalReason.UPDATE_REJECTION_NOT_OBSERVED


def test_a_switch_is_judged_by_the_staged_digest_and_a_rollback_by_its_target() -> None:
    updateops.require_switched(
        {"returncode": 0}, ops.bootc(ops.IMAGE_A, staged=ops.IMAGE_B), ops.IMAGE_B
    )
    updateops.require_rollback_target(ops.bootc(ops.IMAGE_B, rollback=ops.IMAGE_A), ops.IMAGE_A)
    with pytest.raises(errors.Refusal):
        updateops.require_switched({"returncode": 0}, ops.bootc(ops.IMAGE_A), ops.IMAGE_B)
    with pytest.raises(errors.Refusal):
        updateops.require_switched(
            {"returncode": 1}, ops.bootc(ops.IMAGE_A, staged=ops.IMAGE_B), ops.IMAGE_B
        )
    with pytest.raises(errors.Refusal):
        updateops.require_rollback_target(ops.bootc(ops.IMAGE_B, rollback=ops.IMAGE_B), ops.IMAGE_A)
    assert updateops.source_directory("c" * 32, "forward").endswith(f"/{'c' * 32}/b")


def test_the_health_judgement_is_the_older_critical_check_list() -> None:
    healthy = ops.health(ops.IMAGE_A)["observations"]

    assert updateops.health_problem(healthy, ops.IMAGE_A) is None
    assert updateops.health_problem(healthy, ops.IMAGE_B) == (
        "the booted deployment is not the selected fixture image"
    )
    assert (
        updateops.health_problem({**healthy, "gdm": {"returncode": 3, "stdout": ""}}, ops.IMAGE_A)
        == "guest gdm failed"
    )
    assert (
        updateops.health_problem(
            {**healthy, "selinux": {"returncode": 0, "stdout": "Permissive"}}, ops.IMAGE_A
        )
        == "SELinux is not enforcing"
    )
    assert (
        updateops.health_problem(
            {**healthy, "failed_units": {"returncode": 0, "stdout": "x.service"}}, ops.IMAGE_A
        )
        == "units have failed"
    )


def test_the_marker_and_the_sentinel_are_the_fixture_s_own() -> None:
    updateops.require_marker({"fixture": "c" * 32, "version": "a"}, "c" * 32, "a")
    updateops.require_sentinel({"sha256": updateops.SENTINEL_DIGEST})
    with pytest.raises(errors.Refusal):
        updateops.require_marker({"fixture": "c" * 32, "version": "b"}, "c" * 32, "a")
    with pytest.raises(errors.Refusal):
        updateops.require_sentinel({"sha256": "0" * 64})


def test_the_recovery_preimage_is_the_digest_of_the_configuration_as_read() -> None:
    inspection = ops.inspection(ops.IMAGE_A)

    assert recoveryops.preimage(inspection) == hashlib.sha256(b"grub_config output\n").hexdigest()
    recoveryops.require_staged(ops.bootc(ops.IMAGE_A, staged=ops.IMAGE_B), ops.IMAGE_B)
    with pytest.raises(errors.Refusal):
        recoveryops.require_staged(ops.bootc(ops.IMAGE_A), ops.IMAGE_B)
    assert recoveryops.require_preset(identifiers.Digest("9" * 64)) == "9" * 64
    with pytest.raises(errors.Refusal) as raised:
        recoveryops.require_preset(None)
    assert raised.value.reason is refusals.RefusalReason.FIXTURE_REPORT_MALFORMED


def inspection_document(**changes: Any) -> dict[str, Any]:
    return {
        "status": "PASS",
        "action": "inspect",
        "fixture": ops.FIXTURE,
        "images": {"a": ops.IMAGE_A, "b": ops.IMAGE_B},
        "machine_process": 4242,
        "guest": {"plan": {}, "sha256": "e" * 64},
        **changes,
    }


def test_an_injection_is_bound_to_an_inspection_of_this_fixture_on_this_machine() -> None:
    images = {"a": ops.IMAGE_A, "b": ops.IMAGE_B}

    assert (
        initramfsops.require_inspection(
            inspection_document(), fixture=ops.FIXTURE, images=images, process=4242
        )
        == "e" * 64
    )
    for changed in (
        inspection_document(status="FAIL"),
        inspection_document(action="inject"),
        inspection_document(fixture="d" * 32),
        inspection_document(machine_process=1),
        inspection_document(guest={}),
    ):
        with pytest.raises(errors.Refusal) as raised:
            initramfsops.require_inspection(
                changed, fixture=ops.FIXTURE, images=images, process=4242
            )
        assert raised.value.reason is refusals.RefusalReason.INSPECTION_MISMATCH
