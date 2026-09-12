"""Write the run's record, then fail the run if the guest did.

The record lands before the verdict so a failed build is never mistaken for one that did
not happen. A partial output is never a candidate; the record says FAIL and the log stays.
"""

from __future__ import annotations

from apex.composition import exports, keys
from apex.config import defaults
from apex.kernel import encoding, identifiers
from apex.model import builds
from apex.pipeline import effects, stages
from apex.ports import portset


def apply(context: stages.RunContext[portset.HostPorts]) -> stages.StageResult:
    completed = context.facts[keys.BUILD_RUN]
    passed = completed.succeeded and context.facts[keys.RETRIEVED]
    record = builds.BuildRecord(
        status=builds.BuildStatus.PASS if passed else builds.BuildStatus.FAIL,
        kind=context.facts[keys.KIND],
        profile=context.facts[keys.BUILD_PROFILE],
        source=context.facts[keys.SOURCE_BUNDLE].archive_digest,
        remote=context.facts[keys.REMOTE],
        parent=context.facts[keys.PARENT],
        test_access=False,
    )
    root = context.facts[keys.RUNTIME_ROOT]
    run = context.facts[keys.RUN_ID]
    context.ports.files.write_atomic(
        exports.inside(root, run, builds.RECORD_NAME),
        encoding.canonical(record.document()) + b"\n",
        mode=defaults.RECORD_MODE,
    )
    if not passed:
        log = exports.inside(root, run, builds.BUILD_LOG)
        return stages.Fail(
            cause=f"the guest build exited with {completed.exit_code}; retained log: {log}"
        )
    return stages.Advance(facts={keys.BUILD_RECORD: record})


STAGE = stages.SimpleStage(
    id=identifiers.StageId("build.record"),
    reads=(
        keys.BUILD_RUN, keys.RETRIEVED, keys.KIND, keys.BUILD_PROFILE, keys.SOURCE_BUNDLE,
        keys.REMOTE, keys.PARENT, keys.RUNTIME_ROOT, keys.RUN_ID,
    ),
    writes=(keys.BUILD_RECORD,),
    attests=frozenset(),
    effects=frozenset({effects.Effect.WRITES_RUNTIME}),
    preflight=stages.always_ready,
    apply=apply,
)
