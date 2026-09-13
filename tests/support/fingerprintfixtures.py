"""A builder ready for the fingerprint test, with the host's delivery in place.

One spec says what the target image and the builder answer and what the harness leaves
behind. The fake ports are derived from it, and the older shell's stand-in programs read
the same spec, so both sides of a parity see one builder.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from apex.adapters.fakes import (
    fake_archives,
    fake_blockdevices,
    fake_clock,
    fake_containers,
    fake_digesting,
    fake_extents,
    fake_files,
    fake_ids,
    fake_process,
)
from apex.agent import agentports
from apex.config import defaults
from apex.kernel import commands, quantities, safepaths, timing

WORK = "/var/tmp/apex-fingerprint-" + "f" * 32
BASE = "https://example.invalid/tests/"
BODIES = {
    "fprintd.py": b"# upstream cases\n",
    "output_checker.py": b"# output checker\n",
    "dbusmock/polkitd.py": b"# polkit mock\n",
}
IMAGE_ID = "sha256:" + "b" * 64
DIGEST = "sha256:" + "a" * 64
FROZEN = {"profile": "fedora", "digest": DIGEST, "image_id": IMAGE_ID}
TARGET_RPMS = "fprintd-1.94.5-5.fc44.x86_64\nlibfprint-1.94.100-1.fc44.x86_64\n"
ENVIRONMENT_RPMS = (
    "zlib-1.3.1-1.fc44.x86_64\nbash-5.3.0-1.fc44.x86_64\nfprintd-1.94.5-5.fc44.x86_64\n"
)
UPSTREAM_CASES = [
    "FPrintdVirtualDeviceStorageTest.test_claim_from_other_client_is_released_when_vanished",
    "FPrintdVirtualDeviceStorageTest.test_claim_disconnect",
    "FPrintdVirtualDeviceStorageTest.test_enroll_running_disconnect",
    "FPrintdVirtualDeviceStorageTest.test_enroll_done_disconnect",
    "FPrintdVirtualDeviceNoStorageEnrollTests.test_enroll_error_proto",
    "FPrintdUtilsTest.test_enroll_error",
]
PUBLIC = quantities.FileMode(0o644)
NEVRA_QUERY = ("-q", "fprintd", "libfprint", "--qf", defaults.RPM_NEVRA_FORMAT)
HANG = timing.Elapsed(1000)

Writer = Callable[[Path, bytes], None]


def lock_document(bodies: Mapping[str, bytes] | None = None) -> dict[str, Any]:
    held = BODIES if bodies is None else bodies
    return {
        "version": "1.94.5",
        "base_url": BASE,
        "files": {name: hashlib.sha256(body).hexdigest() for name, body in held.items()},
    }


def harness_report(**changes: Any) -> dict[str, Any]:
    report: dict[str, Any] = {
        "status": "PASS",
        "tests_run": 8,
        "upstream_cases": UPSTREAM_CASES,
        "source_lock": lock_document(),
        "failures": [],
        "errors": [],
        "skipped": [],
        "hardware_acceptance": "NOT TESTED",
        "scope": "packaged daemon/libfprint with a private D-Bus and virtual device",
    }
    report.update(changes)
    return report


@dataclasses.dataclass(frozen=True, slots=True)
class BuilderSpec:
    target_rpms: str = TARGET_RPMS
    installed_rpms: str = TARGET_RPMS
    environment_rpms: str = ENVIRONMENT_RPMS
    report: dict[str, Any] | None = dataclasses.field(default_factory=harness_report)
    harness_exit: int = 0
    harness_hangs: bool = False
    bodies: Mapping[str, bytes] = dataclasses.field(default_factory=lambda: dict(BODIES))
    delivered: Mapping[str, bytes] | None = None

    def as_document(self) -> dict[str, Any]:
        """The spec as the older shell's stand-in programs read it."""
        return {
            "target_rpms": self.target_rpms,
            "installed_rpms": self.installed_rpms,
            "environment_rpms": self.environment_rpms,
            "report": self.report,
            "harness_exit": self.harness_exit,
            "base": BASE,
            "bodies": {name: body.decode() for name, body in self.bodies.items()},
        }

    def placed(self) -> Mapping[str, bytes]:
        return self.bodies if self.delivered is None else self.delivered


class Builder(fake_process.ScriptedProcess):
    """Answers the builder's programs and leaves behind what the harness would."""

    def __init__(self, spec: BuilderSpec, write: Writer) -> None:
        super().__init__()
        self.spec = spec
        self.write = write

    def run(self, argv: Any, **keywords: Any) -> Any:
        vector = tuple(str(item) for item in argv)
        self.expect(vector, self._answer(vector))
        return super().run(argv, **keywords)

    def _answer(self, vector: tuple[str, ...]) -> fake_process.Reply:
        spec = self.spec
        if vector == ("systemd-detect-virt", "--vm"):
            return fake_process.Reply(stdout=b"kvm\n")
        if vector[:2] == ("podman", "run"):
            return fake_process.Reply(stdout=spec.target_rpms.encode())
        if vector[:2] == ("rpm", "-q"):
            return fake_process.Reply(stdout=spec.installed_rpms.encode())
        if vector[:2] == ("rpm", "-qa"):
            return fake_process.Reply(stdout=spec.environment_rpms.encode())
        if vector[:1] == ("runuser",):
            if spec.harness_hangs:
                return fake_process.Reply(delay=HANG)
            if spec.report is not None:
                self.write(Path(vector[-1]) / "results.json", json.dumps(spec.report).encode())
            return fake_process.Reply(exit_code=spec.harness_exit)
        return fake_process.Reply()


def fingerprint_guest(
    spec: BuilderSpec, work: str = WORK
) -> tuple[Builder, fake_files.MemoryFiles, agentports.AgentPorts]:
    files = fake_files.MemoryFiles()
    root = safepaths.SafePath(Path(work))

    def write(path: Path, payload: bytes) -> None:
        files.write_atomic(safepaths.SafePath(path), payload, mode=PUBLIC)

    write(Path(defaults.BUILDER_MARKER), f"{defaults.BUILDER_MARKER_TEXT}\n".encode())
    write(root.path / "target-image.json", json.dumps(FROZEN).encode())
    write(
        root.path / defaults.FINGERPRINT_LOCK_DIRECTORY / defaults.FINGERPRINT_LOCK_NAME,
        json.dumps(lock_document(spec.bodies)).encode(),
    )
    sources = root / defaults.FINGERPRINT_SOURCES_NAME
    files.make_directory(sources, mode=quantities.FileMode(0o700))
    for name, body in spec.placed().items():
        write(sources.path / name, body)
    registry = fake_containers.FakeRegistry()
    registry.reply(
        IMAGE_ID,
        NEVRA_QUERY,
        commands.CompletedRun(
            exit_code=0, stdout=spec.target_rpms.encode(), stderr=b"", truncated=False
        ),
    )
    process = Builder(spec, write)
    ports = agentports.AgentPorts(
        processes=process,
        files=files,
        clock=fake_clock.ManualClock(),
        containers=registry,
        digests=fake_digesting.CountingDigests(),
        archives=fake_archives.MemoryArchives(),
        identities=fake_ids.SequenceIdentities(),
        extents=fake_extents.FakeExtents(),
        blocks=fake_blockdevices.FakeBlockDevices(),
    )
    return process, files, ports
