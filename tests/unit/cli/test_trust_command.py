"""The trust command judges a build's output against an outside key and keeps the builder's."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest
from signedbundle import BUILD, keys, real_files_bundle, signed_output

from apex.adapters.fakes import fake_guestshell, fake_hypervisor, fake_process
from apex.cli import commandspecs
from apex.cli.commands import trust_command
from apex.config import defaults, loader
from apex.kernel import claims, errors, hashing, refusals, safepaths
from apex.model import machines
from apex.ports import portset
from apex.provisioning import launching
from apex.wiring import contexts

REPOSITORY = Path(__file__).resolve().parents[3]
PEM = b"-----BEGIN PUBLIC KEY-----\nMCowBQYDK2VwAyEA\n-----END PUBLIC KEY-----\n"


@pytest.fixture
def root(tmp_path: Path) -> safepaths.RuntimeRoot:
    base = tmp_path / "runtime"
    base.mkdir(mode=0o700)
    return safepaths.RuntimeRoot.adopt(base)


def request(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot | None, *arguments: str
) -> commandspecs.Request:
    return commandspecs.Request(
        arguments=arguments,
        context=contexts.Context(
            settings=loader.load(host_file=None, environment={}),
            repository=safepaths.SourceRoot.adopt(REPOSITORY),
            root=root,
            environment={},
            bundle=lambda _root: ports,
        ),
    )


def test_a_signed_output_verifies_against_the_operators_key_as_the_older_tool_said(
    root: safepaths.RuntimeRoot,
) -> None:
    ports = real_files_bundle()
    private, public = keys(ports, root)
    signed_output(ports, root, private)

    reply = trust_command.run(
        request(ports, root, "verify", "--build", str(BUILD), "--key", str(public))
    )

    assert reply.document == {
        "status": "PASS",
        "digest": "sha256:" + "a" * 64,
        "purpose": None,
        "trusted_key_sha256": hashing.digest_bytes(public.read_bytes()).hex,
        "files_verified": 1,
        "bootc_update_policy": "NOT TESTED",
    }


def test_a_key_that_did_not_sign_the_inventory_is_refused(root: safepaths.RuntimeRoot) -> None:
    ports = real_files_bundle()
    private, _ = keys(ports, root)
    signed_output(ports, root, private)
    ports.signing.generate_key_pair(
        private_into=root.child("keys/other.key"), public_into=root.child("keys/other.pub")
    )

    with pytest.raises(errors.Refusal) as raised:
        trust_command.run(request(
            ports, root, "verify", "--build", str(BUILD), "--key", str(root.path / "keys/other.pub")
        ))

    assert raised.value.reason is refusals.RefusalReason.SIGNATURE_REJECTED


def test_a_key_inside_the_bundle_cannot_establish_its_trust(root: safepaths.RuntimeRoot) -> None:
    ports = real_files_bundle()
    private, public = keys(ports, root)
    directory = signed_output(
        ports, root, private, extra={"development-signing.pub": public.read_bytes()}
    )

    with pytest.raises(errors.Refusal) as raised:
        trust_command.run(request(
            ports, root, "verify", "--build", str(BUILD),
            "--key", str(directory / "development-signing.pub"),
        ))

    assert raised.value.reason is refusals.RefusalReason.TRUST_ANCHOR_FROM_BUNDLE


def test_the_exercise_refuses_every_negative_and_files_its_results(
    root: safepaths.RuntimeRoot,
) -> None:
    ports = real_files_bundle()
    private, public = keys(ports, root)
    signed_output(ports, root, private)

    reply = trust_command.run(
        request(ports, root, "exercise", "--build", str(BUILD), "--key", str(public))
    )

    assert isinstance(reply.document, dict)
    assert reply.document["status"] == "PASS"
    checks = reply.document["checks"]
    assert isinstance(checks, dict) and set(checks) == {
        "trust.bundled-key", "trust.changed-manifest", "trust.changed-payload",
        "trust.untrusted-key",
    }
    assert all(value == "PASS" for value in checks.values())
    proof = Path(str(reply.document["proof"]))
    assert proof.parent.parent == root.path / "signature-tests"
    filed = json.loads(proof.read_bytes())
    assert filed["digest"] == "sha256:" + "a" * 64
    assert filed["accepted_bundle"]["files_verified"] == 1
    assert proof.stat().st_mode & 0o777 == 0o600


def builder_running(ports: portset.HostPorts, root: safepaths.RuntimeRoot) -> None:
    for name in ("disk.qcow2", "code.fd", "vars.fd"):
        (root.path / name).write_bytes(b"")
    (root.path / defaults.BUILDER_KEY_NAME).write_bytes(b"key")
    present = lambda name: safepaths.SafePath.regular_file(root.path / name, within=root)  # noqa: E731
    spec = machines.VmSpec.build(
        role=machines.VmRole.BUILDER,
        resources=machines.VmResources(memory=defaults.TEST_MACHINE.memory, processors=2),
        root_disk=present("disk.qcow2"),
        firmware=machines.Firmware(code=present("code.fd"), variables=present("vars.fd")),
        monitor=machines.MonitorSocket(root.child("qmp.sock")),
        serial=machines.SerialFile(root.child("serial.log")),
    )
    run = ports.identities.run_id()
    root.child(f"vm-runs/{run}").path.mkdir(parents=True)
    launching.launch(
        ports, root=root, spec=spec, run=run, run_directory=root.child(f"vm-runs/{run}")
    )


class KeyTools(fake_process.ScriptedProcess):
    def __init__(self, *, valid: bool = True) -> None:
        super().__init__()
        self.valid = valid

    def run(self, argv: Any, **keywords: Any) -> Any:
        vector = tuple(str(item) for item in argv)
        if vector[:2] == ("openssl", "pkey"):
            self.expect(vector, fake_process.Reply(exit_code=0 if self.valid else 1))
        return super().run(argv, **keywords)


def answering(pem: bytes) -> fake_guestshell.ScriptedGuest:
    guest = fake_guestshell.ScriptedGuest()
    guest.expect(
        trust_command.developmentkey.FETCH.rendered(), fake_guestshell.GuestReply(stdout=pem)
    )
    return guest


def test_the_development_key_is_kept_from_the_builders_channel_with_its_record(
    root: safepaths.RuntimeRoot,
) -> None:
    ports = dataclasses.replace(real_files_bundle(), processes=KeyTools(), guest=answering(PEM))
    builder_running(ports, root)

    reply = trust_command.run(request(ports, root, "development-key"))
    again = trust_command.run(request(ports, root, "development-key"))

    kept = root.path / "trust" / "development.pub"
    assert kept.read_bytes() == PEM and kept.stat().st_mode & 0o777 == 0o600
    assert reply.document == {
        "purpose": "local-development-only",
        "path": str(kept),
        "sha256": hashing.digest_bytes(PEM).hex,
        "source": "authenticated builder ssh; not the artifact bundle",
        "release_trust": False,
    }
    assert again.document == reply.document
    assert json.loads((root.path / "trust" / "development.json").read_bytes()) == reply.document
    assert ports.guest.targets[-1].user == "builder"  # type: ignore[attr-defined]


def test_a_key_that_differs_from_the_kept_one_is_refused(root: safepaths.RuntimeRoot) -> None:
    ports = dataclasses.replace(real_files_bundle(), processes=KeyTools(), guest=answering(PEM))
    builder_running(ports, root)
    trust_command.run(request(ports, root, "development-key"))
    rotated = dataclasses.replace(ports, guest=answering(PEM.replace(b"MCow", b"MDow")))

    with pytest.raises(errors.Refusal) as raised:
        trust_command.run(request(rotated, root, "development-key"))

    assert raised.value.reason is refusals.RefusalReason.DEVELOPMENT_KEY_CHANGED
    assert (root.path / "trust" / "development.pub").read_bytes() == PEM


def test_an_answer_that_is_not_a_public_key_is_refused(root: safepaths.RuntimeRoot) -> None:
    ports = dataclasses.replace(
        real_files_bundle(), processes=KeyTools(valid=False), guest=answering(b"garbage")
    )
    builder_running(ports, root)

    with pytest.raises(errors.Refusal) as raised:
        trust_command.run(request(ports, root, "development-key"))

    assert raised.value.reason is refusals.RefusalReason.PUBLIC_KEY_MALFORMED
    assert not (root.path / "trust").exists()


def test_without_the_builder_the_key_is_not_fetched(root: safepaths.RuntimeRoot) -> None:
    ports = real_files_bundle()

    with pytest.raises(errors.Refusal) as raised:
        trust_command.run(request(ports, root, "development-key"))

    assert raised.value.reason is refusals.RefusalReason.MACHINE_NOT_RUNNING
    assert isinstance(ports.hypervisor, fake_hypervisor.FakeQemu)
    assert claims.EnvironmentKind.SIMULATED is ports.environment
