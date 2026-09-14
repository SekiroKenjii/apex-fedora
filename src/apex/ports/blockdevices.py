"""Writing a device's own bytes back to it, to learn whether the kernel lets a write through.

The one operation is the write-denial fault: read a range, write the same bytes to the same
place, read again. It happens on one descriptor whose identity was checked against the
number sysfs gave for the node, so a node renamed between the snapshot and the attempt is
refused rather than written to.
"""

from __future__ import annotations

import dataclasses
import errno
from abc import abstractmethod
from typing import Protocol

from apex.kernel import claims, safepaths
from apex.ports import files

DENIALS = frozenset({errno.EPERM, errno.EROFS})


@dataclasses.dataclass(frozen=True, slots=True)
class Rewrite:
    before: bytes
    after: bytes
    written: int | None
    error_number: int | None

    @property
    def denied(self) -> bool:
        """The kernel refused the write with the error a read-only device gives."""
        return self.error_number in DENIALS

    @property
    def unchanged(self) -> bool:
        return self.before == self.after


class BlockDevicePort(Protocol):
    environment: claims.EnvironmentKind

    @abstractmethod
    def rewrite(
        self, node: safepaths.SafePath, *, expected: files.DeviceNumber, offset: int, length: int
    ) -> Rewrite:
        """Read `length` bytes at `offset`, write them back there, read again.

        A node that is not the block device `expected` names is refused before any read.
        A write the kernel refuses is an outcome; a node that cannot be opened or read in
        full is a port failure.
        """
        ...
