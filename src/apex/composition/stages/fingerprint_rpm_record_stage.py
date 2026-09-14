"""Write the package build's record with the host's own verdict on the guest's report.

A guest build that passed is a passed package build only once the host has bound the
report to the checkout's lock and patches and digested every inventoried artifact; the
record says PASS only then, and the verification it rests on is kept beside it either way.
"""

from __future__ import annotations

from apex.composition import artifactchecks, exports, fingerprintpackages, keys
from apex.composition.stages import record_result_stage
from apex.config import defaults
from apex.kernel import encoding, errors, identifiers
from apex.pipeline import effects, stages
from apex.ports import portset


def _verified(
    context: stages.RunContext[portset.HostPorts],
) -> tuple[encoding.Document | None, str]:
    """The bound report and no reason, or nothing and why the report was not accepted."""
    root = context.facts[keys.RUNTIME_ROOT]
    repository = context.facts[keys.REPOSITORY]
    home = exports.inside(root, context.facts[keys.RUN_ID], exports.OUTPUT)
    try:
        lock = fingerprintpackages.load_lock(repository)
        document = encoding.parse_object(
            context.ports.files.read_bytes(
                home / defaults.RESULTS_NAME, limit=defaults.DOCUMENT_LIMIT.value
            )
        )
        report = fingerprintpackages.parse_rpm_report(
            document, lock, fingerprintpackages.patch_digests(context.ports, repository, lock)
        )
        artifactchecks.require_artifacts(context.ports, root, home, report.artifacts)
    except (errors.Refusal, errors.PortFailure, ValueError) as problem:
        return None, str(problem)
    return report.document, ""


def apply(context: stages.RunContext[portset.HostPorts]) -> stages.StageResult:
    guest_passed = context.facts[keys.BUILD_RUN].succeeded and context.facts[keys.RETRIEVED]
    report, why = _verified(context) if guest_passed else (None, "the guest build failed")
    record = record_result_stage.write_record(context, passed=report is not None)
    artifacts = report.get("artifacts") if report is not None else None
    verification: encoding.Document = {
        "status": str(record.status),
        "reason": why,
        "artifacts": len(artifacts) if isinstance(artifacts, dict) else 0,
        "ready_to_install": False,
    }
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
        return stages.Fail(cause=f"the package report was not accepted: {why}")
    return stages.Advance(facts={keys.BUILD_RECORD: record, keys.FINGERPRINT_REPORT: report})


STAGE = stages.SimpleStage(
    id=identifiers.StageId("fingerprint.rpm-record"),
    reads=(
        keys.BUILD_RUN,
        keys.RETRIEVED,
        keys.KIND,
        keys.BUILD_PROFILE,
        keys.SOURCE_BUNDLE,
        keys.REMOTE,
        keys.PARENT,
        keys.ACCESS,
        keys.REPOSITORY,
        keys.RUNTIME_ROOT,
        keys.RUN_ID,
    ),
    writes=(keys.BUILD_RECORD, keys.FINGERPRINT_REPORT),
    attests=frozenset(),
    effects=frozenset({effects.Effect.WRITES_RUNTIME, effects.Effect.READS_HOST}),
    preflight=stages.always_ready,
    apply=apply,
)
