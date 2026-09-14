"""Exercise fprintd's cleanup with upstream virtual devices in the isolated builder.

This is `guest/fingerprint-tests.sh` and the older host's reading of it, through ports: the
target image's fprintd and libfprint named from a read-only container of it, the same two
installed on the builder with the test dependencies and compared, the builder's packages
listed, the delivered upstream test files checked against the reviewed lock, and the
verbatim harness run as the unprivileged builder over them. Its report is judged as the
older host judged it and carried whole. The downloads the older shell made on the builder
happen on the host, because a guest never downloads.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from pathlib import Path

from apex.agent import agentports, builder, fingerprintharness, units
from apex.config import defaults
from apex.kernel import (
    commands,
    encoding,
    errors,
    hashing,
    identifiers,
    quantities,
    refusals,
    safepaths,
    timing,
)
from apex.model import builds, oci, pinnedfiles
from apex.ports import containers, files

SCOPE = "packaged daemon and libfprint in the builder VM over a virtual device; no sensor"
NOT_TESTED = "NOT TESTED"
WORK_PREFIX = defaults.FINGERPRINT_WORK_PREFIX
TRAVERSABLE = quantities.FileMode(0o755)
PLAIN = quantities.FileMode(0o644)
PACKAGE_COUNT = 2
TARGET_RPMS = "target-rpms.txt"
TEST_RPMS = "test-rpms.txt"
ENVIRONMENT_RPMS = "environment-rpms.txt"
RESULTS = "results.json"
INSTALL_LOG = "install.log"
HARNESS_LOG = "harness.log"


@dataclasses.dataclass(frozen=True, slots=True)
class Site:
    root: safepaths.SafePath

    @property
    def sources(self) -> safepaths.SafePath:
        return self.root / defaults.FINGERPRINT_SOURCES_NAME

    @property
    def lock(self) -> safepaths.SafePath:
        return self.root / defaults.FINGERPRINT_LOCK_DIRECTORY / defaults.FINGERPRINT_LOCK_NAME

    @property
    def output(self) -> safepaths.SafePath:
        return safepaths.SafePath(self.root.path / defaults.FINGERPRINT_OUTPUT_DIRECTORY)

    @property
    def harness(self) -> safepaths.SafePath:
        return self.root / fingerprintharness.ASSET

    @property
    def target(self) -> safepaths.SafePath:
        return self.root / builds.TARGET_DOCUMENT


@dataclasses.dataclass(frozen=True, slots=True)
class Outcome:
    """What running the harness came to: its exit, or why the port could not run it."""

    exit_code: int | None
    failure: str | None
    report: encoding.Document | None

    @property
    def status(self) -> str:
        if self.exit_code is None:
            return fingerprintharness.BLOCKED
        return fingerprintharness.judge(self.report, exit_code=self.exit_code)


def _unexpected(detail: str) -> errors.Refusal:
    return errors.Refusal(refusals.RefusalReason.FIXTURE_STATE_UNEXPECTED, subject=detail)


def _read(ports: agentports.AgentPorts, path: safepaths.SafePath) -> bytes:
    return ports.files.read_bytes(path, limit=defaults.DOCUMENT_LIMIT.value)


def _run(
    ports: agentports.AgentPorts,
    argv: commands.Argv,
    *,
    deadline: timing.Deadline,
    transcript: safepaths.SafePath | None = None,
) -> commands.CompletedRun:
    completed = ports.processes.run(
        argv, deadline=deadline, limit=commands.OutputLimit.default(), transcript=transcript
    )
    if not completed.succeeded:
        raise errors.PortFailure(
            port="process",
            cause=f"{argv.arguments[0]} exited with {completed.exit_code}: "
            f"{completed.stderr.decode(errors='replace').strip()}",
        )
    return completed


def _site_of(arguments: Mapping[str, encoding.JsonValue]) -> Site:
    value = arguments.get("work")
    if not isinstance(value, str) or not value.startswith(WORK_PREFIX):
        raise errors.Refusal(
            refusals.RefusalReason.REQUEST_MALFORMED,
            subject=f"work must be a directory under {WORK_PREFIX}",
        )
    try:
        identifiers.RunId.parse(value.removeprefix(WORK_PREFIX))
    except errors.Refusal as fault:
        raise errors.Refusal(
            refusals.RefusalReason.REQUEST_MALFORMED, subject="work must be named for its run"
        ) from fault
    return Site(root=safepaths.SafePath(Path(value)))


def _lock(ports: agentports.AgentPorts, site: Site) -> pinnedfiles.PinnedFileSet:
    try:
        document = encoding.parse_document(_read(ports, site.lock))
    except ValueError as fault:
        raise errors.Refusal(
            refusals.RefusalReason.LOCK_UNREADABLE, subject=str(site.lock)
        ) from fault
    return pinnedfiles.parse(document)


def _verified_sources(
    ports: agentports.AgentPorts, site: Site, lock: pinnedfiles.PinnedFileSet
) -> dict[str, encoding.JsonValue]:
    """Every pinned file delivered, regular and matching, and nothing delivered unpinned."""
    digests: dict[str, encoding.JsonValue] = {}
    for item in lock.files:
        path = site.sources / item.name
        try:
            kind = ports.files.inspect(path).kind
        except errors.PortFailure as failure:
            raise _unexpected(f"the host did not deliver {item.name}: {failure.cause}") from failure
        if kind is not files.EntryKind.REGULAR:
            raise errors.Refusal(refusals.RefusalReason.PATH_NOT_A_REGULAR_FILE, subject=str(path))
        found = hashing.digest_bytes(_read(ports, path))
        if found != item.sha256:
            raise errors.Refusal(
                refusals.RefusalReason.ARTIFACT_CHECKSUM_MISMATCH,
                subject=item.name,
                remedy="fetch the pinned upstream tests again on the host",
            )
        digests[item.name] = found.hex
    delivered = {
        entry.relative
        for entry in ports.files.list_tree(site.sources)
        if entry.kind is not files.EntryKind.DIRECTORY
    }
    unpinned = sorted(delivered - lock.names)
    if unpinned:
        raise _unexpected(f"unpinned files were delivered with the sources: {', '.join(unpinned)}")
    return digests


def _target_packages(
    ports: agentports.AgentPorts, site: Site, frozen: oci.FrozenImage
) -> list[str]:
    completed = ports.containers.run(
        containers.RunRequest(
            image=str(frozen.image_id),
            argv=commands.Argv.of(
                "-q", *defaults.FINGERPRINT_PACKAGES, "--qf", defaults.RPM_NEVRA_FORMAT
            ),
            read_only=True,
            network_none=True,
            entrypoint="rpm",
        )
    )
    if not completed.succeeded:
        raise errors.PortFailure(
            port="containers", cause=f"rpm in the target image exited with {completed.exit_code}"
        )
    ports.files.write_atomic(site.output / TARGET_RPMS, completed.stdout, mode=PLAIN)
    listed = completed.stdout.decode(errors="replace").splitlines()
    if len(listed) != PACKAGE_COUNT:
        raise _unexpected(
            f"the target image names {len(listed)} fprintd and libfprint packages, "
            f"not {PACKAGE_COUNT}"
        )
    return listed


def _install(ports: agentports.AgentPorts, site: Site, target: list[str]) -> None:
    _run(
        ports,
        commands.Argv.of("dnf5", "install", "-y", *target, *defaults.FINGERPRINT_TEST_PACKAGES),
        deadline=defaults.PACKAGE_INSTALL_DEADLINE,
        transcript=site.output / INSTALL_LOG,
    )


def _installed_packages(ports: agentports.AgentPorts, site: Site, target: list[str]) -> list[str]:
    completed = _run(
        ports,
        commands.Argv.of(
            "rpm", "-q", *defaults.FINGERPRINT_PACKAGES, "--qf", defaults.RPM_NEVRA_FORMAT
        ),
        deadline=defaults.ENGINE_QUERY_DEADLINE,
    )
    ports.files.write_atomic(site.output / TEST_RPMS, completed.stdout, mode=PLAIN)
    installed = completed.stdout.decode(errors="replace").splitlines()
    if installed != target:
        raise _unexpected("the installed fprintd and libfprint differ from the target image's")
    return installed


def _environment_packages(ports: agentports.AgentPorts, site: Site) -> int:
    completed = _run(
        ports,
        commands.Argv.of("rpm", "-qa", "--qf", defaults.RPM_EVRA_FORMAT),
        deadline=defaults.ENGINE_QUERY_DEADLINE,
    )
    listed = sorted(completed.stdout.decode(errors="replace").splitlines())
    ports.files.write_atomic(
        site.output / ENVIRONMENT_RPMS, "".join(f"{line}\n" for line in listed).encode(), mode=PLAIN
    )
    return len(listed)


def _report(ports: agentports.AgentPorts, site: Site) -> encoding.Document | None:
    path = site.output / RESULTS
    if not ports.files.exists(path):
        return None
    try:
        return encoding.parse_object(_read(ports, path))
    except ValueError as fault:
        raise errors.Refusal(
            refusals.RefusalReason.FIXTURE_REPORT_MALFORMED, subject=str(path)
        ) from fault


def _harness(ports: agentports.AgentPorts, site: Site) -> Outcome:
    """Run the harness as the builder user; a run the port cannot complete blocks the verdict."""
    try:
        completed = ports.processes.run(
            fingerprintharness.argv(site.harness, site.sources, site.output),
            deadline=defaults.FINGERPRINT_TEST_DEADLINE,
            limit=commands.OutputLimit.default(),
            transcript=site.output / HARNESS_LOG,
            cwd=site.root,
        )
    except errors.PortFailure as failure:
        return Outcome(exit_code=None, failure=failure.cause, report=_report(ports, site))
    return Outcome(exit_code=completed.exit_code, failure=None, report=_report(ports, site))


def run(
    ports: agentports.AgentPorts, *, arguments: Mapping[str, encoding.JsonValue]
) -> encoding.Document:
    builder.require_isolated(ports)
    site = _site_of(arguments)
    frozen = oci.FrozenImage.parse(_read(ports, site.target))
    lock = _lock(ports, site)
    sources = _verified_sources(ports, site, lock)
    ports.files.make_directory(site.output, mode=TRAVERSABLE)
    target = _target_packages(ports, site, frozen)
    _install(ports, site, target)
    installed = _installed_packages(ports, site, target)
    environment = _environment_packages(ports, site)
    harness = fingerprintharness.place(ports.files, site.root)
    _run(
        ports,
        commands.Argv.of("chown", defaults.BUILDER_OWNER, site.output),
        deadline=defaults.PROBE_DEADLINE,
    )
    outcome = _harness(ports, site)
    return {
        "status": outcome.status,
        "scope": SCOPE,
        "hardware_acceptance": NOT_TESTED,
        "work_directory": str(site.root),
        "profile": frozen.profile,
        "digest": str(frozen.digest),
        "image_id": str(frozen.image_id),
        "target_rpms": target,
        "test_rpms": installed,
        "environment_rpm_count": environment,
        "source_lock_version": lock.version,
        "sources": sources,
        "harness_sha256": harness.hex,
        "harness_returncode": outcome.exit_code,
        "harness_failure": outcome.failure,
        "report": outcome.report,
    }


units.declare(units.Unit(id=identifiers.ProbeId("fault.fingerprint-cleanup"), run=run))
