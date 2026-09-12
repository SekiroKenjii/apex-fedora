"""The session's theme settings, extensions and Shell theme composition, read as the user."""

from __future__ import annotations

from apex.kernel import claims, identifiers
from apex.verification import probes, probing

probes.declare(
    probing.ProbeCase(
        unit=identifiers.ProbeId("desktop.theme-settings"),
        environment=claims.EnvironmentKind.VM,
        summary=(
            "The GTK theme, the Shell theme, the enabled extensions and the recorded Shell "
            "theme composition of the logged-in session, read once and judged on the host."
        ),
        privileged=False,
    )
)
