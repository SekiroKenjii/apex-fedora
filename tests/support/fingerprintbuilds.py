"""A completed fingerprint package build and a passed dialog test, laid out where a run reads them.

The package build's report names the checkout's lock and patches and inventories every file
it left; the dialog test's report names its inputs and every case's log. Both are written on
the disk and into the mirrored file port, so digests and reads agree.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from mirroredfiles import MirroredFiles

from apex.composition import exports, fingerprintpackages
from apex.config import defaults
from apex.kernel import identifiers, quantities, safepaths

REPOSITORY = Path(__file__).resolve().parents[2]
RPM_BUILD = identifiers.BuildId("1" * 32)
GTK_TEST = identifiers.BuildId("2" * 32)
PRIVATE = quantities.FileMode(0o600)
CASES = ("error-cancel-retry", "error-close", "cancel-twice", "close-pending", "daemon-replace")


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def patch_digests() -> dict[str, str]:
    lock = fingerprintpackages.load_lock(safepaths.SourceRoot.adopt(REPOSITORY))
    return {
        item.name: digest((REPOSITORY / item.patch).read_bytes()) for item in lock.packages
    }


def rpm_build(
    files: MirroredFiles, root: safepaths.RuntimeRoot, build: identifiers.BuildId = RPM_BUILD
) -> dict[str, Any]:
    """The package build's exports: mock outputs, package repository, archive and report."""
    lock = fingerprintpackages.load_lock(safepaths.SourceRoot.adopt(REPOSITORY))
    patches = patch_digests()
    home = exports.inside(root, build, "output")
    artifacts: dict[str, str] = {}
    packages: dict[str, Any] = {}

    def place(relative: str, payload: bytes) -> None:
        files.write_atomic(safepaths.SafePath(home.path / relative), payload, mode=PRIVATE)
        artifacts[relative] = digest(payload)

    for item in lock.packages:
        rpms = {}
        for name in _rpms_of(item, lock):
            place(f"{item.name}/{defaults.FINGERPRINT_MOCK_DIRECTORY}/{name}", name.encode())
            place(f"{defaults.FINGERPRINT_PACKAGES_DIRECTORY}/{name}", name.encode())
            rpms[name] = f"{item.name}|{item.version}"
        packages[item.name] = {"status": "PASS", "patch_sha256": patches[item.name], "rpms": rpms}
    settings = lock.package(fingerprintpackages.SETTINGS)
    place(f"{settings.name}/sources/{settings.archive}", b"settings archive")
    place(f"{defaults.FINGERPRINT_REPODATA_PREFIX}repomd.xml", b"<repomd/>")
    report = {
        "stage": "rpm-build", "status": "PASS", "source_lock_sha256": lock.digest.hex,
        "packages": packages, "ready_to_install": False, "hardware": "NOT TESTED",
        "image_integration": "NOT TESTED", "full_gtk_dbus_integration": "NOT TESTED",
        "artifacts": artifacts,
    }
    files.write_atomic(home / defaults.RESULTS_NAME, json.dumps(report).encode(), mode=PRIVATE)
    return report


def _rpms_of(
    item: fingerprintpackages.LockedPackage, lock: fingerprintpackages.PackageLock
) -> tuple[str, ...]:
    if item.name == fingerprintpackages.LIBRARY:
        return fingerprintpackages.smoke_rpms(lock)
    return tuple(name for name in fingerprintpackages.image_rpms(lock) if item.name in name)


def gtk_test(
    files: MirroredFiles, root: safepaths.RuntimeRoot, test: identifiers.BuildId = GTK_TEST
) -> dict[str, Any]:
    """The dialog test's exports: a log per case per variant, and the report naming them."""
    home = exports.inside(root, test, "output")
    variants: dict[str, Any] = {}
    for variant in ("original", "patched"):
        cases = {}
        for case in CASES:
            log = f"{variant} {case} log\n".encode()
            files.write_atomic(
                safepaths.SafePath(home.path / variant / case / "dialog.log"), log, mode=PRIVATE
            )
            cases[case] = {"status": "PASS", "log_sha256": digest(log)}
        variants[variant] = cases
    inputs = dict.fromkeys(defaults.GTK_INPUT_FILES, "0" * 64)
    report = {
        "status": "PASS", "inputs": inputs, "variants": variants,
        "patch_sha256": patch_digests()[fingerprintpackages.SETTINGS],
    }
    files.write_atomic(home / defaults.RESULTS_NAME, json.dumps(report).encode(), mode=PRIVATE)
    return report
