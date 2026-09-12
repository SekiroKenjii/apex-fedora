"""Show native libadwaita controls in the user's session, or stop them once the host has looked."""

from __future__ import annotations

from collections.abc import Mapping

from apex.agent import agentports, desktopprobing, units
from apex.kernel import encoding, identifiers

MODE = "adwaita"


def run(
    ports: agentports.AgentPorts, *, arguments: Mapping[str, encoding.JsonValue]
) -> encoding.Document:
    return desktopprobing.theme(ports, MODE, arguments)


units.declare(units.Unit(id=identifiers.ProbeId("desktop.theme-adwaita"), run=run))
