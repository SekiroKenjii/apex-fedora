"""Ask bootc to switch to a fixture image or to roll back, and report what it said.

The switch enforces the container signature policy and reads the image from the fixture's
own directory under the fixture root; nothing else is an acceptable source. The exit code
and both streams come back as they were, because a refused switch is what the rejection
cases expect and the host judges them.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from apex.agent import agentports, guestguard, units
from apex.config import defaults
from apex.kernel import commands, encoding, errors, identifiers, refusals
from apex.provisioning.fixtures import update_fixture

SWITCH = "switch"
ROLLBACK = "rollback"
OPERATIONS = (SWITCH, ROLLBACK)
SOURCE = re.compile(
    re.escape(update_fixture.FIXTURE_ROOT) + r"/[a-f0-9]{32}/(a|b|wrong-key|unsigned|untrusted)"
)


def _malformed(detail: str) -> errors.Refusal:
    return errors.Refusal(refusals.RefusalReason.REQUEST_MALFORMED, subject=detail)


def argv(arguments: Mapping[str, encoding.JsonValue]) -> commands.Argv:
    operation = arguments.get("operation")
    if operation == ROLLBACK:
        return commands.Argv.of("bootc", ROLLBACK)
    if operation != SWITCH:
        raise _malformed(f"operation {operation!r}")
    source = arguments.get("source")
    if not isinstance(source, str) or not SOURCE.fullmatch(source):
        raise _malformed(f"source {source!r} is not a fixture image directory")
    return commands.Argv.of(
        "bootc", SWITCH, "--enforce-container-sigpolicy", "--transport", "dir", source
    )


def run(
    ports: agentports.AgentPorts, *, arguments: Mapping[str, encoding.JsonValue]
) -> encoding.Document:
    guestguard.require_installed(ports)
    asked = argv(arguments)
    completed = ports.processes.run(
        asked, deadline=defaults.UPDATE_OPERATION_DEADLINE, limit=commands.OutputLimit.default()
    )
    return {
        "operation": str(arguments.get("operation")),
        "argv": list(asked),
        "returncode": completed.exit_code,
        "stdout": completed.stdout.decode(errors="replace"),
        "stderr": completed.stderr.decode(errors="replace"),
        "truncated": completed.truncated,
    }


units.declare(units.Unit(id=identifiers.ProbeId("update.operate"), run=run))
