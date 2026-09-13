"""The initramfs fixture unit: the plan, the injection bound to it, and the rescue check."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest
from installedguest import COMPONENTS, bootc_status, guest

from apex.agent import deployments, guestguard
from apex.agent.units import initramfs_fixture_unit
from apex.kernel import errors, refusals, safepaths
from apex.provisioning.fixtures import initramfs_fixture

GOOD = "sha256:" + "1" * 64
BAD = "sha256:" + "2" * 64
RUN = "d" * 32
HASH_A, HASH_B = "a" * 64, "b" * 64
CHECKSUM_A, CHECKSUM_B = "1" * 64, "2" * 64
DEPLOY = "/sysroot/ostree/deploy/fedora/deploy"
MARKER = "usr/share/apex/recovery-fixture.json"
ENTRY_A = (
    "title Fedora A\nversion 1\n"
    f"options root=UUID=x ostree=/ostree/boot.1/fedora/{HASH_A}/0\n"
    f"linux /boot/ostree/fedora-{HASH_A}/vmlinuz-6.0\n"
    f"initrd /boot/ostree/fedora-{HASH_A}/initramfs-6.0.img\n"
)
ENTRY_B = (
    ENTRY_A.replace("Fedora A", "Fedora B")
    .replace("version 1", "version 2")
    .replace(HASH_A, HASH_B)
)
INITRAMFS = b"\x1f\x8b" + bytes(range(256)) * 20


def tree() -> dict[str, bytes]:
    return {
        f"{initramfs_fixture.BOOT_ENTRIES}/ostree-1.conf": ENTRY_A.encode(),
        f"{initramfs_fixture.BOOT_ENTRIES}/ostree-2.conf": ENTRY_B.encode(),
        f"/boot/ostree/fedora-{HASH_A}/vmlinuz-6.0": b"kernel a",
        f"/boot/ostree/fedora-{HASH_A}/initramfs-6.0.img": INITRAMFS,
        f"/boot/ostree/fedora-{HASH_B}/vmlinuz-6.0": b"kernel b",
        f"/boot/ostree/fedora-{HASH_B}/initramfs-6.0.img": INITRAMFS + b"b",
        initramfs_fixture.GRUB_CONFIG: b"grub\n",
        initramfs_fixture.GRUB_ENVIRONMENT: b"env\n",
        f"{initramfs_fixture.EFI_DIRECTORY}/fedora/grubx64.efi": b"efi",
        f"{DEPLOY}/{CHECKSUM_A}.0/{MARKER}": b'{"fixture": "c", "version": "a"}',
        f"{DEPLOY}/{CHECKSUM_B}.0/{MARKER}": b'{"fixture": "c", "version": "b"}',
    }


LINKS = {
    f"/ostree/boot.1/fedora/{HASH_A}/0": f"{DEPLOY}/{CHECKSUM_A}.0",
    f"/ostree/boot.1/fedora/{HASH_B}/0": f"{DEPLOY}/{CHECKSUM_B}.0",
    "/boot/boot": "/boot",
}


def outputs(*, status: bytes | None = None, environment: bytes | None = None) -> dict:
    return {
        tuple(deployments.COMPONENTS): COMPONENTS,
        tuple(deployments.STATUS): status
        if status is not None
        else bootc_status(GOOD, rollback=BAD, queued=True, checksums=(CHECKSUM_A, CHECKSUM_B)),
        ("getenforce",): b"Enforcing\n",
        (
            "systemctl",
            "show",
            "ostree-finalize-staged",
            "-p",
            "ActiveState",
            "--value",
        ): b"inactive\n",
        (
            "systemctl",
            "show",
            "greenboot-set-rollback-trigger",
            "-p",
            "ActiveState",
            "--value",
        ): b"inactive\n",
        ("grub2-editenv", "-", "list"): environment
        if environment is not None
        else (f"greenboot_next_deployment_id={BAD}\nfallback=1\n".encode()),
    }


@pytest.fixture(autouse=True)
def as_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(guestguard.os, "geteuid", lambda: 0)
    monkeypatch.setattr(deployments, "require_private_mounts", lambda: None)


def armed(*, status: bytes | None = None, environment: bytes | None = None) -> tuple:
    return guest(tree(), outputs(status=status, environment=environment), links=LINKS)


def test_the_inspection_binds_both_entries_and_fingerprints_every_protected_input() -> None:
    _, _, ports = armed()

    found = initramfs_fixture_unit.run(
        ports, arguments={"action": "inspect", "good": GOOD, "bad": BAD}
    )

    plan = cast("dict[str, Any]", found["plan"])
    assert found["sha256"] == initramfs_fixture.plan_digest(plan).hex
    assert plan["entries"]["a"]["fields"]["version"] == "1"
    assert plan["entries"]["b"]["deployment"] == f"{DEPLOY}/{CHECKSUM_B}.0"
    assert (
        plan["entries"]["b"]["files"]["initrd"] == f"/boot/ostree/fedora-{HASH_B}/initramfs-6.0.img"
    )
    assert set(plan["protected"]) == {
        initramfs_fixture.GRUB_CONFIG,
        initramfs_fixture.GRUB_ENVIRONMENT,
        f"{initramfs_fixture.EFI_DIRECTORY}/fedora/grubx64.efi",
        f"/boot/ostree/fedora-{HASH_A}/vmlinuz-6.0",
        f"/boot/ostree/fedora-{HASH_A}/initramfs-6.0.img",
        f"/boot/ostree/fedora-{HASH_B}/vmlinuz-6.0",
        f"/boot/ostree/fedora-{HASH_B}/initramfs-6.0.img",
        f"{initramfs_fixture.BOOT_ENTRIES}/ostree-1.conf",
        f"{initramfs_fixture.BOOT_ENTRIES}/ostree-2.conf",
    }
    assert plan["grubenv"] == {"greenboot_next_deployment_id": BAD, "fallback": "1"}
    assert plan["boot_id"] == "boot-1"


@pytest.mark.parametrize(
    "change",
    [
        {
            "status": bootc_status(
                GOOD, rollback=BAD, queued=False, checksums=(CHECKSUM_A, CHECKSUM_B)
            )
        },
        {
            "status": bootc_status(
                BAD, rollback=GOOD, queued=True, checksums=(CHECKSUM_A, CHECKSUM_B)
            )
        },
        {"environment": b"fallback=1\nboot_counter=2\n"},
    ],
)
def test_a_guest_not_naturally_armed_is_refused(change: dict[str, bytes]) -> None:
    _, _, ports = armed(status=change.get("status"), environment=change.get("environment"))

    with pytest.raises(errors.Refusal) as raised:
        initramfs_fixture_unit.run(ports, arguments={"action": "inspect", "good": GOOD, "bad": BAD})

    assert raised.value.reason is refusals.RefusalReason.FIXTURE_STATE_UNEXPECTED


def test_the_injection_takes_the_reviewed_plan_marks_b_and_leaves_everything_else() -> None:
    process, files, ports = armed()
    plan = initramfs_fixture_unit.run(
        ports, arguments={"action": "inspect", "good": GOOD, "bad": BAD}
    )

    found = initramfs_fixture_unit.run(
        ports,
        arguments={
            "action": "inject",
            "good": GOOD,
            "bad": BAD,
            "run_id": RUN,
            "plan_sha256": plan["sha256"],
        },
    )

    bad_file = f"{initramfs_fixture.FAULT_DIRECTORY}/{RUN}/bad.img"
    entry = safepaths.SafePath(Path(f"{initramfs_fixture.BOOT_ENTRIES}/ostree-2.conf"))
    assert found["status"] == "PASS" and found["bad_file"] == bad_file
    assert files.read_bytes(safepaths.SafePath(Path(bad_file)), limit=1 << 20).startswith(
        b"APEX_BAD_INITRD\n"
    )
    assert (
        files.read_bytes(entry, limit=1 << 20)
        .decode()
        .endswith(f"initrd /apex-initramfs-fault/{RUN}/bad.img\n")
    )
    assert (
        files.read_bytes(
            safepaths.SafePath(Path(f"{initramfs_fixture.BOOT_ENTRIES}/ostree-1.conf")),
            limit=1 << 20,
        )
        == ENTRY_A.encode()
    )
    proof = f"{initramfs_fixture.TEST_DIRECTORY}/{RUN}"
    assert (
        json.loads(
            files.read_bytes(safepaths.SafePath(Path(f"{proof}/before.json")), limit=1 << 20)
        )
        == plan["plan"]
    )
    assert (
        files.read_bytes(safepaths.SafePath(Path(f"{proof}/bls-before.conf")), limit=1 << 20)
        == ENTRY_B.encode()
    )
    vectors = process.vectors()
    assert ("mount", "-o", "remount,rw", "/boot") in vectors
    assert sum(v[0] == "chcon" for v in vectors) == 2 and ("sync", "-f", "/boot") in vectors


def test_a_plan_that_no_longer_matches_is_refused_before_the_boot_tree_is_touched() -> None:
    process, files, ports = armed()
    plan = initramfs_fixture_unit.run(
        ports, arguments={"action": "inspect", "good": GOOD, "bad": BAD}
    )
    files.write_atomic(
        safepaths.SafePath(Path(initramfs_fixture.GRUB_CONFIG)),
        b"changed\n",
        mode=files.mode_of(safepaths.SafePath(Path(initramfs_fixture.GRUB_CONFIG))),
    )

    with pytest.raises(errors.Refusal) as raised:
        initramfs_fixture_unit.run(
            ports,
            arguments={
                "action": "inject",
                "good": GOOD,
                "bad": BAD,
                "run_id": RUN,
                "plan_sha256": plan["sha256"],
            },
        )
    with pytest.raises(errors.Refusal) as stale:
        initramfs_fixture_unit.run(
            ports,
            arguments={
                "action": "inject",
                "good": GOOD,
                "bad": BAD,
                "run_id": RUN,
                "plan_sha256": "f" * 64,
            },
        )

    assert (
        raised.value.reason is stale.value.reason is refusals.RefusalReason.FIXTURE_STATE_UNEXPECTED
    )
    assert ("mount", "-o", "remount,rw", "/boot") not in process.vectors()


def test_the_rescue_check_says_whether_a_boots_its_own_initramfs() -> None:
    _, files, ports = armed(
        status=bootc_status(GOOD, rollback=BAD, checksums=(CHECKSUM_A, CHECKSUM_B))
    )
    faulted = ENTRY_B.replace(
        f"initrd /boot/ostree/fedora-{HASH_B}/initramfs-6.0.img",
        f"initrd /apex-initramfs-fault/{RUN}/bad.img",
    )
    files.write_atomic(
        safepaths.SafePath(Path(f"{initramfs_fixture.BOOT_ENTRIES}/ostree-2.conf")),
        faulted.encode(),
        mode=files.mode_of(safepaths.SafePath(Path(initramfs_fixture.GRUB_CONFIG))),
    )

    safe = initramfs_fixture_unit.run(
        ports, arguments={"action": "verify-rescue", "good": GOOD, "bad": BAD}
    )

    assert safe["status"] == "PASS" and safe["safe_to_reboot_a"] is True
    remapped = ENTRY_A.replace(
        f"initrd /boot/ostree/fedora-{HASH_A}/initramfs-6.0.img",
        f"initrd /apex-initramfs-fault/{RUN}/bad.img",
    )
    files.write_atomic(
        safepaths.SafePath(Path(f"{initramfs_fixture.BOOT_ENTRIES}/ostree-1.conf")),
        remapped.encode(),
        mode=files.mode_of(safepaths.SafePath(Path(initramfs_fixture.GRUB_CONFIG))),
    )
    blocked = initramfs_fixture_unit.run(
        ports, arguments={"action": "verify-rescue", "good": GOOD, "bad": BAD}
    )
    assert blocked["status"] == "BLOCKED" and "do not reboot" in str(blocked["reason"])


def test_an_unknown_action_or_a_missing_digest_is_refused_before_the_guard() -> None:
    process, _, ports = armed()

    for bad in ({"action": "burn", "good": GOOD, "bad": BAD}, {"action": "inspect", "good": GOOD}):
        with pytest.raises(errors.Refusal) as raised:
            initramfs_fixture_unit.run(ports, arguments=bad)
        assert raised.value.reason is refusals.RefusalReason.REQUEST_MALFORMED
    assert process.vectors() == []
