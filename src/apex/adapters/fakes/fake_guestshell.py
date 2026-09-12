"""A guest that answers from a table keyed on the rendered script, and records every copy."""

from __future__ import annotations

import dataclasses

from apex.kernel import bounded, claims, commands, errors, safepaths, timing
from apex.ports import guestshell


@dataclasses.dataclass(frozen=True, slots=True)
class GuestReply:
    exit_code: int = 0
    stdout: bytes = b""
    stderr: bytes = b""


@dataclasses.dataclass(frozen=True, slots=True)
class Sent:
    local: safepaths.SafePath
    remote: safepaths.RemotePath


@dataclasses.dataclass(frozen=True, slots=True)
class Received:
    remote: safepaths.RemotePath
    into: safepaths.SafePath
    recursive: bool


class ScriptedGuest(guestshell.GuestShellPort):
    environment = claims.EnvironmentKind.SIMULATED

    def __init__(
        self, replies: dict[str, GuestReply] | None = None, *, strict: bool = False
    ) -> None:
        """A script not in the table echoes itself, or is a port failure when strict."""
        self._replies = dict(replies or {})
        self._strict = strict
        self.runs: list[guestshell.GuestRun] = []
        self.targets: list[guestshell.GuestTarget] = []
        self.sent: list[Sent] = []
        self.received: list[Received] = []

    @classmethod
    def echoing(cls) -> ScriptedGuest:
        """A guest that answers every script with its own text, for the shared suite."""
        return cls()

    def expect(self, script: str, reply: GuestReply) -> None:
        self._replies[script] = reply

    def run(
        self, target: guestshell.GuestTarget, run: guestshell.GuestRun
    ) -> commands.CompletedRun:
        self.targets.append(target)
        self.runs.append(run)
        text = run.script.rendered()
        reply = self._replies.get(text)
        if reply is None and self._strict:
            raise errors.PortFailure(port="guest", cause=f"undeclared script: {text}")
        if reply is None:
            reply = GuestReply(stdout=text.encode() + (run.stdin or b""))
        if run.transcript is not None:
            return commands.CompletedRun(
                exit_code=reply.exit_code, stdout=b"", stderr=b"", truncated=False
            )
        out = bounded.take(reply.stdout, bounded.Limit(run.limit.value))
        err = bounded.take(reply.stderr, bounded.Limit(run.limit.value))
        return commands.CompletedRun(
            exit_code=reply.exit_code,
            stdout=out.data,
            stderr=err.data,
            truncated=out.truncated or err.truncated,
        )

    def send(
        self,
        target: guestshell.GuestTarget,
        *,
        local: safepaths.SafePath,
        remote: safepaths.RemotePath,
        deadline: timing.Deadline,  # noqa: ARG002
    ) -> None:
        self.targets.append(target)
        self.sent.append(Sent(local=local, remote=remote))

    def receive(
        self,
        target: guestshell.GuestTarget,
        *,
        remote: safepaths.RemotePath,
        into: safepaths.SafePath,
        recursive: bool,
        deadline: timing.Deadline,  # noqa: ARG002
    ) -> None:
        self.targets.append(target)
        self.received.append(Received(remote=remote, into=into, recursive=recursive))
