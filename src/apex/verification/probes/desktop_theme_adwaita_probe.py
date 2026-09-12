"""Native libadwaita controls shown in the logged-in session for the theme screenshot."""

from __future__ import annotations

from apex.kernel import claims, identifiers
from apex.verification import probes, probing

probes.declare(
    probing.ProbeCase(
        unit=identifiers.ProbeId("desktop.theme-adwaita"),
        environment=claims.EnvironmentKind.VM,
        summary=(
            "A libadwaita window of native controls, started in the logged-in user's session "
            "and waited for until presented, so the host can capture it before stopping it."
        ),
        arguments={"action": "present"},
        privileged=False,
    )
)
