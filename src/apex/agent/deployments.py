"""The deployment status of an installed guest, read from bootc and held typed.

The fixture units and the update operations all begin the same way: bootc is asked for its
status, the booted image is compared with the one the host expects, and a guest whose boot
components are not the reviewed versions is refused before anything is changed.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from pathlib import Path

from apex.agent import agentports
from apex.config import defaults
from apex.kernel import commands, encoding, errors, refusals, safepaths, timing

STATUS = commands.Argv.of("bootc", "status", "--format", "json")
COMPONENTS = commands.Argv.of("rpm", "-q", "--qf", "%{NAME}=%{VERSION}\n", "bootupd", "greenboot")
OWN_NAMESPACE = "/proc/self/ns/mnt"
INIT_NAMESPACE = "/proc/1/ns/mnt"
DEPLOYMENTS = "/sysroot/ostree/deploy"


def unexpected(detail: str) -> errors.Refusal:
    return errors.Refusal(refusals.RefusalReason.FIXTURE_STATE_UNEXPECTED, subject=detail)


@dataclasses.dataclass(frozen=True, slots=True)
class Deployment:
    image: str | None
    checksum: str | None
    stateroot: str | None
    serial: int | None

    @classmethod
    def parse(cls, value: encoding.JsonValue) -> Deployment | None:
        if not isinstance(value, dict):
            return None
        image = value.get("image")
        ostree = value.get("ostree")
        digest = image.get("imageDigest") if isinstance(image, dict) else None
        held = ostree if isinstance(ostree, dict) else {}
        serial = held.get("deploySerial")
        return cls(
            image=digest if isinstance(digest, str) and digest else None,
            checksum=_text(held.get("checksum")),
            stateroot=_text(held.get("stateroot")),
            serial=serial if isinstance(serial, int) else None,
        )

    def path(self) -> safepaths.SafePath:
        """Where the deployment's tree is checked out below the OSTree repository."""
        if self.checksum is None or self.stateroot is None or self.serial is None:
            raise unexpected("the deployment does not name its OSTree checkout")
        return safepaths.SafePath(
            Path(DEPLOYMENTS) / self.stateroot / "deploy" / f"{self.checksum}.{self.serial}"
        )


@dataclasses.dataclass(frozen=True, slots=True)
class Status:
    document: encoding.Document
    booted: Deployment | None
    rollback: Deployment | None
    staged: Deployment | None
    rollback_queued: bool

    @classmethod
    def parse(cls, document: encoding.Document) -> Status:
        inner = document.get("status")
        held = inner if isinstance(inner, dict) else {}
        return cls(
            document=document,
            booted=Deployment.parse(held.get("booted")),
            rollback=Deployment.parse(held.get("rollback")),
            staged=Deployment.parse(held.get("staged")),
            rollback_queued=held.get("rollbackQueued") is True,
        )

    def require_booted(self, expected: str) -> None:
        if self.booted is None or self.booted.image != expected:
            raise unexpected("the booted deployment is not the expected image")

    def require_healthy_pair(self) -> None:
        """Two deployments and nothing staged: the fixture before any operation."""
        if self.rollback is None or self.staged is not None:
            raise unexpected("use the healthy two-deployment fixture without a staged update")


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def output(
    ports: agentports.AgentPorts,
    argv: commands.Argv,
    *,
    deadline: timing.Deadline = defaults.PROBE_DEADLINE,
) -> str:
    completed = ports.processes.run(argv, deadline=deadline, limit=commands.OutputLimit.default())
    if not completed.succeeded:
        raise unexpected(f"{argv.arguments[0]} exited with {completed.exit_code}")
    return completed.stdout.decode(errors="replace")


def document(text: str, *, what: str) -> encoding.Document:
    """The object a guest program printed, refused as unexpected state when it is not one."""
    try:
        return encoding.parse_object(text.encode())
    except ValueError as malformed:
        raise unexpected(f"{what} is not a document: {malformed}") from malformed


def read(ports: agentports.AgentPorts) -> Status:
    return Status.parse(document(output(ports, STATUS), what="bootc status"))


def assignments(text: str) -> dict[str, str]:
    """One `name=value` per line, as rpm's query format and grub2-editenv both print."""
    found: dict[str, str] = {}
    for line in text.splitlines():
        name, separator, value = line.partition("=")
        if separator:
            found[name] = value
    return found


def require_components(ports: agentports.AgentPorts, expected: Mapping[str, str]) -> None:
    found = assignments(output(ports, COMPONENTS))
    if found != dict(expected):
        raise unexpected("review changed bootupd/greenboot versions before mutating the fixture")


def require_private_mounts() -> None:
    if Path(OWN_NAMESPACE).readlink() == Path(INIT_NAMESPACE).readlink():
        raise unexpected("use a private mount namespace for fixture changes")


def environment(text: str) -> dict[str, str]:
    """The GRUB environment block as grub2-editenv lists it, one assignment per line."""
    return assignments(text)
