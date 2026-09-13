"""The builder machine is described from the settings and the files under the runtime root."""

from __future__ import annotations

from pathlib import Path

import pytest

from apex.config import loader
from apex.kernel import errors, refusals, safepaths
from apex.model import machines
from apex.provisioning import builderspec


def prepared(tmp_path: Path) -> tuple[loader.Settings, safepaths.RuntimeRoot]:
    base = tmp_path / "runtime"
    base.mkdir(mode=0o700)
    for name in ("builder.qcow2", "seed.iso", "builder-vars.fd"):
        (base / name).write_bytes(b"")
    code = tmp_path / "OVMF_CODE.fd"
    code.write_bytes(b"")
    host = tmp_path / "settings.toml"
    host.write_text(f'[builder]\nfirmware_code = "{code}"\nprocessors = 2\n')
    return loader.load(host_file=host, environment={}), safepaths.RuntimeRoot.adopt(base)


def test_the_builder_attaches_its_disk_seed_firmware_and_loopback_ssh(tmp_path: Path) -> None:
    settings, root = prepared(tmp_path)

    spec = builderspec.spec(settings, root)

    rendered = list(spec.render())
    assert spec.role is machines.VmRole.BUILDER
    assert spec.resources.processors == 2
    assert f"if=virtio,format=qcow2,file={root.path}/builder.qcow2,discard=unmap" in rendered
    assert any("seed.iso" in item for item in rendered)
    assert any(f"file={tmp_path}/OVMF_CODE.fd" in item for item in rendered)
    assert any("hostfwd=tcp:127.0.0.1:22244-:22" in item for item in rendered)


def test_a_missing_disk_is_refused_before_anything_is_rendered(tmp_path: Path) -> None:
    settings, root = prepared(tmp_path)
    (root.path / "builder.qcow2").unlink()

    with pytest.raises(errors.Refusal) as raised:
        builderspec.spec(settings, root)

    assert raised.value.reason is refusals.RefusalReason.PATH_NOT_A_REGULAR_FILE
