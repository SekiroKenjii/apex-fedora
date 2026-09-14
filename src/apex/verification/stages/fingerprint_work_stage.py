"""Lay the fingerprint test's work directory out in the builder, file by file.

The older host packed the checkout and unpacked it in the builder; here only what the unit
reads is sent, each file by name under the work directory the unit expects: the pinned
upstream tests, the reviewed lock beside them, and the target document. The guest never
receives a host path to open.
"""

from __future__ import annotations

from apex.composition import exports
from apex.composition import keys as composition_keys
from apex.config import defaults
from apex.kernel import identifiers, safepaths
from apex.model import builds
from apex.pipeline import effects, stages
from apex.ports import portset
from apex.trust import testsources
from apex.verification import verifykeys, workdirs

LOCK = f"{defaults.FINGERPRINT_LOCK_DIRECTORY}/{defaults.FINGERPRINT_LOCK_NAME}"


def apply(context: stages.RunContext[portset.HostPorts]) -> stages.StageResult:
    root = context.facts[composition_keys.RUNTIME_ROOT]
    run = context.facts[composition_keys.RUN_ID]
    work = safepaths.RemotePath(f"{defaults.FINGERPRINT_WORK_PREFIX}{run}")
    deliveries = [
        *(
            (
                testsources.sources_directory(root) / item.name,
                work.joined(f"{defaults.FINGERPRINT_SOURCES_NAME}/{item.name}"),
            )
            for item in context.facts[verifykeys.TEST_SOURCES].files
        ),
        (testsources.lock_copy(root), work.joined(LOCK)),
        (exports.inside(root, run, builds.TARGET_DOCUMENT), work.joined(builds.TARGET_DOCUMENT)),
    ]
    return workdirs.deliver(context, work, deliveries)


STAGE = stages.SimpleStage(
    id=identifiers.StageId("fingerprint.work"),
    reads=(
        verifykeys.GUEST,
        verifykeys.AGENT,
        verifykeys.TEST_SOURCES,
        verifykeys.TARGET,
        composition_keys.RUNTIME_ROOT,
        composition_keys.RUN_ID,
    ),
    writes=(verifykeys.WORK,),
    attests=frozenset(),
    effects=frozenset({effects.Effect.REMOTE_EXEC}),
    preflight=stages.always_ready,
    apply=apply,
)
