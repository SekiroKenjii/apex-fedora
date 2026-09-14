"""A context opens the serial shell it was wired with, and refuses when it was wired with none."""

from __future__ import annotations

from pathlib import Path

import pytest

from apex.adapters.fakes import fake_guestshell, fake_serialshell
from apex.config import defaults, loader
from apex.kernel import commands as kernel_commands
from apex.kernel import errors, refusals, safepaths
from apex.ports import guestshell
from apex.wiring import contexts

REPOSITORY = Path(__file__).resolve().parents[3]


def test_the_default_serial_factory_is_an_unmet_precondition(tmp_path: Path) -> None:
    context = contexts.Context(
        settings=loader.load(host_file=None, environment={}),
        repository=safepaths.SourceRoot.adopt(REPOSITORY),
        root=None,
        environment={},
        bundle=lambda _root: pytest.fail("never asked"),
    )

    with pytest.raises(errors.PreconditionUnmet) as caught:
        context.serial(safepaths.SafePath(tmp_path / "serial.sock"), 7)

    assert caught.value.reason is refusals.RefusalReason.TOPOLOGY_INCONSISTENT
    assert "serial.sock" in str(caught.value) and "7" in str(caught.value)


def test_a_context_wired_with_the_scripted_serial_shell_answers_scripts_and_remembers_its_socket(
    tmp_path: Path,
) -> None:
    opened: list[fake_serialshell.ScriptedSerialShell] = []

    def factory(socket_path: safepaths.SafePath, process: int) -> guestshell.GuestShellPort:
        shell = fake_serialshell.ScriptedSerialShell(socket_path, expected_process=process)
        opened.append(shell)
        return shell

    context = contexts.Context(
        settings=loader.load(host_file=None, environment={}),
        repository=safepaths.SourceRoot.adopt(REPOSITORY),
        root=None,
        environment={},
        bundle=lambda _root: pytest.fail("never asked"),
        serial=factory,
    )
    console = context.serial(safepaths.SafePath(tmp_path / "serial.sock"), 4242)
    assert isinstance(console, fake_serialshell.ScriptedSerialShell)
    script = guestshell.RemoteScript.of(guestshell.Step.of("cat", "/proc/cmdline"))
    console.expect(script.rendered(), fake_guestshell.GuestReply(stdout=b"rd.live.image\n"))
    target = guestshell.GuestTarget(
        user="root",
        port=defaults.GUEST_SSH_PORT,
        key=safepaths.SafePath(tmp_path / "unused"),
        known_hosts=safepaths.SafePath(tmp_path / "kh"),
    )

    completed = console.run(
        target,
        guestshell.GuestRun(
            script=script,
            deadline=defaults.GUEST_COMMAND_DEADLINE,
            limit=kernel_commands.OutputLimit.default(),
        ),
    )

    assert completed.stdout == b"rd.live.image\n" and completed.exit_code == 0
    assert opened == [console]
    assert console.socket_path.path == tmp_path / "serial.sock"
    assert console.expected_process == 4242
