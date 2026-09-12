"""Walking a disk's backing chain, on the real image tool and on a scripted process.

The fake answers `qemu-img info` from a table keyed on the exact argument vector, so the
chain the walker follows on fakes is the chain the tool would report.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from apex.adapters.fakes import (
    fake_archives,
    fake_clock,
    fake_digesting,
    fake_downloading,
    fake_files,
    fake_hypervisor,
    fake_ids,
    fake_locking,
    fake_process,
    fake_qmp,
    fake_signing,
)
from apex.adapters.real import real_files, real_process
from apex.kernel import errors, quantities, refusals, safepaths
from apex.ports import files, portset, process
from apex.provisioning import backingchain

QEMU_IMG = "qemu-img"
PRIVATE = quantities.FileMode(0o600)


def describe(path: Path, *, image_format: str = "qcow2", backing: str | None = None) -> bytes:
    document: dict[str, object] = {"format": image_format, "filename": path.name}
    if backing is not None:
        document["backing-filename"] = backing
    return json.dumps(document).encode()


class Images:
    """Creates images on disk for the real tool and teaches the fake the same chain."""

    def __init__(self, real: bool, scripted: fake_process.ScriptedProcess) -> None:
        self.real = real
        self.scripted = scripted

    def create(
        self, path: Path, *, image_format: str = "qcow2", backing: Path | None = None
    ) -> None:
        if self.real:
            argv = [QEMU_IMG, "create", "-q", "-f", image_format]
            if backing is not None:
                argv += ["-F", "qcow2", "-b", str(backing)]
            subprocess.run([*argv, str(path), "1M"], check=True)
            return
        path.write_bytes(b"")
        self.scripted.expect(
            (QEMU_IMG, "info", "--output=json", str(path)),
            fake_process.Reply(
                stdout=describe(
                    path,
                    image_format=image_format,
                    backing=None if backing is None else str(backing),
                )
            ),
        )

    def rebase(self, path: Path, *, onto: Path) -> None:
        if self.real:
            subprocess.run(
                [QEMU_IMG, "rebase", "-q", "-u", "-F", "qcow2", "-b", str(onto), str(path)],
                check=True,
            )
            return
        self.scripted.expect(
            (QEMU_IMG, "info", "--output=json", str(path)),
            fake_process.Reply(stdout=describe(path, backing=str(onto))),
        )


@pytest.fixture(params=["real", "fake"])
def images(request: pytest.FixtureRequest) -> Images:
    if request.param == "real":
        if shutil.which(QEMU_IMG) is None:
            pytest.skip(f"NOT TESTED: {QEMU_IMG} is absent")
        return Images(real=True, scripted=fake_process.ScriptedProcess())
    return Images(real=False, scripted=fake_process.ScriptedProcess())


def bundle(images: Images) -> portset.HostPorts:
    processes: process.ProcessPort = (
        real_process.SubprocessRunner() if images.real else images.scripted
    )
    file_system: files.FileSystemPort = (
        real_files.LocalFiles() if images.real else fake_files.MemoryFiles()
    )
    return portset.HostPorts(
        processes=processes,
        files=file_system,
        clock=fake_clock.ManualClock(),
        identities=fake_ids.SequenceIdentities(),
        locks=fake_locking.MemoryLocks(),
        digests=fake_digesting.CountingDigests(),
        archives=fake_archives.MemoryArchives(),
        signing=fake_signing.FakeSigner(),
        downloads=fake_downloading.OfflineFetcher({}),
        hypervisor=fake_hypervisor.FakeQemu(),
        monitor=fake_qmp.ScriptedQmp(),
    )


def test_a_standalone_disk_is_a_chain_of_one(images: Images, root: safepaths.RuntimeRoot) -> None:
    disk = root.path / "base.qcow2"
    images.create(disk)

    chain = backingchain.inspect(bundle(images), disk, root=root)

    assert chain.standalone
    assert chain.disk.path == disk
    assert chain.base.path == disk


def test_an_overlay_lists_its_base_last(images: Images, root: safepaths.RuntimeRoot) -> None:
    base = root.path / "base.qcow2"
    top = root.path / "top.qcow2"
    images.create(base)
    images.create(top, backing=base)

    chain = backingchain.inspect(bundle(images), top, root=root)

    assert [link.path for link in chain.links] == [top, base]
    assert not chain.standalone


def test_a_disk_that_is_not_qcow2_is_refused(images: Images, root: safepaths.RuntimeRoot) -> None:
    raw = root.path / "disk.img"
    images.create(raw, image_format="raw")

    with pytest.raises(errors.Refusal) as raised:
        backingchain.inspect(bundle(images), raw, root=root)

    assert raised.value.reason is refusals.RefusalReason.DISK_NOT_QCOW2


def test_a_base_outside_the_runtime_root_is_refused(
    images: Images, root: safepaths.RuntimeRoot, tmp_path: Path
) -> None:
    outside = tmp_path / "elsewhere.qcow2"
    top = root.path / "top.qcow2"
    images.create(outside)
    images.create(top, backing=outside)

    with pytest.raises(errors.Refusal) as raised:
        backingchain.inspect(bundle(images), top, root=root)

    assert raised.value.reason is refusals.RefusalReason.PATH_OUTSIDE_RUNTIME_ROOT


def test_a_cycle_is_refused_rather_than_walked_forever(
    images: Images, root: safepaths.RuntimeRoot
) -> None:
    base = root.path / "base.qcow2"
    top = root.path / "top.qcow2"
    images.create(base)
    images.create(top, backing=base)
    images.rebase(base, onto=top)

    with pytest.raises(errors.Refusal) as raised:
        backingchain.inspect(bundle(images), top, root=root)

    assert raised.value.reason is refusals.RefusalReason.DISK_CHAIN_CYCLE


def test_a_layered_disk_cannot_pass_as_a_base(images: Images, root: safepaths.RuntimeRoot) -> None:
    base = root.path / "base.qcow2"
    top = root.path / "top.qcow2"
    images.create(base)
    images.create(top, backing=base)
    chain = backingchain.inspect(bundle(images), top, root=root)

    with pytest.raises(errors.Refusal) as raised:
        backingchain.require_standalone(chain)

    assert raised.value.reason is refusals.RefusalReason.DISK_NOT_STANDALONE


def test_an_overlay_is_created_over_the_disk_and_walked_back(
    images: Images, root: safepaths.RuntimeRoot
) -> None:
    base = root.path / "base.qcow2"
    images.create(base)
    ports = bundle(images)
    chain = backingchain.inspect(ports, base, root=root)
    into = root.child("runs/a/disk.qcow2")
    into.path.parent.mkdir(parents=True)
    if not images.real:
        images.scripted.expect(
            (QEMU_IMG, "create", "-f", "qcow2", "-F", "qcow2", "-b", str(base), str(into)),
            fake_process.Reply(),
        )
        images.create(into.path, backing=base)

    layered = backingchain.overlay(ports, chain, into=into, root=root)

    assert [link.path for link in layered.links] == [into.path, base]


def test_an_overlay_never_replaces_an_existing_file(
    images: Images, root: safepaths.RuntimeRoot
) -> None:
    base = root.path / "base.qcow2"
    images.create(base)
    ports = bundle(images)
    chain = backingchain.inspect(ports, base, root=root)
    into = root.child("runs/a/disk.qcow2")
    ports.files.write_atomic(into, b"evidence", mode=PRIVATE)

    with pytest.raises(errors.Refusal) as raised:
        backingchain.overlay(ports, chain, into=into, root=root)

    assert raised.value.reason is refusals.RefusalReason.DISK_OVERLAY_EXISTS
    assert ports.files.read_bytes(into, limit=16) == b"evidence"
