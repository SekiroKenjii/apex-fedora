"""Images and containers inside a guest, through one engine.

Every podman and skopeo call the older scripts make in the builder is an operation here. A
reference carries its transport, so a local store, an archive on disk and a directory bundle
are three values and not three spellings of a string. The port is declared with the others so
host and guest share one definition; only the guest implements it.
"""

from __future__ import annotations

import dataclasses
import enum
from abc import abstractmethod
from collections.abc import Mapping
from typing import Protocol

from apex.kernel import claims, commands, identifiers, safepaths


class Transport(enum.StrEnum):
    STORAGE = "containers-storage"
    OCI_ARCHIVE = "oci-archive"
    DIRECTORY = "dir"


@dataclasses.dataclass(frozen=True, slots=True)
class ImageReference:
    transport: Transport
    name: str

    def __str__(self) -> str:
        return f"{self.transport}:{self.name}"

    @classmethod
    def stored(cls, name: str) -> ImageReference:
        return cls(Transport.STORAGE, name)


@dataclasses.dataclass(frozen=True, slots=True)
class SigstoreSigning:
    private_key: safepaths.SafePath
    passphrase: safepaths.SafePath
    identity: str


@dataclasses.dataclass(frozen=True, slots=True)
class BuildRequest:
    context: safepaths.SafePath
    tag: str
    containerfile: safepaths.SafePath | None = None
    build_arguments: Mapping[str, str] = dataclasses.field(default_factory=dict)
    network_none: bool = True
    pull_never: bool = True
    layers: bool = True
    label_disabled: bool = False


@dataclasses.dataclass(frozen=True, slots=True)
class RunRequest:
    image: str
    argv: commands.Argv
    read_only: bool = False
    network_none: bool = False
    entrypoint: str | None = None


class ContainerEnginePort(Protocol):
    environment: claims.EnvironmentKind

    @abstractmethod
    def image_id(self, name: str) -> identifiers.ImageId: ...

    @abstractmethod
    def inspect(self, name: str) -> bytes:
        """The engine's own description of a stored image, as JSON."""
        ...

    @abstractmethod
    def manifest(self, reference: ImageReference) -> bytes:
        """The raw manifest bytes, which are what a digest is taken over."""
        ...

    @abstractmethod
    def build(self, request: BuildRequest) -> None: ...

    @abstractmethod
    def run(self, request: RunRequest) -> commands.CompletedRun: ...

    @abstractmethod
    def copy(
        self,
        source: ImageReference,
        destination: ImageReference,
        *,
        policy: safepaths.SafePath | None,
        signing: SigstoreSigning | None,
    ) -> None:
        """Copy with digests preserved, under a policy file when one is given."""
        ...

    @abstractmethod
    def generate_sigstore_key(
        self, *, prefix: safepaths.SafePath, passphrase: safepaths.SafePath
    ) -> None: ...

    @abstractmethod
    def running_containers(self) -> bytes:
        """The engine's own listing of running containers, as JSON."""
        ...
