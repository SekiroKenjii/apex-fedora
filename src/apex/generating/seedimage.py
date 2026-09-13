"""An ISO 9660 image of a few small files, written whole and the same way every time.

The builder's NoCloud seed is two text files on a volume labelled for cloud-init, and no
host tool that writes such an image is on every machine, so the bytes are laid out here:
sixteen empty sectors, one primary descriptor, the terminator, both path tables, one root
directory and the files, each on its own sector boundary, with a fixed recording date so
the same files always make the same image. The kernel maps an identifier such as
`USER-DATA.;1` to `user-data` when the volume is mounted, so no extension is written.
"""

from __future__ import annotations

import re
import struct
from collections.abc import Mapping

from apex.kernel import errors, refusals

SECTOR = 2048
SYSTEM_AREA = 16
DESCRIPTOR = 16
TERMINATOR = 17
PATH_TABLE_L = 18
PATH_TABLE_M = 19
ROOT = 20
FIRST_FILE = 21
STANDARD = b"CD001"
VERSION = 1
PRIMARY = 1
SET_TERMINATOR = 255
DIRECTORY_FLAG = 2
FILE_FLAG = 0
RECORDED = bytes((126, 1, 1, 0, 0, 0, 0))
UNSPECIFIED_DATE = b"0" * 16 + b"\x00"
SYSTEM = b"LINUX"
PATH_TABLE_SIZE = 10
SUFFIX = ".;1"
NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,29}")
VOLUME = re.compile(r"[A-Za-z0-9_-]{1,32}")
TEXT_FIELDS = ((190, 128), (318, 128), (446, 128), (574, 128), (702, 37), (739, 37), (776, 37))
DATE_FIELDS = (813, 830, 847, 864)


def image(volume: str, files: Mapping[str, bytes]) -> bytes:
    """The whole image: the descriptors, the tables, the root directory and every file."""
    if VOLUME.fullmatch(volume) is None:
        raise _malformed(f"volume {volume!r}")
    names = sorted(files)
    for name in names:
        if NAME.fullmatch(name) is None:
            raise _malformed(f"file name {name!r}")
    root = _record(b"\x00", extent=ROOT, length=SECTOR, flags=DIRECTORY_FLAG)
    directory = root + _record(b"\x01", extent=ROOT, length=SECTOR, flags=DIRECTORY_FLAG)
    extent = FIRST_FILE
    bodies: list[bytes] = []
    for name in names:
        body = files[name]
        directory += _record(
            _identifier(name), extent=extent, length=len(body), flags=FILE_FLAG
        )
        bodies.append(_padded(body))
        extent += max(1, len(bodies[-1]) // SECTOR)
    if len(directory) > SECTOR:
        raise _malformed("too many files for one directory sector")
    return b"".join((
        bytes(SECTOR * SYSTEM_AREA),
        _descriptor(volume, total=extent, root=root),
        _padded(bytes((SET_TERMINATOR,)) + STANDARD + bytes((VERSION,))),
        _padded(_path_table("<")),
        _padded(_path_table(">")),
        _padded(directory),
        *bodies,
    ))


def _identifier(name: str) -> bytes:
    return (name.upper() + SUFFIX).encode()


def _both16(value: int) -> bytes:
    return struct.pack("<H", value) + struct.pack(">H", value)


def _both32(value: int) -> bytes:
    return struct.pack("<I", value) + struct.pack(">I", value)


def _padded(payload: bytes) -> bytes:
    """The payload filled to whole sectors; an empty one still takes a sector of its own."""
    if not payload:
        return bytes(SECTOR)
    return payload + bytes(-len(payload) % SECTOR)


def _record(identifier: bytes, *, extent: int, length: int, flags: int) -> bytes:
    body = (
        b"\x00"
        + _both32(extent)
        + _both32(length)
        + RECORDED
        + bytes((flags, 0, 0))
        + _both16(1)
        + bytes((len(identifier),))
        + identifier
    )
    record = bytes((len(body) + 1,)) + body
    return record if len(record) % 2 == 0 else bytes((len(record) + 1,)) + body + b"\x00"


def _path_table(order: str) -> bytes:
    return (
        bytes((1, 0))
        + struct.pack(f"{order}I", ROOT)
        + struct.pack(f"{order}H", 1)
        + b"\x00\x00"
    )


def _descriptor(volume: str, *, total: int, root: bytes) -> bytes:
    descriptor = bytearray(SECTOR)
    descriptor[0] = PRIMARY
    descriptor[1:6] = STANDARD
    descriptor[6] = VERSION
    descriptor[8:40] = SYSTEM.ljust(32)
    descriptor[40:72] = volume.encode().ljust(32)
    descriptor[80:88] = _both32(total)
    descriptor[120:124] = _both16(1)
    descriptor[124:128] = _both16(1)
    descriptor[128:132] = _both16(SECTOR)
    descriptor[132:140] = _both32(PATH_TABLE_SIZE)
    descriptor[140:144] = struct.pack("<I", PATH_TABLE_L)
    descriptor[148:152] = struct.pack(">I", PATH_TABLE_M)
    descriptor[156:190] = root
    for start, width in TEXT_FIELDS:
        descriptor[start:start + width] = b" " * width
    for start in DATE_FIELDS:
        descriptor[start:start + len(UNSPECIFIED_DATE)] = UNSPECIFIED_DATE
    descriptor[881] = 1
    return bytes(descriptor)


def _malformed(detail: str) -> errors.Refusal:
    return errors.Refusal(
        refusals.RefusalReason.MALFORMED_IDENTIFIER,
        subject=detail,
        remedy="seed files take plain lower-case names and a plain volume label",
    )
