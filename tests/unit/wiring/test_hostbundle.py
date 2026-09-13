"""The composition root assembles real adapters only, and finds the root the settings name."""

from __future__ import annotations

import dataclasses
from pathlib import Path

from apex.adapters.real import real_serialshell
from apex.kernel import claims, safepaths
from apex.wiring import hostbundle


def test_every_member_of_the_host_bundle_is_a_real_adapter(tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    bundle = hostbundle.bundle(safepaths.RuntimeRoot.adopt(tmp_path))

    assert bundle.environment is claims.EnvironmentKind.BUILD
    for field in dataclasses.fields(bundle):
        member = getattr(bundle, field.name)
        assert type(member).__module__.startswith("apex.adapters.real."), field.name


def test_an_overridden_runtime_root_is_resolved_where_the_operator_pointed(
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)

    loaded = hostbundle.load({"APEX_STATE_DIR": str(runtime)})

    assert loaded.root is not None and loaded.root.path == runtime.resolve()
    context = hostbundle.context({"APEX_STATE_DIR": str(runtime)})
    assert context.root == loaded.root
    assert context.repository.path == hostbundle.REPOSITORY


def test_a_root_that_does_not_exist_is_none_rather_than_a_refusal(tmp_path: Path) -> None:
    loaded = hostbundle.load({"APEX_STATE_DIR": str(tmp_path / "absent")})

    assert loaded.root is None


def test_the_serial_shell_the_root_wires_is_the_real_one_for_the_leased_process(
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    context = hostbundle.context({"APEX_STATE_DIR": str(runtime)})

    console = context.serial(safepaths.SafePath(runtime / "serial.sock"), 4242)

    assert isinstance(console, real_serialshell.SerialGuestShell)
    assert console.expected_process == 4242
    assert console.environment is claims.EnvironmentKind.BUILD
