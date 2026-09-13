"""The fingerprint packages: their reviewed lock, the names they come out under, and the reports
that bind a package build, its smoke test, its dialog test and the image made from them.

The lock pins each Fedora source package, its archive and its spec, and names the patch each
carries; a built package comes out under the lock's build number over the supported
distribution tag and the vendor suffix. A package build's report is accepted only when it
names the lock the checkout holds, claims no test it did not run, lists both packages as
passed with the patch the checkout carries and inventories every artifact it left, and
every artifact is digested again on the host after the transfer. The smoke and dialog
reports are bound to the inputs the host sent, and the image request binds the tested
packages by digest to the build that installs them.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from pathlib import PurePosixPath

from apex.config import defaults, sourcepins
from apex.kernel import encoding, errors, hashing, identifiers, refusals, safepaths
from apex.ports import portset
from apex.targeting import releases

SCHEMA = 1
BUILD = "1"
STAGE = "rpm-build"
PASS = "PASS"
NOT_TESTED = "NOT TESTED"
UNTESTED_FIELDS = ("hardware", "image_integration", "full_gtk_dbus_integration")
LIBRARY = "libfprint"
SETTINGS = "gnome-control-center"
TESTS_SUBPACKAGE = "libfprint-tests"
FILESYSTEM_SUBPACKAGE = "gnome-control-center-filesystem"
NOARCH = "noarch"
SMOKE_CASES = frozenset({"fpi-ssm", "fpi-device"})
PATCH_DIGEST = "patch_sha256"
LOG_DIGEST = "log_sha256"


@dataclasses.dataclass(frozen=True, slots=True)
class LockedPackage:
    name: str
    version: str
    archive: str
    patch: str


@dataclasses.dataclass(frozen=True, slots=True)
class PackageLock:
    release: str
    packages: tuple[LockedPackage, ...]
    digest: identifiers.Digest

    def package(self, name: str) -> LockedPackage:
        for item in self.packages:
            if item.name == name:
                return item
        raise errors.Refusal(
            refusals.RefusalReason.FINGERPRINT_LOCK_MALFORMED, subject=f"no package {name}"
        )


@dataclasses.dataclass(frozen=True, slots=True)
class RpmBuildReport:
    document: encoding.Document
    artifacts: Mapping[str, str]
    patches: Mapping[str, str]


@dataclasses.dataclass(frozen=True, slots=True)
class GtkReport:
    document: encoding.Document
    inputs: Mapping[str, str]
    patch: str
    logs: Mapping[str, str]


@dataclasses.dataclass(frozen=True, slots=True)
class Request:
    rpm_build: identifiers.BuildId
    gtk_test: identifiers.BuildId
    gtk_report: identifiers.Digest
    rpms: Mapping[str, identifiers.Digest]

    def document(self) -> encoding.Document:
        return {
            "rpm_build": str(self.rpm_build),
            "gtk_test": str(self.gtk_test),
            "gtk_report_sha256": self.gtk_report.hex,
            "rpms": {name: digest.hex for name, digest in self.rpms.items()},
        }


def _unbound(detail: str) -> errors.Refusal:
    return errors.Refusal(refusals.RefusalReason.FINGERPRINT_REPORT_UNBOUND, subject=detail)


def _malformed(detail: str) -> errors.Refusal:
    return errors.Refusal(refusals.RefusalReason.FINGERPRINT_LOCK_MALFORMED, subject=detail)


def load_lock(repository: safepaths.SourceRoot) -> PackageLock:
    document, parsed = sourcepins.reviewed_document(
        repository.path / defaults.FINGERPRINT_RPMS_LOCK_PATH
    )
    if not isinstance(parsed, Mapping) or parsed.get("schema") != SCHEMA:
        raise _malformed("schema")
    listed = parsed.get("packages")
    if not isinstance(listed, list) or [p.get("name") for p in listed] != [LIBRARY, SETTINGS]:
        raise _malformed("the lock names the library and the settings packages, in that order")
    try:
        packages = tuple(
            LockedPackage(
                name=str(item["name"]), version=str(item["version"]),
                archive=str(item["archive"]), patch=str(item["patch"]),
            )
            for item in listed
        )
    except (KeyError, TypeError) as error:
        raise _malformed(str(error)) from error
    return PackageLock(
        release=str(parsed.get("release", "")), packages=packages,
        digest=hashing.digest_bytes(document),
    )


def release() -> str:
    """The build number over the supported tag and the vendor suffix, as the guest spells it."""
    return releases.current().dist_tag.applied(
        BUILD, vendor_suffix=defaults.FINGERPRINT_VENDOR_SUFFIX
    )


def rpm_name(name: str, version: str, architecture: str | None = None) -> str:
    arch = releases.current().architecture if architecture is None else architecture
    return f"{name}-{version}-{release()}.{arch}.rpm"


def image_rpms(lock: PackageLock) -> tuple[str, ...]:
    """The three packages the image installs: the library, the settings, its filesystem half."""
    library, settings = lock.package(LIBRARY), lock.package(SETTINGS)
    return (
        rpm_name(library.name, library.version),
        rpm_name(settings.name, settings.version),
        rpm_name(FILESYSTEM_SUBPACKAGE, settings.version, NOARCH),
    )


def smoke_rpms(lock: PackageLock) -> tuple[str, ...]:
    library = lock.package(LIBRARY)
    return (rpm_name(library.name, library.version), rpm_name(TESTS_SUBPACKAGE, library.version))


def patch_digests(
    ports: portset.HostPorts, repository: safepaths.SourceRoot, lock: PackageLock
) -> dict[str, identifiers.Digest]:
    return {
        item.name: ports.digests.file(safepaths.SafePath(repository.path / item.patch))
        for item in lock.packages
    }


def _relative(name: str) -> str:
    parsed = PurePosixPath(name)
    if parsed.is_absolute() or ".." in parsed.parts or parsed.as_posix() != name:
        raise _unbound(f"{name}: an artifact path escapes its output")
    return name


def _artifacts(document: encoding.Document) -> dict[str, str]:
    artifacts = document.get("artifacts")
    if not isinstance(artifacts, Mapping) or not artifacts:
        raise _unbound("the report inventories no artifact")
    if not any(str(name).startswith(defaults.FINGERPRINT_REPODATA_PREFIX) for name in artifacts):
        raise _unbound("the report lists no local package repository")
    return {_relative(str(name)): str(value) for name, value in artifacts.items()}


def _package_entries(
    document: encoding.Document, lock: PackageLock, patches: Mapping[str, identifiers.Digest],
    artifacts: Mapping[str, str],
) -> dict[str, str]:
    packages = document.get("packages")
    if not isinstance(packages, Mapping) or set(packages) != {p.name for p in lock.packages}:
        raise _unbound("the report does not cover the locked package set")
    found: dict[str, str] = {}
    for name, entry in packages.items():
        if not isinstance(entry, Mapping):
            raise _unbound(f"{name}: not a package entry")
        rpms = entry.get("rpms")
        if not isinstance(rpms, Mapping) or not rpms or entry.get("status") != PASS:
            raise _unbound(f"{name}: not a passed build with packages")
        if entry.get(PATCH_DIGEST) != patches[str(name)].hex:
            raise _unbound(f"{name}: not a build of the checkout's patch")
        built = (f"{name}/{defaults.FINGERPRINT_MOCK_DIRECTORY}/{rpm}" for rpm in rpms)
        if any(path not in artifacts for path in built):
            raise _unbound(f"{name}: a built package is missing from the inventory")
        found[str(name)] = str(entry.get(PATCH_DIGEST))
    return found


def parse_rpm_report(
    document: encoding.Document, lock: PackageLock, patches: Mapping[str, identifiers.Digest]
) -> RpmBuildReport:
    """The package build's report, accepted only when bound to this lock and these patches."""
    if document.get("status") != PASS or document.get("stage") != STAGE:
        raise _unbound("the report is not a passed rpm-build")
    if document.get("source_lock_sha256") != lock.digest.hex:
        raise _unbound("the report names another lock")
    if document.get("ready_to_install") is not False:
        raise _unbound("the report claims readiness it cannot have")
    if any(document.get(name) != NOT_TESTED for name in UNTESTED_FIELDS):
        raise _unbound("the report claims a test it did not run")
    artifacts = _artifacts(document)
    found = _package_entries(document, lock, patches, artifacts)
    return RpmBuildReport(document=dict(document), artifacts=artifacts, patches=found)


def require_artifacts(
    ports: portset.HostPorts,
    root: safepaths.RuntimeRoot,
    home: safepaths.SafePath,
    artifacts: Mapping[str, str],
) -> None:
    """Every inventoried artifact digests on the host to what the report says it is."""
    for relative, expected in artifacts.items():
        try:
            found = ports.digests.file(
                safepaths.SafePath.regular_file(home.path / relative, within=root)
            )
        except (errors.Refusal, errors.PortFailure) as problem:
            raise errors.Refusal(
                refusals.RefusalReason.ARTIFACT_CHECKSUM_MISMATCH, subject=f"{relative}: {problem}"
            ) from problem
        if found.hex != expected:
            raise errors.Refusal(
                refusals.RefusalReason.ARTIFACT_CHECKSUM_MISMATCH,
                subject=f"{relative}: differs from the transferred report",
            )


def parse_gtk_report(document: encoding.Document) -> GtkReport:
    """The dialog test's report, with every case's log named by digest."""
    if document.get("status") != PASS:
        raise _unbound("the dialog test did not pass")
    inputs, variants = document.get("inputs"), document.get("variants")
    if not isinstance(inputs, Mapping) or not isinstance(variants, Mapping):
        raise _unbound("the dialog report names no inputs or no variants")
    logs: dict[str, str] = {}
    for variant, cases in variants.items():
        if not isinstance(cases, Mapping):
            raise _unbound(f"{variant}: no cases")
        for name, case in cases.items():
            if not isinstance(case, Mapping) or case.get("status") != PASS and variant == "patched":
                raise _unbound(f"{variant}/{name}: not a passed case")
            logs[f"{variant}/{name}"] = str(case.get(LOG_DIGEST, ""))
    return GtkReport(
        document=dict(document),
        inputs={str(name): str(value) for name, value in inputs.items()},
        patch=str(document.get(PATCH_DIGEST, "")),
        logs=logs,
    )


def require_gtk_logs(
    ports: portset.HostPorts,
    root: safepaths.RuntimeRoot,
    home: safepaths.SafePath,
    report: GtkReport,
) -> None:
    require_artifacts(
        ports, root, home, {f"{case}/dialog.log": digest for case, digest in report.logs.items()}
    )


def judge_smoke(document: encoding.Document, inputs: Mapping[str, str]) -> str | None:
    """Why the smoke report is not a pass over the packages sent, or nothing when it is."""
    if document.get("status") != PASS:
        return "the packaged library tests did not pass"
    if document.get("rpm_sha256") != dict(inputs):
        return "the report names other packages than the ones sent"
    cases = document.get("cases")
    if not isinstance(cases, Mapping) or set(cases) != SMOKE_CASES:
        return "the report does not cover both test programs"
    if any(not isinstance(case, Mapping) or case.get("status") != PASS for case in cases.values()):
        return "a test program did not pass"
    if document.get("hardware") != NOT_TESTED:
        return "the report claims a hardware test it did not run"
    return None


def judge_gtk(report: GtkReport, inputs: Mapping[str, str]) -> str | None:
    if dict(report.inputs) != dict(inputs):
        return "the report names other inputs than the ones sent"
    return None
