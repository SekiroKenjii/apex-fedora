"""A small NVIDIA lock and the output a guest build would leave for it, agreeing by digest.

The lock names two vendor packages whose digests are the digests of the bytes written for
them here, so a run on fakes can be bound the way a real one is; the report is what the
older guest script writes, field for field.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from apex.config import defaults
from apex.kernel import quantities, safepaths
from apex.ports import files

PRIVATE = quantities.FileMode(0o600)
VERSION = "610.57.04"
KERNEL = "7.1.13-200.fc44.x86_64"
COMPILER = "gcc (GCC) 16.2.1 20260819 (Red Hat 16.2.1-2)"
VENDOR = {
    "nvidia-driver": b"the driver package",
    "nvidia-driver-libs": b"the driver libraries",
}
KMOD = f"packages/{defaults.NVIDIA_KMOD_PACKAGE}-{VERSION}-1.fc44.x86_64.rpm"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def lock_document() -> dict[str, object]:
    return {
        "schema": 1,
        "version": VERSION,
        "kernel_release": KERNEL,
        "compiler_text": COMPILER,
        "packages": [
            {"name": name, "version": VERSION, "release": "1.fc44", "arch": "x86_64",
             "sha256": digest(data)}
            for name, data in VENDOR.items()
        ],
    }


def lock_bytes() -> bytes:
    return json.dumps(lock_document(), indent=2).encode() + b"\n"


def write_lock(repository: Path, filesystem: files.FileSystemPort) -> str:
    """The lock on the disk, for the digest port, and in the file port, for the reader."""
    target = repository / defaults.NVIDIA_LOCK_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(lock_bytes())
    filesystem.write_atomic(safepaths.SafePath(target), lock_bytes(), mode=PRIVATE)
    return digest(lock_bytes())


def kernel_config(compiler: str = COMPILER) -> bytes:
    return f'CONFIG_LOCALVERSION=""\nCONFIG_CC_VERSION_TEXT="{compiler}"\n'.encode()


def artifacts() -> dict[str, bytes]:
    """Every file the guest leaves under output/nvidia, the report excepted."""
    found = {
        f"packages/{name}-{VERSION}-1.fc44.x86_64.rpm": data for name, data in VENDOR.items()
    }
    found[KMOD] = b"the kernel module package"
    found[defaults.NVIDIA_LOCK_COPY] = lock_bytes()
    found["nvidia-kmod-common.files.txt"] = b"/usr/lib/firmware/nvidia/610.57.04/gsp_ga10x.bin\n"
    return found


def report(image: str, **overrides: object) -> dict[str, object]:
    document: dict[str, object] = {
        "status": "PASS",
        "stage": "rpm-build",
        "image_id": f"sha256:{image}",
        "kernel_release": KERNEL,
        "version": VERSION,
        "vendor_rpms": [],
        "artifacts": {name: digest(data) for name, data in artifacts().items()},
        "source_lock_sha256": digest(lock_bytes()),
        "image_integration": "NOT TESTED",
        "initramfs": "NOT TESTED",
        "hardware": "NOT TESTED",
        "secure_boot": "NOT TESTED",
        "ready_to_install": False,
    }
    document.update(overrides)
    return document
