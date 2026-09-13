"""A completed update fixture, a disposable account and the answers a guest gives for it.

The fixture's report and payload are laid under the runtime root as its build left them;
the answer tables are what the update, recovery and initramfs units observe in a healthy
guest, so a recipe test declares only the part it changes.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from pathlib import Path
from typing import Any

from answeringguest import AnsweringGuest
from mirroredfiles import MirroredFiles

from apex.adapters.fakes import fake_clock, fake_guestshell
from apex.adapters.real import real_digesting
from apex.config import defaults
from apex.kernel import safepaths, secrets
from apex.ports import guestshell, portset
from apex.verification import testaccess, updatefixtures
from apex.verification.stages import guest_ready_stage

FIXTURE = "c" * 32
PARENT = "sha256:" + "0" * 64
IMAGE_A = "sha256:" + "1" * 64
IMAGE_B = "sha256:" + "2" * 64
CONFIG_A = "sha256:" + "3" * 64
CONFIG_B = "sha256:" + "4" * 64
PAYLOADS = b"tar of payloads"
PUBLIC_KEY = b"fixture public key\n"
MANIFEST_A = b'{"config": {"digest": "' + CONFIG_A.encode() + b'"}}'
MANIFEST_B = b'{"config": {"digest": "' + CONFIG_B.encode() + b'"}}'
POLICY_HEX = "5" * 64
PRESET_HEX = "9" * 64
PASSWORD = "Ab-1_"
PRIVATE = defaults.RECORD_MODE
READY = b"kvm\nrunning\n"


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def fixture_report() -> dict[str, Any]:
    return {
        "status": "PASS",
        "id": FIXTURE,
        "parent": {"profile": "fedora", "digest": PARENT, "image_id": "sha256:" + "6" * 64},
        "images": {
            "a": {"digest": IMAGE_A, "config": CONFIG_A, "identity": f"localhost/x-{FIXTURE}:a"},
            "b": {"digest": IMAGE_B, "config": CONFIG_B, "identity": f"localhost/x-{FIXTURE}:b"},
        },
        "files": {"policy.json": POLICY_HEX, "a/manifest.json": digest(MANIFEST_A)},
        "public_key_sha256": digest(PUBLIC_KEY),
        "archive_sha256": digest(PAYLOADS),
        "greenboot_config_sha256": PRESET_HEX,
    }


def exported_fixture(
    ports: portset.HostPorts, files: MirroredFiles, root: safepaths.RuntimeRoot
) -> updatefixtures.Located:
    home = root.child(f"exports/{FIXTURE}/output")
    files.write_atomic(home / "results.json", json.dumps(fixture_report()).encode(), mode=PRIVATE)
    files.write_atomic(home / "payloads.tar", PAYLOADS, mode=PRIVATE)
    files.write_atomic(home / "trusted.pub", PUBLIC_KEY, mode=PRIVATE)
    files.write_atomic(home / "manifest-a.json", MANIFEST_A, mode=PRIVATE)
    files.write_atomic(home / "manifest-b.json", MANIFEST_B, mode=PRIVATE)
    return updatefixtures.locate(dataclasses.replace(ports, files=files), root, FIXTURE)


def credentials(root: safepaths.RuntimeRoot | None = None) -> testaccess.Credentials:
    key = None if root is None else root.path / "access" / defaults.TEST_KEY_NAME
    return testaccess.Credentials(
        user=defaults.TEST_ACCOUNT, password=secrets.Secret(PASSWORD), key=key
    )


def access_directory(files: MirroredFiles, root: safepaths.RuntimeRoot) -> Path:
    directory = root.path / "access"
    files.write_atomic(
        safepaths.SafePath(directory / defaults.CREDENTIALS_NAME),
        json.dumps({"user": defaults.TEST_ACCOUNT, "password": PASSWORD}).encode(),
        mode=PRIVATE,
    )
    files.write_atomic(safepaths.SafePath(directory / defaults.TEST_KEY_NAME), b"", mode=PRIVATE)
    return directory


def guest_target(root: safepaths.RuntimeRoot) -> guestshell.GuestTarget:
    return guestshell.GuestTarget(
        user=defaults.TEST_ACCOUNT,
        port=defaults.GUEST_SSH_PORT,
        key=safepaths.SafePath.regular_file(root.path / "guest_ed25519", within=root),
        known_hosts=root.child(defaults.KNOWN_HOSTS_NAME),
    )


def bootc(booted: str, *, rollback: str | None = None, staged: str | None = None) -> dict[str, Any]:
    def deployment(image: str | None) -> dict[str, Any] | None:
        return None if image is None else {"image": {"imageDigest": image}}

    return {
        "status": {
            "booted": deployment(booted),
            "rollback": deployment(rollback),
            "staged": deployment(staged),
            "rollbackQueued": staged is not None,
        }
    }


def state(
    booted: str,
    *,
    rollback: str | None = None,
    staged: str | None = None,
    policy: str = POLICY_HEX,
    marker: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """What `update.state` observes in a guest booted into the named image."""
    return {
        "boot_id": "boot-1",
        "versions": {"returncode": 0, "stdout": "bootc-1\n"},
        "kernel_inputs": {"/usr/lib/modules/6.0/vmlinuz": "7" * 64},
        "bootc": bootc(booted, rollback=rollback, staged=staged),
        "policy_sha256": policy,
        "marker": marker,
    }


def program(stdout: str, returncode: int = 0) -> dict[str, Any]:
    return {"returncode": returncode, "stdout": stdout, "stderr": "", "truncated": False}


def inspection(
    booted: str, *, rollback: str | None = IMAGE_B, staged: str | None = None
) -> dict[str, Any]:
    """What `recovery.inspect` observes: every program answered, bootc with its status."""
    found = {
        name: program(f"{name} output\n")
        for name in (
            "packages",
            "grub_environment",
            "grub_config",
            "greenboot_config",
            "boot_id",
            "units",
            "boot_files",
            "kernel_inputs",
        )
    }
    found["bootc"] = program(json.dumps(bootc(booted, rollback=rollback, staged=staged)))
    return found


def health(booted: str) -> dict[str, Any]:
    """What `guest.state` observes in a healthy guest booted into the named image."""
    observations = {
        name: {"returncode": 0, "stdout": "", "stderr": ""}
        for name in ("dbus", "root_mount", "failed_units", "sessions")
    }
    observations["gdm"] = {"returncode": 0, "stdout": "active", "stderr": ""}
    observations["selinux"] = {"returncode": 0, "stdout": "Enforcing", "stderr": ""}
    observations["kernel"] = {"returncode": 0, "stdout": "6.0", "stderr": ""}
    observations["bootc"] = {"returncode": 0, "stdout": json.dumps(bootc(booted)), "stderr": ""}
    return {"observations": observations, "visual_test": "NOT TESTED"}


def ready(guest: fake_guestshell.ScriptedGuest) -> None:
    guest.expect(guest_ready_stage.SCRIPT.rendered(), fake_guestshell.GuestReply(stdout=READY))


def answering(answers: dict[str, Any]) -> AnsweringGuest:
    guest = AnsweringGuest(answers)
    ready(guest)
    return guest


def held(
    ports: portset.HostPorts, files: MirroredFiles, guest: AnsweringGuest
) -> portset.HostPorts:
    return dataclasses.replace(
        ports,
        files=files,
        guest=guest,
        digests=real_digesting.CachedDigests(),
        clock=fake_clock.ManualClock(),
    )
