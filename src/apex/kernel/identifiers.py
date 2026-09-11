"""Validated identity values.

Each parses at construction, so a value that exists is a value that was checked, and the
pattern it was checked against lives in one place.
"""

from __future__ import annotations

import dataclasses
import re
from typing import ClassVar, Self

from apex.kernel import errors, refusals

DIGEST_ALGORITHM = "sha256"
_HEX_64 = re.compile(r"[0-9a-f]{64}")
_HEX_32 = re.compile(r"[0-9a-f]{32}")
_DOTTED_NAME = re.compile(r"[a-z0-9]+(?:[.-][a-z0-9]+)*")
_NEVRA_QUERY = re.compile(
    r"(?P<name>[^|]+)\|(?P<epoch>\d+):(?P<version>[^-]+)-(?P<release>.+)\.(?P<architecture>[^.]+)"
)


@dataclasses.dataclass(frozen=True, slots=True)
class Digest:
    hex: str

    def __post_init__(self) -> None:
        if not _HEX_64.fullmatch(self.hex):
            raise errors.Refusal(refusals.RefusalReason.MALFORMED_DIGEST, subject=self.hex)

    @classmethod
    def parse(cls, value: str) -> Self:
        prefix, separator, remainder = value.partition(":")
        if separator and prefix != DIGEST_ALGORITHM:
            raise errors.Refusal(refusals.RefusalReason.MALFORMED_DIGEST, subject=value)
        return cls(remainder if separator else value)

    def __str__(self) -> str:
        return f"{DIGEST_ALGORITHM}:{self.hex}"


class ImageId(Digest):
    """A digest that names a container manifest."""


class MerkleRoot(Digest):
    """A digest over a sorted source bundle."""


@dataclasses.dataclass(frozen=True, slots=True)
class _HexIdentifier:
    value: str
    _pattern: ClassVar[re.Pattern[str]] = _HEX_32

    def __post_init__(self) -> None:
        if not type(self)._pattern.fullmatch(self.value):
            raise errors.Refusal(refusals.RefusalReason.MALFORMED_IDENTIFIER, subject=self.value)

    @classmethod
    def parse(cls, value: str) -> Self:
        return cls(value)

    def __str__(self) -> str:
        return self.value


class BuildId(_HexIdentifier):
    """Identifies one build export directory."""


class RunId(_HexIdentifier):
    """Identifies one pipeline run."""


class Token(_HexIdentifier):
    """A one-shot capability handed to a guest."""


@dataclasses.dataclass(frozen=True, slots=True)
class _DottedName:
    value: str

    def __post_init__(self) -> None:
        if not _DOTTED_NAME.fullmatch(self.value):
            raise errors.Refusal(refusals.RefusalReason.MALFORMED_IDENTIFIER, subject=self.value)

    def __str__(self) -> str:
        return self.value


class CheckId(_DottedName):
    """Names one required evidence check."""


class RuleId(_DottedName):
    """Names one repository rule."""


class StageId(_DottedName):
    """Names one pipeline stage."""


class ProbeId(_DottedName):
    """Names one guest probe."""


class FaultId(_DottedName):
    """Names one injected fault case."""


class ProfileId(_DottedName):
    """Names one release, desktop or hardware profile."""


@dataclasses.dataclass(frozen=True, slots=True)
class Nevra:
    name: str
    epoch: int
    version: str
    release: str
    architecture: str

    @classmethod
    def parse(cls, value: str) -> Self:
        matched = _NEVRA_QUERY.fullmatch(value)
        if matched is None:
            raise errors.Refusal(
                refusals.RefusalReason.MALFORMED_PACKAGE_COORDINATE, subject=value
            )
        return cls(
            name=matched["name"],
            epoch=int(matched["epoch"]),
            version=matched["version"],
            release=matched["release"],
            architecture=matched["architecture"],
        )

    @property
    def filename(self) -> str:
        return f"{self.name}-{self.version}-{self.release}.{self.architecture}.rpm"

    def __str__(self) -> str:
        return f"{self.name}-{self.epoch}:{self.version}-{self.release}.{self.architecture}"
