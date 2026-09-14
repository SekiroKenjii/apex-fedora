"""The installer payload fault seen from the host: the request, the kept report, the result.

The older tool wrote a request beside the machine's run before the guest was asked, naming
the case, the boot image's digest and the machine's process; kept the guest's report beside
it; and judged the run only once the machine was off and its disks compared: the guest had
confirmed the rejection, the image had not changed, and no disk had. The same three
documents live here, read and written through the ports, and the host confirms the report
itself rather than trusting a status string.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from pathlib import Path
from typing import Self

from apex.config import defaults
from apex.kernel import encoding, errors, identifiers, refusals, safepaths, verdicts
from apex.ports import portset
from apex.provisioning import comparing, runrecord

CASES = (
    "missing-signature",
    "altered-signature",
    "wrong-key",
    "changed-manifest",
    "corrupt-blob",
    "unexpected-source",
)
KEY_CASE = "wrong-key"
KEY_HEADER = b"-----BEGIN PUBLIC KEY-----\n"
SCHEMA = 1
STATUS = "status"
GUEST = "guest"
EXPECTED_DISKS = 2


@dataclasses.dataclass(frozen=True, slots=True)
class Request:
    """What was asked of which machine, written before the guest is touched."""

    case: str
    image: identifiers.Digest
    process: int
    run: identifiers.RunId

    def document(self) -> encoding.Document:
        return {
            "schema": SCHEMA,
            "case": self.case,
            "iso_sha256": self.image.hex,
            "vm_pid": self.process,
            "run": str(self.run),
        }

    @classmethod
    def parse(cls, document: Mapping[str, object]) -> Self:
        try:
            return cls(
                case=str(document["case"]),
                image=identifiers.Digest(str(document["iso_sha256"])),
                process=int(str(document["vm_pid"])),
                run=identifiers.RunId.parse(str(document["run"])),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise errors.Refusal(
                refusals.RefusalReason.LEASE_MALFORMED,
                subject=f"{defaults.FAULT_REQUEST_NAME}: {error}",
            ) from error


@dataclasses.dataclass(frozen=True, slots=True)
class Result:
    verdict: verdicts.Verdict
    case: str
    image: identifiers.Digest
    proof: safepaths.SafePath

    def document(self) -> encoding.Document:
        return {
            "status": self.verdict.stored_name,
            "case": self.case,
            "iso_sha256": self.image.hex,
            "proof": str(self.proof),
        }


def require_pairing(case: str, key: str | None) -> None:
    """Only the wrong-key case takes a key, and it always does."""
    if case not in CASES:
        raise errors.Refusal(
            refusals.RefusalReason.UNIT_UNKNOWN,
            subject=case,
            remedy=f"the fault knows these cases: {', '.join(CASES)}",
        )
    if (case == KEY_CASE) != (key is not None):
        raise errors.Refusal(
            refusals.RefusalReason.REQUEST_MALFORMED,
            subject=f"{case} with{'out' if key is None else ''} a public key",
            remedy=f"only {KEY_CASE} takes --wrong-key, and it must",
        )


def read_key(ports: portset.HostPorts, root: safepaths.RuntimeRoot, path: Path) -> str:
    """A small public verification key from inside the runtime root, never a private one."""
    source = safepaths.SafePath.regular_file(path, within=root)
    data = ports.files.read_bytes(source, limit=defaults.PUBLIC_KEY_LIMIT.value + 1)
    if len(data) > defaults.PUBLIC_KEY_LIMIT.value or not data.startswith(KEY_HEADER):
        raise errors.Refusal(
            refusals.RefusalReason.PUBLIC_KEY_MALFORMED,
            subject=str(source),
            remedy="supply a small public verification key, never a private key",
        )
    return data.decode()


def confirmed(observations: Mapping[str, object], case: str) -> bool:
    """Whether the guest's report says what a pass must: the named case, refused before
    Anaconda, with the preflight failed, no upstream log and enforcement kept."""
    record = observations.get("preflight")
    return (
        observations.get("case") == case
        and observations.get(STATUS) == verdicts.Passed.stored_name
        and observations.get("returncode") == 1
        and isinstance(record, Mapping)
        and record.get(STATUS) == verdicts.Failed.stored_name
        and observations.get("upstream_log_created") is False
        and observations.get("selinux_after") == "Enforcing"
    )


def request_path(run_directory: safepaths.SafePath) -> safepaths.SafePath:
    return safepaths.SafePath(run_directory.path / defaults.FAULT_REQUEST_NAME)


def write_request(
    ports: portset.HostPorts, run_directory: safepaths.SafePath, request: Request
) -> None:
    _write(ports, request_path(run_directory), request.document())


def read_request(ports: portset.HostPorts, run_directory: safepaths.SafePath) -> Request:
    return Request.parse(_read(ports, request_path(run_directory)))


def write_kept(
    ports: portset.HostPorts,
    run_directory: safepaths.SafePath,
    *,
    request: Request,
    observations: encoding.Document,
) -> safepaths.SafePath:
    target = safepaths.SafePath(run_directory.path / defaults.FAULT_GUEST_NAME)
    _write(ports, target, {"schema": SCHEMA, "request": request.document(), GUEST: observations})
    return target


def collect(
    ports: portset.HostPorts,
    *,
    root: safepaths.RuntimeRoot,
    run_directory: safepaths.SafePath,
    comparison: comparing.RunComparison,
) -> Result:
    """The result of a finished fault run, written beside it; a changed disk is a refusal."""
    request = read_request(ports, run_directory)
    kept = _read(ports, safepaths.SafePath(run_directory.path / defaults.FAULT_GUEST_NAME))
    guest = kept.get(GUEST)
    if not isinstance(guest, Mapping) or not confirmed(guest, request.case):
        raise errors.Refusal(
            refusals.RefusalReason.FAULT_NOT_CONFIRMED,
            subject=f"{request.case}: the guest did not confirm the rejection before Anaconda",
        )
    _require_same_image(ports, root, run_directory, request)
    passed = len(comparison.disks) == EXPECTED_DISKS and all(
        item.unchanged for item in comparison.disks
    )
    verdict: verdicts.Verdict = verdicts.PASSED if passed else verdicts.FAILED
    proof = safepaths.SafePath(run_directory.path / defaults.FAULT_RESULT_NAME)
    _write(
        ports,
        proof,
        {
            "schema": SCHEMA,
            STATUS: verdict.stored_name,
            "case": request.case,
            "iso_sha256": request.image.hex,
            GUEST: kept,
            "disk_comparison": comparison.document(),
            "run_directory": str(run_directory),
        },
    )
    if not passed:
        raise errors.Refusal(
            refusals.RefusalReason.FAULT_DISK_CHANGED,
            subject=f"{request.case}: a virtual disk changed during the payload rejection",
            remedy=f"inspect {proof}",
        )
    return Result(verdict=verdict, case=request.case, image=request.image, proof=proof)


def _require_same_image(
    ports: portset.HostPorts,
    root: safepaths.RuntimeRoot,
    run_directory: safepaths.SafePath,
    request: Request,
) -> None:
    record = runrecord.read(ports, run_directory)
    if record.iso is None:
        raise errors.Refusal(
            refusals.RefusalReason.TOPOLOGY_INCONSISTENT,
            subject=f"{run_directory}: the run booted no image",
        )
    image = ports.digests.file(safepaths.SafePath.regular_file(record.iso, within=root))
    if image != request.image:
        raise errors.Refusal(
            refusals.RefusalReason.SOURCE_IMAGE_CHANGED,
            subject=f"{record.iso}: not the image the fault was asked against",
        )


def _write(
    ports: portset.HostPorts, target: safepaths.SafePath, document: encoding.Document
) -> None:
    ports.files.write_atomic(
        target, encoding.canonical(document) + b"\n", mode=defaults.RECORD_MODE
    )


def _read(ports: portset.HostPorts, source: safepaths.SafePath) -> dict[str, encoding.JsonValue]:
    if not ports.files.exists(source):
        raise errors.Refusal(
            refusals.RefusalReason.PATH_NOT_A_REGULAR_FILE,
            subject=f"{source}: no such fault record",
            remedy="run the fault against a fresh installer machine first",
        )
    return encoding.parse_object(
        ports.files.read_bytes(source, limit=defaults.DOCUMENT_LIMIT.value)
    )
