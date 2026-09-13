"""The ventoy-media command takes its six inputs, needs the builder, and replies with the medium."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest
import signedbundle
import ventoyinputs as inputs_support
from answeringguest import AnsweringGuest

from apex.cli import commandspecs
from apex.cli.commands import ventoy_media_command
from apex.config import defaults, loader
from apex.kernel import errors, refusals, safepaths
from apex.ports import portset
from apex.wiring import contexts


def request(
    ports: portset.HostPorts,
    root: safepaths.RuntimeRoot,
    repository: safepaths.SourceRoot,
    *arguments: str,
) -> commandspecs.Request:
    return commandspecs.Request(
        arguments=arguments,
        context=contexts.Context(
            settings=loader.load(host_file=None, environment={}),
            repository=repository,
            root=root,
            environment={},
            bundle=lambda _root: ports,
        ),
    )


def options(laid: inputs_support.Laid) -> tuple[str, ...]:
    return (
        "--live-output",
        str(laid.live_output),
        "--ubuntu",
        str(laid.ubuntu),
        "--trusted-key",
        str(laid.trusted_key),
        "--checksums",
        str(laid.checksums),
        "--signature",
        str(laid.signature),
        "--keyring",
        str(laid.keyring),
    )


def test_without_the_builder_running_the_medium_is_refused_before_any_input_is_read(
    tmp_path: Path,
) -> None:
    base = tmp_path / "runtime"
    base.mkdir(mode=0o700)
    (base / defaults.BUILDER_KEY_NAME).write_bytes(b"key")
    (base / defaults.AGENT_WHEEL_NAME).write_bytes(b"wheel")
    root = safepaths.RuntimeRoot.adopt(base)
    ports = signedbundle.real_files_bundle()
    private, public = signedbundle.keys(ports, root)
    laid = inputs_support.lay_out(ports, root, private, public)
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    inputs_support.write_lock(checkout)
    held = dataclasses.replace(ports, guest=AnsweringGuest({}), downloads=inputs_support.fetcher())

    with pytest.raises(errors.Refusal) as refused:
        ventoy_media_command.run(
            request(held, root, safepaths.SourceRoot.adopt(checkout), *options(laid))
        )
    with pytest.raises(SystemExit):
        ventoy_media_command.run(request(held, root, safepaths.SourceRoot.adopt(checkout)))

    assert refused.value.reason is refusals.RefusalReason.MACHINE_NOT_RUNNING
    downloads = held.downloads
    assert getattr(downloads, "fetched", None) == []


def test_the_recipe_declares_the_six_operand_justfile_recipe_it_always_had() -> None:
    recipe = ventoy_media_command.RECIPES[0]

    assert recipe.name == "ventoy-media"
    assert recipe.parameters == (
        "live_output",
        "ubuntu",
        "trusted_key",
        "checksums",
        "signature",
        "keyring",
    )
    assert recipe.argv[0] == "ventoy-media"
    assert recipe.argv[1:3] == ("--live-output", "{{live_output}}")
