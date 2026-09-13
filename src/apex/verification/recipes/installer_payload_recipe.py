"""Damage the installer's payload in one named way and keep what the guard did about it.

The request is written beside the machine's run before the guest is asked; the fault runs
over the serial rescue shell; the report is kept beside the run for the collection that
follows once the machine is off, and retained under the verification run's exports too.
Nothing is minted: `installer.payload-rejection` is recorded by hand from six results.
"""

from __future__ import annotations

from apex.composition import keys as composition_keys
from apex.composition.stages import identify_run_stage
from apex.kernel import identifiers, safepaths
from apex.pipeline import plans, runner, stages
from apex.ports import guestshell, portset
from apex.verification import faults, installerfault, verifykeys
from apex.verification.stages import (
    deliver_agent_stage,
    fault_stage,
    installer_keep_stage,
    installer_request_stage,
    retain_report_stage,
)

NAME = "verify-installer-payload"
CASE = faults.lookup(identifiers.ProbeId("fault.installer-payload"))
CASE_ARGUMENT = "case"
KEY_ARGUMENT = "wrong_public_key"


def _arguments(context: stages.RunContext[portset.HostPorts]) -> dict[str, str]:
    return {
        CASE_ARGUMENT: context.facts[verifykeys.FAULT_CASE],
        KEY_ARGUMENT: context.facts[verifykeys.WRONG_KEY],
    }


STAGES = (
    identify_run_stage.STAGE,
    deliver_agent_stage.STAGE,
    installer_request_stage.STAGE,
    fault_stage.for_case(
        CASE,
        arguments=_arguments,
        after=(verifykeys.INSTALLER_REQUEST, verifykeys.FAULT_CASE, verifykeys.WRONG_KEY),
    ),
    installer_keep_stage.for_case(CASE),
    retain_report_stage.for_case(CASE),
)
SEEDS = frozenset(
    {
        verifykeys.GUEST,
        verifykeys.WHEEL,
        verifykeys.MACHINE_RUN,
        verifykeys.MACHINE_PROCESS,
        verifykeys.FAULT_CASE,
        verifykeys.WRONG_KEY,
        composition_keys.RUNTIME_ROOT,
    }
)
PLAN: plans.Plan[portset.HostPorts] = plans.Plan.of(NAME, STAGES, seeds=SEEDS)


def verify(  # noqa: PLR0913
    ports: portset.HostPorts,
    *,
    guest: guestshell.GuestTarget,
    wheel: safepaths.SafePath,
    root: safepaths.RuntimeRoot,
    run_directory: safepaths.SafePath,
    process: int,
    case: str,
    wrong_key: str | None,
) -> runner.Outcome:
    installerfault.require_pairing(case, wrong_key)
    return runner.run(
        PLAN,
        ports=ports,
        seeds={
            verifykeys.GUEST: guest,
            verifykeys.WHEEL: wheel,
            verifykeys.MACHINE_RUN: run_directory,
            verifykeys.MACHINE_PROCESS: process,
            verifykeys.FAULT_CASE: case,
            verifykeys.WRONG_KEY: "" if wrong_key is None else wrong_key,
            composition_keys.RUNTIME_ROOT: root,
        },
    )
