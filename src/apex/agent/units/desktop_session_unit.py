"""Report the account's session on the seat, or wait for its Wayland session to appear.

Asked without waiting, the answer says whether the account is already on the seat, which
the host checks before it types a password; asked with waiting, the answer arrives when
the account's session is there and says whether it is a Wayland one.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from apex.agent import agentports, guestguard, seatsessions, units
from apex.config import defaults
from apex.kernel import encoding, errors, identifiers, refusals

SCOPE = "the account's session on the seat, reported or waited for, never judged here"
ACCOUNT = re.compile(r"[a-z_][a-z0-9_-]*")
USER = "user"
WAIT = "wait"


def run(
    ports: agentports.AgentPorts, *, arguments: Mapping[str, encoding.JsonValue]
) -> encoding.Document:
    user = arguments.get(USER)
    wait = arguments.get(WAIT, False)
    if not isinstance(user, str) or ACCOUNT.fullmatch(user) is None or not isinstance(wait, bool):
        raise errors.Refusal(
            refusals.RefusalReason.REQUEST_MALFORMED,
            subject=f"user {user!r}, wait {wait!r}",
            remedy="name a plain account and say whether to wait for its session",
        )
    guestguard.require_session_user(ports)
    if wait:
        session, sessions = seatsessions.wait_for(
            ports, defaults.SESSION_APPEARS, user=user, session_type=defaults.WAYLAND_SESSION
        )
    else:
        sessions = seatsessions.on_seat(ports)
        session = seatsessions.find(sessions, user=user)
    return {
        "scope": SCOPE,
        "user": user,
        "waited": wait,
        "found": session is not None,
        "wayland": session is not None and session.session_type == defaults.WAYLAND_SESSION,
        "session": None if session is None else session.document(),
        "sessions": seatsessions.documents(sessions),
    }


units.declare(units.Unit(id=identifiers.ProbeId("desktop.session"), run=run))
