"""The builder's disk is compacted only after every check, and a kept copy is finalised the
same way; a refusal at any step leaves both files where they were with a report that says why."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest

from apex.adapters.fakes import fake_files, fake_process
from apex.config import defaults, loader
from apex.kernel import errors, identifiers, quantities, refusals, safepaths
from apex.model import machines
from apex.ports import portset
from apex.provisioning import compacting, leases

VIRTUAL_SIZE = 160 * 1024**3
ORIGINAL = b"original builder bytes"
COMPRESSED = b"compressed"
RUN = f"{1:032x}"


class Converting(fake_process.ScriptedProcess):
    """Answers every image tool call, and lets a conversion leave its copy on the disk."""

    def __init__(self, filesystem: fake_files.MemoryFiles, source: Path, target: Path) -> None:
        self.filesystem = filesystem
        self.source, self.target = source, target
        info = json.dumps({"format": "qcow2", "virtual-size": VIRTUAL_SIZE}).encode()
        chain = json.dumps(
            [{"format": "qcow2", "filename": str(source), "virtual-size": VIRTUAL_SIZE}]
        ).encode()
        super().__init__(
            {
                ("qemu-img", "--version"): fake_process.Reply(stdout=b"qemu-img version 10.0\n"),
                ("qemu-img", "info", "--output=json", str(source)): fake_process.Reply(stdout=info),
                ("qemu-img", "info", "--output=json", "--backing-chain", str(source)): (
                    fake_process.Reply(stdout=chain)
                ),
                ("qemu-img", "info", "--output=json", str(target)): fake_process.Reply(stdout=info),
                ("qemu-img", "check", "--output=json", str(source)): fake_process.Reply(),
                ("qemu-img", "check", "--output=json", str(target)): fake_process.Reply(),
                (*compacting.CONVERT, str(source), str(target)): fake_process.Reply(),
                (*compacting.COMPARE, str(source), str(target)): fake_process.Reply(),
            }
        )

    def run(self, argv: Any, **keywords: Any) -> Any:
        if tuple(argv)[:2] == ("qemu-img", "convert"):
            self.target.parent.mkdir(parents=True, exist_ok=True)
            self.target.write_bytes(COMPRESSED)
            self.filesystem.write_atomic(
                safepaths.SafePath(self.target), COMPRESSED, mode=defaults.RECORD_MODE
            )
        return super().run(argv, **keywords)


class Mirroring(fake_files.MemoryFiles):
    """Files whose writes also land on the disk, where the digest port reads them."""

    def write_atomic(
        self, path: safepaths.SafePath, payload: bytes, *, mode: quantities.FileMode
    ) -> identifiers.Digest:
        path.path.parent.mkdir(parents=True, exist_ok=True)
        path.path.write_bytes(payload)
        return super().write_atomic(path, payload, mode=mode)


@dataclasses.dataclass(frozen=True, slots=True)
class Host:
    ports: portset.HostPorts
    root: safepaths.RuntimeRoot
    files: fake_files.MemoryFiles
    processes: Converting
    source: Path
    target: Path


@pytest.fixture
def host(ports: portset.HostPorts, tmp_path: Path) -> Host:
    base = tmp_path / "runtime"
    base.mkdir(mode=0o700)
    root = safepaths.RuntimeRoot.adopt(base)
    source = base / defaults.BUILDER_DISK_NAME
    source.write_bytes(ORIGINAL)
    filesystem = Mirroring()
    filesystem.write_atomic(safepaths.SafePath(source), ORIGINAL, mode=defaults.RECORD_MODE)
    filesystem.free = quantities.Gib(20).as_bytes()
    target = base / defaults.COMPACTIONS_DIRECTORY / RUN / defaults.COMPRESSED_DISK_NAME
    processes = Converting(filesystem, source, target)
    return Host(
        ports=dataclasses.replace(ports, files=filesystem, processes=processes),
        root=root,
        files=filesystem,
        processes=processes,
        source=source,
        target=target,
    )


def settings(tmp_path: Path, *, minimum_free_gib: int = 10) -> loader.Settings:
    host_file = tmp_path / "settings.toml"
    host_file.write_text(f"[builder]\nminimum_free_gib = {minimum_free_gib}\n")
    return loader.load(host_file=host_file, environment={})


def steps(processes: fake_process.ScriptedProcess) -> list[str]:
    return [tuple(call)[1] for call in processes.calls]


def report(host: Host, relative: str) -> dict[str, Any]:
    return json.loads(host.files.read_bytes(host.root.child(relative), limit=1 << 20))


def test_a_clean_chain_is_converted_checked_compared_and_swapped_in(
    host: Host, tmp_path: Path
) -> None:
    compacted = compacting.compact(host.ports, settings(tmp_path), host.root)

    assert compacted.status == "PASS" and compacted.replacement == "COMPLETE"
    assert host.files.read_bytes(safepaths.SafePath(host.source), limit=100) == COMPRESSED
    assert not host.files.exists(safepaths.SafePath(host.target))
    assert steps(host.processes) == [
        "info",
        "--version",
        "info",
        "check",
        "convert",
        "info",
        "check",
        "compare",
    ]
    kept = report(host, f"compactions/{RUN}/result.json")
    assert kept["status"] == "PASS" and kept["replacement"] == "COMPLETE"
    assert kept["source_sha256"] != kept["compressed_sha256"]
    assert kept["before"]["identity"][str(host.source)]["links"] == 1
    assert kept["projected_free"] == compacted.projected_free
    assert host.processes.transcripts[-1].path.name == "convert.log"
    assert host.ports.locks.holder(compacting.launching.MACHINE) is None


def test_a_running_machine_refuses_before_anything_is_converted(host: Host, tmp_path: Path) -> None:
    identity = machines.VmIdentity(
        process=4242, pidfd_inode=1, boot_ticks=2, monitor_socket_inode=3
    )
    host.ports.hypervisor._alive[4242] = identity  # type: ignore[attr-defined]  # noqa: SLF001
    intent = leases.MachineIntent(
        role=machines.VmRole.BUILDER,
        run=identifiers.RunId("b" * 32),
        run_directory=host.root.child("vm-runs/b"),
        monitor=host.root.child("qmp.sock"),
        command=compacting.commands.Argv.of("qemu-system-x86_64"),
        written_at=host.ports.clock.stamp(),
        witness=compacting.launching.witness_of(host.ports, machines.VmRole.BUILDER),
    )
    leases.write_lease(
        host.ports, leases.MachineLease(intent=intent, identity=identity), root=host.root
    )

    with pytest.raises(errors.Refusal) as raised:
        compacting.compact(host.ports, settings(tmp_path), host.root)

    assert raised.value.reason is refusals.RefusalReason.MACHINE_RUNNING
    assert host.processes.calls == []


def test_a_chain_holding_a_snapshot_is_refused_with_the_reason_in_its_report(
    host: Host, tmp_path: Path
) -> None:
    host.processes.expect(
        ("qemu-img", "info", "--output=json", "--backing-chain", str(host.source)),
        fake_process.Reply(
            stdout=json.dumps(
                [{"format": "qcow2", "filename": str(host.source), "snapshots": [{}]}]
            ).encode()
        ),
    )

    with pytest.raises(errors.Refusal) as raised:
        compacting.compact(host.ports, settings(tmp_path), host.root)

    assert raised.value.reason is refusals.RefusalReason.COMPACTION_INPUT_UNSAFE
    assert "convert" not in steps(host.processes)
    kept = report(host, f"compactions/{RUN}/result.json")
    assert kept["status"] == "FAIL" and "snapshots" in kept["error"]
    assert host.source.read_bytes() == ORIGINAL


def test_a_copy_short_of_space_is_kept_and_named_for_finalising(host: Host, tmp_path: Path) -> None:
    host.files.free = quantities.Gib(5).as_bytes()

    with pytest.raises(errors.Refusal) as raised:
        compacting.compact(host.ports, settings(tmp_path), host.root)

    assert raised.value.reason is refusals.RefusalReason.COMPACTION_SPACE_INSUFFICIENT
    assert host.files.exists(safepaths.SafePath(host.target))
    assert host.files.read_bytes(safepaths.SafePath(host.source), limit=100) == ORIGINAL
    kept = report(host, f"compactions/{RUN}/result.json")
    assert kept["error"] == compacting.SHORT_OF_SPACE
    assert kept["replacement"] == "NOT PERFORMED" and kept["status"] == "FAIL"
    assert "compressed_sha256" in kept


def kept_short(host: Host, tmp_path: Path) -> None:
    host.files.free = quantities.Gib(5).as_bytes()
    with pytest.raises(errors.Refusal):
        compacting.compact(host.ports, settings(tmp_path), host.root)
    host.processes.calls.clear()


def test_a_kept_copy_is_finalised_after_every_check_again(host: Host, tmp_path: Path) -> None:
    kept_short(host, tmp_path)
    host.files.free = quantities.Gib(20).as_bytes()

    compacted = compacting.finalise(
        host.ports, settings(tmp_path), host.root, identifiers.RunId(RUN)
    )

    assert compacted.status == "PASS" and compacted.replacement == "COMPLETE"
    assert host.files.read_bytes(safepaths.SafePath(host.source), limit=100) == COMPRESSED
    assert steps(host.processes) == ["info", "info", "info", "check", "check", "compare"]
    finalised = json.loads(host.files.read_bytes(compacted.report, limit=1 << 20))
    assert finalised["previous_run"] == RUN and finalised["phase"] == "complete"
    assert compacted.report.path.parent.name.startswith("finalize-")
    assert report(host, f"compactions/{RUN}/result.json")["error"] == compacting.SHORT_OF_SPACE


def test_finalising_refuses_when_the_original_changed_and_keeps_both_files(
    host: Host, tmp_path: Path
) -> None:
    kept_short(host, tmp_path)
    host.files.free = quantities.Gib(20).as_bytes()
    host.files.write_atomic(
        safepaths.SafePath(host.source), b"rewritten", mode=defaults.RECORD_MODE
    )

    with pytest.raises(errors.Refusal) as raised:
        compacting.finalise(host.ports, settings(tmp_path), host.root, identifiers.RunId(RUN))

    assert raised.value.reason is refusals.RefusalReason.COMPACTION_STATE_CHANGED
    assert host.files.exists(safepaths.SafePath(host.target))
    assert host.files.read_bytes(safepaths.SafePath(host.source), limit=100) == b"rewritten"
    assert host.target.read_bytes() == COMPRESSED


def test_a_report_that_is_not_a_compared_copy_short_of_space_cannot_be_finalised(
    host: Host, tmp_path: Path
) -> None:
    kept_short(host, tmp_path)
    path = host.root.child(f"compactions/{RUN}/result.json")
    document = report(host, f"compactions/{RUN}/result.json")
    document["error"] = "Conversion failed"
    host.files.write_atomic(path, json.dumps(document).encode(), mode=defaults.RECORD_MODE)

    with pytest.raises(errors.Refusal) as raised:
        compacting.finalise(host.ports, settings(tmp_path), host.root, identifiers.RunId(RUN))

    assert raised.value.reason is refusals.RefusalReason.COMPACTION_RETAINED_INELIGIBLE
    assert host.processes.calls == [] or steps(host.processes) == ["info"]


def test_a_failed_comparison_keeps_both_files_and_records_the_failure(
    host: Host, tmp_path: Path
) -> None:
    host.processes.expect(
        (*compacting.COMPARE, str(host.source), str(host.target)),
        fake_process.Reply(exit_code=1, stdout=b"Content mismatch at offset 0\n"),
    )

    with pytest.raises(errors.Refusal) as raised:
        compacting.compact(host.ports, settings(tmp_path), host.root)

    assert raised.value.reason is refusals.RefusalReason.COMPACTION_VALIDATION_FAILED
    assert host.files.read_bytes(safepaths.SafePath(host.source), limit=100) == ORIGINAL
    assert host.files.exists(safepaths.SafePath(host.target))
    kept = report(host, f"compactions/{RUN}/result.json")
    assert kept["commands"][-1]["returncode"] == 1 and "compare" in kept["error"]
