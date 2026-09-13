"""The rewrite on Linux: one descriptor, opened without following links, identity checked."""

from __future__ import annotations

import os
import stat

from apex.kernel import claims, errors, refusals, safepaths
from apex.ports import blockdevices, files

FLAGS = os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC


class LinuxBlockDevices(blockdevices.BlockDevicePort):
    environment = claims.EnvironmentKind.BUILD

    def rewrite(
        self, node: safepaths.SafePath, *, expected: files.DeviceNumber, offset: int, length: int
    ) -> blockdevices.Rewrite:
        try:
            descriptor = os.open(node.path, FLAGS)
        except OSError as error:
            raise errors.PortFailure(port="blocks", cause=f"{node}: {error.strerror}") from error
        try:
            _require_identity(node, os.fstat(descriptor), expected)
            before = _read(node, descriptor, offset=offset, length=length)
            written: int | None = None
            error_number: int | None = None
            try:
                written = os.pwrite(descriptor, before, offset)
            except OSError as error:
                error_number = error.errno
            after = _read(node, descriptor, offset=offset, length=length)
        finally:
            os.close(descriptor)
        return blockdevices.Rewrite(
            before=before, after=after, written=written, error_number=error_number
        )


def _require_identity(
    node: safepaths.SafePath, info: os.stat_result, expected: files.DeviceNumber
) -> None:
    found = files.DeviceNumber(os.major(info.st_rdev), os.minor(info.st_rdev))
    if not stat.S_ISBLK(info.st_mode) or found != expected:
        raise errors.Refusal(
            refusals.RefusalReason.DEVICE_IDENTITY_MISMATCH,
            subject=f"{node} is not block device {expected.rendered}",
            remedy="take the snapshot again; the node changed under the fault",
        )


def _read(node: safepaths.SafePath, descriptor: int, *, offset: int, length: int) -> bytes:
    data = os.pread(descriptor, length, offset)
    if len(data) != length:
        raise errors.PortFailure(
            port="blocks", cause=f"{node}: read {len(data)} of {length} bytes at {offset}"
        )
    return data
