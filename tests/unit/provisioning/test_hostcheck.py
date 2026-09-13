"""The host examined through the ports: every finding in one report, every shortfall named."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from apex.adapters.fakes import fake_files, fake_hypervisor, fake_process
from apex.config import defaults, loader
from apex.kernel import quantities, refusals, safepaths
from apex.ports import hypervisor, portset
from apex.provisioning import hostcheck


@pytest.fixture
def root(tmp_path: Path) -> safepaths.RuntimeRoot:
    base = tmp_path / "runtime"
    base.mkdir(mode=0o700)
    return safepaths.RuntimeRoot.adopt(base)


def settings(tmp_path: Path) -> loader.Settings:
    host = tmp_path / "settings.toml"
    host.write_text(
        f'[builder]\nfirmware_code = "{tmp_path}/OVMF_CODE.fd"\n'
        f'firmware_variables = "{tmp_path}/OVMF_VARS.fd"\n'
    )
    return loader.load(host_file=host, environment={})


def bundle(
    ports: portset.HostPorts,
    *,
    tools: tuple[str, ...] = defaults.HOST_TOOLS,
    firmware: bool = True,
    capacity: hypervisor.HostCapacity = fake_hypervisor.AMPLE,
    tmp_path: Path,
) -> portset.HostPorts:
    filesystem = fake_files.MemoryFiles()
    if firmware:
        for name in ("OVMF_CODE.fd", "OVMF_VARS.fd"):
            filesystem.write_atomic(
                safepaths.SafePath(tmp_path / name), b"firmware", mode=defaults.RECORD_MODE
            )
    return dataclasses.replace(
        ports,
        files=filesystem,
        processes=fake_process.ScriptedProcess(
            known={name: Path("/usr/bin") / name for name in tools}
        ),
        hypervisor=fake_hypervisor.FakeQemu(capacity=capacity),
    )


def test_a_ready_host_reports_everything_it_has_and_no_problem(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot, tmp_path: Path
) -> None:
    report = hostcheck.examine(bundle(ports, tmp_path=tmp_path), settings(tmp_path), root)

    assert report.problems() == ()
    document = report.document()
    assert document["tools"] == {name: f"/usr/bin/{name}" for name in defaults.HOST_TOOLS}
    assert document["kvm"] is True and document["firmware"] is True
    assert document["available_memory_mib"] == 16384
    assert (
        document["required_memory_mib"]
        == (defaults.BUILDER.memory + defaults.BUILDER.reserve).value
    )
    assert document["free_gib"] == 500
    assert document["required_free_gib"] == defaults.BUILDER.minimum_free.value
    assert document["state"] == str(root.path) and document["vm"] is None


def test_every_shortfall_is_named_in_the_order_the_older_tool_checked(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot, tmp_path: Path
) -> None:
    short = hypervisor.HostCapacity(
        available_memory=quantities.Mib(1024),
        free_space=quantities.Gib(2).as_bytes(),
        kvm_accessible=False,
    )
    held = bundle(ports, tools=("python3", "uv"), firmware=False, capacity=short, tmp_path=tmp_path)

    problems = hostcheck.examine(held, settings(tmp_path), root).problems()

    assert [problem.reason for problem in problems] == [
        refusals.RefusalReason.HOST_TOOL_MISSING,
        refusals.RefusalReason.FIRMWARE_ABSENT,
        refusals.RefusalReason.HOST_CAPACITY_INSUFFICIENT,
        refusals.RefusalReason.HOST_CAPACITY_INSUFFICIENT,
        refusals.RefusalReason.HOST_CAPACITY_INSUFFICIENT,
    ]
    assert "curl, qemu-img, qemu-system-x86_64, ssh, ssh-keygen" in str(problems[0])
    assert "found 1024 MiB" in str(problems[2])
    assert "found 2 GiB" in str(problems[3])
    assert "kvm" in str(problems[4])
