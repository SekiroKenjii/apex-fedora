"""The real signature checks over a synthetic image, every negative refused for its reason."""

from __future__ import annotations

from apex.kernel import claims, identifiers
from apex.verification import faulting, faults

faults.declare(
    faulting.FaultCase(
        unit=identifiers.ProbeId("fault.installer-trust"),
        environment=claims.EnvironmentKind.BUILD_CONTAINER,
        summary=(
            "A scratch image is built and signed with a fixture key in the isolated builder, "
            "copied under the policy the trust contract implies and opened through the "
            "installer's own proxy check; a wrong key, a wrong identity, no signature, a "
            "tampered signature, a tampered manifest and an unexpected source are each refused."
        ),
        arguments={"work": ""},
    )
)
