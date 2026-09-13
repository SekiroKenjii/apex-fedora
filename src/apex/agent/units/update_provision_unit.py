"""Lay the signed update fixture into the guest and put its policy in force.

This is the older update tool's provisioning program step for step: the uploaded archive is
checked against its digest, unpacked only if every member lies under the fixture's own
name, every listed file is verified where it landed, the fixture's policy must reject by
default, the policy in force must be the bootstrap one or the fixture's own when A is
already installed, and the policy in force is kept beside the fixture before it is replaced.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from pathlib import Path

from apex.agent import agentports, deployments, guestguard, units
from apex.config import defaults
from apex.kernel import commands, encoding, errors, identifiers, quantities, refusals, safepaths
from apex.ports import files
from apex.provisioning.fixtures import update_fixture

ROOT_USER = 0
REJECT = [{"type": "reject"}]
BOOTSTRAP_POLICY: encoding.Document = {"default": REJECT, "transports": {}}
BOOTSTRAP_NAME = "bootstrap-policy.json"
METADATA_NAME = "fixture.json"
POLICY_NAME = "policy.json"
RESTORE = commands.Argv.of("restorecon", update_fixture.BUILDER_POLICY)
PRIVATE_DIRECTORY = quantities.FileMode(0o700)


@dataclasses.dataclass(frozen=True, slots=True)
class Request:
    fixture: identifiers.RunId
    archive: safepaths.SafePath
    archive_digest: identifiers.Digest
    public_key: identifiers.Digest
    policy: identifiers.Digest
    installed_a: bool

    @classmethod
    def parse(cls, arguments: Mapping[str, encoding.JsonValue]) -> Request:
        try:
            archive = str(arguments["archive"])
            if not archive.startswith(defaults.UPDATE_UPLOAD_PREFIX):
                raise errors.Refusal(
                    refusals.RefusalReason.REQUEST_MALFORMED, subject=f"archive {archive}"
                )
            return cls(
                fixture=identifiers.RunId.parse(str(arguments["fixture"])),
                archive=safepaths.SafePath(Path(archive)),
                archive_digest=identifiers.Digest(str(arguments["archive_sha256"])),
                public_key=identifiers.Digest(str(arguments["public_key_sha256"])),
                policy=identifiers.Digest(str(arguments["policy_sha256"])),
                installed_a=arguments.get("installed_a") is True,
            )
        except KeyError as missing:
            raise errors.Refusal(
                refusals.RefusalReason.REQUEST_MALFORMED, subject=f"{missing} must be given"
            ) from missing

    @property
    def base(self) -> safepaths.SafePath:
        return safepaths.SafePath(Path(update_fixture.FIXTURE_ROOT))

    @property
    def target(self) -> safepaths.SafePath:
        return self.base / str(self.fixture)


def _document(ports: agentports.AgentPorts, path: safepaths.SafePath) -> encoding.Document:
    text = ports.files.read_bytes(path, limit=defaults.DOCUMENT_LIMIT.value)
    return deployments.document(text.decode(errors="replace"), what=str(path))


def unpack(ports: agentports.AgentPorts, request: Request) -> None:
    """The archive below the fixture root, after every member is seen to lie under its name."""
    if ports.digests.file(request.archive) != request.archive_digest:
        raise deployments.unexpected("payload archive checksum mismatch")
    if ports.files.exists(request.target):
        raise deployments.unexpected(f"{request.target}: the fixture is already provisioned")
    ports.files.make_directory(request.base, mode=PRIVATE_DIRECTORY)
    seen = ports.files.inspect(request.base)
    if seen.kind is not files.EntryKind.DIRECTORY or seen.owner != ROOT_USER:
        raise deployments.unexpected(f"{request.base}: not a directory owned by root")
    members = ports.archives.members(request.archive)
    if any(name.split("/")[0] != str(request.fixture) for name in members):
        raise deployments.unexpected("the archive carries members outside the fixture")
    ports.archives.extract(request.archive, into=request.base)


def _verify_one(
    ports: agentports.AgentPorts, request: Request, name: str, expected: encoding.JsonValue
) -> None:
    path = request.target / name
    resolved = ports.files.resolve(path)
    if not str(resolved).startswith(str(request.target) + "/"):
        raise deployments.unexpected(f"{name}: escapes the fixture")
    if ports.files.inspect(path).kind is not files.EntryKind.REGULAR:
        raise deployments.unexpected(f"{name}: not a regular file")
    if ports.digests.file(path).hex != expected:
        raise deployments.unexpected(f"{name}: digest differs from the listing")


def verify_files(ports: agentports.AgentPorts, request: Request) -> int:
    """Every file the fixture lists, where it landed, a regular file with the listed digest."""
    metadata = _document(ports, request.target / METADATA_NAME)
    if metadata.get("id") != str(request.fixture):
        raise deployments.unexpected("the fixture metadata names another fixture")
    if metadata.get("public_key_sha256") != request.public_key.hex:
        raise deployments.unexpected("the fixture metadata names another public key")
    listed = metadata.get("files")
    if not isinstance(listed, dict):
        raise deployments.unexpected("the fixture metadata lists no files")
    for name, expected in listed.items():
        _verify_one(ports, request, name, expected)
    policy = _document(ports, request.target / POLICY_NAME)
    if policy.get("default") != REJECT:
        raise deployments.unexpected("the fixture policy does not reject by default")
    return len(listed)


def swap_policy(ports: agentports.AgentPorts, request: Request) -> encoding.Document:
    """Keep the policy in force beside the fixture, then put the fixture's own in force."""
    current = safepaths.SafePath(Path(update_fixture.BUILDER_POLICY))
    if request.installed_a:
        if ports.digests.file(current) != request.policy:
            raise deployments.unexpected("installed A policy changed")
    elif _document(ports, current) != BOOTSTRAP_POLICY:
        raise deployments.unexpected("the policy in force is not the bootstrap policy")
    kept = request.target / BOOTSTRAP_NAME
    ports.files.copy(current, kept)
    if not request.installed_a:
        ports.files.copy(request.target / POLICY_NAME, current)
        deployments.output(ports, RESTORE)
    ports.digests.forget()
    return {
        "bootstrap_policy_sha256": ports.digests.file(kept).hex,
        "consumer_policy_sha256": ports.digests.file(current).hex,
    }


def run(
    ports: agentports.AgentPorts, *, arguments: Mapping[str, encoding.JsonValue]
) -> encoding.Document:
    guestguard.require_installed(ports)
    request = Request.parse(arguments)
    unpack(ports, request)
    verified = verify_files(ports, request)
    return {**swap_policy(ports, request), "files_verified": verified}


units.declare(units.Unit(id=identifiers.ProbeId("update.provision"), run=run))
