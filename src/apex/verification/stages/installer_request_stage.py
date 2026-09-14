"""Write what the fault will ask of which machine, before the guest is touched.

The stage reads nothing the run produces, so it is ordered first and refuses before the
agent is delivered: a second attempt on the same machine starts from a fresh one, as the
older tool demanded, and the machine has to be the one the fault was designed for, an
offline installer boot with a serial console and exactly one extra disk, so the comparison
afterwards covers the two disks it names.
"""

from __future__ import annotations

from apex.composition import keys as composition_keys
from apex.kernel import errors, identifiers, refusals, safepaths
from apex.model import machines
from apex.pipeline import effects, stages
from apex.ports import portset
from apex.provisioning import runrecord
from apex.verification import installerfault, verifykeys

TOPOLOGY = "a fresh offline installer machine with a serial console and one extra disk"


def _suitable(record: runrecord.RunRecord) -> bool:
    return (
        record.medium is machines.Medium.INSTALLER
        and record.iso is not None
        and not record.guest_ssh
        and record.serial_console
        and len(record.extras) == 1
    )


def apply(context: stages.RunContext[portset.HostPorts]) -> stages.StageResult:
    ports = context.ports
    run_directory = context.facts[verifykeys.MACHINE_RUN]
    root = context.facts[composition_keys.RUNTIME_ROOT]
    if ports.files.exists(installerfault.request_path(run_directory)):
        return stages.Refuse(
            reason=refusals.RefusalReason.FAULT_ALREADY_ATTEMPTED,
            detail="use a fresh machine for every fault, including a retry",
        )
    try:
        record = runrecord.read(ports, run_directory)
        if not _suitable(record) or record.iso is None:
            return stages.Refuse(
                reason=refusals.RefusalReason.TOPOLOGY_INCONSISTENT,
                detail=f"the fault needs {TOPOLOGY}",
            )
        image = ports.digests.file(safepaths.SafePath.regular_file(record.iso, within=root))
    except errors.Refusal as refusal:
        return stages.Refuse(reason=refusal.reason, detail=refusal.subject)
    except errors.PortFailure as failure:
        return stages.Fail(cause=failure.cause)
    request = installerfault.Request(
        case=context.facts[verifykeys.FAULT_CASE],
        image=image,
        process=context.facts[verifykeys.MACHINE_PROCESS],
        run=record.run,
    )
    installerfault.write_request(ports, run_directory, request)
    return stages.Advance(facts={verifykeys.INSTALLER_REQUEST: request})


STAGE = stages.SimpleStage(
    id=identifiers.StageId("installer.request"),
    reads=(
        verifykeys.MACHINE_RUN,
        verifykeys.MACHINE_PROCESS,
        verifykeys.FAULT_CASE,
        composition_keys.RUNTIME_ROOT,
    ),
    writes=(verifykeys.INSTALLER_REQUEST,),
    attests=frozenset(),
    effects=frozenset({effects.Effect.WRITES_RUNTIME}),
    preflight=stages.always_ready,
    apply=apply,
)
