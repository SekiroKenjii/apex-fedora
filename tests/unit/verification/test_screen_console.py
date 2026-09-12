"""The screen is captured to a named file and read back; keys go out as the older tool sent them."""

from __future__ import annotations

from pathlib import Path

import pytest

from apex.adapters.fakes import (
    fake_archives,
    fake_clock,
    fake_digesting,
    fake_downloading,
    fake_guestshell,
    fake_hypervisor,
    fake_ids,
    fake_locking,
    fake_process,
    fake_qmp,
    fake_signing,
)
from apex.adapters.real import real_files
from apex.kernel import errors, safepaths
from apex.ports import portset
from apex.verification import console

FRAME = b"P6\n1 1\n255\n\x10\x20\x30"


@pytest.fixture
def root(tmp_path: Path) -> safepaths.RuntimeRoot:
    base = tmp_path / "runtime"
    base.mkdir(mode=0o700)
    return safepaths.RuntimeRoot.adopt(base)


def dumped(into: safepaths.SafePath, payload: bytes) -> None:
    """What the hypervisor does on a screendump: the file appears where it was named."""
    into.path.parent.mkdir(parents=True, exist_ok=True)
    into.path.write_bytes(payload)


def bundle(monitor: fake_qmp.ScriptedQmp) -> portset.HostPorts:
    return portset.HostPorts(
        processes=fake_process.ScriptedProcess(),
        files=real_files.LocalFiles(),
        clock=fake_clock.ManualClock(),
        identities=fake_ids.SequenceIdentities(),
        locks=fake_locking.MemoryLocks(),
        digests=fake_digesting.CountingDigests(),
        archives=fake_archives.MemoryArchives(),
        signing=fake_signing.FakeSigner(),
        downloads=fake_downloading.OfflineFetcher({}),
        hypervisor=fake_hypervisor.FakeQemu(),
        monitor=monitor,
        guest=fake_guestshell.ScriptedGuest(),
    )


def test_a_capture_names_the_file_the_hypervisor_writes_and_reads_it_back(
    root: safepaths.RuntimeRoot,
) -> None:
    into = root.child("screens/application.ppm")
    monitor = fake_qmp.ScriptedQmp({"screendump": {}})
    monitor.react("screendump", lambda: dumped(into, FRAME))

    captured = console.capture(bundle(monitor), root.child("qmp.sock"), into=into)

    assert captured == FRAME
    assert monitor.connections == [root.child("qmp.sock")]
    assert [command.name for command in monitor.executed] == ["screendump"]
    assert dict(monitor.executed[0].arguments) == {"filename": str(into)}


def test_a_png_capture_asks_for_that_format(root: safepaths.RuntimeRoot) -> None:
    into = root.child("screens/application.png")
    monitor = fake_qmp.ScriptedQmp({"screendump": {}})
    monitor.react("screendump", lambda: dumped(into, b"png"))

    console.capture(bundle(monitor), root.child("qmp.sock"), into=into)

    assert dict(monitor.executed[0].arguments) == {"filename": str(into), "format": "png"}


def test_a_monitor_that_cannot_be_reached_is_a_port_failure(root: safepaths.RuntimeRoot) -> None:
    monitor = fake_qmp.ScriptedQmp({"screendump": {}}, reachable=False)

    with pytest.raises(errors.PortFailure):
        console.capture(bundle(monitor), root.child("qmp.sock"), into=root.child("x.ppm"))


def test_keys_are_sent_together_as_codes_held_briefly(root: safepaths.RuntimeRoot) -> None:
    monitor = fake_qmp.ScriptedQmp({"send-key": {}})

    console.press(bundle(monitor), root.child("qmp.sock"), "meta_l", "s")

    assert [command.name for command in monitor.executed] == ["send-key"]
    assert dict(monitor.executed[0].arguments) == {
        "keys": [{"type": "qcode", "data": "meta_l"}, {"type": "qcode", "data": "s"}],
        "hold-time": 40,
    }
