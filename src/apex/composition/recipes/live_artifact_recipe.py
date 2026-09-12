"""Derive the live medium from a frozen image build."""

from __future__ import annotations

from apex.composition import buildplan
from apex.kernel import identifiers, safepaths
from apex.model import builds
from apex.pipeline import runner
from apex.ports import guestshell, portset

NAME = "build-live-artifact"
PLAN = buildplan.plan(NAME)


def derive(
    ports: portset.HostPorts,
    *,
    repository: safepaths.SourceRoot,
    runtime_root: safepaths.RuntimeRoot,
    builder: guestshell.GuestTarget,
    parent: identifiers.BuildId,
) -> runner.Outcome:
    return buildplan.run(
        PLAN, ports, repository=repository, runtime_root=runtime_root, builder=builder,
        profile=builds.Profile.FEDORA, kind=builds.ArtifactKind.LIVE, parent=parent,
    )
