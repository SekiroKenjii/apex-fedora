"""Bring an earlier build's OCI archive into the builder's own store, as the shipped script did.

This is `guest/import-payload.sh` through the engine port: the archive the parent build
left under its run directory is copied with digests preserved into the local store under
a tag named by the target's digest, the stored manifest is written beside the work and
hashed against that digest, and the stored image's identifier is compared with the
target's, because an export can change layer compression and a matching identifier alone
proves nothing.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from apex.agent import agentports, builder, units
from apex.composition import exports
from apex.config import defaults
from apex.kernel import encoding, errors, hashing, identifiers, quantities, refusals, safepaths
from apex.model import builds, oci
from apex.ports import containers, files

WORK = "work"
PARENT = "parent"
TRAVERSABLE = quantities.FileMode(0o755)
PLAIN = quantities.FileMode(0o644)


def run(
    ports: agentports.AgentPorts, *, arguments: Mapping[str, encoding.JsonValue]
) -> encoding.Document:
    builder.require_isolated(ports)
    work, parent = _arguments(arguments)
    frozen = oci.FrozenImage.parse(
        ports.files.read_bytes(work / builds.TARGET_DOCUMENT, limit=defaults.DOCUMENT_LIMIT.value)
    )
    archive = _archive(ports, parent, frozen)
    tag = f"{defaults.PAYLOAD_TAG_PREFIX}{frozen.digest.hex}"
    stored = containers.ImageReference.stored(tag)
    ports.containers.copy(
        containers.ImageReference(containers.Transport.OCI_ARCHIVE, str(archive)), stored,
        policy=None, signing=None,
    )
    manifest = ports.containers.manifest(stored)
    output = work / builds.OUTPUT_DIRECTORY
    ports.files.make_directory(output, mode=TRAVERSABLE)
    ports.files.write_atomic(output / defaults.PAYLOAD_MANIFEST_NAME, manifest, mode=PLAIN)
    found = hashing.digest_bytes(manifest)
    if found != frozen.digest:
        raise _mismatch(f"the stored manifest hashes to {found.hex}, not the target's digest")
    image_id = ports.containers.image_id(tag)
    if image_id != frozen.image_id:
        raise _mismatch(f"the stored image is {image_id}, not the target's {frozen.image_id}")
    return {
        "archive": str(archive),
        "tag": tag,
        "digest": str(frozen.digest),
        "image_id": str(image_id),
        "manifest": f"{builds.OUTPUT_DIRECTORY}/{defaults.PAYLOAD_MANIFEST_NAME}",
    }


def _arguments(
    arguments: Mapping[str, encoding.JsonValue],
) -> tuple[safepaths.SafePath, identifiers.BuildId]:
    work = arguments.get(WORK)
    parent = arguments.get(PARENT)
    if not isinstance(work, str) or not work.startswith(defaults.REMOTE_PREFIX):
        raise errors.Refusal(
            refusals.RefusalReason.REQUEST_MALFORMED,
            subject=f"work must be a directory under {defaults.REMOTE_PREFIX}",
        )
    try:
        identifiers.RunId.parse(work.rsplit("-", 1)[-1])
        parsed = identifiers.BuildId.parse(str(parent))
    except errors.Refusal as fault:
        raise errors.Refusal(
            refusals.RefusalReason.REQUEST_MALFORMED,
            subject="work must be named for its run and parent must be a build identifier",
        ) from fault
    return safepaths.SafePath(Path(work)), parsed


def _archive(
    ports: agentports.AgentPorts, parent: identifiers.BuildId, frozen: oci.FrozenImage
) -> safepaths.RemotePath:
    try:
        profile = builds.Profile(frozen.profile)
    except ValueError as fault:
        raise errors.Refusal(
            refusals.RefusalReason.MALFORMED_IMAGE_DOCUMENT, subject=f"profile {frozen.profile!r}"
        ) from fault
    archive = exports.payload(parent, profile)
    try:
        kind = ports.files.inspect(safepaths.SafePath(Path(str(archive)))).kind
    except errors.PortFailure as failure:
        raise errors.Refusal(
            refusals.RefusalReason.PATH_NOT_A_REGULAR_FILE,
            subject=f"{archive}: {failure.cause}",
            remedy="the parent build's archive must still be in the builder",
        ) from failure
    if kind is not files.EntryKind.REGULAR:
        raise errors.Refusal(refusals.RefusalReason.PATH_NOT_A_REGULAR_FILE, subject=str(archive))
    return archive


def _mismatch(detail: str) -> errors.Refusal:
    return errors.Refusal(
        refusals.RefusalReason.IMAGE_METADATA_MISMATCH,
        subject=detail,
        remedy="import the archive the target document was frozen from",
    )


units.declare(units.Unit(id=identifiers.ProbeId("build.import-payload"), run=run))
