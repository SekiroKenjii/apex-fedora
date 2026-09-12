"""Build the OS image in the isolated builder from the screened sources."""

from __future__ import annotations

from apex.composition import buildplan
from apex.kernel import safepaths
from apex.model import builds
from apex.pipeline import runner
from apex.ports import guestshell, portset

NAME = "build-image"
PLAN = buildplan.plan(NAME)


def build(
    ports: portset.HostPorts,
    *,
    repository: safepaths.SourceRoot,
    runtime_root: safepaths.RuntimeRoot,
    builder: guestshell.GuestTarget,
    profile: builds.Profile,
) -> runner.Outcome:
    return buildplan.run(
        PLAN, ports, repository=repository, runtime_root=runtime_root, builder=builder,
        profile=profile, kind=builds.ArtifactKind.IMAGE, parent=None,
    )
