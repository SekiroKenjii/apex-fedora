"""A probe refuses to run anywhere but the guest it was written for."""

from __future__ import annotations

from pathlib import Path

import pytest

from apex.adapters.fakes import (
    fake_archives,
    fake_clock,
    fake_containers,
    fake_digesting,
    fake_extents,
    fake_files,
    fake_ids,
    fake_process,
)
from apex.agent import agentports, guestguard
from apex.config import defaults
from apex.kernel import errors, quantities, refusals, safepaths

DETECT = ("systemd-detect-virt", "--vm")
CMDLINE = safepaths.SafePath(Path("/proc/cmdline"))


def bundle(
    process: fake_process.ScriptedProcess, files: fake_files.MemoryFiles | None = None
) -> agentports.AgentPorts:
    return agentports.AgentPorts(
        processes=process, files=files or fake_files.MemoryFiles(),
        clock=fake_clock.ManualClock(), containers=fake_containers.FakeRegistry(),
        digests=fake_digesting.CountingDigests(), archives=fake_archives.MemoryArchives(),
        identities=fake_ids.SequenceIdentities(), extents=fake_extents.FakeExtents(),
    )


def virtual(answer: bytes = b"kvm\n", exit_code: int = 0) -> fake_process.ScriptedProcess:
    process = fake_process.ScriptedProcess()
    process.expect(DETECT, fake_process.Reply(stdout=answer, exit_code=exit_code))
    return process


def live_files(cmdline: str) -> fake_files.MemoryFiles:
    files = fake_files.MemoryFiles()
    files.write_atomic(CMDLINE, cmdline.encode(), mode=quantities.FileMode(0o444))
    return files


@pytest.fixture(autouse=True)
def as_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(guestguard.os, "geteuid", lambda: 0)


def refused(action: object) -> None:
    with pytest.raises(errors.Refusal) as caught:
        action()  # type: ignore[operator]
    assert caught.value.reason is refusals.RefusalReason.PROBE_ENVIRONMENT_UNEXPECTED


def test_an_unprivileged_caller_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(guestguard.os, "geteuid", lambda: 1000)

    refused(lambda: guestguard.require_virtual_root(bundle(virtual())))


def test_a_machine_that_is_not_virtual_is_refused() -> None:
    refused(lambda: guestguard.require_virtual_root(bundle(virtual(b"none\n", exit_code=1))))


def test_another_hypervisor_is_refused() -> None:
    refused(lambda: guestguard.require_virtual_root(bundle(virtual(b"vmware\n"))))


def test_a_qemu_guest_as_root_passes() -> None:
    guestguard.require_virtual_root(bundle(virtual()))


def test_a_guest_not_booted_from_the_live_medium_is_refused() -> None:
    ports = bundle(virtual(), live_files("BOOT_IMAGE=/vmlinuz root=/dev/vda3 quiet\n"))

    refused(lambda: guestguard.require_live(ports))


def test_the_live_token_must_be_a_whole_word() -> None:
    ports = bundle(virtual(), live_files(f"{defaults.LIVE_ROOT_TOKEN}-other quiet\n"))

    refused(lambda: guestguard.require_live(ports))


def test_a_live_qemu_guest_as_root_passes() -> None:
    cmdline = f"BOOT_IMAGE=/vmlinuz {defaults.LIVE_ROOT_TOKEN} rd.live.image\n"
    ports = bundle(virtual(), live_files(cmdline))

    guestguard.require_live(ports)
