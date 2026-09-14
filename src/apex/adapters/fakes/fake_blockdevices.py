"""Block devices declared to the fake, each answering a write the way it was told to."""

from __future__ import annotations

import dataclasses
import errno

from apex.kernel import claims, errors, refusals, safepaths
from apex.ports import blockdevices, files


@dataclasses.dataclass(frozen=True, slots=True)
class FakeNode:
    """A device the fake knows: its number, its bytes, and what a write meets."""

    number: files.DeviceNumber
    content: bytes
    denial: int | None = errno.EROFS
    changes_on_write: bool = False


@dataclasses.dataclass(frozen=True, slots=True)
class Attempt:
    node: str
    offset: int
    length: int


class FakeBlockDevices(blockdevices.BlockDevicePort):
    environment = claims.EnvironmentKind.SIMULATED

    def __init__(self) -> None:
        self.nodes: dict[str, FakeNode] = {}
        self.attempts: list[Attempt] = []

    def declare(self, node: safepaths.SafePath, device: FakeNode) -> None:
        self.nodes[str(node)] = device

    def rewrite(
        self, node: safepaths.SafePath, *, expected: files.DeviceNumber, offset: int, length: int
    ) -> blockdevices.Rewrite:
        self.attempts.append(Attempt(str(node), offset, length))
        device = self.nodes.get(str(node))
        if device is None or device.number != expected:
            raise errors.Refusal(
                refusals.RefusalReason.DEVICE_IDENTITY_MISMATCH,
                subject=f"{node} is not block device {expected.rendered}",
                remedy="take the snapshot again; the node changed under the fault",
            )
        before = device.content[offset : offset + length]
        if len(before) != length:
            raise errors.PortFailure(
                port="blocks", cause=f"{node}: read {len(before)} of {length} bytes at {offset}"
            )
        after = bytes([before[0] ^ 1]) + before[1:] if device.changes_on_write else before
        if device.denial is not None:
            return blockdevices.Rewrite(
                before=before, after=after, written=None, error_number=device.denial
            )
        return blockdevices.Rewrite(before=before, after=after, written=length, error_number=None)
