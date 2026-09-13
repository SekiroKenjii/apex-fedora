"""Every overlay against its source, and the firmware variables against their baseline."""

from __future__ import annotations

import pytest
from machinehost import RUN, Host

from apex.adapters.fakes import fake_process
from apex.config import defaults
from apex.kernel import errors, quantities, refusals, safepaths
from apex.provisioning import backingchain, comparing, launching

PRIVATE = quantities.FileMode(0o600)


def chain(host: Host, name: str) -> backingchain.BackingChain:
    target = host.root.path / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"")
    return backingchain.BackingChain((safepaths.SafePath.regular_file(target, within=host.root),))


def variables(host: Host, *, initial: bytes, final: bytes) -> None:
    host.files.write_atomic(
        safepaths.SafePath(host.run_directory.path / defaults.INITIAL_VARIABLES_NAME),
        initial,
        mode=PRIVATE,
    )
    host.files.write_atomic(
        safepaths.SafePath(host.run_directory.path / defaults.VARIABLES_NAME), final, mode=PRIVATE
    )


def expect_compare(
    host: Host, source: str, overlay: str, *, exit_code: int, output: bytes = b""
) -> None:
    host.processes.expect(
        (
            "qemu-img",
            "compare",
            "-f",
            "qcow2",
            "-F",
            "qcow2",
            str(host.root.path / source),
            str(host.root.path / overlay),
        ),
        fake_process.Reply(exit_code=exit_code, stdout=output),
    )


def test_each_disk_is_compared_and_the_record_is_written(host: Host) -> None:
    variables(host, initial=b"vars", final=b"vars")
    expect_compare(
        host,
        "base.qcow2",
        f"vm-runs/{RUN}/disk.qcow2",
        exit_code=0,
        output=b"Images are identical.",
    )
    expect_compare(
        host,
        "other.qcow2",
        f"vm-runs/{RUN}/other-1.qcow2",
        exit_code=1,
        output=b"Content mismatch at offset 0!",
    )

    comparison = comparing.compare(
        host.ports,
        root=host.root,
        run_directory=host.run_directory,
        disks=(
            comparing.Layered(chain(host, "base.qcow2"), chain(host, f"vm-runs/{RUN}/disk.qcow2")),
            comparing.Layered(
                chain(host, "other.qcow2"), chain(host, f"vm-runs/{RUN}/other-1.qcow2")
            ),
        ),
    )

    assert [item.unchanged for item in comparison.disks] == [True, False]
    assert comparison.variables_unchanged
    assert str(host.run_directory.path / defaults.COMPARISON_RECORD) in host.files.writes


def test_changed_firmware_variables_are_reported(host: Host) -> None:
    variables(host, initial=b"before", final=b"after")

    comparison = comparing.compare(
        host.ports, root=host.root, run_directory=host.run_directory, disks=()
    )

    assert not comparison.variables_unchanged


def test_a_tool_failure_is_neither_changed_nor_unchanged(host: Host) -> None:
    variables(host, initial=b"vars", final=b"vars")
    expect_compare(host, "base.qcow2", f"vm-runs/{RUN}/disk.qcow2", exit_code=2)

    with pytest.raises(errors.PortFailure):
        comparing.compare(
            host.ports,
            root=host.root,
            run_directory=host.run_directory,
            disks=(
                comparing.Layered(
                    chain(host, "base.qcow2"), chain(host, f"vm-runs/{RUN}/disk.qcow2")
                ),
            ),
        )


def test_a_running_machine_blocks_the_comparison(host: Host) -> None:
    launching.launch(
        host.ports, root=host.root, spec=host.spec(), run=RUN, run_directory=host.run_directory
    )

    with pytest.raises(errors.Refusal) as raised:
        comparing.compare(host.ports, root=host.root, run_directory=host.run_directory, disks=())

    assert raised.value.reason is refusals.RefusalReason.MACHINE_RUNNING
