"""Wait for the Shell's Overview to be open or closed, as the host expects after a key.

The Overview is read over the account's bus and never changed that way: the host presses
the key and asks here whether the Shell followed, so a pass means the keyboard reached the
Shell and not that a bus call did.
"""

from __future__ import annotations

from collections.abc import Mapping

from apex.agent import agentports, guestguard, observing, units
from apex.config import defaults
from apex.kernel import commands, encoding, errors, identifiers, refusals

SCOPE = "whether the Shell's Overview is open, read over the bus and never changed here"
OVERVIEW = commands.Argv.of(
    "busctl", "--user", "get-property", "org.gnome.Shell", "/org/gnome/Shell",
    "org.gnome.Shell", "OverviewActive",
)
EXPECTED = "expected"


def rendered(active: bool) -> str:
    """How busctl prints the boolean property."""
    return f"b {str(active).lower()}"


def run(
    ports: agentports.AgentPorts, *, arguments: Mapping[str, encoding.JsonValue]
) -> encoding.Document:
    expected = arguments.get(EXPECTED)
    if not isinstance(expected, bool):
        raise errors.Refusal(
            refusals.RefusalReason.REQUEST_MALFORMED,
            subject=f"expected {expected!r}",
            remedy="say whether the Overview should be open, true or false",
        )
    guestguard.require_shell_session(ports)
    replies: list[encoding.Document] = []

    def reached() -> bool:
        replies.append(observing.program(ports, OVERVIEW))
        text = replies[-1].get("stdout")
        if replies[-1].get("returncode") != 0 or not isinstance(text, str):
            return False
        return text.strip() == rendered(expected)

    settled = observing.settle(ports, reached, defaults.OVERVIEW_SETTLES)
    return {
        "scope": SCOPE,
        "expected": expected,
        "reached": settled,
        "polls": len(replies),
        "reply": replies[-1] if replies else {},
    }


units.declare(units.Unit(id=identifiers.ProbeId("desktop.overview"), run=run))
