"""Extent sharing that answers the way the kernel does, from the bytes and nothing else.

It reads both files to decide between identical and differing, records every request, and
never changes a file, which is also what the real call promises about content.
"""

from __future__ import annotations

import dataclasses

from apex.kernel import claims, errors, safepaths
from apex.model import extents
from apex.ports import extents as extent_port


@dataclasses.dataclass(frozen=True, slots=True)
class Shared:
    source: safepaths.SafePath
    target: safepaths.SafePath
    span: extents.DedupeRange


class FakeExtents(extent_port.ExtentPort):
    environment = claims.EnvironmentKind.SIMULATED

    def __init__(self, *, supported: bool = True) -> None:
        self._supported = supported
        self.requests: list[Shared] = []

    def share(
        self, source: safepaths.SafePath, target: safepaths.SafePath, span: extents.DedupeRange
    ) -> extents.DedupeOutcome:
        self.requests.append(Shared(source, target, span))
        if not self._supported:
            raise errors.PortFailure(port="extents", cause="Operation not supported")
        try:
            with source.path.open("rb") as left, target.path.open("rb") as right:
                left.seek(span.offset)
                right.seek(span.offset)
                same = left.read(span.length) == right.read(span.length)
        except OSError as error:
            raise errors.PortFailure(port="extents", cause=str(error)) from error
        if same:
            return extents.DedupeOutcome(bytes_deduped=span.length, status=extents.SAME_DATA)
        return extents.DedupeOutcome(bytes_deduped=0, status=extents.DIFFERS)
