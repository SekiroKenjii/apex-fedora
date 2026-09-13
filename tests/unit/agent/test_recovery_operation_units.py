"""The recovery units: the inspection, the two single programs, and the fixture's changes."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, cast

import pytest
from installedguest import COMPONENTS, bootc_status, guest

from apex.agent import deployments, guestguard
from apex.agent.units import recovery_fixture_unit, recovery_inspect_unit, recovery_operate_unit
from apex.kernel import errors, refusals, safepaths
from apex.provisioning.fixtures import initramfs_fixture, recovery_fixture

IMAGE_A = "sha256:" + "1" * 64
IMAGE_B = "sha256:" + "2" * 64
RUN = "d" * 32
BROKEN = b"set timeout=5\nsave_env boot_success### END 08_greenboot.cfg ###\n"
FRAGMENT = b"if x; then\nsave_env boot_success\n"
GRUBENV = b"boot_success=1\n"


@pytest.fixture(autouse=True)
def as_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(guestguard.os, "geteuid", lambda: 0)
    monkeypatch.setattr(deployments, "require_private_mounts", lambda: None)


def tree() -> dict[str, bytes]:
    return {
        initramfs_fixture.GRUB_CONFIG: BROKEN,
        initramfs_fixture.GRUB_ENVIRONMENT: GRUBENV,
        "/usr/lib/bootupd/grub2-static/configs.d/08_greenboot.cfg": FRAGMENT,
        recovery_fixture.GREENBOOT_CONFIG: b"GREENBOOT_MAX_BOOT_ATTEMPTS=2\n",
    }


def outputs(**changes: bytes) -> dict[tuple[str, ...], bytes]:
    return {
        tuple(deployments.COMPONENTS): COMPONENTS,
        tuple(deployments.STATUS): bootc_status(IMAGE_A, rollback=IMAGE_B),
        **{tuple(k.split()): v for k, v in changes.items()},
    }


def read(ports: object, name: str) -> bytes:
    return ports.files.read_bytes(safepaths.SafePath(Path(name)), limit=1 << 20)  # type: ignore[attr-defined]


def test_the_inspection_runs_every_older_program_and_judges_nothing() -> None:
    process, _, ports = guest({}, {})

    found = recovery_inspect_unit.run(ports, arguments={})

    assert set(found) == set(recovery_inspect_unit.COMMANDS)
    assert all(isinstance(item, dict) and item["returncode"] == 0 for item in found.values())
    assert process.vectors()[1] == ("bootc", "status", "--json")


def test_the_migration_and_the_collection_are_one_program_each_plus_the_records() -> None:
    process, _, ports = guest(
        {f"{recovery_fixture.TEST_DIRECTORY}/{RUN}/x-gdm-start.json": b"{}"}, {}
    )

    migrated = cast(
        "dict[str, Any]", recovery_operate_unit.run(ports, arguments={"operation": "migrate"})
    )
    collected = cast(
        "dict[str, Any]", recovery_operate_unit.run(ports, arguments={"operation": "collect"})
    )

    assert migrated["program"]["argv"] == ["bootupctl", "migrate-static-grub-config"]
    assert set(collected["programs"]) == {"boots", "journal"}
    assert list(collected["records"]) == [
        f"{recovery_fixture.TEST_DIRECTORY}/{RUN}/x-gdm-start.json"
    ]
    with pytest.raises(errors.Refusal):
        recovery_operate_unit.run(ports, arguments={"operation": "reboot"})


def test_the_grub_repair_applies_the_exact_newline_fix_and_keeps_the_preimage() -> None:
    process, files, ports = guest(tree(), outputs())
    preimage = hashlib.sha256(BROKEN).hexdigest()

    found = recovery_fixture_unit.run(
        ports,
        arguments={
            "action": "repair-grub",
            "expected_digest": IMAGE_A,
            "run_id": RUN,
            "preimage": preimage,
        },
    )

    repaired = recovery_fixture.repaired_config(BROKEN, FRAGMENT)
    assert found["status"] == "PASS" and found["before_sha256"] == preimage
    assert found["after_sha256"] == hashlib.sha256(repaired).hexdigest()
    assert read(ports, initramfs_fixture.GRUB_CONFIG) == repaired
    assert read(ports, f"{recovery_fixture.TEST_DIRECTORY}/{RUN}/grub.cfg.before") == BROKEN
    assert read(ports, f"{recovery_fixture.TEST_DIRECTORY}/{RUN}/result.json")
    vectors = process.vectors()
    assert ("mount", "-o", "remount,rw", "/boot") in vectors
    assert any(v[0] == "grub2-script-check" for v in vectors)
    assert ("sync", "-f", initramfs_fixture.GRUB_CONFIG) in vectors


@pytest.mark.parametrize(
    "change", [{"preimage": "f" * 64}, {"expected_digest": IMAGE_B}, {"run_id": "short"}]
)
def test_a_repair_over_another_preimage_deployment_or_run_is_refused(
    change: dict[str, str],
) -> None:
    process, files, ports = guest(tree(), outputs())
    given = {
        "action": "repair-grub",
        "expected_digest": IMAGE_A,
        "run_id": RUN,
        "preimage": hashlib.sha256(BROKEN).hexdigest(),
        **change,
    }

    with pytest.raises(errors.Refusal):
        recovery_fixture_unit.run(ports, arguments=given)

    assert read(ports, initramfs_fixture.GRUB_CONFIG) == BROKEN
    assert ("mount", "-o", "remount,rw", "/boot") not in process.vectors()


def test_arming_gdm_writes_the_observer_and_both_drop_ins_then_reloads() -> None:
    process, files, ports = guest(tree(), outputs())

    found = recovery_fixture_unit.run(
        ports,
        arguments={
            "action": "arm-gdm",
            "expected_digest": IMAGE_A,
            "run_id": RUN,
            "bad_digest": IMAGE_B,
        },
    )

    program = f"{recovery_fixture.TEST_DIRECTORY}/{RUN}/observe.py"
    assert found["status"] == "PASS" and found["bad_digest"] == IMAGE_B
    assert files.mode_of(safepaths.SafePath(Path(program))).value == 0o700
    assert IMAGE_B in read(ports, program).decode()
    for unit in ("gdm.service", "greenboot-healthcheck.service"):
        drop_in = f"{recovery_fixture.SYSTEMD_UNITS}/{unit}.d/{recovery_fixture.DROP_IN}"
        text = read(ports, drop_in).decode()
        assert program in text
    assert process.vectors()[-1] == ("systemctl", "daemon-reload")


def test_the_retry_variant_replaces_the_two_retry_line_and_keeps_the_original() -> None:
    _, files, ports = guest(tree(), outputs())

    found = recovery_fixture_unit.run(
        ports, arguments={"action": "retry-config", "expected_digest": IMAGE_A, "run_id": RUN}
    )

    assert found["status"] == "PASS"
    assert read(ports, recovery_fixture.GREENBOOT_CONFIG) == b"GREENBOOT_MAX_BOOT_ATTEMPTS=1\n"
    assert read(ports, f"{recovery_fixture.TEST_DIRECTORY}/{RUN}/greenboot.conf.before") == (
        b"GREENBOOT_MAX_BOOT_ATTEMPTS=2\n"
    )
    with pytest.raises(errors.Refusal) as again:
        recovery_fixture_unit.run(
            ports, arguments={"action": "retry-config", "expected_digest": IMAGE_A, "run_id": RUN}
        )
    assert "already exists" in again.value.subject


def test_a_staged_update_or_other_components_refuse_every_change() -> None:
    _, _, staged = guest(
        tree(),
        outputs(
            **{
                "bootc status --format json": bootc_status(
                    IMAGE_A, rollback=IMAGE_B, staged=IMAGE_B
                )
            }
        ),
    )
    _, _, other = guest(tree(), {**outputs(), tuple(deployments.COMPONENTS): b"bootupd=0.3.0\n"})

    for ports in (staged, other):
        with pytest.raises(errors.Refusal) as raised:
            recovery_fixture_unit.run(
                ports,
                arguments={"action": "retry-config", "expected_digest": IMAGE_A, "run_id": RUN},
            )
        assert raised.value.reason is refusals.RefusalReason.FIXTURE_STATE_UNEXPECTED


def test_the_namespace_guard_reads_both_mount_namespaces(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.undo()
    monkeypatch.setattr(Path, "readlink", lambda self: Path("mnt:[1]"))

    with pytest.raises(errors.Refusal) as raised:
        deployments.require_private_mounts()

    assert raised.value.reason is refusals.RefusalReason.FIXTURE_STATE_UNEXPECTED
    monkeypatch.setattr(Path, "readlink", lambda self: Path(f"mnt:[{len(str(self))}]"))
    deployments.require_private_mounts()
