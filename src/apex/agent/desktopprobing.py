"""Showing a GTK program in the user's session and reading what it said, for the desktop probes.

A program is placed, started as a transient unit of the user's manager, and waited for until
its journal carries the line it prints once its window is presented. The journal is the
observation and the display type is read from that line. Dismissing stops the unit. The
screenshot that judges the window is the host's, so nothing here ever says PASS.
"""

from __future__ import annotations

import json
from collections.abc import Mapping

from apex.agent import agentports, desktopprograms, guestguard, observing
from apex.config import defaults
from apex.kernel import encoding, errors, refusals

NOT_TESTED = "NOT TESTED"
PRESENT = "present"
DISMISS = "dismiss"
ACTIONS = (PRESENT, DISMISS)
RETURN_CODE = "returncode"
STDOUT = "stdout"


def action_of(arguments: Mapping[str, encoding.JsonValue]) -> str:
    action = arguments.get("action", PRESENT)
    if action not in ACTIONS:
        raise errors.Refusal(
            refusals.RefusalReason.REQUEST_MALFORMED,
            subject=f"action {action!r}",
            remedy=f"ask for one of {', '.join(ACTIONS)}",
        )
    return str(action)


def display_type(journal: str) -> str | None:
    """The display the program reported when its window was presented, from its journal."""
    for line in journal.splitlines():
        try:
            event = json.loads(line[line.index("{"):]) if "{" in line else None
        except ValueError:
            continue
        if isinstance(event, dict) and event.get("event") == desktopprograms.PRESENTED:
            found = event.get("display_type")
            return found if isinstance(found, str) else None
    return None


def present(
    ports: agentports.AgentPorts,
    program: desktopprograms.Program,
    unit: str,
    *arguments: str,
) -> encoding.Document:
    guestguard.require_shell_session(ports)
    digest = program.place(ports.files)
    launched = observing.program(ports, desktopprograms.launch(program, unit, *arguments))
    journals: list[encoding.Document] = []

    def presented() -> bool:
        journals.append(observing.program(ports, desktopprograms.journal(unit)))
        text = journals[-1].get(STDOUT)
        return isinstance(text, str) and desktopprograms.PRESENTED in text

    if launched.get(RETURN_CODE) == 0:
        try:
            ports.clock.wait_until(presented, defaults.WINDOW_APPEARS)
        except errors.PortFailure:
            journals.append(observing.program(ports, desktopprograms.journal(unit)))
    journal = journals[-1] if journals else {}
    text = journal.get(STDOUT)
    shown = isinstance(text, str) and desktopprograms.PRESENTED in text
    return {
        "unit": unit,
        "program_sha256": digest.hex,
        "launch": launched,
        "journal": journal,
        "presented": shown,
        "display_type": display_type(text) if isinstance(text, str) else None,
    }


def dismiss(ports: agentports.AgentPorts, unit: str) -> encoding.Document:
    guestguard.require_shell_session(ports)
    return {"unit": unit, "stop": observing.program(ports, desktopprograms.stop(unit))}


def theme(
    ports: agentports.AgentPorts, mode: str, arguments: Mapping[str, encoding.JsonValue]
) -> encoding.Document:
    """One theme probe in one mode: shown for the host's screenshot, or stopped after it."""
    unit = f"apex-theme-{mode}"
    if action_of(arguments) == DISMISS:
        return dismiss(ports, unit)
    return {
        "mode": mode,
        "visual_review": NOT_TESTED,
        **present(ports, desktopprograms.THEME, unit, mode),
    }
