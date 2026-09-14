"""Derive a disk, either the installed QCOW2 or the installer, from a frozen image build."""

from __future__ import annotations

from apex.composition import buildplan
from apex.kernel import errors, identifiers, refusals, safepaths
from apex.model import builds
from apex.pipeline import runner
from apex.ports import guestshell, portset

NAME = "build-disk-artifact"
PLAN = buildplan.plan(NAME)
KINDS = frozenset({builds.ArtifactKind.QCOW2, builds.ArtifactKind.INSTALLER})


def derive(
    ports: portset.HostPorts,
    *,
    repository: safepaths.SourceRoot,
    runtime_root: safepaths.RuntimeRoot,
    builder: guestshell.GuestTarget,
    kind: builds.ArtifactKind,
    parent: identifiers.BuildId,
    test_access: bool = False,
) -> runner.Outcome:
    if kind not in KINDS:
        raise errors.Refusal(
            refusals.RefusalReason.BUILD_PARENT_REQUIRED,
            subject=f"{kind} is not a disk artifact",
            remedy="this recipe derives qcow2 and installer artifacts",
        )
    return buildplan.run(
        PLAN,
        ports,
        repository=repository,
        runtime_root=runtime_root,
        builder=builder,
        profile=builds.Profile.FEDORA,
        kind=kind,
        parent=parent,
        test_access=test_access,
    )
