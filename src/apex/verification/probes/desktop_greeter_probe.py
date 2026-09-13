"""GDM's greeter on the seat, waited for by the guest before the host types anything."""

from __future__ import annotations

from apex.kernel import claims, identifiers
from apex.verification import probes, probing

probes.declare(
    probing.ProbeCase(
        unit=identifiers.ProbeId("desktop.greeter"),
        environment=claims.EnvironmentKind.VM,
        summary=(
            "The seat's sessions as logind lists them, polled once a second until one of "
            "class greeter appears or a minute has passed; the host types at the greeter "
            "only after this says it is there."
        ),
        privileged=False,
    )
)
