"""One engine, two programs: what an image is, what it holds, and what a run inside it says."""

from __future__ import annotations

import pytest

from apex.adapters.fakes import fake_containers
from apex.kernel import commands, errors, identifiers, safepaths
from apex.ports import containers

IMAGE = "localhost/apex:fedora"


def test_an_image_has_one_identity(engines: containers.ContainerEnginePort) -> None:
    assert engines.image_id(IMAGE) == identifiers.ImageId("a" * 64)


def test_an_image_that_is_not_there_is_a_port_failure(
    engines: containers.ContainerEnginePort,
) -> None:
    with pytest.raises(errors.PortFailure):
        engines.image_id("localhost/apex:absent")


def test_the_manifest_is_the_raw_bytes(engines: containers.ContainerEnginePort) -> None:
    payload = engines.manifest(containers.ImageReference.stored(IMAGE))

    assert payload == b'{"schemaVersion": 2}'


def test_a_run_inside_the_image_reports_its_output_and_exit(
    engines: containers.ContainerEnginePort,
) -> None:
    listing = engines.run(
        containers.RunRequest(image=IMAGE, argv=commands.Argv.of("rpm", "-qa"), read_only=True)
    )
    failing = engines.run(containers.RunRequest(image=IMAGE, argv=commands.Argv.of("false")))

    assert listing.succeeded
    assert listing.stdout == b"bash-5\n"
    assert not failing.succeeded


def test_a_build_and_a_copy_are_accepted_and_recorded(
    engines: containers.ContainerEnginePort, root: safepaths.RuntimeRoot
) -> None:
    context = root.child("context")
    engines.build(containers.BuildRequest(context=context, tag="localhost/apex-recovery:a"))
    engines.copy(
        containers.ImageReference.stored(IMAGE),
        containers.ImageReference(containers.Transport.DIRECTORY, str(root.child("bundle/a"))),
        policy=None,
        signing=None,
    )

    if isinstance(engines, fake_containers.FakeRegistry):
        assert [item.tag for item in engines.builds] == ["localhost/apex-recovery:a"]
        assert len(engines.copies) == 1


def test_the_running_container_listing_is_json(engines: containers.ContainerEnginePort) -> None:
    assert engines.running_containers().strip() == b"[]"
