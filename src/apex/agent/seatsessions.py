"""What logind says is on the seat, read for the login probes and never judged here.

The older host listed the sessions and asked each seat session for its class and type;
the same two programs are asked here, and a session whose identifier is not plain is left
out as it was, so a probe never passes an odd token back into a command line.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Sequence

from apex.agent import agentports, observing
from apex.config import defaults
from apex.kernel import commands, encoding, timing

LIST = commands.Argv.of("loginctl", "list-sessions", "--no-legend", "--no-pager")
PLAIN = re.compile(r"[a-zA-Z0-9]+")
CLASS = "Class"
TYPE = "Type"
SEAT_COLUMN = 3
USER_COLUMN = 2


@dataclasses.dataclass(frozen=True, slots=True)
class SeatSession:
    id: str
    user: str
    seat: str
    session_class: str
    session_type: str

    def document(self) -> encoding.Document:
        return {
            "id": self.id,
            "user": self.user,
            "seat": self.seat,
            "class": self.session_class,
            "type": self.session_type,
        }


def show(session: str) -> commands.Argv:
    return commands.Argv.of("loginctl", "show-session", session, "-p", CLASS, "-p", TYPE)


def on_seat(ports: agentports.AgentPorts) -> tuple[SeatSession, ...]:
    """Every session on the seat the display is attached to, with its class and type."""
    listed = observing.program(ports, LIST)
    text = listed.get("stdout")
    if listed.get("returncode") != 0 or not isinstance(text, str):
        return ()
    found: list[SeatSession] = []
    for row in text.splitlines():
        columns = row.split()
        if len(columns) <= SEAT_COLUMN or columns[SEAT_COLUMN] != defaults.SEAT:
            continue
        if PLAIN.fullmatch(columns[0]) is not None:
            found.append(_described(ports, columns[0], columns[USER_COLUMN]))
    return tuple(found)


def find(
    sessions: Sequence[SeatSession],
    *,
    user: str | None = None,
    session_class: str | None = None,
    session_type: str | None = None,
) -> SeatSession | None:
    """The first session matching every condition given, or nothing."""
    for session in sessions:
        wanted = (
            (user, session.user),
            (session_class, session.session_class),
            (session_type, session.session_type),
        )
        if all(expected is None or expected == actual for expected, actual in wanted):
            return session
    return None


def wait_for(
    ports: agentports.AgentPorts,
    policy: timing.WaitPolicy,
    *,
    user: str | None = None,
    session_class: str | None = None,
    session_type: str | None = None,
) -> tuple[SeatSession | None, tuple[SeatSession, ...]]:
    """The matching session once it appears within the policy, and what the seat showed last."""
    seen: list[tuple[SeatSession, ...]] = []

    def present() -> bool:
        seen.append(on_seat(ports))
        found = find(seen[-1], user=user, session_class=session_class, session_type=session_type)
        return found is not None

    observing.settle(ports, present, policy)
    last = seen[-1] if seen else ()
    return find(last, user=user, session_class=session_class, session_type=session_type), last


def documents(sessions: Sequence[SeatSession]) -> list[encoding.JsonValue]:
    return [session.document() for session in sessions]


def _described(ports: agentports.AgentPorts, session: str, user: str) -> SeatSession:
    shown = observing.program(ports, show(session))
    text = shown.get("stdout")
    properties = _properties(text if isinstance(text, str) else "")
    return SeatSession(
        id=session,
        user=user,
        seat=defaults.SEAT,
        session_class=properties.get(CLASS, ""),
        session_type=properties.get(TYPE, ""),
    )


def _properties(text: str) -> dict[str, str]:
    pairs = (line.partition("=") for line in text.splitlines() if "=" in line)
    return {name: value for name, _, value in pairs}
