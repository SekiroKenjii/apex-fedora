"""Run a program through the operating system."""

from __future__ import annotations

import subprocess

from apex.kernel import bounded, claims, commands, errors, timing
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
    ) -> commands.CompletedRun:
        try:
            completed = subprocess.run(  # noqa: S603
                list(argv),
                capture_output=True,
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
