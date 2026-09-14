"""A completed update fixture as the host finds it: where it lives and what its report binds.

A fixture is named by the directory a run exported it to, or by that run's identifier; its
report is accepted only as a passed fixture whose two images are distinct, and the digests
the later operations rely on, the archive's, the public key's and the recovery preset's,
are read from it here and nowhere else.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

from apex.composition import exports
from apex.config import defaults
from apex.kernel import encoding, errors, identifiers, refusals, safepaths
from apex.ports import portset
from apex.provisioning.fixtures import update_fixture

PAYLOADS_NAME = "payloads.tar"
PUBLIC_KEY_NAME = "trusted.pub"
PRESET_DIGEST = "greenboot_config_sha256"
MANIFEST_PREFIX = "manifest-"


@dataclasses.dataclass(frozen=True, slots=True)
class Located:
    directory: safepaths.SafePath
    report: update_fixture.UpdateFixtureReport
    document: encoding.Document
    preset: identifiers.Digest | None

    @property
    def output(self) -> safepaths.SafePath:
        return self.directory / exports.OUTPUT

    @property
    def payloads(self) -> safepaths.SafePath:
        return self.output / PAYLOADS_NAME

    @property
    def image_a(self) -> update_fixture.FixtureImage:
        return self.report.images["a"]

    @property
    def image_b(self) -> update_fixture.FixtureImage:
        return self.report.images["b"]

    def manifest(self, version: str) -> safepaths.SafePath:
        return self.output / f"{MANIFEST_PREFIX}{version}.json"


def _directory(root: safepaths.RuntimeRoot, value: str) -> safepaths.SafePath:
    candidate = Path(value)
    if candidate.is_absolute():
        resolved = candidate.resolve()
        if not resolved.is_relative_to(root.path):
            raise errors.Refusal(refusals.RefusalReason.PATH_OUTSIDE_RUNTIME_ROOT, subject=value)
        return safepaths.SafePath(resolved)
    return root.child(f"{defaults.EXPORT_DIRECTORY}/{identifiers.RunId.parse(value)}")


def locate(ports: portset.HostPorts, root: safepaths.RuntimeRoot, value: str) -> Located:
    """The fixture the operator named, with its report parsed and its two images distinct."""
    directory = _directory(root, value)
    results = directory / exports.OUTPUT / defaults.RESULTS_NAME
    if not ports.files.exists(results):
        raise errors.Refusal(
            refusals.RefusalReason.PATH_NOT_A_REGULAR_FILE,
            subject=f"{results}: no completed fixture there",
            remedy="name a fixture the update-fixtures build exported",
        )
    document = encoding.parse_object(
        ports.files.read_bytes(results, limit=defaults.DOCUMENT_LIMIT.value)
    )
    report = update_fixture.parse_report(document)
    if report.images["a"].digest == report.images["b"].digest:
        raise errors.Refusal(
            refusals.RefusalReason.FIXTURE_REPORT_MALFORMED,
            subject="the two images of the fixture share one digest",
        )
    preset = document.get(PRESET_DIGEST)
    return Located(
        directory=directory,
        report=report,
        document=document,
        preset=identifiers.Digest(str(preset)) if isinstance(preset, str) else None,
    )


def require_manifest(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot, located: Located, version: str
) -> None:
    """The exported manifest of one image hashes to the digest the report gives that image."""
    manifest = safepaths.SafePath.regular_file(located.manifest(version).path, within=root)
    ports.digests.forget()
    if str(ports.digests.file(manifest)) != str(located.report.images[version].digest):
        raise errors.Refusal(
            refusals.RefusalReason.FIXTURE_REPORT_MALFORMED,
            subject=f"{manifest}: the exported manifest is not the image's",
        )
