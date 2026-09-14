"""The lock fault runs the guard without CAP_SYS_ADMIN and always restores the fixture."""

from __future__ import annotations

from pathlib import Path

import pytest
from livefixture_trees import Guest
from lockfixtures import CAPS_WITH_ADMIN, DIGEST, LATCH, PUBLIC, Kernel, breakpoint_guest

from apex.adapters.fakes import fake_process
from apex.agent import guestguard
from apex.agent.units import live_lock_unit
from apex.config import defaults
from apex.kernel import commands, errors, refusals, safepaths


@pytest.fixture(autouse=True)
def as_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(guestguard.os, "geteuid", lambda: 0)


def argv_of(fixture: Guest) -> list[tuple[str, ...]]:
    return [tuple(call) for call in fixture.process.calls]


def test_the_denied_lock_latches_and_the_fixture_is_restored() -> None:
    fixture = breakpoint_guest()

    report = live_lock_unit.run(fixture.ports(), arguments={"guard_sha256": DIGEST})

    assert report["status"] == "PASS"
    assert report["kernel_denial"] == "PASS"
    assert report["ro_before_denial"] == "0"
    assert report["ro_after_denial"] == "0"
    assert report["failure_latched"] is True
    assert report["ro_after_cleanup"] == "1"
    assert report["child_capabilities"] == {
        "CapEff": "000001ffffdfffff",
        "CapBnd": "000001ffffdfffff",
    }
    assert report["boot_rejection"] == "NOT TESTED"
    assert argv_of(fixture) == [
        ("systemd-detect-virt", "--vm"),
        ("udevadm", "settle", "--timeout=15"),
        ("udevadm", "control", "--stop-exec-queue"),
        ("blockdev", "--setrw", "/dev/vda"),
        (
            "/bin/sh",
            "-c",
            'sed -n "/^CapEff:/p; /^CapBnd:/p" /proc/self/status; exec '
            "/usr/libexec/apex/live-disk-guard.sh /dev/vda",
        ),
        ("blockdev", "--setro", "/dev/vda"),
        ("udevadm", "control", "--start-exec-queue"),
    ]
    process = fixture.process
    assert isinstance(process, fake_process.ScriptedProcess)
    assert [bool(item) for item in process.restrictions] == [
        False,
        False,
        False,
        False,
        True,
        False,
        False,
    ]
    assert process.restrictions[4] == frozenset({commands.Capability.SYS_ADMIN})
    assert all(item == {"LC_ALL": "C"} for item in process.variables[1:])


def test_a_child_that_kept_the_capability_fails_the_fault() -> None:
    fixture = breakpoint_guest(caps=CAPS_WITH_ADMIN)

    report = live_lock_unit.run(fixture.ports(), arguments={"guard_sha256": DIGEST})

    assert report["status"] == "FAIL" and report["kernel_denial"] == "FAIL"
    assert report["ro_after_cleanup"] == "1"


def test_a_guard_that_succeeded_fails_the_fault() -> None:
    fixture = breakpoint_guest(guard_exit=0, denial=b"")

    report = live_lock_unit.run(fixture.ports(), arguments={"guard_sha256": DIGEST})

    assert report["status"] == "FAIL"


def test_a_missing_latch_fails_the_fault() -> None:
    fixture = breakpoint_guest(latches=False)

    report = live_lock_unit.run(fixture.ports(), arguments={"guard_sha256": DIGEST})

    assert report["status"] == "FAIL" and report["failure_latched"] is False


def test_a_fixture_not_protected_again_afterwards_fails_the_fault() -> None:
    fixture = breakpoint_guest(restores=False)

    report = live_lock_unit.run(fixture.ports(), arguments={"guard_sha256": DIGEST})

    assert report["kernel_denial"] == "PASS"
    assert report["status"] == "FAIL" and report["ro_after_cleanup"] == "0"


def test_the_udev_queue_is_restarted_even_when_a_step_halts() -> None:
    fixture = breakpoint_guest()
    process = fixture.process
    assert isinstance(process, Kernel)
    original = process.read_only

    def stubborn(device: str, value: bytes) -> None:
        original(device, b"1\n" if value == b"0\n" else value)

    process.read_only = stubborn  # type: ignore[method-assign]

    report = live_lock_unit.run(fixture.ports(), arguments={"guard_sha256": DIGEST})

    assert report["status"] == "FAIL"
    assert report["failure"] == "fixture was not writable before the denied lock"
    assert argv_of(fixture)[-1] == ("udevadm", "control", "--start-exec-queue")
    assert ("/bin/sh", "-c") not in [call[:2] for call in argv_of(fixture)]


def test_a_guard_that_differs_from_the_reviewed_source_is_refused_before_any_command() -> None:
    fixture = breakpoint_guest()

    with pytest.raises(errors.Refusal) as caught:
        live_lock_unit.run(fixture.ports(), arguments={"guard_sha256": "0" * 64})

    assert caught.value.reason is refusals.RefusalReason.PROBE_ENVIRONMENT_UNEXPECTED
    assert argv_of(fixture) == [("systemd-detect-virt", "--vm")]


def test_a_malformed_digest_argument_is_refused() -> None:
    fixture = breakpoint_guest()

    with pytest.raises(errors.Refusal) as caught:
        live_lock_unit.run(fixture.ports(), arguments={"guard_sha256": "abc"})

    assert caught.value.reason is refusals.RefusalReason.REQUEST_MALFORMED


@pytest.mark.parametrize("state", ["not-initramfs", "root-mounted", "already-latched"])
def test_outside_the_clean_breakpoint_the_fault_refuses(state: str) -> None:
    fixture = breakpoint_guest()
    files = fixture.files
    if state == "not-initramfs":
        files.remove(safepaths.SafePath(Path(defaults.INITRD_RELEASE)))
    elif state == "root-mounted":
        files.write_atomic(
            safepaths.SafePath(Path(defaults.MOUNTS)),
            b"rootfs / rootfs rw 0 0\n/dev/vdb /sysroot ext4 ro 0 0\n",
            mode=PUBLIC,
        )
    else:
        files.write_atomic(LATCH, b"", mode=PUBLIC)

    with pytest.raises(errors.Refusal) as caught:
        live_lock_unit.run(fixture.ports(), arguments={"guard_sha256": DIGEST})

    assert caught.value.reason is refusals.RefusalReason.PROBE_ENVIRONMENT_UNEXPECTED
    assert argv_of(fixture) == [("systemd-detect-virt", "--vm")]
