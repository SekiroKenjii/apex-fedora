"""The check command runs the checks in order, names each verdict, and fails when one does."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from apex.adapters.fakes import fake_files, fake_process
from apex.cli import commandspecs
from apex.cli.commands import check_command
from apex.config import loader
from apex.kernel import errors, refusals, safepaths
from apex.ports import portset
from apex.wiring import contexts

REPOSITORY = Path(__file__).resolve().parents[3]
TOOL_CHECKS = ("format", "lint", "types", "pyright", "deadcode", "duplicates", "imports")


class Replying(fake_process.ScriptedProcess):
    def __init__(self, failing: frozenset[str] = frozenset()) -> None:
        super().__init__()
        self.failing = failing

    def run(self, argv: Any, **keywords: Any) -> Any:
        vector = tuple(str(item) for item in argv)
        failing = any(word in self.failing for word in vector)
        self.expect(
            vector,
            fake_process.Reply(
                exit_code=1 if failing else 0, stderr=b"broken\n" if failing else b""
            ),
        )
        return super().run(argv, **keywords)


def request(
    ports: portset.HostPorts, processes: fake_process.ScriptedProcess, *arguments: str
) -> commandspecs.Request:
    return commandspecs.Request(
        arguments=arguments,
        context=contexts.Context(
            settings=loader.load(host_file=None, environment={}),
            repository=safepaths.SourceRoot.adopt(REPOSITORY),
            root=None,
            environment={},
            bundle=lambda _root: ports,
            processes=processes,
            filesystem=fake_files.MemoryFiles(),
        ),
    )


def test_the_tool_checks_run_in_order_and_every_verdict_is_named(ports: portset.HostPorts) -> None:
    processes = Replying()

    reply = check_command.run(
        request(ports, processes, *(word for name in TOOL_CHECKS for word in ("--only", name)))
    )

    assert reply.exit_code == 0
    assert isinstance(reply.document, dict) and reply.document["status"] == "PASS"
    assert [item["id"] for item in reply.document["checks"]] == list(TOOL_CHECKS)  # type: ignore[index,union-attr]
    assert reply.narrative.splitlines()[:2] == ["format: PASS", "lint: PASS"]
    assert len(processes.calls) == len(TOOL_CHECKS)


def test_one_failing_check_fails_the_command_and_its_words_are_in_the_narrative(
    ports: portset.HostPorts,
) -> None:
    processes = Replying(frozenset({"--strict"}))

    reply = check_command.run(request(ports, processes, "--only", "lint", "--only", "types"))

    assert reply.exit_code == 1
    assert isinstance(reply.document, dict) and reply.document["status"] == "FAIL"
    assert "types: FAIL" in reply.narrative and "broken" in reply.narrative
    assert len(processes.calls) == 2


def test_the_list_names_every_check_in_order_and_runs_none(ports: portset.HostPorts) -> None:
    processes = Replying()

    reply = check_command.run(request(ports, processes, "--list"))

    assert isinstance(reply.document, dict)
    listed = reply.document["checks"]
    assert isinstance(listed, list) and len(listed) == 10
    assert [item["id"] for item in listed][:2] == ["format", "lint"]  # type: ignore[index]
    assert processes.calls == []


def test_a_check_nobody_declared_is_refused_by_name(ports: portset.HostPorts) -> None:
    with pytest.raises(errors.Refusal) as raised:
        check_command.run(request(ports, Replying(), "--only", "spelling"))

    assert raised.value.reason is refusals.RefusalReason.UNIT_UNKNOWN


def test_the_recipe_is_the_bare_command() -> None:
    assert [(r.name, r.parameters, r.argv) for r in check_command.RECIPES] == [
        ("check", (), ("check",))
    ]
