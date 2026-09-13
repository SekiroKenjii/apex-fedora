"""The update, recovery and initramfs operations on fakes: asked as root, judged, reported."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import guestoperations as ops
import pytest
from mirroredfiles import MirroredFiles
from monitorfixtures import DrawingMonitor

from apex.adapters.fakes import fake_guestshell
from apex.composition import keys as composition_keys
from apex.kernel import refusals, safepaths
from apex.ports import portset
from apex.verification import updateops, verifykeys
from apex.verification.recipes import (
    initramfs_operation_recipe,
    recovery_operation_recipe,
    update_check_recipe,
    update_operation_recipe,
)

HEADER = b"P6\n300 100\n255\n"
BARS = HEADER + (b"\xe6\x26\x26" * 100 + b"\x26\xbf\x40" * 100 + b"\x26\x4c\xe6" * 100) * 100
PROCESS = 4242
SENTINEL = {"action": "verify", "sha256": updateops.SENTINEL_DIGEST}


@pytest.fixture
def root(tmp_path: Path) -> safepaths.RuntimeRoot:
    base = tmp_path / "runtime"
    base.mkdir(mode=0o700)
    (base / "guest_ed25519").write_bytes(b"")
    (base / "apex-agent.whl").write_bytes(b"not a wheel")
    return safepaths.RuntimeRoot.adopt(base)


def wheel(root: safepaths.RuntimeRoot) -> safepaths.SafePath:
    return safepaths.SafePath.regular_file(root.path / "apex-agent.whl", within=root)


def report_of(
    files: MirroredFiles, root: safepaths.RuntimeRoot, outcome: Any, name: str
) -> dict[str, Any]:
    run = outcome.facts[composition_keys.RUN_ID]
    return json.loads((root.path / "exports" / str(run) / f"{name}.json").read_bytes())


def update(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot, action: str, answers: dict[str, Any]
) -> tuple[Any, Any, MirroredFiles]:
    files = MirroredFiles()
    located = ops.exported_fixture(ports, files, root)
    guest = ops.answering(answers)
    outcome = update_operation_recipe.verify(
        ops.held(ports, files, guest),
        guest=ops.guest_target(root),
        wheel=wheel(root),
        fixture=located,
        action=action,
        credentials=ops.credentials(),
        process=PROCESS,
        root=root,
    )
    return outcome, guest, files


def test_provisioning_sends_the_archive_lays_the_fixture_in_and_creates_the_sentinel(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    outcome, guest, files = update(
        ports,
        root,
        "provision",
        {
            "update.state": ops.state(ops.PARENT),
            "update.provision": {"files_verified": 2, "consumer_policy_sha256": ops.POLICY_HEX},
            "update.sentinel": [
                {"action": "create", "sha256": updateops.SENTINEL_DIGEST},
                SENTINEL,
            ],
        },
    )

    assert outcome.succeeded, outcome.detail
    assert guest.asked == ["update.state", "update.provision", "update.sentinel", "update.sentinel"]
    assert guest.passwords == [ops.PASSWORD, ops.PASSWORD]
    assert [str(item.remote) for item in guest.sent][
        -1
    ] == f"/var/tmp/apex-update-{ops.FIXTURE}.tar"
    provision = guest.requests[1]["arguments"]
    assert provision["installed_a"] is False and provision["archive_sha256"] == ops.digest(
        ops.PAYLOADS
    )
    report = report_of(files, root, outcome, "update")
    assert report["status"] == "PASS" and report["action"] == "provision"
    assert report["sentinel_sha256"] == updateops.SENTINEL_DIGEST and report["boot_id"] == "boot-1"
    assert str(outcome.facts[verifykeys.retained_report("update")]).endswith("/update.json")


def test_a_switch_is_judged_by_what_bootc_staged_and_a_rejection_by_its_words(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    forward, guest, files = update(
        ports,
        root,
        "forward",
        {
            "update.state": [ops.state(ops.IMAGE_A), ops.state(ops.IMAGE_A, staged=ops.IMAGE_B)],
            "update.operate": {"returncode": 0, "stdout": "", "stderr": ""},
            "update.sentinel": SENTINEL,
        },
    )
    rejected, _, _ = update(
        ports,
        root,
        "wrong-key",
        {
            "update.state": [ops.state(ops.IMAGE_A), ops.state(ops.IMAGE_A)],
            "update.operate": {
                "returncode": 1,
                "stdout": "",
                "stderr": "signature verification failed",
            },
            "update.sentinel": SENTINEL,
        },
    )
    accepted, _, accepted_files = update(
        ports,
        root,
        "unsigned",
        {
            "update.state": [ops.state(ops.IMAGE_A), ops.state(ops.IMAGE_A, staged=ops.IMAGE_B)],
            "update.operate": {"returncode": 0, "stdout": "", "stderr": ""},
            "update.sentinel": SENTINEL,
        },
    )

    assert forward.succeeded, forward.detail
    assert guest.requests[1]["arguments"] == {
        "operation": "switch",
        "source": f"/var/lib/apex-update-fixture/{ops.FIXTURE}/b",
    }
    assert rejected.succeeded, rejected.detail
    assert accepted.refusal is refusals.RefusalReason.UPDATE_REJECTION_NOT_OBSERVED
    kept = report_of(accepted_files, root, accepted, "update")
    assert kept["status"] == "FAIL" and "rejection" in kept["failure"]


def test_a_rollback_needs_b_booted_with_a_behind_it_and_a_policy_that_is_the_fixture_s(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    rolled, guest, _ = update(
        ports,
        root,
        "rollback",
        {
            "update.state": [ops.state(ops.IMAGE_B, rollback=ops.IMAGE_A), ops.state(ops.IMAGE_B)],
            "update.operate": {"returncode": 0},
            "update.sentinel": SENTINEL,
        },
    )
    wrong_policy, _, _ = update(
        ports,
        root,
        "rollback",
        {
            "update.state": ops.state(ops.IMAGE_B, rollback=ops.IMAGE_A, policy="0" * 64),
        },
    )
    wrong_slot, _, _ = update(
        ports,
        root,
        "rollback",
        {
            "update.state": ops.state(ops.IMAGE_A, rollback=ops.IMAGE_B),
        },
    )

    assert rolled.succeeded, rolled.detail
    assert guest.requests[1]["arguments"] == {"operation": "rollback"}
    assert wrong_policy.refusal is refusals.RefusalReason.UPDATE_STATE_UNEXPECTED
    assert "policy" in wrong_policy.detail
    assert wrong_slot.refusal is refusals.RefusalReason.UPDATE_STATE_UNEXPECTED


def test_the_check_logs_in_reads_the_health_and_the_marker_and_the_sentinel(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    files = MirroredFiles()
    located = ops.exported_fixture(ports, files, root)
    guest = ops.answering(
        {
            "desktop.session": [
                {"found": False, "wayland": False},
                {"found": True, "wayland": True},
            ],
            "desktop.greeter": {"found": True},
            "desktop.shell-startup": {"found": True, "pid": 1, "event": {}},
            "desktop.overview": [{"reached": True}, {"reached": True}, {"reached": True}],
            "desktop.render": {"presented": True, "display_type": "GdkWaylandDisplay"},
            "update.state": ops.state(ops.IMAGE_A, marker={"fixture": ops.FIXTURE, "version": "a"}),
            "guest.state": ops.health(ops.IMAGE_A),
            "recovery.prerequisites": {"prerequisites": {"status": "NOT TESTED"}},
            "update.sentinel": SENTINEL,
        }
    )
    held = ops.held(ports, files, guest)
    held = dataclasses.replace(held, monitor=DrawingMonitor(files, {"application.ppm": BARS}))

    outcome = update_check_recipe.verify(
        held,
        guest=ops.guest_target(root),
        wheel=wheel(root),
        fixture=located,
        action="check-a",
        credentials=ops.credentials(),
        process=PROCESS,
        monitor=root.child("qmp.sock"),
        root=root,
    )

    assert outcome.succeeded, outcome.detail
    assert guest.asked[-4:] == [
        "update.state",
        "guest.state",
        "recovery.prerequisites",
        "update.sentinel",
    ]
    report = report_of(files, root, outcome, "update")
    assert report["status"] == "PASS" and report["login"]["verdict"] == "PASS"
    assert report["marker"] == {"fixture": ops.FIXTURE, "version": "a"}
    assert ops.PASSWORD not in json.dumps(report)


def recovery(
    ports: portset.HostPorts,
    root: safepaths.RuntimeRoot,
    action: str,
    answers: dict[str, Any],
    *,
    reboot_exit: int | None = None,
) -> tuple[Any, Any, MirroredFiles]:
    files = MirroredFiles()
    located = ops.exported_fixture(ports, files, root)
    guest = ops.answering(answers)
    if reboot_exit is not None:
        guest.expect(
            "sudo -k -S -p '' systemctl reboot", fake_guestshell.GuestReply(exit_code=reboot_exit)
        )
    outcome = recovery_operation_recipe.verify(
        ops.held(ports, files, guest),
        guest=ops.guest_target(root),
        wheel=wheel(root),
        fixture=located,
        action=action,
        credentials=ops.credentials(),
        process=PROCESS,
        root=root,
    )
    return outcome, guest, files


def test_a_change_is_inspected_around_and_bound_to_a_with_the_preimage(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    outcome, guest, files = recovery(
        ports,
        root,
        "repair-grub",
        {
            "recovery.inspect": [ops.inspection(ops.IMAGE_A), ops.inspection(ops.IMAGE_A)],
            "fixture.recovery": {"status": "PASS", "before_sha256": "x"},
        },
    )
    inspected, _, _ = recovery(
        ports,
        root,
        "inspect",
        {"recovery.inspect": [ops.inspection(ops.IMAGE_B), ops.inspection(ops.IMAGE_B)]},
    )
    wrong, _, _ = recovery(
        ports, root, "arm-gdm", {"recovery.inspect": ops.inspection(ops.IMAGE_B)}
    )

    assert outcome.succeeded, outcome.detail
    assert guest.asked == ["recovery.inspect", "fixture.recovery", "recovery.inspect"]
    change = guest.requests[1]["arguments"]
    assert change["action"] == "repair-grub" and change["expected_digest"] == ops.IMAGE_A
    assert len(change["preimage"]) == 64 and len(change["run_id"]) == 32
    assert "unshare --mount --propagation slave" in guest.runs[-2].script.rendered()
    report = report_of(files, root, outcome, "recovery")
    assert (
        report["scope"].startswith("Recovery fixture only") and report["change"]["status"] == "PASS"
    )
    assert inspected.succeeded
    assert wrong.refusal is refusals.RefusalReason.UPDATE_STATE_UNEXPECTED


def test_the_installed_check_and_the_reboot_are_judged_by_the_guest_and_the_request(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    installed, guest, files = recovery(
        ports,
        root,
        "verify-installed",
        {
            "recovery.installed": {"status": "FAIL", "failure": "SELinux is not enforcing"},
        },
    )
    rebooted, _, reboot_files = recovery(
        ports,
        root,
        "reboot",
        {
            "recovery.inspect": ops.inspection(ops.IMAGE_A, staged=ops.IMAGE_B),
        },
        reboot_exit=255,
    )
    unstaged, _, _ = recovery(
        ports, root, "reboot", {"recovery.inspect": ops.inspection(ops.IMAGE_A)}, reboot_exit=0
    )

    assert installed.succeeded and guest.requests[0]["arguments"] == {
        "expected_digest": ops.IMAGE_A,
        "config_sha256": ops.PRESET_HEX,
    }
    assert report_of(files, root, installed, "recovery")["status"] == "FAIL"
    assert rebooted.succeeded, rebooted.detail
    kept = report_of(reboot_files, root, rebooted, "recovery")
    assert kept["reboot_request_returncode"] == 255 and "NOT TESTED" in kept["scope"]
    assert unstaged.refusal is refusals.RefusalReason.UPDATE_STATE_UNEXPECTED


def initramfs(
    ports: portset.HostPorts,
    root: safepaths.RuntimeRoot,
    action: str,
    answer: dict[str, Any],
    inspection: dict[str, Any] | None = None,
) -> tuple[Any, Any, MirroredFiles]:
    files = MirroredFiles()
    located = ops.exported_fixture(ports, files, root)
    guest = ops.answering({"fixture.initramfs": answer})
    outcome = initramfs_operation_recipe.verify(
        ops.held(ports, files, guest),
        guest=ops.guest_target(root),
        wheel=wheel(root),
        fixture=located,
        action=action,
        credentials=ops.credentials(),
        process=PROCESS,
        inspection=inspection,
        root=root,
    )
    return outcome, guest, files


def test_the_injection_is_bound_to_the_reviewed_inspection_and_the_rescue_may_block(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    inspected, _, files = initramfs(ports, root, "inspect", {"plan": {"x": 1}, "sha256": "e" * 64})
    review = report_of(files, root, inspected, "initramfs")
    injected, guest, _ = initramfs(ports, root, "inject", {"status": "PASS"}, review)
    unreviewed, _, _ = initramfs(ports, root, "inject", {"status": "PASS"}, None)
    other = {**review, "machine_process": 1}
    mismatched, _, _ = initramfs(ports, root, "inject", {"status": "PASS"}, other)
    blocked, _, blocked_files = initramfs(
        ports, root, "verify-rescue", {"status": "BLOCKED", "reason": "do not reboot"}
    )

    assert review["status"] == "PASS" and review["guest"]["sha256"] == "e" * 64
    assert injected.succeeded, injected.detail
    asked = guest.requests[0]["arguments"]
    assert (
        asked["plan_sha256"] == "e" * 64
        and asked["good"] == ops.IMAGE_A
        and len(asked["run_id"]) == 32
    )
    assert unreviewed.refusal is refusals.RefusalReason.INSPECTION_MISMATCH
    assert mismatched.refusal is refusals.RefusalReason.INSPECTION_MISMATCH
    assert blocked.succeeded
    assert report_of(blocked_files, root, blocked, "initramfs")["status"] == "BLOCKED"
