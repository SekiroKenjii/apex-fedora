"""The builder's storage is made once, piece by piece, and left alone after."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest
from storagefixtures import PUBLIC_KEY, Storage

from apex.adapters.fakes import fake_downloading
from apex.adapters.real import real_files
from apex.config import loader
from apex.generating import builderseed
from apex.kernel import errors, hashing, identifiers, locators, quantities, refusals, safepaths
from apex.model import machines, sourcelock
from apex.ports import portset
from apex.provisioning import builderprepare, launching

BODY = b"qcow2 base image bytes"
URL = "https://example.invalid/base.qcow2"
RUN = identifiers.RunId("a" * 32)


def base() -> sourcelock.LockedSource:
    return sourcelock.LockedSource(
        name="base_image",
        url=locators.HttpsUrl(URL),
        sha256=hashing.digest_bytes(BODY),
        filename=locators.Basename("builder-base.qcow2"),
        commit=None,
    )


@pytest.fixture
def root(tmp_path: Path) -> safepaths.RuntimeRoot:
    directory = tmp_path / "runtime"
    directory.mkdir(mode=0o700)
    return safepaths.RuntimeRoot.adopt(directory)


def settings(tmp_path: Path) -> loader.Settings:
    for name in ("OVMF_CODE.fd", "OVMF_VARS.fd"):
        (tmp_path / name).write_bytes(name.encode())
    host = tmp_path / "settings.toml"
    host.write_text(
        f'[builder]\nfirmware_code = "{tmp_path}/OVMF_CODE.fd"\n'
        f'firmware_variables = "{tmp_path}/OVMF_VARS.fd"\n'
    )
    return loader.load(host_file=host, environment={})


def bundle(ports: portset.HostPorts, process: Storage) -> portset.HostPorts:
    return dataclasses.replace(
        ports,
        files=real_files.LocalFiles(),
        downloads=fake_downloading.OfflineFetcher({URL: BODY}),
        processes=process,
    )


def prepare(
    held: portset.HostPorts, root: safepaths.RuntimeRoot, tmp_path: Path
) -> builderprepare.Prepared:
    return builderprepare.prepare(held, settings(tmp_path), root, base=base(), instance=RUN)


def test_a_fresh_root_gets_every_piece_and_says_so(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot, tmp_path: Path
) -> None:
    process = Storage()
    held = bundle(ports, process)

    prepared = prepare(held, root, tmp_path)

    assert prepared.document() == {
        "base": str(root.path / "builder-base.qcow2"),
        "base_fetched": True,
        "disk_created": True,
        "key_created": True,
        "seed_created": True,
        "variables_copied": True,
    }
    assert (root.path / "builder-base.qcow2").read_bytes() == BODY
    calls = [tuple(call) for call in process.calls]
    assert (
        "qemu-img",
        "create",
        "-f",
        "qcow2",
        "-F",
        "qcow2",
        "-b",
        str(root.path / "builder-base.qcow2"),
        str(root.path / "builder.qcow2"),
        "160G",
    ) in calls
    assert (
        "ssh-keygen",
        "-q",
        "-t",
        "ed25519",
        "-N",
        "",
        "-C",
        "apex-local-builder",
        "-f",
        str(root.path / "builder_ed25519"),
    ) in calls
    assert (root.path / "seed.iso").read_bytes() == builderseed.seed(PUBLIC_KEY, RUN)
    assert (root.path / "user-data").read_bytes() == builderseed.user_data(PUBLIC_KEY)
    assert (root.path / "meta-data").read_bytes() == builderseed.meta_data(RUN)
    assert (root.path / "builder-vars.fd").read_bytes() == b"OVMF_VARS.fd"
    assert (root.path / "seed.iso").stat().st_mode & 0o777 == 0o600


def test_a_second_run_leaves_everything_alone(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot, tmp_path: Path
) -> None:
    process = Storage()
    held = bundle(ports, process)
    prepare(held, root, tmp_path)
    seed = (root.path / "seed.iso").read_bytes()

    prepared = prepare(held, root, tmp_path)

    assert prepared.document() == {
        "base": str(root.path / "builder-base.qcow2"),
        "base_fetched": False,
        "disk_created": False,
        "key_created": False,
        "seed_created": False,
        "variables_copied": False,
    }
    fetcher = held.downloads
    assert isinstance(fetcher, fake_downloading.OfflineFetcher)
    assert fetcher.fetched == [URL]
    assert [call.arguments[0] for call in process.calls].count("ssh-keygen") == 1
    assert [tuple(call)[:2] for call in process.calls].count(("qemu-img", "create")) == 1
    assert (root.path / "seed.iso").read_bytes() == seed


def test_a_running_machine_refuses_before_anything_is_fetched(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot, tmp_path: Path
) -> None:
    held = bundle(ports, Storage())
    present = {}
    for name in ("disk.qcow2", "code.fd", "vars.fd"):
        (root.path / name).write_bytes(b"")
        present[name] = safepaths.SafePath.regular_file(root.path / name, within=root)
    run_directory = root.child(f"vm-runs/{RUN}")
    run_directory.path.mkdir(parents=True)
    launching.launch(
        held,
        root=root,
        spec=machines.VmSpec.build(
            role=machines.VmRole.TEST,
            resources=machines.VmResources(memory=quantities.Mib(1024), processors=1),
            root_disk=present["disk.qcow2"],
            firmware=machines.Firmware(code=present["code.fd"], variables=present["vars.fd"]),
            monitor=machines.MonitorSocket(root.child("qmp.sock")),
            serial=machines.SerialFile(root.child("serial.log")),
        ),
        run=RUN,
        run_directory=run_directory,
    )

    with pytest.raises(errors.Refusal) as caught:
        prepare(held, root, tmp_path)

    assert caught.value.reason is refusals.RefusalReason.MACHINE_RUNNING
    fetcher = held.downloads
    assert isinstance(fetcher, fake_downloading.OfflineFetcher)
    assert fetcher.fetched == []


def test_a_base_with_a_backing_file_is_refused_before_the_disk_is_made(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot, tmp_path: Path
) -> None:
    process = Storage(backing="other.qcow2")
    (root.path / "other.qcow2").write_bytes(b"")

    with pytest.raises(errors.Refusal) as caught:
        prepare(bundle(ports, process), root, tmp_path)

    assert caught.value.reason is refusals.RefusalReason.DISK_NOT_STANDALONE
    assert not (root.path / "builder.qcow2").exists()


def test_a_key_that_cannot_be_generated_fails_the_port(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot, tmp_path: Path
) -> None:
    with pytest.raises(errors.PortFailure) as caught:
        prepare(bundle(ports, Storage(keygen_exit=1)), root, tmp_path)

    assert caught.value.port == "ssh-keygen"
    assert not (root.path / "seed.iso").exists()
