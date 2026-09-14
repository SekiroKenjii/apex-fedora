"""Putting the guest program into a guest and asking it to run one unit.

The wheel is unpacked with the interpreter's own archive module, so the guest needs nothing
installed to answer. Every reply comes back framed under a token the host chose, decoded by
the shared codec, and the guest's refusals arrive as refusals here with the guest's words.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping

from apex.config import defaults
from apex.kernel import (
    commands,
    distribution,
    encoding,
    errors,
    identifiers,
    refusals,
    safepaths,
    secrets,
    timing,
)
from apex.model import agentwire, serialframe
from apex.ports import guestshell, portset

MODULE = "apex.agent.main"


class _FirstLine:
    """The sink a password reaches: the first line of the guest's standard input."""

    def __init__(self, payload: bytes) -> None:
        self.stdin = payload

    def accept(self, material: str) -> None:
        self.stdin = material.encode() + b"\n" + self.stdin


def standard_input(payload: bytes, password: secrets.Secret[str] | None) -> bytes:
    """The payload, behind the password's line when sudo is to read one."""
    sink = _FirstLine(payload)
    if password is not None:
        password.reveal_into(sink)
    return sink.stdin


def as_root(
    ports: portset.HostPorts,
    target: guestshell.GuestTarget,
    *arguments: str,
    password: secrets.Secret[str],
    deadline: timing.Deadline,
) -> commands.CompletedRun:
    """One program as root with the password on standard input; the run comes back as is."""
    step = guestshell.Step.of(*guestshell.SUDO_ASKING, *arguments)
    return ports.guest.run(
        target,
        guestshell.GuestRun(
            script=guestshell.RemoteScript.of(step),
            deadline=deadline,
            limit=commands.OutputLimit.default(),
            stdin=standard_input(b"", password),
        ),
    )


@dataclasses.dataclass(frozen=True, slots=True)
class AgentInstall:
    directory: safepaths.RemotePath
    digest: identifiers.Digest

    @property
    def library(self) -> safepaths.RemotePath:
        return self.directory.joined(defaults.AGENT_LIBRARY)


def deliver(
    ports: portset.HostPorts,
    target: guestshell.GuestTarget,
    *,
    wheel: safepaths.SafePath,
    remote: safepaths.RemotePath,
) -> AgentInstall:
    """Send the wheel and unpack it beside the run; the digest is what every request names."""
    digest = ports.digests.file(wheel)
    directory = remote.joined(defaults.AGENT_DIRECTORY)
    archive = remote.joined(defaults.AGENT_WHEEL_NAME)
    ports.guest.send(target, local=wheel, remote=archive, deadline=defaults.TRANSFER_DEADLINE)
    library = directory.joined(defaults.AGENT_LIBRARY)
    completed = ports.guest.run(
        target,
        guestshell.GuestRun(
            script=guestshell.RemoteScript.of(
                guestshell.Step.of(
                    "mkdir", "-p", "-m", defaults.REMOTE_DIRECTORY_MODE, str(directory)
                ),
                guestshell.Step.of("python3", "-m", "zipfile", "-e", str(archive), str(library)),
            ),
            deadline=defaults.GUEST_COMMAND_DEADLINE,
            limit=commands.OutputLimit.default(),
        ),
    )
    if not completed.succeeded:
        raise errors.PortFailure(
            port="guest", cause=f"the guest could not unpack the agent: {_stderr(completed)}"
        )
    return AgentInstall(directory=directory, digest=digest)


def run_unit(
    ports: portset.HostPorts,
    target: guestshell.GuestTarget,
    install: AgentInstall,
    *,
    unit: identifiers.ProbeId,
    arguments: Mapping[str, encoding.JsonValue],
    token: identifiers.Token,
    privileged: bool = True,
    password: secrets.Secret[str] | None = None,
    private_mounts: bool = False,
) -> agentwire.AgentReply:
    """One request in, one framed reply out.

    A privileged request runs as root under the guest's build lock, sudo reading the
    password from the line before the request when the account has one to give. A session
    request runs as the shell's own user with no lock, which is how a unit reaches that
    user's desktop. Private mounts confine a fixture's remount to its own namespace.
    """
    request = agentwire.AgentRequest(
        host_version=distribution.installed_version(),
        unit=unit,
        arguments=arguments,
        agent_digest=install.digest,
    )
    invocation = guestshell.RemoteScript.of(
        guestshell.Step.of(
            "env",
            f"PYTHONPATH={install.library}",
            "python3",
            "-m",
            MODULE,
            "run",
            "--framed",
            str(token),
        )
    )
    asked = invocation.steps[0]
    if privileged:
        asked = invocation.under_lock(
            defaults.BUILD_LOCK, asking=password is not None, private_mounts=private_mounts
        )
    completed = ports.guest.run(
        target,
        guestshell.GuestRun(
            script=guestshell.RemoteScript.of(
                guestshell.Step.of("cd", str(install.directory)), asked
            ),
            deadline=defaults.BUILD_DEADLINE,
            limit=commands.OutputLimit(defaults.AGENT_REPLY_LIMIT.value),
            stdin=standard_input(encoding.canonical(request.document()), password),
        ),
    )
    if completed.exit_code == errors.Refusal.exit_code:
        raise errors.Refusal(
            refusals.RefusalReason.AGENT_REFUSED, subject=f"{unit}: {_stderr(completed)}"
        )
    if not completed.succeeded:
        raise errors.PortFailure(
            port="agent", cause=f"{unit} exited with {completed.exit_code}: {_stderr(completed)}"
        )
    payload = serialframe.decode_lines(completed.stdout.splitlines(), token=token)
    reply = agentwire.AgentReply.parse(payload)
    if reply.unit != unit:
        raise errors.Refusal(
            refusals.RefusalReason.REQUEST_MALFORMED,
            subject=f"the guest answered for {reply.unit}, not {unit}",
        )
    return reply


def _stderr(completed: commands.CompletedRun) -> str:
    return completed.stderr.decode(errors="replace").strip()
