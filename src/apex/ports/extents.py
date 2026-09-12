"""Asking the kernel to share identical extents between two files.

Only the guest implements this, on the builder's copy-on-write scratch. The port is one call,
one range at a time, so a caller that submits a range the kernel rejects learns which one.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Protocol

from apex.kernel import claims, safepaths
from apex.model import extents


class ExtentPort(Protocol):
    environment: claims.EnvironmentKind

    @abstractmethod
    def share(
        self, source: safepaths.SafePath, target: safepaths.SafePath, span: extents.DedupeRange
    ) -> extents.DedupeOutcome:
        """Share `span` of `source` into `target`. A differing range is an outcome, not a
        failure; a filesystem that cannot share is a port failure."""
        ...
