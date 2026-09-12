"""The installer's preflight, loaded from its verbatim bytes and called through types.

The program that runs before Anaconda is the one safety artifact the installer has, and it
is not rewritten. It is executed from the bytes the package carries, and three of its
functions are exposed here with the types the product uses: the policy that the trust
contract implies, the proxy check that a policy accepts an image, and the whole
verification. Its `ValueError` is a refused contract and its `RuntimeError` a rejected
signature, which is what those exceptions mean in its source.
"""

from __future__ import annotations

import dataclasses
import types
from collections.abc import Mapping
from importlib import resources
from pathlib import Path

from apex.kernel import encoding, errors, hashing, identifiers, refusals

ASSET = "installer-preflight.py"
SUFFIX = ".verbatim"
PACKAGE = "apex.assets.verbatim"


def source() -> bytes:
    return resources.files(PACKAGE).joinpath(ASSET + SUFFIX).read_bytes()


def digest() -> identifiers.Digest:
    return hashing.digest_bytes(source())


def _refused(fault: ValueError) -> errors.Refusal:
    return errors.Refusal(
        refusals.RefusalReason.PAYLOAD_CONTRACT_INVALID,
        subject=str(fault),
        remedy="the trust metadata, the key and the policy must agree before any image is opened",
    )


def _rejected(fault: RuntimeError) -> errors.Refusal:
    return errors.Refusal(
        refusals.RefusalReason.SIGNATURE_REJECTED,
        subject=str(fault),
        remedy="the policy did not accept the image, which is the answer when it should not",
    )


@dataclasses.dataclass(frozen=True, slots=True)
class Preflight:
    """The verbatim program as a module, behind the three calls the product makes."""

    program: types.ModuleType

    def signature_policy(
        self, metadata: Mapping[str, object], public_key: bytes, *, payload: Path
    ) -> encoding.Document:
        try:
            policy = self.program.signature_policy(dict(metadata), public_key, payload=payload)
        except ValueError as fault:
            raise _refused(fault) from fault
        return encoding.parse_object(encoding.canonical(policy))

    def verified_open(self, source_reference: str, policy: Path) -> encoding.Document:
        try:
            outcome = self.program.verified_open(source_reference, policy)
        except RuntimeError as fault:
            raise _rejected(fault) from fault
        return encoding.parse_object(encoding.canonical(outcome))

    def verify(self, trust: Path, policy: Path, *, payload: Path) -> encoding.Document:
        try:
            outcome = self.program.verify(trust, policy, payload=payload)
        except ValueError as fault:
            raise _refused(fault) from fault
        except RuntimeError as fault:
            raise _rejected(fault) from fault
        return encoding.parse_object(encoding.canonical(outcome))


def load() -> Preflight:
    """Execute the verbatim bytes as a module. Nothing runs at load beyond its definitions."""
    module = types.ModuleType(ASSET.removesuffix(".py"))
    module.__file__ = ASSET
    exec(compile(source(), ASSET, "exec"), module.__dict__)  # noqa: S102
    return Preflight(program=module)
