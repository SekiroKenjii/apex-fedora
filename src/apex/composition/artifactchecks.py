"""Every artifact a guest's report lists, verified where it landed against the listed digest."""

from __future__ import annotations

from collections.abc import Mapping

from apex.kernel import errors, refusals, safepaths
from apex.ports import portset


def require_artifacts(
    ports: portset.HostPorts,
    root: safepaths.RuntimeRoot,
    home: safepaths.SafePath,
    artifacts: Mapping[str, str],
) -> None:
    for relative, expected in artifacts.items():
        try:
            found = ports.digests.file(
                safepaths.SafePath.regular_file(home.path / relative, within=root)
            )
        except (errors.Refusal, errors.PortFailure) as problem:
            raise errors.Refusal(
                refusals.RefusalReason.ARTIFACT_CHECKSUM_MISMATCH, subject=f"{relative}: {problem}"
            ) from problem
        if found.hex != expected:
            raise errors.Refusal(
                refusals.RefusalReason.ARTIFACT_CHECKSUM_MISMATCH,
                subject=f"{relative}: differs from the transferred report",
            )
