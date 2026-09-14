"""Lay the update fixture's work directory out in the builder, file by file.

The fixture unit reads the target document, the grub repair script and the reviewed retry
preset under a directory named for its run; the host sends each by name and nothing else.
"""

from __future__ import annotations

from apex.composition import exports
from apex.composition import keys as composition_keys
from apex.config import defaults
from apex.kernel import identifiers, safepaths
from apex.model import builds
from apex.pipeline import effects, stages
from apex.ports import portset
from apex.verification import verifykeys, workdirs


def apply(context: stages.RunContext[portset.HostPorts]) -> stages.StageResult:
    root = context.facts[composition_keys.RUNTIME_ROOT]
    run = context.facts[composition_keys.RUN_ID]
    repository = context.facts[composition_keys.REPOSITORY]
    work = safepaths.RemotePath(f"{defaults.UPDATE_WORK_PREFIX}{run}")
    deliveries = (
        (exports.inside(root, run, builds.TARGET_DOCUMENT), work.joined(builds.TARGET_DOCUMENT)),
        (
            safepaths.SafePath(repository.path / defaults.GRUB_REPAIR_PATH),
            work.joined(defaults.GRUB_REPAIR_PATH),
        ),
        (
            safepaths.SafePath(repository.path / defaults.RETRY_PRESET_PATH),
            work.joined(defaults.RETRY_PRESET_PATH),
        ),
    )
    return workdirs.deliver(context, work, deliveries)


STAGE = stages.SimpleStage(
    id=identifiers.StageId("update.work"),
    reads=(
        verifykeys.GUEST,
        verifykeys.AGENT,
        verifykeys.TARGET,
        composition_keys.REPOSITORY,
        composition_keys.RUNTIME_ROOT,
        composition_keys.RUN_ID,
    ),
    writes=(verifykeys.WORK,),
    attests=frozenset(),
    effects=frozenset({effects.Effect.REMOTE_EXEC}),
    preflight=stages.always_ready,
    apply=apply,
)
