"""A QCOW2 disk and everything it is layered over, checked link by link.

`inspect` walks the chain the way the hypervisor will: every link is a regular file below the
runtime root in qcow2 format, and a link already seen is a cycle. The result is the only kind
of disk the machine context attaches, so a disk that was not walked cannot be attached.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from apex.config import defaults
from apex.kernel import commands, errors, quantities, refusals, safepaths
from apex.ports import portset

QEMU_IMG = "qemu-img"
QCOW2 = "qcow2"
FORMAT_KEY = "format"
BACKING_KEY = "backing-filename"


@dataclasses.dataclass(frozen=True, slots=True)
class BackingChain:
    """The disk first, its base last. A standalone disk is a chain of one."""

    links: tuple[safepaths.SafePath, ...]

    @property
    def disk(self) -> safepaths.SafePath:
        return self.links[0]

    @property
    def base(self) -> safepaths.SafePath:
        return self.links[-1]

    @property
    def standalone(self) -> bool:
        return len(self.links) == 1


def inspect(
    ports: portset.HostPorts, candidate: Path, *, root: safepaths.RuntimeRoot
) -> BackingChain:
    links: list[safepaths.SafePath] = []
    current = candidate
    while True:
        link = safepaths.SafePath.regular_file(current, within=root)
        if link in links:
            raise errors.Refusal(
                refusals.RefusalReason.DISK_CHAIN_CYCLE,
                subject=f"{link} is its own ancestor",
            )
        links.append(link)
        description = _describe(ports, link)
        if description.get(FORMAT_KEY) != QCOW2:
            raise errors.Refusal(
                refusals.RefusalReason.DISK_NOT_QCOW2,
                subject=f"{link} is {description.get(FORMAT_KEY)}",
            )
        backing = description.get(BACKING_KEY)
        if not backing:
            return BackingChain(tuple(links))
        current = link.path.parent / str(backing)


def require_standalone(chain: BackingChain) -> BackingChain:
    if not chain.standalone:
        raise errors.Refusal(
            refusals.RefusalReason.DISK_NOT_STANDALONE,
            subject=f"{chain.disk} is layered over {chain.base}",
            remedy="a base image must not reference another host file",
        )
    return chain


def overlay(
    ports: portset.HostPorts,
    base: BackingChain,
    *,
    into: safepaths.SafePath,
    root: safepaths.RuntimeRoot,
    size: quantities.Gib | None = None,
) -> BackingChain:
    """A fresh copy-on-write layer over `base`, so a guest never writes to the base.

    Given a size, the layer is that large and the guest sees the base grown to it, which
    is how the builder's disk is made bigger than the cloud image it starts from.
    """
    if ports.files.exists(into):
        raise errors.Refusal(
            refusals.RefusalReason.DISK_OVERLAY_EXISTS,
            subject=str(into),
            remedy="a run writes each overlay once; choose a fresh run directory",
        )
    argv = commands.Argv.of(QEMU_IMG, "create", "-f", QCOW2, "-F", QCOW2, "-b", base.disk, into)
    created = ports.processes.run(
        argv if size is None else argv.extended(f"{size.value}G"),
        deadline=defaults.IMAGE_TOOL_DEADLINE,
        limit=commands.OutputLimit.default(),
    )
    if not created.succeeded:
        raise errors.PortFailure(port=QEMU_IMG, cause=created.stderr.decode(errors="replace"))
    return inspect(ports, into.path, root=root)


def _describe(ports: portset.HostPorts, link: safepaths.SafePath) -> dict[str, object]:
    completed = ports.processes.run(
        commands.Argv.of(QEMU_IMG, "info", "--output=json", link),
        deadline=defaults.IMAGE_TOOL_DEADLINE,
        limit=commands.OutputLimit.default(),
    )
    if not completed.succeeded:
        raise errors.PortFailure(
            port=QEMU_IMG, cause=completed.stderr.decode(errors="replace").strip()
        )
    try:
        loaded = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise errors.PortFailure(port=QEMU_IMG, cause=f"{link}: {error.msg}") from error
    if not isinstance(loaded, dict):
        raise errors.PortFailure(port=QEMU_IMG, cause=f"{link}: not an object")
    return loaded
