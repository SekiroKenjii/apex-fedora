"""The hardware command: a snapshot kept under the root, a coefficient decoded on paper."""

from __future__ import annotations

from pathlib import Path

import pytest

from apex.cli import commandspecs
from apex.cli.commands import hardware_command
from apex.config import loader
from apex.kernel import errors, refusals, safepaths
from apex.ports import portset
from apex.wiring import contexts

REPOSITORY = Path(__file__).resolve().parents[3]


def request(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot | None, *arguments: str
) -> commandspecs.Request:
    return commandspecs.Request(
        arguments=arguments,
        context=contexts.Context(
            settings=loader.load(host_file=None, environment={}),
            repository=safepaths.SourceRoot.adopt(REPOSITORY),
            root=root,
            environment={},
            bundle=lambda _root: ports,
        ),
    )


def test_a_coefficient_is_decoded_without_a_root_or_a_device(ports: portset.HostPorts) -> None:
    reply = hardware_command.run(request(ports, None, "decode-coefficient", "0x20", "0x500", "0x0"))

    assert reply.exit_code == 0
    assert reply.document == {
        "nid": "0x20", "hwdep_word": "0x20050000", "canonical_verb": "0x500",
        "effective_parameter": "0x0000", "parameter_changed_by_overlap": False,
        "device_access": False,
    }


def test_a_snapshot_lands_under_the_root_and_needs_one(
    ports: portset.HostPorts, tmp_path: Path
) -> None:
    base = tmp_path / "runtime"
    base.mkdir(mode=0o700)
    root = safepaths.RuntimeRoot.adopt(base)

    reply = hardware_command.run(request(ports, root, "snapshot"))
    with pytest.raises(errors.PreconditionUnmet) as refused:
        hardware_command.run(request(ports, None, "snapshot"))

    assert isinstance(reply.document, dict)
    written = Path(str(reply.document["observations"]))
    assert written.parent.parent == base / "hardware-observations"
    assert written.name == "observations.json"
    assert ports.files.exists(safepaths.SafePath(written))
    assert refused.value.reason is refusals.RefusalReason.PATH_NOT_A_DIRECTORY


def test_an_unknown_action_stops_at_the_parser(ports: portset.HostPorts) -> None:
    with pytest.raises(SystemExit):
        hardware_command.run(request(ports, None, "reboot"))
