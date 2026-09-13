"""Stand a stored fixture image in as the payload a disk build derives from.

The recovery disk is built from image A of a completed update fixture, which the builder
holds in its store under the fixture's own tag; the disk script reads the payload under the
tag the target document's digest names, and reads that payload's manifest from the work
directory. Both are made here through the engine port, and the stored manifest must hash
to the digest the host asked for, so a tag that drifted since the fixture was built refuses.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from apex.agent import agentports, builder, units
from apex.config import defaults
from apex.kernel import encoding, errors, hashing, identifiers, quantities, refusals, safepaths
from apex.model import builds
from apex.ports import containers

WORK = "work"
SOURCE = "source"
DIGEST = "digest"
TRAVERSABLE = quantities.FileMode(0o755)
PLAIN = quantities.FileMode(0o644)


def run(
    ports: agentports.AgentPorts, *, arguments: Mapping[str, encoding.JsonValue]
) -> encoding.Document:
    builder.require_isolated(ports)
    work, source, digest = _arguments(arguments)
    tag = f"{defaults.PAYLOAD_TAG_PREFIX}{digest.hex}"
    stored = containers.ImageReference.stored(tag)
    ports.containers.copy(
        containers.ImageReference.stored(source), stored, policy=None, signing=None
    )
    manifest = ports.containers.manifest(stored)
    found = hashing.digest_bytes(manifest)
    if found != digest:
        raise errors.Refusal(
            refusals.RefusalReason.IMAGE_METADATA_MISMATCH,
            subject=f"{source} hashes to {found.hex}, not the fixture's digest",
            remedy="build the disk from the fixture the report names",
        )
    output = work / builds.OUTPUT_DIRECTORY
    ports.files.make_directory(output, mode=TRAVERSABLE)
    ports.files.write_atomic(output / defaults.PAYLOAD_MANIFEST_NAME, manifest, mode=PLAIN)
    return {
        "source": source,
        "tag": tag,
        "digest": str(digest),
        "image_id": str(ports.containers.image_id(tag)),
        "manifest": f"{builds.OUTPUT_DIRECTORY}/{defaults.PAYLOAD_MANIFEST_NAME}",
    }


def _arguments(
    arguments: Mapping[str, encoding.JsonValue],
) -> tuple[safepaths.SafePath, str, identifiers.Digest]:
    work, source, digest = arguments.get(WORK), arguments.get(SOURCE), arguments.get(DIGEST)
    if not isinstance(work, str) or not work.startswith(defaults.REMOTE_PREFIX):
        raise errors.Refusal(
            refusals.RefusalReason.REQUEST_MALFORMED,
            subject=f"work must be a directory under {defaults.REMOTE_PREFIX}",
        )
    if not isinstance(source, str) or not source.startswith("localhost/"):
        raise errors.Refusal(
            refusals.RefusalReason.REQUEST_MALFORMED, subject="source must be a stored local tag"
        )
    try:
        parsed = identifiers.Digest.parse(str(digest))
    except errors.Refusal as fault:
        raise errors.Refusal(
            refusals.RefusalReason.REQUEST_MALFORMED, subject="digest must name the fixture image"
        ) from fault
    return safepaths.SafePath(Path(work)), source, parsed


units.declare(units.Unit(id=identifiers.ProbeId("build.tag-payload"), run=run))
