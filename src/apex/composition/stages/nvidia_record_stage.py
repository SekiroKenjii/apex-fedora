"""Write the NVIDIA run's record with the host's own verdict on the guest's report.

A guest build that passed is not a passed NVIDIA build until the host has bound the
report to the image, the lock and the package set it asked for; the record says PASS only
then, and the verification it rests on is kept beside it either way.
"""

from __future__ import annotations

from apex.composition import exports, keys, nvidialock
from apex.composition.stages import record_result_stage
from apex.config import defaults
from apex.kernel import encoding, errors, identifiers
from apex.model import builds
from apex.pipeline import effects, stages
from apex.ports import portset


def _verified(
    context: stages.RunContext[portset.HostPorts],
) -> tuple[encoding.Document | None, str]:
    """The bound report and no reason, or nothing and why the report was not accepted."""
    frozen = context.facts[keys.FROZEN]
    if frozen is None:
        return None, "no frozen image to bind the report to"
    home = exports.inside(
        context.facts[keys.RUNTIME_ROOT],
        context.facts[keys.RUN_ID],
        f"{builds.OUTPUT_DIRECTORY}/{defaults.NVIDIA_OUTPUT_DIRECTORY}",
    )
    try:
        report = nvidialock.verify_report(
            context.ports,
            context.facts[keys.RUNTIME_ROOT],
            home,
            frozen=frozen,
            lock=context.facts[keys.NVIDIA_LOCK],
        )
    except errors.Refusal as refusal:
        return None, str(refusal)
    return report, ""


def apply(context: stages.RunContext[portset.HostPorts]) -> stages.StageResult:
    guest_passed = context.facts[keys.BUILD_RUN].succeeded and context.facts[keys.RETRIEVED]
    report, why = _verified(context) if guest_passed else (None, "the guest build failed")
    record = record_result_stage.write_record(context, passed=report is not None)
    verification: encoding.Document = {
        "status": str(record.status),
        "reason": why,
        "parent_build": str(context.facts[keys.PARENT]),
        "ready_to_install": False,
    }
    context.ports.files.write_atomic(
        exports.inside(
            context.facts[keys.RUNTIME_ROOT],
            context.facts[keys.RUN_ID],
            defaults.NVIDIA_VERIFICATION_NAME,
        ),
        encoding.canonical(verification) + b"\n",
        mode=defaults.RECORD_MODE,
    )
    if not guest_passed:
        return record_result_stage.failed_guest(context)
    if report is None:
        return stages.Fail(cause=f"the NVIDIA report was not accepted: {why}")
    return stages.Advance(facts={keys.BUILD_RECORD: record, keys.NVIDIA_REPORT: report})


STAGE = stages.SimpleStage(
    id=identifiers.StageId("nvidia.record"),
    reads=(
        keys.BUILD_RUN,
        keys.RETRIEVED,
        keys.KIND,
        keys.BUILD_PROFILE,
        keys.SOURCE_BUNDLE,
        keys.REMOTE,
        keys.PARENT,
        keys.ACCESS,
        keys.FROZEN,
        keys.NVIDIA_LOCK,
        keys.RUNTIME_ROOT,
        keys.RUN_ID,
    ),
    writes=(keys.BUILD_RECORD, keys.NVIDIA_REPORT),
    attests=frozenset(),
    effects=frozenset({effects.Effect.WRITES_RUNTIME}),
    preflight=stages.always_ready,
    apply=apply,
)
