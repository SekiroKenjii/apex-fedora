"""The guest shell over the system's ssh and scp, run through the process port."""

from __future__ import annotations

from apex.config import defaults
from apex.kernel import claims, commands, errors, safepaths, timing
from apex.ports import guestshell, process

SSH = "ssh"
SCP = "scp"


class OpensshGuestShell(guestshell.GuestShellPort):
    environment = claims.EnvironmentKind.BUILD

    def __init__(self, processes: process.ProcessPort) -> None:
        self._processes = processes

    def run(
        self, target: guestshell.GuestTarget, run: guestshell.GuestRun
    ) -> commands.CompletedRun:
        argv = commands.Argv.of(
            SSH,
            "-i", target.key,
            "-p", str(target.port),
            *_options(
                "IdentitiesOnly=yes",
                "BatchMode=yes",
                f"ConnectTimeout={int(defaults.SSH_CONNECT_TIMEOUT.seconds)}",
                "StrictHostKeyChecking=accept-new",
                f"UserKnownHostsFile={target.known_hosts}",
            ),
            target.address,
            run.script.rendered(),
        )
        return self._processes.run(
            argv, deadline=run.deadline, limit=run.limit, transcript=run.transcript
        )

    def send(
        self,
        target: guestshell.GuestTarget,
        *,
        local: safepaths.SafePath,
        remote: safepaths.RemotePath,
        deadline: timing.Deadline,
    ) -> None:
        self._copy(
            target, str(local), f"{target.address}:{remote}", recursive=False, deadline=deadline
        )

    def receive(
        self,
        target: guestshell.GuestTarget,
        *,
        remote: safepaths.RemotePath,
        into: safepaths.SafePath,
        recursive: bool,
        deadline: timing.Deadline,
    ) -> None:
        self._copy(
            target, f"{target.address}:{remote}", str(into), recursive=recursive, deadline=deadline
        )

    def _copy(
        self,
        target: guestshell.GuestTarget,
        source: str,
        destination: str,
        *,
        recursive: bool,
        deadline: timing.Deadline,
    ) -> None:
        argv = commands.Argv.of(
            SCP,
            "-i", target.key,
            "-P", str(target.port),
            *_options(
                "IdentitiesOnly=yes",
                "BatchMode=yes",
                "StrictHostKeyChecking=yes",
                f"UserKnownHostsFile={target.known_hosts}",
            ),
            *(["-r"] if recursive else []),
            source,
            destination,
        )
        completed = self._processes.run(
            argv, deadline=deadline, limit=commands.OutputLimit.default()
        )
        if not completed.succeeded:
            raise errors.PortFailure(
                port="guest",
                cause=f"{SCP} exited with {completed.exit_code}: "
                f"{completed.stderr.decode(errors='replace').strip()}",
            )


def _options(*values: str) -> list[str]:
    rendered: list[str] = []
    for value in values:
        rendered.extend(("-o", value))
    return rendered
