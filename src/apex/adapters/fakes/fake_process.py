"""A process port backed by a table of expected argument vectors.

An argument vector the test did not declare fails the test rather than silently returning
nothing, so a change in what a stage runs cannot pass unnoticed.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping

from apex.kernel import bounded, claims, commands, errors, safepaths, timing
from apex.ports import process


@dataclasses.dataclass(frozen=True, slots=True)
class Reply:
    exit_code: int = 0
    stdout: bytes = b""
    stderr: bytes = b""
    delay: timing.Elapsed = timing.Elapsed(0)
    missing: bool = False


class ScriptedProcess(process.ProcessPort):
    environment = claims.EnvironmentKind.SIMULATED

    def __init__(self, replies: dict[tuple[str, ...], Reply] | None = None) -> None:
        self._replies = dict(replies or {})
        self.calls: list[commands.Argv] = []
        self.transcripts: list[safepaths.SafePath] = []
        self.directories: list[safepaths.SafePath | None] = []
        self.variables: list[Mapping[str, str] | None] = []
        self.restrictions: list[frozenset[commands.Capability]] = []

    @classmethod
    def with_shell_probe(cls) -> ScriptedProcess:
        """The replies the shared contract suite exercises."""
        return cls(
            {
                ("printf", "hello"): Reply(stdout=b"hello"),
                ("false",): Reply(exit_code=1),
                ("printf", "abcdefghij"): Reply(stdout=b"abcdefghij"),
                ("printf", "%s", "; touch owned"): Reply(stdout=b"; touch owned"),
                ("apex-no-such-program",): Reply(missing=True),
                ("sleep", "5"): Reply(delay=timing.Elapsed(5)),
                ("env",): Reply(stdout=b"APEX_CONTRACT=held\n"),
                ("cat", "/proc/self/status"): Reply(stdout=b"CapBnd:\t000001ffffdfffff\n"),
            }
        )

    def expect(self, argv: tuple[str, ...], reply: Reply) -> None:
        self._replies[argv] = reply

    def run(
        self,
        argv: commands.Argv,
        *,
        deadline: timing.Deadline,
        limit: commands.OutputLimit,
        stdin: bytes | None = None,  # noqa: ARG002
        transcript: safepaths.SafePath | None = None,
        cwd: safepaths.SafePath | None = None,
        variables: Mapping[str, str] | None = None,
        dropping: frozenset[commands.Capability] = frozenset(),
    ) -> commands.CompletedRun:
        # `stdin` is part of the port and is ignored here; a fake that needed it would
        # record it, and no contract case supplies one yet.
        self.calls.append(argv)
        self.directories.append(cwd)
        self.variables.append(variables)
        self.restrictions.append(dropping)
        if transcript is not None:
            self.transcripts.append(transcript)
        key = tuple(argv)
        if key not in self._replies:
            raise errors.PortFailure(
                port="process", cause=f"undeclared argument vector: {' '.join(key)}"
            )
        reply = self._replies[key]
        if reply.missing:
            raise errors.PortFailure(port="process", cause=f"{key[0]}: not found")
        if reply.delay.seconds > deadline.budget.seconds:
            raise errors.PortFailure(
                port="process", cause=f"{key[0]} exceeded {deadline.budget.seconds}s"
            )
        if transcript is not None:
            return commands.CompletedRun(
                exit_code=reply.exit_code, stdout=b"", stderr=b"", truncated=False
            )
        out = bounded.take(reply.stdout, bounded.Limit(limit.value))
        err = bounded.take(reply.stderr, bounded.Limit(limit.value))
        return commands.CompletedRun(
            exit_code=reply.exit_code,
            stdout=out.data,
            stderr=err.data,
            truncated=out.truncated or err.truncated,
        )
