"""An engine that answers from tables and records every build, run, copy and key."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable

from apex.kernel import claims, commands, errors, identifiers, safepaths
from apex.ports import containers


@dataclasses.dataclass(frozen=True, slots=True)
class Copied:
    source: containers.ImageReference
    destination: containers.ImageReference
    policy: safepaths.SafePath | None
    signing: containers.SigstoreSigning | None


@dataclasses.dataclass(frozen=True, slots=True)
class KeyPair:
    prefix: safepaths.SafePath
    passphrase: safepaths.SafePath


class FakeRegistry(containers.ContainerEnginePort):
    environment = claims.EnvironmentKind.SIMULATED

    def __init__(self) -> None:
        self._ids: dict[str, identifiers.ImageId] = {}
        self._manifests: dict[str, bytes] = {}
        self._inspections: dict[str, bytes] = {}
        self._replies: dict[tuple[str, tuple[str, ...]], commands.CompletedRun] = {}
        self.containers_listing = b"[]"
        self.builds: list[containers.BuildRequest] = []
        self.runs: list[containers.RunRequest] = []
        self.copies: list[Copied] = []
        self.keys: list[KeyPair] = []
        self.on_copy: Callable[[containers.ImageReference], None] | None = None
        self.on_key: Callable[[safepaths.SafePath], None] | None = None

    @classmethod
    def with_shell_probe(cls) -> FakeRegistry:
        """The tables the shared contract suite exercises."""
        registry = cls()
        registry.hold("localhost/apex:fedora", identifiers.ImageId("a" * 64), b'{"config": {}}')
        registry.manifest_of(
            containers.ImageReference.stored("localhost/apex:fedora"), b'{"schemaVersion": 2}'
        )
        registry.reply(
            "localhost/apex:fedora", ("rpm", "-qa"),
            commands.CompletedRun(exit_code=0, stdout=b"bash-5\n", stderr=b"", truncated=False),
        )
        registry.reply(
            "localhost/apex:fedora", ("false",),
            commands.CompletedRun(exit_code=1, stdout=b"", stderr=b"", truncated=False),
        )
        return registry

    def hold(self, name: str, image_id: identifiers.ImageId, inspection: bytes) -> None:
        self._ids[name] = image_id
        self._inspections[name] = inspection

    def manifest_of(self, reference: containers.ImageReference, payload: bytes) -> None:
        self._manifests[str(reference)] = payload

    def reply(self, image: str, argv: tuple[str, ...], completed: commands.CompletedRun) -> None:
        self._replies[(image, argv)] = completed

    def image_id(self, name: str) -> identifiers.ImageId:
        if name not in self._ids:
            raise errors.PortFailure(port="containers", cause=f"podman: no such image {name}")
        return self._ids[name]

    def inspect(self, name: str) -> bytes:
        if name not in self._inspections:
            raise errors.PortFailure(port="containers", cause=f"podman: no such image {name}")
        return self._inspections[name]

    def manifest(self, reference: containers.ImageReference) -> bytes:
        key = str(reference)
        if key not in self._manifests:
            raise errors.PortFailure(port="containers", cause=f"skopeo: no such image {key}")
        return self._manifests[key]

    def build(self, request: containers.BuildRequest) -> None:
        self.builds.append(request)
        self._ids.setdefault(request.tag, identifiers.ImageId("b" * 64))
        self._inspections.setdefault(request.tag, b"[]")

    def run(self, request: containers.RunRequest) -> commands.CompletedRun:
        self.runs.append(request)
        key = (request.image, tuple(request.argv))
        if key not in self._replies:
            raise errors.PortFailure(
                port="containers", cause=f"undeclared run: {request.image} {' '.join(key[1])}"
            )
        return self._replies[key]

    def copy(
        self,
        source: containers.ImageReference,
        destination: containers.ImageReference,
        *,
        policy: safepaths.SafePath | None,
        signing: containers.SigstoreSigning | None,
    ) -> None:
        self.copies.append(Copied(source, destination, policy, signing))
        if str(source) in self._manifests:
            self._manifests[str(destination)] = self._manifests[str(source)]
        if self.on_copy is not None:
            self.on_copy(destination)

    def generate_sigstore_key(
        self, *, prefix: safepaths.SafePath, passphrase: safepaths.SafePath
    ) -> None:
        self.keys.append(KeyPair(prefix=prefix, passphrase=passphrase))
        if self.on_key is not None:
            self.on_key(prefix)

    def running_containers(self) -> bytes:
        return self.containers_listing
