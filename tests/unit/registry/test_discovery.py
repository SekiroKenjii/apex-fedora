"""Discovery is eager, ordered, and cannot touch the world."""

from __future__ import annotations

import pytest

from apex.kernel import commands, errors, timing
from apex.registry import discovery


def test_refusing_ports_refuse_a_process_run() -> None:
    ports = discovery.RefusingPorts()

    with pytest.raises(errors.InternalDefect):
        ports.processes.run(
            commands.Argv.of("echo", "hi"),
            deadline=timing.Deadline(timing.Elapsed(1)),
            limit=commands.OutputLimit.default(),
        )


def test_refusing_ports_refuse_a_file_read() -> None:
    ports = discovery.RefusingPorts()

    with pytest.raises(errors.InternalDefect):
        ports.files.read_bytes(None, limit=1)  # type: ignore[arg-type]


def test_refusing_ports_refuse_the_clock() -> None:
    ports = discovery.RefusingPorts()

    with pytest.raises(errors.InternalDefect):
        ports.clock.now()


def test_refusing_ports_refuse_identity() -> None:
    ports = discovery.RefusingPorts()

    with pytest.raises(errors.InternalDefect):
        ports.identities.run_id()


def test_a_refusal_names_what_was_attempted() -> None:
    ports = discovery.RefusingPorts()

    with pytest.raises(errors.InternalDefect) as raised:
        ports.clock.sleep(timing.Elapsed(1))

    assert "import" in str(raised.value).lower()


def test_module_names_are_walked_in_sorted_order() -> None:
    walked = discovery.module_names("apex.kernel")

    assert walked == sorted(walked)
    assert "apex.kernel.verdicts" in walked


def test_walking_an_absent_package_is_empty() -> None:
    assert discovery.module_names("apex.no_such_package") == []


def test_discovery_imports_every_module_in_the_namespace() -> None:
    imported = discovery.discover(["apex.kernel"])

    assert "apex.kernel.identifiers" in imported
    assert imported == sorted(imported)
