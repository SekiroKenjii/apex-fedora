"""Show the GTK4 render probe in the user's session; the host's screenshot judges its bars."""

from __future__ import annotations

from collections.abc import Mapping

from apex.agent import agentports, desktopprobing, desktopprograms, units
from apex.kernel import encoding, identifiers

UNIT = "apex-render-probe"
SCOPE = "GTK4 window presented in the logged-in Wayland session of a disposable guest"


def run(
    ports: agentports.AgentPorts,
    *,
    arguments: Mapping[str, encoding.JsonValue],  # noqa: ARG001
) -> encoding.Document:
    # The render probe takes no arguments and is never stopped; the older host let the boot end it.
    return {
        "scope": SCOPE,
        "rendering": desktopprobing.NOT_TESTED,
        **desktopprobing.present(ports, desktopprograms.RENDER, UNIT),
    }


units.declare(units.Unit(id=identifiers.ProbeId("desktop.render"), run=run))
