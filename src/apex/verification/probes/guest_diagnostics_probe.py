"""Read-only diagnostics of the machine the live medium is running on, kept on its own storage."""

from __future__ import annotations

from apex.kernel import claims, identifiers
from apex.verification import probes, probing

probes.declare(
    probing.ProbeCase(
        unit=identifiers.ProbeId("guest.diagnostics"),
        environment=claims.EnvironmentKind.PHYSICAL,
        summary=(
            "Kernel, packages, audio routing, mixer state, the fingerprint journal, the "
            "sessions and every codec dump, written once to a destination the operator "
            "chose and never over an earlier capture."
        ),
        arguments={"destination": ""},
    )
)
