"""The three shapes every observation probe reports: a program's output, a file, a path.

Each is bounded the way the older scripts bounded it, and each records a failure to observe
as an observation rather than stopping the others. The report never says PASS; a probe reads
and the host judges.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from pathlib import Path

from apex.agent import agentports
from apex.config import defaults
from apex.kernel import commands, encoding, errors, safepaths, timing

OVERREAD = 1
CLOCK = "clock"


def settle(
    ports: agentports.AgentPorts, condition: Callable[[], bool], policy: timing.WaitPolicy
) -> bool:
    """Whether the condition held within the policy; the clock giving up is an observation."""
    try:
        ports.clock.wait_until(condition, policy)
    except errors.PortFailure as failure:
        if failure.port != CLOCK:
            raise
        return False
    return True


def program(ports: agentports.AgentPorts, argv: commands.Argv) -> encoding.Document:
    try:
        completed = ports.processes.run(
            argv,
            deadline=defaults.OBSERVATION_DEADLINE,
            limit=commands.OutputLimit(defaults.OBSERVATION_LIMIT.value),
        )
    except errors.PortFailure as failure:
        return {"argv": list(argv), "returncode": None, "error": failure.cause}
    return {
        "argv": list(argv),
        "returncode": completed.exit_code,
        "stdout": completed.stdout.decode(errors="replace"),
        "stderr": completed.stderr.decode(errors="replace"),
        "truncated": completed.truncated,
    }


def programs(
    ports: agentports.AgentPorts, named: Mapping[str, commands.Argv]
) -> encoding.Document:
    return {name: program(ports, argv) for name, argv in named.items()}


def text(ports: agentports.AgentPorts, path: safepaths.SafePath) -> encoding.Document:
    """The file's text up to the limit, and its digest only when the whole file was read."""
    limit = defaults.OBSERVATION_LIMIT.value
    try:
        data = ports.files.read_bytes(path, limit=limit + OVERREAD)
    except errors.PortFailure as failure:
        return {"error": failure.cause}
    truncated = len(data) > limit
    kept = data[:limit]
    return {
        "text": kept.decode(errors="replace"),
        "truncated": truncated,
        "sha256": None if truncated else hashlib.sha256(kept).hexdigest(),
    }


def texts(ports: agentports.AgentPorts, paths: tuple[str, ...]) -> encoding.Document:
    return {name: text(ports, safepaths.SafePath(Path(name))) for name in paths}


def metadata(ports: agentports.AgentPorts, path: safepaths.SafePath) -> encoding.Document:
    try:
        seen = ports.files.inspect(path)
    except errors.PortFailure as failure:
        return {"error": failure.cause}
    return {
        "uid": seen.owner,
        "gid": seen.group,
        "mode": oct(seen.mode.value),
        "selinux": seen.label,
    }
