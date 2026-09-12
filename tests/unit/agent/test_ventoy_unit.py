"""The ventoy unit runs the older script's steps, in order, and refuses what it refused."""

from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path
from typing import Any

import pytest

from apex.adapters.fakes import fake_clock, fake_containers, fake_process
from apex.adapters.real import real_archives, real_digesting, real_files
from apex.agent import agentports, builder
from apex.agent.units import ventoy_unit
from apex.config import defaults
from apex.kernel import errors, hashing, quantities, refusals
from apex.provisioning.fixtures import ventoy_fixture

VERSION = "1.1.05"
TABLE = {"partitiontable": {"label": "dos", "partitions": [{"node": "p1"}, {"node": "p2"}]}}


class Answering(fake_process.ScriptedProcess):
    """Answers every vector with what the builder would say, and records it."""

    def run(self, argv: Any, **keywords: Any) -> Any:
        produce(list(argv))
        self.expect(tuple(argv), fake_process.Reply(stdout=answer(list(argv))))
        return super().run(argv, **keywords)


def produce(argv: list[str]) -> None:
    """The one output the unit hashes afterwards: the converted image, as the tool leaves it."""
    if argv[:2] == ["qemu-img", "convert"]:
        Path(argv[-1]).write_bytes(b"qcow2")


def answer(argv: list[str]) -> bytes:
    if argv[0] == "systemd-detect-virt":
        return b"kvm\n"
    if argv[0] == "losetup" and "--find" in argv:
        return b"/dev/loop0\n"
    if argv[:2] == ["sfdisk", "--json"]:
        return json.dumps(TABLE).encode()
    if argv[:3] == ["sh", "Ventoy2Disk.sh", "-l"]:
        return f"Ventoy Version in Disk: {VERSION}\n".encode()
    if argv[0] == "rpm":
        return b"parted-3\n"
    return b""


def prepare(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, version: str = VERSION) -> Path:
    work = tmp_path / "work"
    work.mkdir(mode=0o700)
    packed = work / "ventoy.tar.gz"
    with tarfile.open(packed, "w:gz") as opened:
        member = tarfile.TarInfo(f"ventoy-{version}/ventoy/version")
        member.size = len(version)
        opened.addfile(member, io.BytesIO(version.encode()))
    files = {}
    for name in ("ventoy.tar.gz", "Apex-Live.iso", "Ubuntu.iso"):
        if name != "ventoy.tar.gz":
            (work / name).write_bytes(name.encode())
        files[name] = hashing.digest_bytes((work / name).read_bytes()).hex
    (work / "request.json").write_text(json.dumps({"files": files, "ventoy_version": VERSION}))
    marker = tmp_path / "apex-builder"
    marker.write_text(f"{defaults.BUILDER_MARKER_TEXT}\n")
    monkeypatch.setattr(defaults, "BUILDER_MARKER", str(marker))
    monkeypatch.setattr(builder.os, "geteuid", lambda: 0)
    devices = tmp_path / "dev"
    devices.mkdir()
    (devices / "loop0").write_bytes(b"")
    (devices / "loop0p1").write_bytes(b"")
    sysfs = tmp_path / "block" / "loop0" / "loop"
    sysfs.mkdir(parents=True)
    (sysfs / "backing_file").write_text(f"{work}/ventoy.raw\n")
    monkeypatch.setattr(ventoy_unit, "BLOCK_CLASS", str(tmp_path / "block"))
    monkeypatch.setattr(ventoy_unit, "LOOP", ventoy_unit.re.compile(rf"{devices}/loop[0-9]+"))
    monkeypatch.setattr(ventoy_unit.os, "sync", lambda: None)
    # The temporary filesystem here is smaller than the builder's scratch; the check itself
    # is exercised by the older script's parity harness on the same numbers.
    monkeypatch.setattr(ventoy_fixture, "REQUIRED_FREE", quantities.Gib(0))
    return work


def bundle(tmp_path: Path) -> tuple[agentports.AgentPorts, Answering]:
    process = Answering()
    devices = tmp_path / "dev"

    def answering(argv: list[str]) -> bytes:
        if argv[0] == "losetup" and "--find" in argv:
            return f"{devices}/loop0\n".encode()
        return answer(argv)

    def run(argv: Any, **keywords: Any) -> Any:
        if list(argv)[:2] == ["qemu-img", "convert"]:
            Path(list(argv)[-1]).write_bytes(b"qcow2")
        process.expect(tuple(argv), fake_process.Reply(stdout=answering(list(argv))))
        return fake_process.ScriptedProcess.run(process, argv, **keywords)

    process.run = run  # type: ignore[method-assign]
    ports = agentports.AgentPorts(
        processes=process,
        files=real_files.LocalFiles(),
        clock=fake_clock.ManualClock(),
        containers=fake_containers.FakeRegistry(),
        digests=real_digesting.CachedDigests(),
        archives=real_archives.TarArchives(),
    )
    return ports, process


def test_the_unit_runs_the_older_steps_in_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work = prepare(tmp_path, monkeypatch)
    ports, process = bundle(tmp_path)
    loop = f"{tmp_path}/dev/loop0"

    report = ventoy_unit.run(ports, arguments={"work": str(work)})

    programs = [tuple(call)[:2] for call in process.calls]
    assert programs == [
        ("systemd-detect-virt", "--vm"),
        ("dnf5", "-y"),
        ("losetup", "--find"),
        ("sh", "Ventoy2Disk.sh"),
        ("udevadm", "settle"),
        ("sfdisk", "--json"),
        ("sh", "Ventoy2Disk.sh"),
        ("mount", "-t"),
        ("umount", f"{work}/mount"),
        ("fsck.exfat", "-n"),
        ("losetup", "--detach"),
        ("qemu-img", "convert"),
        ("qemu-img", "check"),
        ("rpm", "-q"),
    ]
    assert tuple(process.calls[3]) == (
        "sh", "Ventoy2Disk.sh", "-i", "-r", "2048", loop,
    )
    assert str(process.directories[3]) == f"{work}/upstream/ventoy-{VERSION}"
    assert report["status"] == "PASS"
    assert report["physical_media_accessed"] is False
    assert report["boot_acceptance"] == "NOT TESTED"
    assert (work / "mount" / "Ubuntu.iso").read_bytes() == b"Ubuntu.iso"
    assert (work / "output" / "media.json").exists()


def test_an_archive_of_another_version_is_refused_before_the_device_is_touched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work = prepare(tmp_path, monkeypatch, version="1.0.99")
    ports, process = bundle(tmp_path)

    with pytest.raises(errors.Refusal) as raised:
        ventoy_unit.run(ports, arguments={"work": str(work)})

    assert raised.value.reason is refusals.RefusalReason.FIXTURE_STATE_UNEXPECTED
    assert all(call.arguments[0] != "losetup" for call in process.calls)


def test_a_changed_input_is_refused_before_any_package_is_installed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work = prepare(tmp_path, monkeypatch)
    (work / "Ubuntu.iso").write_bytes(b"tampered")
    ports, process = bundle(tmp_path)

    with pytest.raises(errors.Refusal) as raised:
        ventoy_unit.run(ports, arguments={"work": str(work)})

    assert raised.value.reason is refusals.RefusalReason.FIXTURE_REQUEST_MALFORMED
    assert all(call.arguments[0] != "dnf5" for call in process.calls)
