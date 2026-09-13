"""The Ventoy medium on fakes: inputs proven on the host, the builder asked once, medium bound."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest
import signedbundle
import ventoyinputs as inputs_support
from answeringguest import AnsweringGuest

from apex.composition import keys as composition_keys
from apex.config import defaults
from apex.kernel import refusals, safepaths
from apex.ports import guestshell, portset
from apex.provisioning.fixtures import ventoy_fixture
from apex.verification import ventoymedia, verifykeys
from apex.verification.recipes import ventoy_media_recipe


class MediumGuest(AnsweringGuest):
    """Answers the fixture unit with its report and lands the medium on the disk when received."""

    def __init__(self, image: bytes = inputs_support.MEDIUM) -> None:
        super().__init__({"fixture.ventoy": inputs_support.report(inputs_support.request_files())})
        self.image = image

    def receive(
        self,
        target: guestshell.GuestTarget,
        *,
        remote: safepaths.RemotePath,
        into: safepaths.SafePath,
        recursive: bool,
        deadline: Any,
    ) -> None:
        super().receive(target, remote=remote, into=into, recursive=recursive, deadline=deadline)
        output = into.path / "output"
        output.mkdir(parents=True, exist_ok=True)
        (output / ventoy_fixture.IMAGE).write_bytes(self.image)
        (output / ventoy_fixture.REPORT_NAME).write_text(json.dumps(self.answers["fixture.ventoy"]))


@pytest.fixture
def root(tmp_path: Path) -> safepaths.RuntimeRoot:
    base = tmp_path / "runtime"
    base.mkdir(mode=0o700)
    (base / "builder_ed25519").write_bytes(b"")
    (base / "apex-agent.whl").write_bytes(b"not a wheel")
    return safepaths.RuntimeRoot.adopt(base)


@pytest.fixture
def repository(tmp_path: Path) -> safepaths.SourceRoot:
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    inputs_support.write_lock(checkout)
    return safepaths.SourceRoot.adopt(checkout)


def builder(root: safepaths.RuntimeRoot) -> guestshell.GuestTarget:
    return guestshell.GuestTarget(
        user=defaults.BUILDER_USER,
        port=defaults.BUILDER_SSH_PORT,
        key=safepaths.SafePath.regular_file(root.path / "builder_ed25519", within=root),
        known_hosts=root.child(defaults.KNOWN_HOSTS_NAME),
    )


def prepare(
    root: safepaths.RuntimeRoot,
    repository: safepaths.SourceRoot,
    guest: MediumGuest,
    *,
    gpgv: inputs_support.Gpgv | None = None,
) -> tuple[Any, portset.HostPorts]:
    ports = signedbundle.real_files_bundle()
    private, public = signedbundle.keys(ports, root)
    laid = inputs_support.lay_out(ports, root, private, public)
    ports = dataclasses.replace(
        ports,
        processes=gpgv or inputs_support.Gpgv(),
        downloads=inputs_support.fetcher(),
        guest=guest,
    )
    outcome = ventoy_media_recipe.prepare(
        ports,
        builder=builder(root),
        wheel=safepaths.SafePath.regular_file(root.path / "apex-agent.whl", within=root),
        root=root,
        repository=repository,
        inputs=ventoymedia.Inputs(**dataclasses.asdict(laid)),
    )
    return outcome, ports


def test_the_plan_proves_the_inputs_before_the_work_and_binds_after_the_unit() -> None:
    order = [str(item) for item in ventoy_media_recipe.PLAN.order]

    assert order[:3] == ["builder.guard", "run.identify", "agent.deliver"]
    assert order.index("ventoy.inputs") < order.index("ventoy.work") < order.index("fixture.ventoy")
    assert order.index("fixture.ventoy") < order.index("ventoy.retrieve")
    assert not any(stage.attests for stage in ventoy_media_recipe.STAGES)


def test_the_builder_gets_the_request_and_the_three_inputs_and_the_medium_comes_home_bound(
    root: safepaths.RuntimeRoot, repository: safepaths.SourceRoot
) -> None:
    guest = MediumGuest()

    outcome, ports = prepare(root, repository, guest)

    assert outcome.succeeded, outcome.detail
    run = outcome.facts[composition_keys.RUN_ID]
    work = f"/var/tmp/apex-{run}/{defaults.VENTOY_WORK_DIRECTORY}"
    assert guest.asked == ["fixture.ventoy"]
    assert guest.requests[0]["arguments"] == {"work": work}
    assert [str(item.remote) for item in guest.sent][-4:] == [
        f"{work}/request.json",
        f"{work}/ventoy.tar.gz",
        f"{work}/Apex-Live.iso",
        f"{work}/Ubuntu.iso",
    ]
    assert [str(item.remote) for item in guest.received] == [f"{work}/output"]
    medium = outcome.facts[verifykeys.MEDIA]
    assert medium.path == root.path / "exports" / str(run) / "output" / ventoy_fixture.IMAGE
    execution = json.loads(
        (root.path / "exports" / str(run) / defaults.MEDIA_EXECUTION_NAME).read_text()
    )
    assert execution["status"] == "PASS" and execution["physical_usb_written"] is False
    assert execution["boot_acceptance"] == "NOT TESTED"
    retained = outcome.facts[verifykeys.retained_observation(ventoy_media_recipe.CASE)]
    assert retained.path.name == "fixture.ventoy.json"
    assert (root.path / "exports" / str(run) / ventoy_fixture.REQUEST_NAME).is_file()


def test_an_input_the_host_cannot_accept_stops_the_run_before_the_builder_is_asked(
    root: safepaths.RuntimeRoot, repository: safepaths.SourceRoot
) -> None:
    guest = MediumGuest()

    outcome, _ = prepare(root, repository, guest, gpgv=inputs_support.Gpgv("0" * 40))

    assert outcome.refusal is refusals.RefusalReason.UBUNTU_SIGNER_UNKNOWN
    assert guest.asked == [] and not any("Ubuntu.iso" in str(item.remote) for item in guest.sent)


def test_a_medium_that_differs_from_the_report_fails_the_run_after_the_report_is_kept(
    root: safepaths.RuntimeRoot, repository: safepaths.SourceRoot
) -> None:
    guest = MediumGuest(image=b"lost bytes on the way home")

    outcome, _ = prepare(root, repository, guest)

    assert not outcome.succeeded
    assert outcome.refusal is refusals.RefusalReason.STAGE_FAILED
    assert "differs from the report" in outcome.detail
    assert verifykeys.retained_observation(ventoy_media_recipe.CASE) in outcome.facts
