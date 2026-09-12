"""Fetching a pinned archive.

The address is https by type and the expected digest is a required argument, so a fetch
without a pin cannot be written. A mismatch keeps the partial download for inspection and
never replaces the destination.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Protocol

from apex.kernel import claims, identifiers, locators, safepaths, timing


class DownloadPort(Protocol):
    environment: claims.EnvironmentKind

    @abstractmethod
    def fetch(
        self,
        url: locators.HttpsUrl,
        *,
        into: safepaths.SafePath,
        expected: identifiers.Digest,
        deadline: timing.Deadline,
    ) -> identifiers.Digest: ...
