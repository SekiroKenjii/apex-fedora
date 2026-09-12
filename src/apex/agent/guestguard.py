"""Which guest a probe is running in, refused before the first observation.

A probe reads a machine and says what it saw, so the one thing it must never do is read the
operator's laptop and file that as a virtual observation. Every guard here asks the same
question the older script asked, through the ports, and refuses with the same strictness.
"""

from __future__ import annotations

import os
from pathlib import Path

from apex.agent import agentports
from apex.config import defaults
from apex.kernel import commands, errors, refusals, safepaths

ROOT_USER = 0
CMDLINE = safepaths.SafePath(Path("/proc/cmdline"))


def refuse(detail: str) -> errors.Refusal:
    return errors.Refusal(
        refusals.RefusalReason.PROBE_ENVIRONMENT_UNEXPECTED,
        subject=detail,
        remedy="a probe runs only inside the disposable guest it was written for",
    )


def require_root() -> None:
    if os.geteuid() != ROOT_USER:
        raise refuse("not running as root")


def require_virtual(ports: agentports.AgentPorts) -> None:
    completed = ports.processes.run(
        commands.Argv.of("systemd-detect-virt", "--vm"),
        deadline=defaults.PROBE_DEADLINE,
        limit=commands.OutputLimit.default(),
    )
    if not completed.succeeded:
        raise refuse("systemd-detect-virt does not report a virtual machine")
    if completed.stdout.decode(errors="replace").strip() not in defaults.VIRTUALISERS:
        raise refuse("not a QEMU virtual machine")


def require_virtual_root(ports: agentports.AgentPorts) -> None:
    require_root()
    require_virtual(ports)


def require_live(ports: agentports.AgentPorts) -> None:
    """Root, virtual, and booted from the live medium: the older script's three conditions."""
    require_virtual_root(ports)
    cmdline = ports.files.read_bytes(CMDLINE, limit=defaults.DOCUMENT_LIMIT.value)
    if defaults.LIVE_ROOT_TOKEN not in cmdline.decode(errors="replace").split():
        raise refuse("the kernel command line does not name the live medium")


def require_initramfs(ports: agentports.AgentPorts) -> None:
    """A live guest stopped at its pre-mount breakpoint, before the guard has ever failed."""
    require_live(ports)
    if not ports.files.exists(safepaths.SafePath(Path(defaults.INITRD_RELEASE))):
        raise refuse("not in the initramfs")
    mounts = ports.files.read_bytes(
        safepaths.SafePath(Path(defaults.MOUNTS)), limit=defaults.DOCUMENT_LIMIT.value
    )
    for line in mounts.decode(errors="replace").splitlines():
        fields = line.split()
        if len(fields) > 1 and fields[1] == defaults.SYSROOT:
            raise refuse("the root filesystem is already mounted")
    if ports.files.exists(safepaths.SafePath(Path(defaults.PROTECTION_LATCH))):
        raise refuse("the protection latch is already set")
