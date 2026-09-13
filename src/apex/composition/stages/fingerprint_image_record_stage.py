"""Write the fingerprint image's record once its output verifies against the development key.

The guest signs what it made with the builder's development key; the host verifies the
output against the copy of that key it fetched over the builder's own channel, and the
record says PASS only when the signed inventory holds and the frozen digest it names is
what the image document says. The verification is kept beside the record either way.
"""

from __future__ import annotations

from apex.composition import exports, keys
from apex.composition.stages import fingerprint_inputs_stage, record_result_stage
from apex.config import defaults
from apex.kernel import encoding, errors, identifiers
from apex.model import builds
from apex.pipeline import effects, stages
from apex.ports import portset
from apex.trust import verifying

NOT_TESTED = "NOT TESTED"


def _verified(
    context: stages.RunContext[portset.HostPorts],
) -> tuple[encoding.Document | None, str]:
    root = context.facts[keys.RUNTIME_ROOT]
    location = verifying.BundleLocation(
        root=root,
        relative=f"{defaults.EXPORT_DIRECTORY}/{context.facts[keys.RUN_ID]}/{builds.OUTPUT_DIRECTORY}",
    )
    try:
        verified = verifying.verify_bundle(
            context.ports,
            location=location,
            anchor=fingerprint_inputs_stage.development_anchor(root),
        )
    except (errors.Refusal, errors.PortFailure) as problem:
        return None, str(problem)
    return {
        "status": str(builds.BuildStatus.PASS),
        "digest": str(verified.digest),
        "purpose": verified.manifest.purpose,
        "files_verified": verified.files_verified,
        "bootc_update_policy": NOT_TESTED,
        "ready_to_install": False,
    }, ""


def apply(context: stages.RunContext[portset.HostPorts]) -> stages.StageResult:
    guest_passed = context.facts[keys.BUILD_RUN].succeeded and context.facts[keys.RETRIEVED]
    report, why = _verified(context) if guest_passed else (None, "the guest build failed")
    record = record_result_stage.write_record(context, passed=report is not None)
    verification: encoding.Document = report or {"status": str(record.status), "reason": why}
    context.ports.files.write_atomic(
        exports.inside(
            context.facts[keys.RUNTIME_ROOT],
            context.facts[keys.RUN_ID],
            defaults.FINGERPRINT_VERIFICATION_NAME,
        ),
        encoding.canonical(verification) + b"\n",
        mode=defaults.RECORD_MODE,
    )
    if not guest_passed:
        return record_result_stage.failed_guest(context)
    if report is None:
        return stages.Fail(cause=f"the image output did not verify: {why}")
    return stages.Advance(facts={keys.BUILD_RECORD: record, keys.FINGERPRINT_REPORT: report})


STAGE = stages.SimpleStage(
    id=identifiers.StageId("fingerprint.image-record"),
    reads=(
        keys.BUILD_RUN,
        keys.RETRIEVED,
        keys.KIND,
        keys.BUILD_PROFILE,
        keys.SOURCE_BUNDLE,
        keys.REMOTE,
        keys.PARENT,
        keys.ACCESS,
        keys.FINGERPRINT_REQUEST,
        keys.RUNTIME_ROOT,
        keys.RUN_ID,
    ),
    writes=(keys.BUILD_RECORD, keys.FINGERPRINT_REPORT),
    attests=frozenset(),
    effects=frozenset({effects.Effect.WRITES_RUNTIME, effects.Effect.READS_HOST}),
    preflight=stages.always_ready,
    apply=apply,
)
