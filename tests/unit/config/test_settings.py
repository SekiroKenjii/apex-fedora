"""Settings are assembled once, validated once, then frozen.

Today `project.json` is re-parsed at all nine of its call sites, four of them inside one
function, and `checks.json` is re-read inside the loop that validates against it.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from apex.config import defaults, layers, loader, overrides
from apex.kernel import errors, quantities, refusals


def test_the_two_ssh_ports_are_declared_once_and_differ() -> None:
    assert defaults.BUILDER_SSH_PORT != defaults.GUEST_SSH_PORT


def test_the_capture_limit_matches_what_the_guest_probes_use() -> None:
    assert defaults.CAPTURE_LIMIT.value == 262144


def test_the_serial_chunk_is_declared_once_for_both_sides() -> None:
    assert defaults.SERIAL_CHUNK.value == 768


def test_the_builder_defaults_match_the_recorded_project_file() -> None:
    assert defaults.BUILDER.memory == quantities.Mib(6144)
    assert defaults.BUILDER.reserve == quantities.Mib(1536)
    assert defaults.BUILDER.processors == 4
    assert defaults.BUILDER.disk == quantities.Gib(160)
    assert defaults.BUILDER.minimum_free == quantities.Gib(180)


def test_settings_are_frozen_after_loading(tmp_path: Path) -> None:
    settings = loader.load(host_file=None, environment={})

    with pytest.raises(dataclasses.FrozenInstanceError):
        settings.builder = defaults.BUILDER  # type: ignore[misc]


def test_a_host_file_overrides_a_default(tmp_path: Path) -> None:
    host = tmp_path / "settings.toml"
    host.write_text("[builder]\nprocessors = 8\n")

    settings = loader.load(host_file=host, environment={})

    assert settings.builder.processors == 8
    assert settings.builder.memory == defaults.BUILDER.memory


def test_the_layer_that_supplied_a_value_is_recorded(tmp_path: Path) -> None:
    host = tmp_path / "settings.toml"
    host.write_text("[builder]\nprocessors = 8\n")

    settings = loader.load(host_file=host, environment={})

    assert settings.explain("builder.processors") == layers.Layer.HOST_FILE
    assert settings.explain("builder.memory") == layers.Layer.DEFAULT


def test_a_declared_environment_override_is_applied(tmp_path: Path) -> None:
    settings = loader.load(
        host_file=None, environment={"APEX_STATE_DIR": str(tmp_path / "runtime")}
    )

    assert settings.explain("runtime_root") == layers.Layer.ENVIRONMENT


def test_an_undeclared_apex_variable_is_a_hard_error(tmp_path: Path) -> None:
    with pytest.raises(errors.Refusal) as raised:
        loader.load(host_file=None, environment={"APEX_STATE_DIRR": "/tmp/typo"})

    assert raised.value.reason is refusals.RefusalReason.UNKNOWN_SETTING
    assert "APEX_STATE_DIRR" in str(raised.value)


def test_a_variable_outside_the_namespace_is_ignored(tmp_path: Path) -> None:
    settings = loader.load(host_file=None, environment={"HOME": "/root"})

    assert settings.builder.processors == defaults.BUILDER.processors


def test_an_unknown_key_in_the_host_file_is_refused(tmp_path: Path) -> None:
    host = tmp_path / "settings.toml"
    host.write_text("[builder]\nwishful = true\n")

    with pytest.raises(errors.Refusal) as raised:
        loader.load(host_file=host, environment={})

    assert "wishful" in str(raised.value)


def test_the_reserve_must_stay_below_the_total_memory(tmp_path: Path) -> None:
    host = tmp_path / "settings.toml"
    host.write_text("[builder]\nmemory_mib = 1024\nreserve_mib = 4096\n")

    with pytest.raises(errors.Refusal) as raised:
        loader.load(host_file=host, environment={})

    assert raised.value.reason is refusals.RefusalReason.INCONSISTENT_SETTINGS


def test_every_declared_override_names_the_field_it_sets() -> None:
    for descriptor in overrides.DECLARED:
        assert descriptor.variable.startswith("APEX_")
        assert descriptor.field


def test_explaining_an_unknown_field_is_refused(tmp_path: Path) -> None:
    settings = loader.load(host_file=None, environment={})

    with pytest.raises(errors.Refusal):
        settings.explain("builder.wishful")


@pytest.mark.parametrize("variable", sorted(overrides.TOOLING_VARIABLES))
def test_a_tooling_variable_is_neither_a_setting_nor_a_typo(variable: str) -> None:
    settings = loader.load(host_file=None, environment={variable: "anything"})

    assert settings.explain("runtime_root") is layers.Layer.DEFAULT


def test_the_firmware_paths_come_from_the_host_file_or_the_defaults(tmp_path: Path) -> None:
    host = tmp_path / "settings.toml"
    host.write_text('[builder]\nfirmware_code = "~/code.fd"\n')

    settings = loader.load(host_file=host, environment={})

    assert settings.builder.firmware_code == Path("~/code.fd").expanduser()
    assert settings.explain("builder.firmware_code") is layers.Layer.HOST_FILE
    assert settings.builder.firmware_variables == Path(defaults.BUILDER.firmware_variables)
    assert settings.explain("builder.firmware_variables") is layers.Layer.DEFAULT
