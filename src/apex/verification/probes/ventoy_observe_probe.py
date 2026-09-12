"""A Ventoy boot of the live medium, observed for its storage mappings and session."""

from __future__ import annotations

from apex.kernel import claims, identifiers
from apex.verification import probes, probing

probes.declare(
    probing.ProbeCase(
        unit=identifiers.ProbeId("ventoy.observe"),
        environment=claims.EnvironmentKind.LIVE_VM,
        summary=(
            "Disks, mounts, device mapper tables, firmware entries and the session state of "
            "a guest booted through Ventoy, with no automatic acceptance."
        ),
    )
)
