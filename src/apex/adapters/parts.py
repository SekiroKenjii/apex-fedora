"""Settling a partial download into its destination, once the bytes match the pin.

Both fetchers write a `.part` file first. A mismatch leaves it where it is and refuses, so
the destination is only ever a file whose digest was checked.
"""

from __future__ import annotations

from pathlib import Path

from apex.kernel import errors, hashing, identifiers, quantities, refusals

PART_SUFFIX = ".part"
PRIVATE_FILE = quantities.FileMode(0o600)
PRIVATE_DIRECTORY = 0o700


def part_of(destination: Path) -> Path:
    return destination.with_name(destination.name + PART_SUFFIX)


def settle(part: Path, destination: Path, expected: identifiers.Digest) -> identifiers.Digest:
    with part.open("rb") as handle:
        observed = hashing.digest_stream(iter(lambda: handle.read(hashing.READ_CHUNK), b""))
    if observed != expected:
        raise errors.Refusal(
            refusals.RefusalReason.DOWNLOAD_CHECKSUM_MISMATCH,
            subject=destination.name,
            remedy=f"the partial download is retained at {part} for inspection",
        )
    part.chmod(PRIVATE_FILE.value)
    part.replace(destination)
    return observed
