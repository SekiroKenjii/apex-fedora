"""The update units: the state read, the fixture provisioned, bootc asked, the sentinel kept."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, cast

import pytest
from installedguest import bootc_status, guest

from apex.adapters.fakes import fake_archives, fake_files
from apex.agent import guestguard
from apex.agent.units import (
    update_operate_unit,
    update_provision_unit,
    update_sentinel_unit,
    update_state_unit,
)
from apex.kernel import errors, refusals, safepaths
from apex.provisioning.fixtures import update_fixture

FIXTURE = "c" * 32
IMAGE_A = "sha256:" + "1" * 64
PARENT = "sha256:" + "0" * 64
POLICY = b'{"default": [{"type": "reject"}], "transports": {}}'
FIXTURE_POLICY = json.dumps({"default": [{"type": "reject"}], "transports": {"dir": {}}}).encode()
MANIFEST = b'{"config": {}}'
ARCHIVE = f"/var/tmp/apex-update-{FIXTURE}.tar"
ARCHIVE_BYTES = b"tar bytes"


@pytest.fixture(autouse=True)
def as_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(guestguard.os, "geteuid", lambda: 0)


def test_the_state_names_the_boot_the_kernels_the_status_the_policy_and_the_marker() -> None:
    process, _, ports = guest(
        {
            "/usr/lib/modules/6.0/vmlinuz": b"kernel",
            "/usr/lib/modules/6.0/initramfs.img": b"rd",
            "/usr/lib/modules/6.0/config": b"ignored",
            update_fixture.BUILDER_POLICY: POLICY,
            "/usr/share/apex/recovery-fixture.json": b'{"fixture": "x", "version": "a"}',
        },
        {
            ("bootc", "status", "--format", "json"): bootc_status(IMAGE_A, rollback=None),
            tuple(update_state_unit.VERSIONS): b"bootc-1\n",
        },
    )

    found = cast("dict[str, Any]", update_state_unit.run(ports, arguments={}))

    assert found["boot_id"] == "boot-1"
    assert found["versions"]["stdout"] == "bootc-1\n"
    assert found["kernel_inputs"] == {
        "/usr/lib/modules/6.0/vmlinuz": hashlib.sha256(b"kernel").hexdigest(),
        "/usr/lib/modules/6.0/initramfs.img": hashlib.sha256(b"rd").hexdigest(),
    }
    assert found["bootc"]["status"]["booted"]["image"]["imageDigest"] == IMAGE_A
    assert found["policy_sha256"] == hashlib.sha256(POLICY).hexdigest()
    assert found["marker"] == {"fixture": "x", "version": "a"}
    assert process.vectors()[0] == ("systemd-detect-virt", "--vm")


def provisioning(*, members: dict[str, bytes] | None = None, current: bytes = POLICY) -> tuple:
    held = (
        members
        if members is not None
        else {
            f"{FIXTURE}/fixture.json": json.dumps(
                {
                    "id": FIXTURE,
                    "public_key_sha256": "e" * 64,
                    "files": {
                        "policy.json": hashlib.sha256(FIXTURE_POLICY).hexdigest(),
                        "a/manifest.json": hashlib.sha256(MANIFEST).hexdigest(),
                    },
                }
            ).encode(),
            f"{FIXTURE}/policy.json": FIXTURE_POLICY,
            f"{FIXTURE}/a/manifest.json": MANIFEST,
        }
    )
    process, files, ports = guest(
        {ARCHIVE: ARCHIVE_BYTES, update_fixture.BUILDER_POLICY: current}, {}
    )
    assert isinstance(ports.archives, fake_archives.MemoryArchives)
    ports.archives.hold(safepaths.SafePath(Path(ARCHIVE)), held)
    return process, files, ports


def arguments(**changes: Any) -> dict[str, Any]:
    return {
        "fixture": FIXTURE,
        "archive": ARCHIVE,
        "archive_sha256": hashlib.sha256(ARCHIVE_BYTES).hexdigest(),
        "public_key_sha256": "e" * 64,
        "policy_sha256": hashlib.sha256(FIXTURE_POLICY).hexdigest(),
        "installed_a": False,
        **changes,
    }


def test_the_fixture_is_unpacked_verified_and_its_policy_put_in_force() -> None:
    process, files, ports = provisioning()

    found = update_provision_unit.run(ports, arguments=arguments())

    base = update_fixture.FIXTURE_ROOT
    assert found == {
        "bootstrap_policy_sha256": hashlib.sha256(POLICY).hexdigest(),
        "consumer_policy_sha256": hashlib.sha256(FIXTURE_POLICY).hexdigest(),
        "files_verified": 2,
    }
    assert (
        files.read_bytes(safepaths.SafePath(Path(update_fixture.BUILDER_POLICY)), limit=1 << 20)
        == FIXTURE_POLICY
    )
    assert (
        files.read_bytes(
            safepaths.SafePath(Path(f"{base}/{FIXTURE}/bootstrap-policy.json")), limit=1 << 20
        )
        == POLICY
    )
    assert ("restorecon", update_fixture.BUILDER_POLICY) in process.vectors()


def test_with_a_installed_the_policy_in_force_must_be_the_fixture_s_and_stays() -> None:
    process, files, ports = provisioning(current=FIXTURE_POLICY)

    found = update_provision_unit.run(ports, arguments=arguments(installed_a=True))

    assert found["files_verified"] == 2
    assert ("restorecon", update_fixture.BUILDER_POLICY) not in process.vectors()
    with pytest.raises(errors.Refusal) as raised:
        update_provision_unit.run(
            provisioning(current=POLICY)[2], arguments=arguments(installed_a=True)
        )
    assert raised.value.reason is refusals.RefusalReason.FIXTURE_STATE_UNEXPECTED


@pytest.mark.parametrize(
    "fault", ["archive-digest", "member-outside", "listed-digest", "policy-not-reject", "other-id"]
)
def test_a_fixture_that_is_not_the_one_named_is_refused_before_the_policy_moves(fault: str) -> None:
    given = arguments()
    members = None
    if fault == "member-outside":
        members = {f"{FIXTURE}/fixture.json": b"{}", "other/policy.json": b"{}"}
    process, files, ports = provisioning(members=members)
    if fault == "archive-digest":
        given["archive_sha256"] = "f" * 64
    if fault == "listed-digest":
        ports.archives.held[ARCHIVE][f"{FIXTURE}/a/manifest.json"] = b"changed"  # type: ignore[attr-defined]
    if fault == "policy-not-reject":
        ports.archives.held[ARCHIVE][f"{FIXTURE}/policy.json"] = b'{"default": []}'  # type: ignore[attr-defined]
    if fault == "other-id":
        given["fixture"] = "d" * 32

    with pytest.raises(errors.Refusal) as raised:
        update_provision_unit.run(ports, arguments=given)

    assert raised.value.reason is refusals.RefusalReason.FIXTURE_STATE_UNEXPECTED
    assert (
        files.read_bytes(safepaths.SafePath(Path(update_fixture.BUILDER_POLICY)), limit=1 << 20)
        == POLICY
    )


def test_bootc_is_asked_to_switch_only_to_a_fixture_directory_and_its_words_come_back() -> None:
    source = f"{update_fixture.FIXTURE_ROOT}/{FIXTURE}/wrong-key"
    process, _, ports = guest({}, {})
    process.failing.add(
        ("bootc", "switch", "--enforce-container-sigpolicy", "--transport", "dir", source)
    )

    found = cast(
        "dict[str, Any]",
        update_operate_unit.run(ports, arguments={"operation": "switch", "source": source}),
    )
    rolled = update_operate_unit.run(ports, arguments={"operation": "rollback"})

    assert found["returncode"] == 1 and found["stderr"] == "failed\n"
    assert found["argv"][-1] == source
    assert rolled["argv"] == ["bootc", "rollback"] and rolled["returncode"] == 0
    for bad in ({"operation": "switch", "source": "/tmp/x"}, {"operation": "install"}):
        with pytest.raises(errors.Refusal) as raised:
            update_operate_unit.run(ports, arguments=bad)
        assert raised.value.reason is refusals.RefusalReason.REQUEST_MALFORMED


def test_the_sentinel_is_created_once_and_read_back_by_the_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(guestguard.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: Path("/var/home/apex-test")))
    _, files, ports = guest({}, {})

    created = update_sentinel_unit.run(ports, arguments={"action": "create"})
    verified = update_sentinel_unit.run(ports, arguments={"action": "verify"})

    expected = hashlib.sha256(update_fixture.SENTINEL_TEXT).hexdigest()
    assert created["sha256"] == verified["sha256"] == expected
    assert created["path"] == "/var/home/apex-test/apex-update-sentinel.txt"
    assert isinstance(files, fake_files.MemoryFiles)
    with pytest.raises(errors.Refusal) as raised:
        update_sentinel_unit.run(ports, arguments={"action": "create"})
    assert raised.value.reason is refusals.RefusalReason.FIXTURE_STATE_UNEXPECTED


def test_the_sentinel_unit_refuses_root() -> None:
    _, _, ports = guest({}, {})

    with pytest.raises(errors.Refusal) as raised:
        update_sentinel_unit.run(ports, arguments={"action": "verify"})

    assert raised.value.reason is refusals.RefusalReason.PROBE_ENVIRONMENT_UNEXPECTED
