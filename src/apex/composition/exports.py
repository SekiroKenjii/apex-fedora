"""Where one run keeps what it produced, and where the guest keeps its copy."""

from __future__ import annotations

from apex.config import defaults
from apex.kernel import identifiers, safepaths
from apex.model import builds

OUTPUT = builds.OUTPUT_DIRECTORY


def directory(root: safepaths.RuntimeRoot, run: identifiers.RunId) -> safepaths.SafePath:
    return root.child(f"{defaults.EXPORT_DIRECTORY}/{run}")


def inside(
    root: safepaths.RuntimeRoot, run: identifiers.RunId | identifiers.BuildId, name: str
) -> safepaths.SafePath:
    return root.child(f"{defaults.EXPORT_DIRECTORY}/{run}/{name}")


def output(
    root: safepaths.RuntimeRoot, run: identifiers.RunId | identifiers.BuildId
) -> safepaths.SafePath:
    """Where a run's retrieved output lives, the guest's output directory brought home."""
    return inside(root, run, OUTPUT)


def remote(run: identifiers.RunId) -> safepaths.RemotePath:
    return safepaths.RemotePath(f"{defaults.REMOTE_PREFIX}{run}")


def payload(parent: identifiers.BuildId, profile: builds.Profile) -> safepaths.RemotePath:
    """The OCI archive an earlier image build left in the guest, by its run directory."""
    return safepaths.RemotePath(
        f"{defaults.REMOTE_PREFIX}{parent}/{builds.OUTPUT_DIRECTORY}/apex-{profile}.oci.tar"
    )
