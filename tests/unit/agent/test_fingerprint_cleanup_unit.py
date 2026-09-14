"""The fingerprint test installs the target's packages, checks the delivery and runs the harness."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from fingerprintfixtures import (
    BODIES,
    IMAGE_ID,
    TARGET_RPMS,
    WORK,
    BuilderSpec,
    fingerprint_guest,
    harness_report,
)

from apex.adapters.fakes import fake_containers
from apex.agent import builder, fingerprintharness
from apex.agent.units import fingerprint_cleanup_unit
from apex.config import defaults
from apex.kernel import errors, refusals, safepaths
from apex.ports import containers

ROOT = Path(WORK)
OUTPUT = safepaths.SafePath(ROOT / "output" / "fingerprint")
SOURCES = safepaths.SafePath(ROOT / "fingerprint-sources")


@pytest.fixture(autouse=True)
def as_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(builder.os, "geteuid", lambda: 0)


def stored(files: Any, path: safepaths.SafePath) -> bytes:
    payload: bytes = files.read_bytes(path, limit=1 << 20)
    return payload


def registry_of(ports: Any) -> fake_containers.FakeRegistry:
    assert isinstance(ports.containers, fake_containers.FakeRegistry)
    return ports.containers


def test_a_complete_pass_reports_what_the_builder_showed() -> None:
    process, files, ports = fingerprint_guest(BuilderSpec())

    report = fingerprint_cleanup_unit.run(ports, arguments={"work": WORK})

    assert report["status"] == "PASS"
    assert report["target_rpms"] == TARGET_RPMS.splitlines() == report["test_rpms"]
    assert report["environment_rpm_count"] == 3
    assert report["sources"] == {
        name: hashlib.sha256(body).hexdigest() for name, body in BODIES.items()
    }
    assert report["source_lock_version"] == "1.94.5"
    assert report["harness_sha256"] == fingerprintharness.digest().hex
    assert report["harness_returncode"] == 0 and report["harness_failure"] is None
    assert report["report"] == harness_report()
    assert report["hardware_acceptance"] == "NOT TESTED"
    assert report["image_id"] == IMAGE_ID and report["profile"] == "fedora"
    assert stored(files, OUTPUT / "target-rpms.txt") == TARGET_RPMS.encode()
    assert stored(files, OUTPUT / "test-rpms.txt") == TARGET_RPMS.encode()
    assert stored(files, OUTPUT / "environment-rpms.txt") == (
        b"bash-5.3.0-1.fc44.x86_64\nfprintd-1.94.5-5.fc44.x86_64\nzlib-1.3.1-1.fc44.x86_64\n"
    )
    harness = safepaths.SafePath(ROOT / "test-fingerprint.py")
    assert stored(files, harness) == fingerprintharness.source()
    assert files.mode_of(harness).value == 0o644


def test_the_programs_run_in_the_older_order_and_the_harness_runs_as_builder_in_the_work() -> None:
    process, _, ports = fingerprint_guest(BuilderSpec())

    fingerprint_cleanup_unit.run(ports, arguments={"work": WORK})

    assert [tuple(call) for call in process.calls] == [
        ("systemd-detect-virt", "--vm"),
        (
            "dnf5",
            "install",
            "-y",
            *TARGET_RPMS.splitlines(),
            "python3-dbusmock",
            "python3-gobject",
            "python3-cairo",
            "dbus-daemon",
        ),
        ("rpm", "-q", "fprintd", "libfprint", "--qf", defaults.RPM_NEVRA_FORMAT),
        ("rpm", "-qa", "--qf", defaults.RPM_EVRA_FORMAT),
        ("chown", "builder:builder", str(OUTPUT)),
        (
            "runuser",
            "-u",
            "builder",
            "--",
            "env",
            "PYTHONDONTWRITEBYTECODE=1",
            "python3",
            f"{ROOT}/test-fingerprint.py",
            str(SOURCES),
            str(OUTPUT),
        ),
    ]
    assert process.directories[-1] == safepaths.SafePath(ROOT)
    assert [str(item) for item in process.transcripts] == [
        f"{OUTPUT}/install.log",
        f"{OUTPUT}/harness.log",
    ]
    assert registry_of(ports).runs == [
        containers.RunRequest(
            image=IMAGE_ID,
            argv=registry_of(ports).runs[0].argv,
            read_only=True,
            network_none=True,
            entrypoint="rpm",
        )
    ]
    assert list(registry_of(ports).runs[0].argv) == [
        "-q",
        "fprintd",
        "libfprint",
        "--qf",
        defaults.RPM_NEVRA_FORMAT,
    ]


@pytest.mark.parametrize(
    "report,exit_code,expected",
    [
        (harness_report(status="FAIL", failures=[["case", "trace"]]), 1, "FAIL"),
        (harness_report(skipped=[["case", "no virtual driver"]]), 0, "BLOCKED"),
        (harness_report(status="BLOCKED", tests_run=7), 1, "BLOCKED"),
        (None, 1, "BLOCKED"),
    ],
)
def test_anything_short_of_a_complete_pass_is_reported_with_the_harness_s_own_words(
    report: dict[str, Any] | None, exit_code: int, expected: str
) -> None:
    _, _, ports = fingerprint_guest(BuilderSpec(report=report, harness_exit=exit_code))

    found = fingerprint_cleanup_unit.run(ports, arguments={"work": WORK})

    assert found["status"] == expected
    assert found["report"] == report
    assert found["harness_returncode"] == exit_code


def test_a_harness_the_port_cannot_complete_blocks_with_the_cause() -> None:
    _, _, ports = fingerprint_guest(BuilderSpec(harness_hangs=True))

    found = fingerprint_cleanup_unit.run(ports, arguments={"work": WORK})

    assert found["status"] == "BLOCKED"
    assert found["harness_returncode"] is None
    assert isinstance(found["harness_failure"], str) and "exceeded" in found["harness_failure"]


def test_a_target_image_that_does_not_name_two_packages_is_refused_before_installing() -> None:
    spec = BuilderSpec(target_rpms=TARGET_RPMS + "extra-1-1.x86_64\n")
    process, _, ports = fingerprint_guest(spec)

    with pytest.raises(errors.Refusal) as caught:
        fingerprint_cleanup_unit.run(ports, arguments={"work": WORK})

    assert caught.value.reason is refusals.RefusalReason.FIXTURE_STATE_UNEXPECTED
    assert [call.arguments[0] for call in process.calls] == ["systemd-detect-virt"]


def test_installed_packages_that_differ_from_the_target_s_are_refused_before_the_harness() -> None:
    process, _, ports = fingerprint_guest(
        BuilderSpec(
            installed_rpms="fprintd-1.94.4-1.fc44.x86_64\nlibfprint-1.94.100-1.fc44.x86_64\n"
        )
    )

    with pytest.raises(errors.Refusal) as caught:
        fingerprint_cleanup_unit.run(ports, arguments={"work": WORK})

    assert caught.value.reason is refusals.RefusalReason.FIXTURE_STATE_UNEXPECTED
    assert "runuser" not in [call.arguments[0] for call in process.calls]


@pytest.mark.parametrize(
    "delivered,reason",
    [
        ({**BODIES, "fprintd.py": b"# edited"}, refusals.RefusalReason.ARTIFACT_CHECKSUM_MISMATCH),
        (
            {name: body for name, body in BODIES.items() if name != "output_checker.py"},
            refusals.RefusalReason.FIXTURE_STATE_UNEXPECTED,
        ),
        ({**BODIES, "extra.py": b"# unpinned"}, refusals.RefusalReason.FIXTURE_STATE_UNEXPECTED),
    ],
)
def test_a_delivery_that_is_not_the_reviewed_lock_s_is_refused_before_any_program_runs(
    delivered: dict[str, bytes], reason: refusals.RefusalReason
) -> None:
    process, _, ports = fingerprint_guest(BuilderSpec(delivered=delivered))

    with pytest.raises(errors.Refusal) as caught:
        fingerprint_cleanup_unit.run(ports, arguments={"work": WORK})

    assert caught.value.reason is reason
    assert [call.arguments[0] for call in process.calls] == ["systemd-detect-virt"]
    assert registry_of(ports).runs == []


def test_a_delivered_file_that_is_a_link_is_refused() -> None:
    _, files, ports = fingerprint_guest(BuilderSpec())
    files.symlink(SOURCES / "fprintd.py", target=safepaths.SafePath(Path("/etc/passwd")))

    with pytest.raises(errors.Refusal) as caught:
        fingerprint_cleanup_unit.run(ports, arguments={"work": WORK})

    assert caught.value.reason is refusals.RefusalReason.PATH_NOT_A_REGULAR_FILE


@pytest.mark.parametrize("work", ["/tmp/elsewhere", "/var/tmp/apex-fingerprint-short", 5])
def test_a_work_directory_that_is_not_named_for_a_run_is_refused(work: Any) -> None:
    _, _, ports = fingerprint_guest(BuilderSpec())

    with pytest.raises(errors.Refusal) as caught:
        fingerprint_cleanup_unit.run(ports, arguments={"work": work})

    assert caught.value.reason is refusals.RefusalReason.REQUEST_MALFORMED


def test_a_lock_that_is_not_a_document_is_refused() -> None:
    _, files, ports = fingerprint_guest(BuilderSpec())
    files.write_atomic(
        safepaths.SafePath(ROOT / "config" / "fingerprint-tests.lock.json"),
        b"{",
        mode=fingerprint_cleanup_unit.PLAIN,
    )

    with pytest.raises(errors.Refusal) as caught:
        fingerprint_cleanup_unit.run(ports, arguments={"work": WORK})

    assert caught.value.reason is refusals.RefusalReason.LOCK_UNREADABLE


def test_a_target_document_that_names_no_image_is_refused() -> None:
    _, files, ports = fingerprint_guest(BuilderSpec())
    files.write_atomic(
        safepaths.SafePath(ROOT / "target-image.json"),
        json.dumps({"profile": "fedora"}).encode(),
        mode=fingerprint_cleanup_unit.PLAIN,
    )

    with pytest.raises(errors.Refusal) as caught:
        fingerprint_cleanup_unit.run(ports, arguments={"work": WORK})

    assert caught.value.reason is refusals.RefusalReason.MALFORMED_IMAGE_DOCUMENT


def test_a_report_the_harness_left_unreadable_is_refused_not_judged() -> None:
    process, files, ports = fingerprint_guest(BuilderSpec(report=None))

    def unreadable(path: Path, _payload: bytes) -> None:
        mode = fingerprint_cleanup_unit.PLAIN
        files.write_atomic(safepaths.SafePath(path), b"not json", mode=mode)

    process.write = unreadable
    process.spec = BuilderSpec()

    with pytest.raises(errors.Refusal) as caught:
        fingerprint_cleanup_unit.run(ports, arguments={"work": WORK})

    assert caught.value.reason is refusals.RefusalReason.FIXTURE_REPORT_MALFORMED


def test_the_unit_refuses_outside_the_isolated_builder(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(builder.os, "geteuid", lambda: 1000)
    _, _, ports = fingerprint_guest(BuilderSpec())

    with pytest.raises(errors.Refusal) as caught:
        fingerprint_cleanup_unit.run(ports, arguments={"work": WORK})

    assert caught.value.reason is refusals.RefusalReason.BUILDER_NOT_ISOLATED
