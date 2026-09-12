"""Run a program through the operating system."""

from __future__ import annotations

import subprocess
from typing import IO

from apex.kernel import bounded, claims, commands, errors, safepaths, timing
from apex.ports import process


class SubprocessRunner(process.ProcessPort):
    environment = claims.EnvironmentKind.BUILD

    def run(
        self,
        argv: commands.Argv,
        *,
        deadline: timing.Deadline,
        limit: commands.OutputLimit,
        stdin: bytes | None = None,
        transcript: safepaths.SafePath | None = None,
    ) -> commands.CompletedRun:
        if transcript is not None:
            transcript.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with transcript.path.open("ab") as handle:
                return self._run(argv, deadline=deadline, limit=limit, stdin=stdin, sink=handle)
        return self._run(argv, deadline=deadline, limit=limit, stdin=stdin, sink=None)

    def _run(
        self,
        argv: commands.Argv,
        *,
        deadline: timing.Deadline,
        limit: commands.OutputLimit,
        stdin: bytes | None,
        sink: IO[bytes] | None,
    ) -> commands.CompletedRun:
        try:
            completed = subprocess.run(  # noqa: S603
                list(argv),
                capture_output=sink is None,
                stdout=sink,
                stderr=subprocess.STDOUT if sink is not None else None,
                input=stdin,
                timeout=deadline.budget.seconds,
                check=False,
            )
        except FileNotFoundError as error:
            raise errors.PortFailure(
                port="process", cause=f"{argv.arguments[0]}: not found"
            ) from error
        except PermissionError as error:
            raise errors.PortFailure(port="process", cause=str(error)) from error
        except subprocess.TimeoutExpired as error:
            raise errors.PortFailure(
                port="process", cause=f"{argv.arguments[0]} exceeded {deadline.budget.seconds}s"
            ) from error
        out = bounded.take(completed.stdout or b"", bounded.Limit(limit.value))
        err = bounded.take(completed.stderr or b"", bounded.Limit(limit.value))
        return commands.CompletedRun(
            exit_code=completed.returncode,
            stdout=out.data,
            stderr=err.data,
            truncated=out.truncated or err.truncated,
        )
