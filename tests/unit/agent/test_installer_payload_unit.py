"""The payload fault damages one thing, keeps its bytes, and reads what the guard did."""

from __future__ import annotations

import dataclasses
import hashlib
import json
from pathlib import Path

import pytest
from installerfixtures import (
    BLOB,
    BLOB_DIGEST,
    MANIFEST,
    ORIGINAL_KEY,
    SIGNATURE,
    WRONG_KEY,
    InstallerSpec,
    installer_guest,
)

from apex.agent import guestguard
from apex.agent.units import installer_payload_unit
from apex.config import defaults
from apex.kernel import errors, quantities, refusals, safepaths

PAYLOAD = Path(defaults.INSTALLER_PAYLOAD)
TRUST = Path(defaults.INSTALLER_TRUST)
FAULT = Path(defaults.INSTALLER_FAULT_DIRECTORY)
KEYED = {"wrong-key": {"wrong_public_key": WRONG_KEY}}


@pytest.fixture(autouse=True)
def as_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(guestguard.os, "geteuid", lambda: 0)


def arguments(case: str) -> dict[str, str]:
    return {"case": case, **KEYED.get(case, {})}


def stored(files: object, path: Path) -> bytes:
    return files.read_bytes(safepaths.SafePath(path), limit=1 << 20)  # type: ignore[attr-defined]


@pytest.mark.parametrize("case", sorted(installer_payload_unit.CASES))
def test_each_case_is_refused_by_the_entry_point_and_passes(case: str) -> None:
    process, files, ports = installer_guest(InstallerSpec(), case)

    report = installer_payload_unit.run(ports, arguments=arguments(case))

    assert report["status"] == "PASS", report
    assert report["returncode"] == 1
    assert report["upstream_log_created"] is False
    assert report["selinux_after"] == "Enforcing"
    mutation = report["mutation"]
    assert isinstance(mutation, dict)
    assert mutation["before_sha256"] != mutation["after_sha256"]
    assert stored(files, FAULT / "original") == _original(case)
    assert [tuple(call) for call in process.calls] == [
        ("systemd-detect-virt", "--vm"),
        ("getenforce",),
        ("lsblk", "-bJ", "-o", "NAME,SIZE,TYPE,SERIAL,MOUNTPOINTS"),
        ("systemctl", "show", "anaconda.service", "-p", "ActiveState",
         "-p", "ExecMainStartTimestampMonotonic"),
        ("/usr/bin/anaconda", "--text"),
        ("getenforce",),
    ]


def _original(case: str) -> bytes:
    return {
        "missing-signature": SIGNATURE,
        "altered-signature": SIGNATURE,
        "wrong-key": ORIGINAL_KEY,
        "changed-manifest": MANIFEST,
        "corrupt-blob": BLOB,
        "unexpected-source": stored_metadata(),
    }[case]


def stored_metadata() -> bytes:
    _, files, _ = installer_guest(InstallerSpec())
    return stored(files, TRUST / "payload.json")


def test_the_missing_signature_case_removes_the_only_signature() -> None:
    _, files, ports = installer_guest(InstallerSpec(), "missing-signature")

    report = installer_payload_unit.run(ports, arguments={"case": "missing-signature"})

    mutation = report["mutation"]
    assert isinstance(mutation, dict) and mutation["after_sha256"] is None
    assert not files.exists(safepaths.SafePath(PAYLOAD / "signature-1"))


def test_a_corrupt_blob_keeps_its_size_and_flips_its_last_byte() -> None:
    _, files, ports = installer_guest(InstallerSpec(), "corrupt-blob")

    installer_payload_unit.run(ports, arguments={"case": "corrupt-blob"})

    after = stored(files, PAYLOAD / BLOB_DIGEST)
    assert len(after) == len(BLOB) and after[:-1] == BLOB[:-1] and after[-1] == BLOB[-1] ^ 1


def test_the_wrong_key_case_rewrites_the_key_the_metadata_and_the_policy() -> None:
    _, files, ports = installer_guest(InstallerSpec(), "wrong-key")

    installer_payload_unit.run(ports, arguments=arguments("wrong-key"))

    assert stored(files, TRUST / "payload.pub") == WRONG_KEY.encode()
    metadata = json.loads(stored(files, TRUST / "payload.json"))
    assert metadata["public_key_sha256"] == hashlib.sha256(WRONG_KEY.encode()).hexdigest()
    policy = json.loads(stored(files, Path(defaults.CONTAINER_POLICY)))
    assert policy["default"] == [{"type": "reject"}]
    requirement = policy["transports"]["dir"][defaults.INSTALLER_PAYLOAD][0]
    assert requirement["signedIdentity"]["dockerReference"] == metadata["identity"]


def test_the_wrong_key_case_needs_a_different_valid_key() -> None:
    _, _, ports = installer_guest(InstallerSpec(), "wrong-key")

    with pytest.raises(errors.Refusal) as caught:
        installer_payload_unit.run(ports, arguments={"case": "wrong-key"})

    assert caught.value.reason is refusals.RefusalReason.REQUEST_MALFORMED


def test_an_unknown_case_is_refused_before_any_program() -> None:
    process, _, ports = installer_guest(InstallerSpec())

    with pytest.raises(errors.Refusal) as caught:
        installer_payload_unit.run(ports, arguments={"case": "invented"})

    assert caught.value.reason is refusals.RefusalReason.REQUEST_MALFORMED
    assert process.calls == []


@pytest.mark.parametrize(
    "spec",
    [
        InstallerSpec(cmdline="BOOT_IMAGE=/vmlinuz quiet"),
        InstallerSpec(enforcement="Permissive"),
        InstallerSpec(interfaces=("lo", "enp1s0")),
    ],
)
def test_a_guest_that_is_not_the_offline_diagnostic_installer_is_refused(
    spec: InstallerSpec,
) -> None:
    _, files, ports = installer_guest(spec)

    with pytest.raises(errors.Refusal) as caught:
        installer_payload_unit.run(ports, arguments={"case": "missing-signature"})

    assert caught.value.reason is refusals.RefusalReason.PROBE_ENVIRONMENT_UNEXPECTED
    assert not files.exists(safepaths.SafePath(FAULT))


@pytest.mark.parametrize(
    "spec",
    [
        InstallerSpec(entered=True),
        InstallerSpec(anaconda_running=True),
        InstallerSpec(anaconda_state="ActiveState=active\nExecMainStartTimestampMonotonic=99"),
        dataclasses.replace(
            InstallerSpec(),
            disks={"blockdevices": [{"name": "vda", "size": 48 * 1024**3, "type": "disk",
                                     "serial": "x", "mountpoints": [None]}]},
        ),
    ],
)
def test_a_boot_that_already_entered_the_installer_or_a_wrong_fixture_is_refused(
    spec: InstallerSpec,
) -> None:
    _, files, ports = installer_guest(spec)

    with pytest.raises(errors.Refusal) as caught:
        installer_payload_unit.run(ports, arguments={"case": "missing-signature"})

    assert caught.value.reason is refusals.RefusalReason.FIXTURE_STATE_UNEXPECTED
    assert not files.exists(safepaths.SafePath(FAULT))


def test_a_symlinked_payload_is_refused() -> None:
    _, files, ports = installer_guest(InstallerSpec())
    files.symlink(safepaths.SafePath(PAYLOAD), target=safepaths.SafePath(Path("/elsewhere")))

    with pytest.raises(errors.Refusal) as caught:
        installer_payload_unit.run(ports, arguments={"case": "missing-signature"})

    assert caught.value.reason is refusals.RefusalReason.PROBE_ENVIRONMENT_UNEXPECTED


def test_a_second_mutation_in_one_boot_is_refused_and_the_first_backup_kept() -> None:
    _, files, ports = installer_guest(InstallerSpec())
    files.make_directory(safepaths.SafePath(FAULT), mode=quantities.FileMode(0o700))
    files.write_atomic(
        safepaths.SafePath(FAULT / "original"), b"earlier", mode=quantities.FileMode(0o600)
    )

    with pytest.raises(errors.Refusal) as caught:
        installer_payload_unit.run(ports, arguments={"case": "missing-signature"})

    assert caught.value.reason is refusals.RefusalReason.FIXTURE_STATE_UNEXPECTED
    assert stored(files, FAULT / "original") == b"earlier"


@pytest.mark.parametrize(
    "spec",
    [
        InstallerSpec(entry_exit=0),
        InstallerSpec(preflight_status="PASS"),
        InstallerSpec(preflight_error="some other complaint"),
        InstallerSpec(creates_log=True),
        InstallerSpec(enforcement_after="Permissive"),
    ],
)
def test_anything_short_of_the_expected_rejection_is_a_failure_that_is_still_reported(
    spec: InstallerSpec,
) -> None:
    _, _, ports = installer_guest(spec)

    report = installer_payload_unit.run(ports, arguments={"case": "missing-signature"})

    assert report["status"] == "FAIL"
    assert "mutation" in report and "before" in report
