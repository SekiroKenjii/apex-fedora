"""A host bundle of fakes whose members the machine tests can reach by name."""

from __future__ import annotations

import dataclasses

from apex.adapters.fakes import (
    fake_clock,
    fake_files,
    fake_hypervisor,
    fake_locking,
    fake_process,
    fake_qmp,
)
from apex.kernel import identifiers, quantities, safepaths
from apex.model import machines
from apex.ports import portset

RUN = identifiers.RunId("a" * 32)


@dataclasses.dataclass(frozen=True, slots=True)
class Host:
    ports: portset.HostPorts
    root: safepaths.RuntimeRoot
    hypervisor: fake_hypervisor.FakeQemu
    monitor: fake_qmp.ScriptedQmp
    clock: fake_clock.ManualClock
    files: fake_files.MemoryFiles
    processes: fake_process.ScriptedProcess
    locks: fake_locking.MemoryLocks

    @property
    def run_directory(self) -> safepaths.SafePath:
        return self.root.child(f"vm-runs/{RUN}")

    def spec(self, role: machines.VmRole = machines.VmRole.TEST) -> machines.VmSpec:
        return machines.VmSpec.build(
            role=role,
            resources=machines.VmResources(memory=quantities.Mib(4096), processors=4),
            root_disk=self._present("disk.qcow2"),
            firmware=machines.Firmware(
                code=self._present("code.fd"), variables=self._present("vars.fd")
            ),
            monitor=machines.MonitorSocket(self.root.child("qmp.sock")),
            serial=machines.SerialFile(self.root.child("serial.log")),
        )

    def _present(self, name: str) -> safepaths.SafePath:
        target = self.root.path / name
        target.write_bytes(b"")
        return safepaths.SafePath.regular_file(target, within=self.root)
