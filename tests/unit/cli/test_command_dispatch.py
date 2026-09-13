"""Commands are registered by being there, dispatched by name, and rendered on two streams."""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from apex.cli import commands, commandspecs, dispatch
from apex.config import loader
from apex.kernel import errors, refusals, safepaths
from apex.ports import portset
from apex.wiring import contexts

SOURCE = Path(__file__).resolve().parents[3] / "src" / "apex" / "cli" / "commands"
REPOSITORY = Path(__file__).resolve().parents[3]


def context(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot | None = None
) -> contexts.Context:
    return contexts.Context(
        settings=loader.load(host_file=None, environment={}),
        repository=safepaths.SourceRoot.adopt(REPOSITORY),
        root=root,
        environment={},
        bundle=lambda _root: ports,
    )


def streams() -> tuple[io.StringIO, io.StringIO]:
    return io.StringIO(), io.StringIO()


def test_every_command_module_declares_one_command_and_the_registry_holds_them_all() -> None:
    modules = sorted(p.stem for p in SOURCE.glob("*.py") if not p.name.startswith("_"))

    assert len(commands.names()) == len(modules)
    assert commands.names() == (
        "build",
        "candidate",
        "check",
        "doctor",
        "evidence",
        "git-hook",
        "hardware",
        "hooks",
        "machine",
        "operate",
        "patch",
        "plan",
        "readiness",
        "record",
        "sources",
        "trust",
        "ventoy-media",
        "verify",
    )
    assert commands.lookup("no-such-command") is None


def test_a_registered_name_runs_as_a_command_and_the_document_goes_to_standard_output(
    ports: portset.HostPorts,
) -> None:
    out, err = streams()

    code = dispatch.run(
        ["plan", "artifact", "qcow2"], context_of=lambda: context(ports), stdout=out, stderr=err
    )

    assert code == 0
    assert '"name": "build-disk-artifact"' in out.getvalue()
    assert err.getvalue() == ""


def test_a_refusal_raised_by_a_command_keeps_its_exit_code_and_is_narrated(
    ports: portset.HostPorts, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refusing(request: commandspecs.Request) -> commandspecs.Reply:
        raise errors.Refusal(refusals.RefusalReason.UNKNOWN_SETTING, subject="x")

    monkeypatch.setattr(
        commands, "lookup", lambda name: commandspecs.Command(name="x", summary="s", run=refusing)
    )
    out, err = streams()

    code = dispatch.run(["x"], context_of=lambda: context(ports), stdout=out, stderr=err)

    assert code == errors.Refusal.exit_code
    assert "settings.unknown" in err.getvalue() and out.getvalue() == ""


def test_a_parser_that_stops_the_run_keeps_the_code_it_chose(
    ports: portset.HostPorts, capsys: pytest.CaptureFixture[str]
) -> None:
    out, err = streams()

    helped = dispatch.run(
        ["plan", "--help"], context_of=lambda: context(ports), stdout=out, stderr=err
    )
    wrong = dispatch.run(
        ["plan", "artifact", "floppy"], context_of=lambda: context(ports), stdout=out, stderr=err
    )

    assert helped == 0 and wrong == 2
    captured = capsys.readouterr()
    assert "usage: apex plan" in captured.out and "invalid choice" in captured.err


def test_a_name_nobody_owns_is_refused_with_the_names_that_exist(ports: portset.HostPorts) -> None:
    out, err = streams()

    code = dispatch.run(
        ["older-tool", "--json"], context_of=lambda: context(ports), stdout=out, stderr=err
    )
    empty = dispatch.run([], context_of=lambda: context(ports), stdout=out, stderr=err)

    assert code == errors.Refusal.exit_code and empty == errors.Refusal.exit_code
    assert "command.unknown: older-tool" in err.getvalue()
    assert "the commands are build, candidate" in err.getvalue()
    assert out.getvalue() == ""


def test_a_retired_name_is_refused_with_its_replacement(ports: portset.HostPorts) -> None:
    out, err = streams()

    code = dispatch.run(
        ["test-vm", "disk.qcow2"], context_of=lambda: context(ports), stdout=out, stderr=err
    )

    assert code == errors.Refusal.exit_code
    assert "command.retired" in err.getvalue()
    assert "apex machine start --role test" in err.getvalue()
    assert out.getvalue() == ""
