"""The dedupe ioctl on Linux, over descriptors opened without following links."""

from __future__ import annotations

import fcntl
import os

from apex.kernel import claims, errors, safepaths
from apex.model import extents
from apex.ports import extents as extent_port

READ_FLAGS = os.O_RDONLY | os.O_NOATIME | os.O_NOFOLLOW
WRITE_FLAGS = os.O_RDWR | os.O_NOATIME | os.O_NOFOLLOW


class LinuxExtents(extent_port.ExtentPort):
    environment = claims.EnvironmentKind.BUILD

    def share(
        self, source: safepaths.SafePath, target: safepaths.SafePath, span: extents.DedupeRange
    ) -> extents.DedupeOutcome:
        try:
            reader = os.open(source.path, READ_FLAGS)
        except OSError as error:
            raise errors.PortFailure(port="extents", cause=str(error)) from error
        try:
            writer = os.open(target.path, WRITE_FLAGS)
        except OSError as error:
            os.close(reader)
            raise errors.PortFailure(port="extents", cause=str(error)) from error
        try:
            buffer = extents.request_buffer(span, writer)
            fcntl.ioctl(reader, extents.FIDEDUPERANGE, buffer, True)
            os.fsync(writer)
        except OSError as error:
            raise errors.PortFailure(port="extents", cause=str(error)) from error
        finally:
            os.close(writer)
            os.close(reader)
        return extents.outcome_of(buffer)
