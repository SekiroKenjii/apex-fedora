"""The doctor replies with the whole report, and with a refusal's exit code on any shortfall."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from apex.adapters.fakes import fake_files, fake_hypervisor, fake_process
from apex.cli import commandspecs
from apex.cli.commands import doctor_command
from apex.config import defaults, loader
from apex.kernel import errors, quantities, refusals, safepaths
from apex.ports import hypervisor, portset
from apex.wiring import contexts

REPOSITORY = Path(__file__).resolve().parents[3]


def settings(tmp_path: Path) -> loader.Settings:
    host = tmp_path / "settings.toml"
    host.write_text(
        f'[builder]\nfirmware_code = "{tmp_path}/OVMF_CODE.fd"\n'
        f'firmware_variables = "{tmp_path}/OVMF_VARS.fd"\n'
    )
    return loader.load(host_file=host, environment={})


def request(
    ports: portset.HostPorts, tmp_path: Path, root: safepaths.RuntimeRoot | None
) -> commandspecs.Request:
    return commandspecs.Request(
        arguments=(),
        context=contexts.Context(
            settings=settings(tmp_path),
            repository=safepaths.SourceRoot.adopt(REPOSITORY),
            root=root,
            environment={},
            bundle=lambda _root: ports,
        ),
    )


def bundle(
    ports: portset.HostPorts, tmp_path: Path, *, tools: tuple[str, ...], kvm: bool
) -> portset.HostPorts:
    filesystem = fake_files.MemoryFiles()
    for name in ("OVMF_CODE.fd", "OVMF_VARS.fd"):
        filesystem.write_atomic(
            safepaths.SafePath(tmp_path / name), b"firmware", mode=defaults.RECORD_MODE
        )
    capacity = hypervisor.HostCapacity(
        available_memory=quantities.Mib(16384),
        free_space=quantities.Gib(500).as_bytes(),
        kvm_accessible=kvm,
    )
    return dataclasses.replace(
        ports,
        files=filesystem,
        processes=fake_process.ScriptedProcess(
            known={name: Path("/usr/bin") / name for name in tools}
        ),
        hypervisor=fake_hypervisor.FakeQemu(capacity=capacity),
    )


def test_a_ready_host_gets_its_report_and_exit_zero(
    ports: portset.HostPorts, tmp_path: Path
) -> None:
    base = tmp_path / "runtime"
    base.mkdir(mode=0o700)
    root = safepaths.RuntimeRoot.adopt(base)
    held = bundle(ports, tmp_path, tools=defaults.HOST_TOOLS, kvm=True)

    reply = doctor_command.run(request(held, tmp_path, root))

    assert reply.exit_code == 0 and reply.narrative == ""
    assert isinstance(reply.document, dict)
    assert reply.document["firmware"] is True and reply.document["kvm"] is True
    assert reply.document["state"] == str(base)


def test_a_short_host_still_gets_its_report_with_every_problem_and_a_refusal_s_code(
    ports: portset.HostPorts, tmp_path: Path
) -> None:
    base = tmp_path / "runtime"
    base.mkdir(mode=0o700)
    root = safepaths.RuntimeRoot.adopt(base)
    held = bundle(ports, tmp_path, tools=("python3",), kvm=False)

    reply = doctor_command.run(request(held, tmp_path, root))

    assert reply.exit_code == errors.Refusal.exit_code
    assert isinstance(reply.document, dict) and reply.document["kvm"] is False
    lines = reply.narrative.splitlines()
    assert lines[0].startswith(str(refusals.RefusalReason.HOST_TOOL_MISSING))
    assert lines[-1].startswith(str(refusals.RefusalReason.HOST_CAPACITY_INSUFFICIENT))
    assert "kvm" in lines[-1]


def test_without_a_runtime_root_there_is_nothing_to_examine(
    ports: portset.HostPorts, tmp_path: Path
) -> None:
    with pytest.raises(errors.PreconditionUnmet) as refused:
        doctor_command.run(request(ports, tmp_path, None))

    assert refused.value.reason is refusals.RefusalReason.PATH_NOT_A_DIRECTORY
