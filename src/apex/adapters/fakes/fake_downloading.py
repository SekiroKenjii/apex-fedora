"""Fetching from a table of served bodies, and a network that refuses to be used at all."""

from __future__ import annotations

from collections.abc import Mapping

from apex.adapters import parts
from apex.kernel import claims, errors, identifiers, locators, refusals, safepaths, timing
from apex.ports import downloading


class OfflineFetcher(downloading.DownloadPort):
    environment = claims.EnvironmentKind.SIMULATED

    def __init__(self, served: Mapping[str, bytes]) -> None:
        self._served = dict(served)
        self.fetched: list[str] = []
        self.deadlines: list[timing.Deadline] = []

    def fetch(
        self,
        url: locators.HttpsUrl,
        *,
        into: safepaths.SafePath,
        expected: identifiers.Digest,
        deadline: timing.Deadline,
    ) -> identifiers.Digest:
        self.deadlines.append(deadline)
        body = self._served.get(str(url))
        if body is None:
            raise errors.PortFailure(port="downloads", cause=f"{url}: unreachable")
        into.path.parent.mkdir(parents=True, exist_ok=True, mode=parts.PRIVATE_DIRECTORY)
        part = parts.part_of(into.path)
        part.write_bytes(body)
        self.fetched.append(str(url))
        return parts.settle(part, into.path, expected)


class RefusingNetwork(downloading.DownloadPort):
    environment = claims.EnvironmentKind.SIMULATED

    def fetch(
        self,
        url: locators.HttpsUrl,
        *,
        into: safepaths.SafePath,  # noqa: ARG002
        expected: identifiers.Digest,  # noqa: ARG002
        deadline: timing.Deadline,  # noqa: ARG002
    ) -> identifiers.Digest:
        # The port shape is kept so a caller cannot tell this apart from a fetcher until it
        # refuses; only the address is worth naming in the refusal.
        raise errors.Refusal(
            refusals.RefusalReason.NETWORK_NOT_PERMITTED,
            subject=str(url),
            remedy="this run declared no network; fetch the sources in a run that does",
        )
