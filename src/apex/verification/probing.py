"""Asking a guest for one observation and holding the answer as proof.

The host does not judge the answer here. It carries the whole reply, canonically encoded, so
the bytes that reach the store are the bytes the guest sent, and a reader can re-run the
same judgement over the same document later.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping

from apex.attestation import minting
from apex.composition import agentrun
from apex.kernel import claims, encoding, errors, identifiers
from apex.ports import guestshell, portset

REPORT_KIND = ".json"


@dataclasses.dataclass(frozen=True, slots=True)
class ProbeCase:
    """One question a guest can be asked, and where it must be standing to be asked.

    The isolated builder is a guest too, so the build environment is a place a probe can
    stand; a simulation and the operator's own machine are not.
    """

    unit: identifiers.ProbeId
    environment: claims.EnvironmentKind
    summary: str
    arguments: Mapping[str, encoding.JsonValue] = dataclasses.field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.environment in {claims.EnvironmentKind.SIMULATED, claims.EnvironmentKind.OPERATOR}:
            raise errors.RegistrationError(
                f"{self.unit}: a probe observes a guest, and {self.environment} is not one"
            )
        if not self.summary:
            raise errors.RegistrationError(f"{self.unit}: say what the probe observes")


@dataclasses.dataclass(frozen=True, slots=True)
class Observation:
    case: ProbeCase
    observations: encoding.Document
    proof: minting.Offered


def observe(
    ports: portset.HostPorts,
    target: guestshell.GuestTarget,
    install: agentrun.AgentInstall,
    case: ProbeCase,
    *,
    token: identifiers.Token,
) -> Observation:
    reply = agentrun.run_unit(
        ports, target, install, unit=case.unit, arguments=case.arguments, token=token
    )
    return Observation(
        case=case,
        observations=reply.observations,
        proof=minting.Offered(payload=encoding.canonical(reply.document()), kind=REPORT_KIND),
    )
