"""Wait for GNOME Shell on the account's bus and the journal event that says it started.

The older host asked the bus for the Shell's owner and then the journal for the startup
message of that process, once a second for ninety seconds; the same two programs are asked
here and the event is reported as the journal gave it. The Shell opens Welcome as it
finishes starting; dismissing it is the host's to do, by key, after this report.
"""

from __future__ import annotations

import json
from collections.abc import Mapping

from apex.agent import agentports, guestguard, observing, units
from apex.config import defaults
from apex.kernel import commands, encoding, errors, identifiers, refusals

SCOPE = "the Shell's startup event on the account's bus, waited for and never judged here"
MESSAGE_ID = "MESSAGE_ID"
PROCESS = "_PID"
ONE_LINE = "1"


def journal_query(pid: int) -> commands.Argv:
    return commands.Argv.of(
        "journalctl", "--user", "-b", f"{MESSAGE_ID}={defaults.SHELL_STARTED_MESSAGE}",
        f"{PROCESS}={pid}", "-n", ONE_LINE, "-o", "json", "--no-pager",
    )


def shell_pid(owner: encoding.Document) -> int | None:
    """The Shell's process number when the bus named an owner, else nothing."""
    text = owner.get("stdout")
    if owner.get("returncode") != 0 or not isinstance(text, str):
        return None
    if guestguard.SHELL_PID.fullmatch(text.strip()) is None:
        return None
    return int(text.split()[1])


def startup_event(text: str, pid: int) -> encoding.Document | None:
    """The journal's startup entry for the process, as it was written."""
    for line in text.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        started = event.get(MESSAGE_ID) == defaults.SHELL_STARTED_MESSAGE
        if started and event.get(PROCESS) == str(pid):
            return event
    return None


def run(
    ports: agentports.AgentPorts, *, arguments: Mapping[str, encoding.JsonValue]
) -> encoding.Document:
    if arguments:
        raise errors.Refusal(
            refusals.RefusalReason.REQUEST_MALFORMED,
            subject=f"arguments {sorted(arguments)}",
            remedy="the startup probe takes none",
        )
    guestguard.require_session_user(ports)
    latest: dict[str, encoding.JsonValue] = {"owner": {}, "journal": {}}
    found: list[tuple[int, encoding.Document]] = []

    def started() -> bool:
        owner = observing.program(ports, guestguard.SHELL_OWNER)
        latest["owner"] = owner
        pid = shell_pid(owner)
        if pid is None:
            return False
        journal = observing.program(ports, journal_query(pid))
        latest["journal"] = journal
        text = journal.get("stdout")
        event = startup_event(text, pid) if isinstance(text, str) else None
        if event is None:
            return False
        found.append((pid, event))
        return True

    observing.settle(ports, started, defaults.SHELL_STARTS)
    return {
        "scope": SCOPE,
        "found": bool(found),
        "pid": found[0][0] if found else None,
        "event": found[0][1] if found else None,
        **latest,
    }


units.declare(units.Unit(id=identifiers.ProbeId("desktop.shell-startup"), run=run))
