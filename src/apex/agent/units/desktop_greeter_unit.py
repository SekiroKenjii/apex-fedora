"""Wait for GDM's greeter on the seat, so the host knows when to type."""

from __future__ import annotations

from collections.abc import Mapping

from apex.agent import agentports, guestguard, seatsessions, units
from apex.config import defaults
from apex.kernel import encoding, errors, identifiers, refusals

SCOPE = "a greeter session on the seat, waited for and reported, never judged here"


def run(
    ports: agentports.AgentPorts, *, arguments: Mapping[str, encoding.JsonValue]
) -> encoding.Document:
    if arguments:
        raise errors.Refusal(
            refusals.RefusalReason.REQUEST_MALFORMED,
            subject=f"arguments {sorted(arguments)}",
            remedy="the greeter probe takes none",
        )
    guestguard.require_session_user(ports)
    greeter, sessions = seatsessions.wait_for(
        ports, defaults.GREETER_APPEARS, session_class=defaults.GREETER_CLASS
    )
    return {
        "scope": SCOPE,
        "found": greeter is not None,
        "session": None if greeter is None else greeter.document(),
        "sessions": seatsessions.documents(sessions),
    }


units.declare(units.Unit(id=identifiers.ProbeId("desktop.greeter"), run=run))
