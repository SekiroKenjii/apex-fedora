"""Run a program through the operating system."""

from __future__ import annotations

import ctypes
import dataclasses
import os
import shutil
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path
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
        cwd: safepaths.SafePath | None = None,
        variables: Mapping[str, str] | None = None,
        dropping: frozenset[commands.Capability] = frozenset(),
    ) -> commands.CompletedRun:
        launch = _Launch(
            deadline=deadline,
            stdin=stdin,
            cwd=cwd,
            added=None if variables is None else {**os.environ, **variables},
            dropping=dropping,
        )
        if transcript is not None:
            transcript.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with transcript.path.open("ab") as handle:
                return self._run(argv, launch, limit=limit, sink=handle)
        return self._run(argv, launch, limit=limit, sink=None)

    def locate(self, program: str) -> Path | None:
        found = shutil.which(program)
        return None if found is None else Path(found)

    def _run(
        self,
        argv: commands.Argv,
        launch: _Launch,
        *,
        limit: commands.OutputLimit,
        sink: IO[bytes] | None,
    ) -> commands.CompletedRun:
        deadline = launch.deadline
        try:
            completed = subprocess.run(  # noqa: S603
                list(argv),
                capture_output=sink is None,
                stdout=sink,
                stderr=subprocess.STDOUT if sink is not None else None,
                input=launch.stdin,
                timeout=deadline.budget.seconds,
                check=False,
                cwd=None if launch.cwd is None else launch.cwd.path,
                env=launch.added,
                preexec_fn=_dropper(launch.dropping) if launch.dropping else None,
            )
        except subprocess.SubprocessError as error:
            if isinstance(error, subprocess.TimeoutExpired):
                raise errors.PortFailure(
                    port="process", cause=f"{argv.arguments[0]} exceeded {deadline.budget.seconds}s"
                ) from error
            raise errors.PortFailure(
                port="process", cause=f"{argv.arguments[0]}: cannot restrict the child"
            ) from error
        except FileNotFoundError as error:
            raise errors.PortFailure(
                port="process", cause=f"{argv.arguments[0]}: not found"
            ) from error
        except PermissionError as error:
            raise errors.PortFailure(port="process", cause=str(error)) from error
        out = bounded.take(completed.stdout or b"", bounded.Limit(limit.value))
        err = bounded.take(completed.stderr or b"", bounded.Limit(limit.value))
        return commands.CompletedRun(
            exit_code=completed.returncode,
            stdout=out.data,
            stderr=err.data,
            truncated=out.truncated or err.truncated,
        )


@dataclasses.dataclass(frozen=True, slots=True)
class _Launch:
    deadline: timing.Deadline
    stdin: bytes | None
    cwd: safepaths.SafePath | None
    added: Mapping[str, str] | None
    dropping: frozenset[commands.Capability]


PR_CAPBSET_DROP = 24


def _dropper(capabilities: frozenset[commands.Capability]) -> Callable[[], None]:
    """Runs in the child between fork and exec; a failure there fails the whole run."""

    def drop() -> None:
        libc = ctypes.CDLL(None, use_errno=True)
        libc.prctl.argtypes = [
            ctypes.c_int,
            ctypes.c_ulong,
            ctypes.c_ulong,
            ctypes.c_ulong,
            ctypes.c_ulong,
        ]
        libc.prctl.restype = ctypes.c_int
        for capability in sorted(capabilities):
            if libc.prctl(PR_CAPBSET_DROP, int(capability), 0, 0, 0) != 0:
                raise OSError(ctypes.get_errno(), f"cannot drop {capability.name}")

    return drop
