"""One of six damages to the bundled payload, which the guard must refuse before Anaconda."""

from __future__ import annotations

from apex.kernel import claims, identifiers
from apex.verification import faulting, faults

faults.declare(
    faulting.FaultCase(
        unit=identifiers.ProbeId("fault.installer-payload"),
        environment=claims.EnvironmentKind.VM,
        summary=(
            "In the offline installer guest at its diagnostic target, one named damage is done "
            "to the payload with a byte-for-byte backup, the production entry point is run, "
            "and a pass is its refusal before Anaconda with no storage touched."
        ),
        arguments={"case": "", "wrong_public_key": ""},
    )
)
