"""QEMU as a detached process, identified by more than its process number."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

from apex.adapters import pidfds
from apex.config import defaults
from apex.kernel import claims, errors, quantities, refusals, safepaths, timing
from apex.model import machines
from apex.ports import hypervisor

MEMINFO = Path("/proc/meminfo")
KVM_DEVICE = Path("/dev/kvm")
PROCESS_STATUS_FIELD = 0
START_TICKS_FIELD = 19
GONE_STATES = frozenset({"Z", "X"})


class QemuHypervisor:
    environment = claims.EnvironmentKind.BUILD

    def __init__(self) -> None:
        self._children: dict[int, subprocess.Popen[bytes]] = {}

    def capacity(self, root: safepaths.RuntimeRoot) -> hypervisor.HostCapacity:
        return hypervisor.HostCapacity(
            available_memory=_available_memory(),
            free_space=quantities.ByteCount(shutil.disk_usage(root.path).free),
            kvm_accessible=os.access(KVM_DEVICE, os.R_OK | os.W_OK),
        )

    def spawn(
        self,
        spec: machines.VmSpec,
        *,
        monitor: safepaths.SafePath,
        log: safepaths.SafePath,
        deadline: timing.Deadline,
    ) -> machines.VmIdentity:
        if monitor.path.exists():
            monitor.path.unlink()
        with log.path.open("ab") as handle:
            try:
                child = subprocess.Popen(  # noqa: S603
                    list(spec.render()),
                    stdin=subprocess.DEVNULL,
                    stdout=handle,
                    stderr=handle,
                    start_new_session=True,
                )
            except OSError as error:
                raise errors.PortFailure(port="hypervisor", cause=str(error)) from error
        self._children[child.pid] = child
        self._await_monitor(child, monitor, deadline, log)
        return _identity_of(child.pid, monitor)

    def _await_monitor(
        self,
        child: subprocess.Popen[bytes],
        monitor: safepaths.SafePath,
        deadline: timing.Deadline,
        log: safepaths.SafePath,
    ) -> None:
        started = time.monotonic()
        while not monitor.path.exists():
            if child.poll() is not None:
                raise errors.PortFailure(
                    port="hypervisor",
                    cause=f"{machines.QEMU_PROGRAM} exited with {child.returncode}; see {log}",
                )
            if time.monotonic() - started > deadline.budget.seconds:
                raise errors.PortFailure(
                    port="hypervisor",
                    cause=f"no monitor socket at {monitor} after {deadline.budget.seconds}s",
                )
            time.sleep(defaults.MONITOR_POLL.seconds)

    def running(self, identity: machines.VmIdentity) -> bool:
        child = self._children.get(identity.process)
        if child is not None and child.poll() is not None:
            return False
        observed = _start_ticks(identity.process)
        return observed is not None and observed == identity.boot_ticks

    def terminate(self, identity: machines.VmIdentity) -> None:
        try:
            descriptor = pidfds.open_process(identity.process)
        except OSError as error:
            raise errors.Refusal(
                refusals.RefusalReason.MACHINE_NOT_RUNNING,
                subject=f"process {identity.process}: {error.strerror}",
            ) from error
        try:
            observed = machines.VmIdentity(
                process=identity.process,
                pidfd_inode=os.fstat(descriptor).st_ino,
                boot_ticks=_start_ticks(identity.process) or 0,
                monitor_socket_inode=identity.monitor_socket_inode,
            )
            if observed != identity:
                raise errors.Refusal(
                    refusals.RefusalReason.MACHINE_IDENTITY_CHANGED,
                    subject=f"process {identity.process} is not the machine that was started",
                    remedy="the identifier was reused; nothing was signalled",
                )
            pidfds.send_signal(descriptor, signal.SIGKILL)
        finally:
            os.close(descriptor)
        child = self._children.get(identity.process)
        if child is not None:
            child.wait(timeout=defaults.REAP_DEADLINE.budget.seconds)


def _available_memory() -> quantities.Mib:
    for line in MEMINFO.read_text().splitlines():
        if line.startswith("MemAvailable:"):
            return quantities.Mib(int(line.split()[1]) // 1024)
    raise errors.PortFailure(port="hypervisor", cause=f"{MEMINFO} has no MemAvailable line")


def _start_ticks(process: int) -> int | None:
    try:
        text = Path(f"/proc/{process}/stat").read_text()
    except OSError:
        return None
    # The command name is parenthesised and may itself hold spaces or parentheses.
    fields = text.rpartition(")")[2].split()
    if fields[PROCESS_STATUS_FIELD] in GONE_STATES:
        return None
    return int(fields[START_TICKS_FIELD])


def _identity_of(process: int, monitor: safepaths.SafePath) -> machines.VmIdentity:
    descriptor = pidfds.open_process(process)
    try:
        pidfd_inode = os.fstat(descriptor).st_ino
    finally:
        os.close(descriptor)
    return machines.VmIdentity(
        process=process,
        pidfd_inode=pidfd_inode,
        boot_ticks=_start_ticks(process) or 0,
        monitor_socket_inode=monitor.path.stat().st_ino,
    )
