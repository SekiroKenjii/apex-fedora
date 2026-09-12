"""fprintd's cleanup after vanished and disconnected clients, over an upstream virtual device."""

from __future__ import annotations

from apex.kernel import claims, identifiers
from apex.verification import faulting, faults

faults.declare(
    faulting.FaultCase(
        unit=identifiers.ProbeId("fault.fingerprint-cleanup"),
        environment=claims.EnvironmentKind.BUILD,
        summary=(
            "The target image's fprintd and libfprint are installed on the isolated builder "
            "with the test dependencies, the pinned upstream tests the host fetched are "
            "checked against the reviewed lock, and the verbatim harness runs as the "
            "unprivileged builder: a client that vanishes, disconnects during or after "
            "enrolment, or fails with a protocol error must leave the virtual device "
            "claimable, and a second client must be refused while the first still owns it."
        ),
        arguments={"work": ""},
    )
)
