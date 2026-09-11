"""Verifying a signed bundle, on the real file system with a real or a fake signer.

The bundle is built by the signer under test, so the same specification runs against openssl
and against the keyed-hash fake. The refusals are matched by reason, never by prose.
"""

from __future__ import annotations

import json

import pytest

from apex.adapters.fakes import fake_clock, fake_ids, fake_locking, fake_process, fake_signing
from apex.adapters.real import real_archives, real_digesting, real_downloading, real_files
from apex.kernel import errors, hashing, refusals, safepaths
from apex.model import bundles
from apex.ports import portset, signing
from apex.trust import anchors, exercising, negatives, verifying

SIGNED_DIGEST = "sha256:" + "a" * 64


def bundle_of(signer: signing.SigningPort) -> portset.HostPorts:
    return portset.HostPorts(
        processes=fake_process.ScriptedProcess(),
        files=real_files.LocalFiles(),
        clock=fake_clock.ManualClock(),
        identities=fake_ids.SequenceIdentities(),
        locks=fake_locking.MemoryLocks(),
        digests=real_digesting.CachedDigests(),
        archives=real_archives.TarArchives(),
        signing=signer,
        downloads=real_downloading.CurlDownloads(),
    )


def sign_inventory(
    ports: portset.HostPorts,
    location: verifying.BundleLocation,
    private: safepaths.RegularFile,
    *,
    digest: str = SIGNED_DIGEST,
) -> None:
    directory = location.directory().path
    files = {
        path.name: hashing.digest_bytes(path.read_bytes()).hex
        for path in sorted(directory.iterdir())
        if path.name not in (bundles.MANIFEST_NAME, bundles.SIGNATURE_NAME)
    }
    inventory = json.dumps({"schema": 1, "digest": digest, "files": files}).encode()
    (directory / bundles.MANIFEST_NAME).write_bytes(inventory)
    (directory / bundles.SIGNATURE_NAME).write_bytes(
        ports.signing.sign(payload=inventory, private_key=private)
    )


@pytest.fixture
def signed(
    signers: signing.SigningPort, root: safepaths.RuntimeRoot
) -> tuple[portset.HostPorts, negatives.Trial, safepaths.RegularFile]:
    ports = bundle_of(signers)
    ports.signing.generate_key_pair(
        private_into=root.child("keys/signing.key"), public_into=root.child("keys/trusted.pub")
    )
    private = safepaths.RegularFile.adopt(root.path / "keys" / "signing.key")
    location = verifying.BundleLocation(root=root, relative="exports/one/output")
    location.directory().path.mkdir(parents=True)
    (location.directory().path / "payload.txt").write_text("frozen artifact")
    sign_inventory(ports, location, private)
    trial = negatives.Trial(
        location=location, anchor=anchors.operator_supplied(root.path / "keys" / "trusted.pub")
    )
    return ports, trial, private


def refusal_of(ports: portset.HostPorts, trial: negatives.Trial) -> refusals.RefusalReason:
    with pytest.raises(errors.Refusal) as raised:
        verifying.verify_bundle(ports, location=trial.location, anchor=trial.anchor)
    return raised.value.reason


def test_a_signed_bundle_verifies(
    signed: tuple[portset.HostPorts, negatives.Trial, safepaths.RegularFile],
) -> None:
    ports, trial, _ = signed

    verified = verifying.verify_bundle(ports, location=trial.location, anchor=trial.anchor)

    assert verified.digest.hex == "a" * 64
    assert verified.files_verified == 1


def test_a_changed_payload_is_a_checksum_mismatch(
    signed: tuple[portset.HostPorts, negatives.Trial, safepaths.RegularFile],
) -> None:
    ports, trial, _ = signed
    (trial.location.directory().path / "payload.txt").write_text("tampered")

    assert refusal_of(ports, trial) is refusals.RefusalReason.ARTIFACT_CHECKSUM_MISMATCH


def test_an_unsigned_extra_file_is_refused(
    signed: tuple[portset.HostPorts, negatives.Trial, safepaths.RegularFile],
) -> None:
    ports, trial, _ = signed
    (trial.location.directory().path / "substitute.qcow2").write_bytes(b"unsigned")

    assert refusal_of(ports, trial) is refusals.RefusalReason.BUNDLE_CONTENT_UNSIGNED


def test_a_symlink_in_the_bundle_is_refused(
    signed: tuple[portset.HostPorts, negatives.Trial, safepaths.RegularFile],
) -> None:
    ports, trial, _ = signed
    directory = trial.location.directory().path
    (directory / "link.txt").symlink_to(directory / "payload.txt")

    assert refusal_of(ports, trial) is refusals.RefusalReason.BUNDLE_CONTENT_UNSIGNED


def test_a_changed_inventory_fails_the_signature(
    signed: tuple[portset.HostPorts, negatives.Trial, safepaths.RegularFile],
) -> None:
    ports, trial, _ = signed
    (trial.location.directory().path / bundles.MANIFEST_NAME).write_text("{}")

    assert refusal_of(ports, trial) is refusals.RefusalReason.SIGNATURE_REJECTED


def test_a_key_shipped_in_the_bundle_is_not_an_anchor(
    signed: tuple[portset.HostPorts, negatives.Trial, safepaths.RegularFile],
) -> None:
    ports, trial, _ = signed
    shipped = trial.location.directory().path / bundles.BUNDLED_KEY_NAME
    shipped.write_bytes(trial.anchor.public_key.path.read_bytes())
    inside = negatives.Trial(location=trial.location, anchor=anchors.operator_supplied(shipped))

    assert refusal_of(ports, inside) is refusals.RefusalReason.TRUST_ANCHOR_FROM_BUNDLE


def test_a_signed_inventory_cannot_mislabel_the_oci_digest(
    signed: tuple[portset.HostPorts, negatives.Trial, safepaths.RegularFile],
) -> None:
    ports, trial, private = signed
    (trial.location.directory().path / "payload-manifest.json").write_text('{"schemaVersion": 2}')
    sign_inventory(ports, trial.location, private)

    assert refusal_of(ports, trial) is refusals.RefusalReason.SIGNED_DIGEST_MISMATCH


def test_image_metadata_must_agree_with_the_oci_configuration(
    signed: tuple[portset.HostPorts, negatives.Trial, safepaths.RegularFile],
) -> None:
    ports, trial, private = signed
    directory = trial.location.directory().path
    manifest = json.dumps({"schemaVersion": 2, "config": {"digest": "sha256:" + "c" * 64}}).encode()
    (directory / "manifest.json").write_bytes(manifest)
    signed_digest = "sha256:" + hashing.digest_bytes(manifest).hex
    image = {"profile": "fedora", "digest": signed_digest, "image_id": "sha256:" + "d" * 64}
    (directory / "image.json").write_text(json.dumps(image))
    sign_inventory(ports, trial.location, private, digest=signed_digest)

    assert refusal_of(ports, trial) is refusals.RefusalReason.IMAGE_METADATA_MISMATCH


def test_the_exercise_refuses_every_negative_for_its_declared_reason(
    signed: tuple[portset.HostPorts, negatives.Trial, safepaths.RegularFile],
) -> None:
    ports, trial, _ = signed
    scratch = verifying.BundleLocation(root=trial.location.root, relative="signature-tests/run")

    report = exercising.exercise(ports, trial=trial, scratch=scratch)

    assert report.accepted.digest.hex == "a" * 64
    assert set(report.refused) == {str(item.id) for item in negatives.registered()}


def test_the_exercise_catches_a_verifier_that_accepts_a_forgery(
    root: safepaths.RuntimeRoot,
) -> None:
    ports = bundle_of(fake_signing.AcceptingSigner())
    ports.signing.generate_key_pair(
        private_into=root.child("keys/signing.key"), public_into=root.child("keys/trusted.pub")
    )
    location = verifying.BundleLocation(root=root, relative="exports/two/output")
    location.directory().path.mkdir(parents=True)
    (location.directory().path / "payload.txt").write_text("frozen artifact")
    sign_inventory(ports, location, safepaths.RegularFile.adopt(root.path / "keys" / "signing.key"))
    trial = negatives.Trial(
        location=location, anchor=anchors.operator_supplied(root.path / "keys" / "trusted.pub")
    )

    with pytest.raises(errors.Refusal) as raised:
        exercising.exercise(
            ports, trial=trial, scratch=verifying.BundleLocation(root=root, relative="tests")
        )

    # The first negative such a verifier cannot tell apart is refused for a reason other than
    # the one declared, or not refused at all. Either is the exercise doing its job.
    assert raised.value.reason in {
        refusals.RefusalReason.NEGATIVE_ACCEPTED,
        refusals.RefusalReason.NEGATIVE_WRONG_REASON,
    }
