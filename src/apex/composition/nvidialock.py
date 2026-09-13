"""The reviewed NVIDIA lock, the compiler it binds the image to, and the report it must bind.

The older `build-nvidia` refused before the build when the frozen image's compiler was not
the lock's, and refused after it unless the guest's report was bound to the same image, the
same lock and the same package set, artifact by artifact, digest by digest. The same
refusals live here, through the ports, with names.
"""

from __future__ import annotations

import dataclasses
import json
import re
from collections.abc import Mapping
from pathlib import PurePosixPath

from apex.composition import exports
from apex.config import defaults
from apex.kernel import encoding, errors, identifiers, refusals, safepaths
from apex.model import builds, oci
from apex.ports import portset
from apex.targeting import releases

COMPILER_LINE = re.compile(r'^CONFIG_CC_VERSION_TEXT="([^"]+)"$', re.MULTILINE)
PASS = "PASS"
STAGE = "rpm-build"
NOT_TESTED = "NOT TESTED"
UNTESTED_FIELDS = ("image_integration", "initramfs", "hardware", "secure_boot")
PACKAGES = "packages/"
RPM = ".rpm"


@dataclasses.dataclass(frozen=True, slots=True)
class LockedPackage:
    name: str
    version: str
    release: str
    arch: str
    sha256: str

    @property
    def path(self) -> str:
        return f"{PACKAGES}{self.name}-{self.version}-{self.release}.{self.arch}{RPM}"


@dataclasses.dataclass(frozen=True, slots=True)
class NvidiaLock:
    version: str
    kernel_release: str
    compiler_text: str
    packages: tuple[LockedPackage, ...]
    digest: identifiers.Digest

    @property
    def kmod_path(self) -> str:
        current = releases.current()
        release = current.dist_tag.applied("1")
        return (
            f"{PACKAGES}{defaults.NVIDIA_KMOD_PACKAGE}-{self.version}-{release}"
            f".{current.architecture}{RPM}"
        )

    @property
    def expected_rpms(self) -> frozenset[str]:
        return frozenset({package.path for package in self.packages} | {self.kmod_path})


def load(ports: portset.HostPorts, repository: safepaths.SourceRoot) -> NvidiaLock:
    """The lock as the checkout holds it, with the digest the guest must report back."""
    path = safepaths.SafePath(repository.path / defaults.NVIDIA_LOCK_PATH)
    try:
        payload = ports.files.read_bytes(path, limit=defaults.DOCUMENT_LIMIT.value)
        document = encoding.parse_object(payload)
        packages = document["packages"]
        if not isinstance(packages, list):
            raise TypeError("packages")
        return NvidiaLock(
            version=str(document["version"]),
            kernel_release=str(document["kernel_release"]),
            compiler_text=str(document["compiler_text"]),
            packages=tuple(_package(item) for item in packages),
            digest=ports.digests.file(path),
        )
    except (errors.PortFailure, KeyError, TypeError, ValueError) as error:
        raise errors.Refusal(
            refusals.RefusalReason.NVIDIA_LOCK_MALFORMED,
            subject=f"{defaults.NVIDIA_LOCK_PATH}: {error}",
        ) from error


def _package(item: object) -> LockedPackage:
    if not isinstance(item, Mapping):
        raise TypeError("package")
    return LockedPackage(
        name=str(item["name"]), version=str(item["version"]), release=str(item["release"]),
        arch=str(item["arch"]), sha256=str(item["sha256"]),
    )


def require_compiler(
    ports: portset.HostPorts,
    root: safepaths.RuntimeRoot,
    parent: identifiers.BuildId,
    lock: NvidiaLock,
) -> None:
    """The parent image was compiled by the compiler the lock names, or nothing is built."""
    path = exports.inside(root, parent, f"{builds.OUTPUT_DIRECTORY}/{defaults.KERNEL_CONFIG_NAME}")
    try:
        text = ports.files.read_bytes(path, limit=defaults.DOCUMENT_LIMIT.value).decode(
            errors="replace"
        )
    except errors.PortFailure as failure:
        raise errors.Refusal(
            refusals.RefusalReason.BUILD_PARENT_NOT_COMPLETE,
            subject=f"build {parent} left no {defaults.KERNEL_CONFIG_NAME}: {failure.cause}",
        ) from failure
    if COMPILER_LINE.findall(text) != [lock.compiler_text]:
        raise errors.Refusal(
            refusals.RefusalReason.NVIDIA_COMPILER_MISMATCH,
            subject=f"build {parent}: the kernel config does not name {lock.compiler_text!r}",
            remedy="review the lock against the image, or rebuild the image",
        )


def _unbound(detail: str) -> errors.Refusal:
    return errors.Refusal(refusals.RefusalReason.NVIDIA_REPORT_UNBOUND, subject=detail)


def _bound(report: Mapping[str, object], frozen: oci.FrozenImage, lock: NvidiaLock) -> None:
    if report.get("status") != PASS or report.get("stage") != STAGE:
        raise _unbound("the report is not a passed rpm-build")
    if report.get("image_id") != str(frozen.image_id):
        raise _unbound("the report names another image")
    if report.get("source_lock_sha256") != lock.digest.hex:
        raise _unbound("the report names another lock")
    if report.get("ready_to_install") is not False:
        raise _unbound("the report claims readiness it cannot have")
    if any(report.get(name) != NOT_TESTED for name in UNTESTED_FIELDS):
        raise _unbound("the report claims a test it did not run")
    if report.get("kernel_release") != lock.kernel_release or report.get("version") != lock.version:
        raise _unbound("the report's kernel or version differ from the lock")


def _artifacts(report: Mapping[str, object]) -> dict[str, str]:
    artifacts = report.get("artifacts")
    if not isinstance(artifacts, Mapping) or defaults.NVIDIA_LOCK_COPY not in artifacts:
        raise _unbound("the output is incomplete")
    for relative in artifacts:
        parsed = PurePosixPath(relative)
        if parsed.is_absolute() or ".." in parsed.parts or parsed.as_posix() != relative:
            raise _unbound(f"{relative}: an artifact path escapes its output")
    return {str(name): str(value) for name, value in artifacts.items()}


def _require_digests(
    ports: portset.HostPorts,
    root: safepaths.RuntimeRoot,
    home: safepaths.SafePath,
    artifacts: Mapping[str, str],
) -> None:
    for relative, expected in artifacts.items():
        try:
            found = ports.digests.file(
                safepaths.SafePath.regular_file(home.path / relative, within=root)
            )
        except (errors.Refusal, errors.PortFailure) as problem:
            raise errors.Refusal(
                refusals.RefusalReason.ARTIFACT_CHECKSUM_MISMATCH,
                subject=f"{relative}: {problem}",
            ) from problem
        if found.hex != expected:
            raise errors.Refusal(
                refusals.RefusalReason.ARTIFACT_CHECKSUM_MISMATCH,
                subject=f"{relative}: differs from the transferred report",
            )


def _require_packages(artifacts: Mapping[str, str], lock: NvidiaLock) -> None:
    if artifacts[defaults.NVIDIA_LOCK_COPY] != lock.digest.hex:
        raise _unbound("the transferred lock differs from the build input")
    actual = frozenset(
        name for name in artifacts if name.startswith(PACKAGES) and name.endswith(RPM)
    )
    if actual != lock.expected_rpms:
        raise errors.Refusal(
            refusals.RefusalReason.NVIDIA_PACKAGES_INCOMPLETE,
            subject=f"expected {len(lock.expected_rpms)} packages, found {len(actual)}",
        )
    for package in lock.packages:
        if artifacts[package.path] != package.sha256:
            raise errors.Refusal(
                refusals.RefusalReason.NVIDIA_PACKAGES_INCOMPLETE,
                subject=f"{package.path}: differs from its source lock",
            )


def verify_report(
    ports: portset.HostPorts,
    root: safepaths.RuntimeRoot,
    home: safepaths.SafePath,
    *,
    frozen: oci.FrozenImage,
    lock: NvidiaLock,
) -> encoding.Document:
    """The guest's report, accepted only when bound to this image, this lock and its packages."""
    path = safepaths.SafePath(home.path / defaults.NVIDIA_REPORT_NAME)
    try:
        report = encoding.parse_object(
            ports.files.read_bytes(path, limit=defaults.DOCUMENT_LIMIT.value)
        )
    except (errors.PortFailure, json.JSONDecodeError, errors.Refusal) as problem:
        raise _unbound(f"{defaults.NVIDIA_REPORT_NAME}: {problem}") from problem
    _bound(report, frozen, lock)
    artifacts = _artifacts(report)
    _require_digests(ports, root, home, artifacts)
    _require_packages(artifacts, lock)
    return report
