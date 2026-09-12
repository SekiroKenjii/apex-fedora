"""The GTK4 render probe shown in the logged-in session; the host's screenshot judges it."""

from __future__ import annotations

from apex.kernel import claims, identifiers
from apex.verification import probes, probing

probes.declare(
    probing.ProbeCase(
        unit=identifiers.ProbeId("desktop.render"),
        environment=claims.EnvironmentKind.VM,
        summary=(
            "A GTK4 window with three wide colour bars, started as a transient unit of the "
            "logged-in user's session under Wayland and waited for until it reports its "
            "window presented; the bars are judged from the hypervisor's screenshot."
        ),
        privileged=False,
    )
)
