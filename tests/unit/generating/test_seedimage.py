"""The seed image is an ISO 9660 volume laid out sector by sector, the same for the same files."""

from __future__ import annotations

import struct

import pytest

from apex.generating import seedimage
from apex.kernel import errors, refusals

SECTOR = 2048
FILES = {"user-data": b"#cloud-config\n", "meta-data": b"{}"}


def records(directory: bytes) -> list[tuple[bytes, int, int, int]]:
    """Each record's identifier, extent, length and flags, read the way a reader would."""
    found: list[tuple[bytes, int, int, int]] = []
    offset = 0
    while offset < len(directory) and directory[offset]:
        length = directory[offset]
        extent = struct.unpack_from("<I", directory, offset + 2)[0]
        size = struct.unpack_from("<I", directory, offset + 10)[0]
        flags = directory[offset + 25]
        width = directory[offset + 32]
        found.append((directory[offset + 33 : offset + 33 + width], extent, size, flags))
        offset += length
    return found


def sector(image: bytes, index: int) -> bytes:
    return image[index * SECTOR : (index + 1) * SECTOR]


def test_the_descriptor_names_the_volume_the_tables_and_the_root_directory() -> None:
    image = seedimage.image("cidata", FILES)

    descriptor = sector(image, 16)
    assert descriptor[0] == 1 and descriptor[1:6] == b"CD001" and descriptor[6] == 1
    assert descriptor[40:72] == b"cidata".ljust(32)
    assert struct.unpack_from("<I", descriptor, 80)[0] == 23
    assert struct.unpack_from(">I", descriptor, 84)[0] == 23
    assert struct.unpack_from("<H", descriptor, 128)[0] == SECTOR
    assert struct.unpack_from("<I", descriptor, 140)[0] == 18
    assert struct.unpack_from(">I", descriptor, 148)[0] == 19
    assert records(descriptor[156:190]) == [(b"\x00", 20, SECTOR, 2)]
    assert descriptor[881] == 1
    assert sector(image, 17)[:7] == b"\xffCD001\x01"
    assert len(image) == 23 * SECTOR


def test_the_path_tables_point_at_the_root_in_both_byte_orders() -> None:
    image = seedimage.image("cidata", FILES)

    assert sector(image, 18)[:10] == bytes((1, 0)) + struct.pack("<I", 20) + b"\x01\x00\x00\x00"
    assert sector(image, 19)[:10] == bytes((1, 0)) + struct.pack(">I", 20) + b"\x00\x01\x00\x00"


def test_the_root_directory_lists_both_files_in_order_at_their_extents() -> None:
    image = seedimage.image("cidata", FILES)

    assert records(sector(image, 20)) == [
        (b"\x00", 20, SECTOR, 2),
        (b"\x01", 20, SECTOR, 2),
        (b"META-DATA.;1", 21, 2, 0),
        (b"USER-DATA.;1", 22, 14, 0),
    ]
    assert sector(image, 21)[:2] == b"{}"
    assert sector(image, 22)[:14] == b"#cloud-config\n"
    assert sector(image, 22)[14:] == bytes(SECTOR - 14)


def test_a_file_longer_than_a_sector_moves_the_next_extent() -> None:
    image = seedimage.image("cidata", {"a": b"x" * (SECTOR + 1), "b": b"y"})

    assert records(sector(image, 20))[2:] == [(b"A.;1", 21, SECTOR + 1, 0), (b"B.;1", 23, 1, 0)]
    assert len(image) == 24 * SECTOR
    assert sector(image, 23)[:1] == b"y"


def test_the_same_files_make_the_same_bytes() -> None:
    reversed_files = dict(reversed(FILES.items()))

    assert seedimage.image("cidata", FILES) == seedimage.image("cidata", reversed_files)


@pytest.mark.parametrize(
    "volume,files",
    [
        ("bad label!", {"a": b""}),
        ("", {"a": b""}),
        ("cidata", {"User-Data": b""}),
        ("cidata", {"a" * 31: b""}),
        ("cidata", {"a/b": b""}),
    ],
)
def test_a_label_or_name_outside_the_plain_set_is_refused(
    volume: str, files: dict[str, bytes]
) -> None:
    with pytest.raises(errors.Refusal) as caught:
        seedimage.image(volume, files)

    assert caught.value.reason is refusals.RefusalReason.MALFORMED_IDENTIFIER
