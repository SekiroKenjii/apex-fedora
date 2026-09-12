"""The live medium, observed from inside without touching its protection."""

from __future__ import annotations

from apex.kernel import claims, identifiers
from apex.verification import probes, probing

probes.declare(
    probing.ProbeCase(
        unit=identifiers.ProbeId("live.observe"),
        environment=claims.EnvironmentKind.LIVE_VM,
        summary=(
            "Mounts, swap, the protection units, the guard script and every block device of "
            "a live guest, read once and judged on the host."
        ),
    )
)
