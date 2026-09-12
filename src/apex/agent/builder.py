"""Whether this guest is the isolated builder, checked before any fixture is made in it."""

from __future__ import annotations

import os
from pathlib import Path

from apex.agent import agentports
from apex.config import defaults
from apex.kernel import commands, errors, refusals, safepaths

ROOT_USER = 0


def require_isolated(ports: agentports.AgentPorts) -> None:
    if os.geteuid() != ROOT_USER:
        raise _refuse("not running as root")
    marker = safepaths.SafePath(Path(defaults.BUILDER_MARKER))
    try:
        text = ports.files.read_bytes(marker, limit=defaults.DOCUMENT_LIMIT.value)
    except errors.PortFailure as failure:
        raise _refuse(f"no builder marker: {failure.cause}") from failure
    if text.decode(errors="replace").strip() != defaults.BUILDER_MARKER_TEXT:
        raise _refuse("the builder marker names another builder")
    completed = ports.processes.run(
        commands.Argv.of("systemd-detect-virt", "--vm"),
        deadline=defaults.PROBE_DEADLINE,
        limit=commands.OutputLimit.default(),
    )
    if completed.stdout.decode(errors="replace").strip() not in defaults.VIRTUALISERS:
        raise _refuse("not a QEMU virtual machine")


def _refuse(detail: str) -> errors.Refusal:
    return errors.Refusal(
        refusals.RefusalReason.BUILDER_NOT_ISOLATED,
        subject=detail,
        remedy="fixtures are made only inside the isolated Fedora builder",
    )
