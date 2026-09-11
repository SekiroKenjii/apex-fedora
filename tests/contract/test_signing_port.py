"""Signing and verifying over bytes, so what is parsed is exactly what was verified."""

from __future__ import annotations

import pytest

from apex.adapters.fakes import fake_signing
from apex.kernel import errors, safepaths
from apex.ports import signing as signing_port

PAYLOAD = (
    b'{"schema": 1, "digest": "sha256:' + b"a" * 64 + b'", "files": {"x": "' + b"b" * 64 + b'"}}'
)


def key_pair(
    signers: signing_port.SigningPort, root: safepaths.RuntimeRoot, name: str = "signing"
) -> tuple[safepaths.RegularFile, safepaths.RegularFile]:
    private = root.child(f"{name}.key")
    public = root.child(f"{name}.pub")
    signers.generate_key_pair(private_into=private, public_into=public)
    return safepaths.RegularFile.adopt(private.path), safepaths.RegularFile.adopt(public.path)


def test_a_signature_verifies_with_the_matching_public_key(
    signers: signing_port.SigningPort, root: safepaths.RuntimeRoot
) -> None:
    private, public = key_pair(signers, root)

    signature = signers.sign(payload=PAYLOAD, private_key=private)

    assert signers.verify(payload=PAYLOAD, signature=signature, public_key=public)


def test_a_changed_payload_does_not_verify(
    signers: signing_port.SigningPort, root: safepaths.RuntimeRoot
) -> None:
    private, public = key_pair(signers, root)
    signature = signers.sign(payload=PAYLOAD, private_key=private)

    assert not signers.verify(payload=b"X" + PAYLOAD[1:], signature=signature, public_key=public)


def test_another_key_does_not_verify(
    signers: signing_port.SigningPort, root: safepaths.RuntimeRoot
) -> None:
    private, _ = key_pair(signers, root, "trusted")
    _, other = key_pair(signers, root, "other")
    signature = signers.sign(payload=PAYLOAD, private_key=private)

    assert not signers.verify(payload=PAYLOAD, signature=signature, public_key=other)


def test_garbage_in_place_of_a_signature_does_not_verify(
    signers: signing_port.SigningPort, root: safepaths.RuntimeRoot
) -> None:
    _, public = key_pair(signers, root)

    assert not signers.verify(payload=PAYLOAD, signature=b"not a signature", public_key=public)


def test_generated_key_material_is_private(
    signers: signing_port.SigningPort, root: safepaths.RuntimeRoot
) -> None:
    private, public = key_pair(signers, root)

    assert private.path.stat().st_mode & 0o077 == 0
    assert public.path.is_file()


def test_a_missing_key_is_a_port_failure_not_a_rejection(
    signers: signing_port.SigningPort, root: safepaths.RuntimeRoot
) -> None:
    _, public = key_pair(signers, root, "gone")
    public.path.unlink()

    with pytest.raises(errors.PortFailure):
        signers.verify(payload=PAYLOAD, signature=b"x", public_key=public)


def test_the_rejecting_signer_refuses_everything(root: safepaths.RuntimeRoot) -> None:
    signer = fake_signing.RejectingSigner()
    private, public = key_pair(signer, root)
    signature = signer.sign(payload=PAYLOAD, private_key=private)

    assert not signer.verify(payload=PAYLOAD, signature=signature, public_key=public)
