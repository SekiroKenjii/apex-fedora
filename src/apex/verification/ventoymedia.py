"""The host side of the Ventoy medium: the inputs proven, the request written, the medium bound.

The older `ventoy-media` accepted the live bundle only against a key supplied from outside
it, the Ubuntu image only against the checksums Canonical signed with the pinned signer, and
the Ventoy release only at the pinned digest with its own checksum file agreeing; then it
handed the builder the three inputs and a request naming their digests, and accepted the
medium only when the builder's report echoed that request and the medium it received
carried the reported digest. The same acceptances live here, through the ports.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from pathlib import Path

from apex.composition import exports
from apex.config import defaults
from apex.kernel import commands, encoding, errors, identifiers, locators, refusals, safepaths
from apex.ports import portset
from apex.provisioning.fixtures import ventoy_fixture
from apex.trust import anchors, verifying

PASS = "PASS"
NOT_TESTED = "NOT TESTED"
VALIDSIG = "[GNUPG:] VALIDSIG "
GPGV = "gpgv"
SIGNER_FIELD = 2


@dataclasses.dataclass(frozen=True, slots=True)
class Inputs:
    """What the operator named: where the live bundle is, and the Ubuntu inputs it goes with."""

    live_output: Path
    ubuntu: Path
    trusted_key: Path
    checksums: Path
    signature: Path
    keyring: Path


@dataclasses.dataclass(frozen=True, slots=True)
class VentoyLock:
    version: str
    commit: str
    url: locators.HttpsUrl
    digest: identifiers.Digest
    checksum_url: locators.HttpsUrl
    checksum_digest: identifiers.Digest
    ubuntu_filename: str
    ubuntu_digest: identifiers.Digest
    ubuntu_signer: str
    document: encoding.Document

    @property
    def archive_name(self) -> str:
        return f"ventoy-{self.version}-linux.tar.gz"


@dataclasses.dataclass(frozen=True, slots=True)
class Prepared:
    """Everything the builder is handed, with the proofs the host drew before handing it."""

    request: ventoy_fixture.VentoyRequest
    request_document: encoding.Document
    archive: safepaths.SafePath
    live: safepaths.SafePath
    ubuntu: safepaths.SafePath
    sums: safepaths.SafePath
    live_digest: identifiers.Digest


def load_lock(ports: portset.HostPorts, repository: safepaths.SourceRoot) -> VentoyLock:
    path = safepaths.SafePath(repository.path / defaults.VENTOY_LOCK_PATH)
    try:
        document = encoding.parse_object(
            ports.files.read_bytes(path, limit=defaults.DOCUMENT_LIMIT.value)
        )
        ventoy = document["ventoy"]
        ubuntu = document["ubuntu"]
        if not isinstance(ventoy, Mapping) or not isinstance(ubuntu, Mapping):
            raise TypeError("ventoy and ubuntu")
        return VentoyLock(
            version=str(ventoy["version"]),
            commit=str(ventoy["commit"]),
            url=locators.HttpsUrl(str(ventoy["url"])),
            digest=identifiers.Digest(str(ventoy["sha256"])),
            checksum_url=locators.HttpsUrl(str(ventoy["checksum_url"])),
            checksum_digest=identifiers.Digest(str(ventoy["checksum_sha256"])),
            ubuntu_filename=str(ubuntu["filename"]),
            ubuntu_digest=identifiers.Digest(str(ubuntu["sha256"])),
            ubuntu_signer=str(ubuntu["signer"]),
            document=document,
        )
    except (errors.PortFailure, KeyError, TypeError, ValueError) as error:
        raise errors.Refusal(
            refusals.RefusalReason.VENTOY_LOCK_MALFORMED,
            subject=f"{defaults.VENTOY_LOCK_PATH}: {error}",
        ) from error


def _inside(root: safepaths.RuntimeRoot, candidate: Path) -> str:
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root.path):
        raise errors.Refusal(
            refusals.RefusalReason.PATH_OUTSIDE_RUNTIME_ROOT, subject=str(candidate)
        )
    return str(resolved.relative_to(root.path))


def verify_live(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot, inputs: Inputs
) -> tuple[verifying.VerifiedBundle, safepaths.SafePath]:
    """The live bundle accepted against the operator's key, and the ISO it carries."""
    location = verifying.BundleLocation(root=root, relative=_inside(root, inputs.live_output))
    verified = verifying.verify_bundle(
        ports, location=location, anchor=anchors.operator_supplied(inputs.trusted_key)
    )
    return verified, location.regular_entry(defaults.LIVE_ISO_RELATIVE)


def _signers(status: bytes) -> list[str]:
    return [
        line.split()[SIGNER_FIELD]
        for line in status.decode(errors="replace").splitlines()
        if line.startswith(VALIDSIG) and len(line.split()) > SIGNER_FIELD
    ]


def _checksum_entries(text: str, filename: str) -> list[str]:
    entries = [line.split() for line in text.splitlines() if line.strip()]
    return [
        entry[0]
        for entry in entries
        if len(entry) == 2 and entry[1].lstrip("*") == filename  # noqa: PLR2004
    ]


def verify_ubuntu(
    ports: portset.HostPorts,
    root: safepaths.RuntimeRoot,
    run: identifiers.RunId,
    inputs: Inputs,
    lock: VentoyLock,
) -> tuple[encoding.Document, safepaths.SafePath]:
    """The Ubuntu image accepted against Canonical's signed checksums and the pinned signer."""
    iso = safepaths.SafePath.regular_file(inputs.ubuntu, within=root)
    checksums = safepaths.RegularFile.adopt(inputs.checksums)
    signature = safepaths.RegularFile.adopt(inputs.signature)
    keyring = safepaths.RegularFile.adopt(inputs.keyring)
    home = exports.inside(root, run, defaults.GPGV_HOME)
    ports.files.make_directory(home, mode=safepaths.PRIVATE_DIRECTORY_MODE)
    checked = ports.processes.run(
        commands.Argv.of(
            GPGV,
            "--homedir",
            str(home),
            "--keyring",
            str(keyring.path),
            "--status-fd",
            "1",
            str(signature.path),
            str(checksums.path),
        ),
        deadline=defaults.GPGV_DEADLINE,
        limit=commands.OutputLimit.default(),
    )
    ports.files.write_atomic(
        exports.inside(root, run, defaults.UBUNTU_SIGNATURE_LOG),
        checked.stdout + checked.stderr,
        mode=defaults.RECORD_MODE,
    )
    signers = _signers(checked.stdout)
    if not checked.succeeded or signers != [lock.ubuntu_signer]:
        raise errors.Refusal(
            refusals.RefusalReason.UBUNTU_SIGNER_UNKNOWN,
            subject=f"{inputs.checksums}: signed by {signers or 'nobody the keyring knows'}",
            remedy="the checksums must carry the pinned signer's valid signature",
        )
    text = ports.files.read_bytes(
        safepaths.SafePath(checksums.path), limit=defaults.DOCUMENT_LIMIT.value
    ).decode(errors="replace")
    if _checksum_entries(text, lock.ubuntu_filename) != [lock.ubuntu_digest.hex]:
        raise errors.Refusal(
            refusals.RefusalReason.DOWNLOAD_CHECKSUM_MISMATCH,
            subject=f"{lock.ubuntu_filename}: the signed checksums do not pin it as the lock does",
        )
    if ports.digests.file(iso) != lock.ubuntu_digest:
        raise errors.Refusal(
            refusals.RefusalReason.DOWNLOAD_CHECKSUM_MISMATCH,
            subject=f"{inputs.ubuntu}: differs from the signed pinned checksum",
        )
    report: encoding.Document = {
        "status": PASS,
        "iso_sha256": lock.ubuntu_digest.hex,
        "signer": signers[0],
        "checksums_sha256": ports.digests.file(safepaths.SafePath(checksums.path)).hex,
        "signature_sha256": ports.digests.file(safepaths.SafePath(signature.path)).hex,
    }
    ports.files.write_atomic(
        exports.inside(root, run, defaults.UBUNTU_VERIFICATION_NAME),
        encoding.canonical(report) + b"\n",
        mode=defaults.RECORD_MODE,
    )
    return report, iso


def _fetched(
    ports: portset.HostPorts,
    url: locators.HttpsUrl,
    into: safepaths.SafePath,
    expected: identifiers.Digest,
) -> None:
    """The pinned file, fetched unless the one already there carries the pinned digest."""
    if ports.files.exists(into) and ports.digests.file(into) == expected:
        return
    ports.downloads.fetch(url, into=into, expected=expected, deadline=defaults.DOWNLOAD_DEADLINE)


def fetch_ventoy(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot, lock: VentoyLock
) -> tuple[safepaths.SafePath, safepaths.SafePath]:
    """The pinned Ventoy release and its own checksum file, which must agree with the pin."""
    archive = root.child(f"{defaults.VENTOY_INPUTS_DIRECTORY}/{lock.archive_name}")
    sums = root.child(f"{defaults.VENTOY_INPUTS_DIRECTORY}/{defaults.VENTOY_SUMS_NAME}")
    _fetched(ports, lock.url, archive, lock.digest)
    _fetched(ports, lock.checksum_url, sums, lock.checksum_digest)
    lines = (
        ports.files.read_bytes(sums, limit=defaults.DOCUMENT_LIMIT.value)
        .decode(errors="replace")
        .splitlines()
    )
    if f"{lock.digest.hex}  {lock.archive_name}" not in lines:
        raise errors.Refusal(
            refusals.RefusalReason.DOWNLOAD_CHECKSUM_MISMATCH,
            subject=f"{defaults.VENTOY_SUMS_NAME}: does not name the pinned archive",
        )
    return archive, sums


def prepare(
    ports: portset.HostPorts,
    root: safepaths.RuntimeRoot,
    run: identifiers.RunId,
    repository: safepaths.SourceRoot,
    inputs: Inputs,
) -> Prepared:
    """Every input proven and every proof written under the run, before the builder is asked."""
    lock = load_lock(ports, repository)
    verified, live = verify_live(ports, root, inputs)
    _ubuntu_report, ubuntu = verify_ubuntu(ports, root, run, inputs, lock)
    archive, sums = fetch_ventoy(ports, root, lock)
    files = {
        ventoy_fixture.ARCHIVE: ports.digests.file(archive),
        ventoy_fixture.ISOS[0]: ports.digests.file(live),
        ventoy_fixture.ISOS[1]: lock.ubuntu_digest,
    }
    request_document: encoding.Document = {
        "files": {name: digest.hex for name, digest in files.items()},
        "ventoy_version": lock.version,
        "ventoy_commit": lock.commit,
        "digest": str(verified.digest),
    }
    documents: dict[str, encoding.Document] = {
        ventoy_fixture.REQUEST_NAME: request_document,
        defaults.LIVE_VERIFICATION_NAME: {
            "status": PASS,
            "digest": str(verified.digest),
            "files_verified": verified.files_verified,
        },
        defaults.INPUTS_LOCK_NAME: lock.document,
    }
    for name, document in documents.items():
        ports.files.write_atomic(
            exports.inside(root, run, name),
            encoding.canonical(document) + b"\n",
            mode=defaults.RECORD_MODE,
        )
    return Prepared(
        request=ventoy_fixture.VentoyRequest(files=files, version=lock.version),
        request_document=request_document,
        archive=archive,
        live=live,
        ubuntu=ubuntu,
        sums=sums,
        live_digest=verified.digest,
    )


def bind(
    ports: portset.HostPorts,
    root: safepaths.RuntimeRoot,
    run: identifiers.RunId,
    prepared: Prepared,
    observations: Mapping[str, object],
    *,
    remote: safepaths.RemotePath,
) -> tuple[safepaths.SafePath, encoding.Document]:
    """The received medium accepted only when the report echoes the request and its digest."""
    report = ventoy_fixture.parse_report(observations)
    if report.request != prepared.request:
        raise errors.Refusal(
            refusals.RefusalReason.FIXTURE_REPORT_MALFORMED,
            subject="the report answers another request",
        )
    image = safepaths.SafePath.regular_file(
        exports.inside(root, run, f"output/{ventoy_fixture.IMAGE}").path, within=root
    )
    if ports.digests.file(image) != report.image:
        raise errors.Refusal(
            refusals.RefusalReason.ARTIFACT_CHECKSUM_MISMATCH,
            subject=f"{ventoy_fixture.IMAGE}: differs from the report",
        )
    ports.files.copy(prepared.sums, exports.inside(root, run, defaults.VENTOY_SUMS_NAME))
    execution: encoding.Document = {
        "status": PASS,
        "remote": str(remote),
        "image_sha256": report.image.hex,
        "boot_acceptance": NOT_TESTED,
        "physical_usb_written": False,
    }
    ports.files.write_atomic(
        exports.inside(root, run, defaults.MEDIA_EXECUTION_NAME),
        encoding.canonical(execution) + b"\n",
        mode=defaults.RECORD_MODE,
    )
    return image, execution
