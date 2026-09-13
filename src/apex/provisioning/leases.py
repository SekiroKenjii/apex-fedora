"""The two records a machine leaves in the runtime root, and how they read back.

The intent is written before the process is started and the lease after, so an interrupted
start leaves an intent with no lease, which is what a reclaim looks for. Neither record is
ever deleted: a lease is released by writing that it was, and stays as evidence.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Self

from apex.config import defaults
from apex.kernel import claims, commands, encoding, errors, identifiers, refusals, safepaths
from apex.model import machines
from apex.ports import clock, portset

SCHEMA = 1


@dataclasses.dataclass(frozen=True, slots=True)
class MachineIntent:
    """What was meant to start, and the environment the machine will be witnessed as.

    The witness is the hypervisor adapter's word, fixed at launch: a real hypervisor makes a
    builder a build environment and a test machine a virtual one, and a simulated one makes
    either a simulation, so no later stage can claim more for the guest than its launcher.
    """

    role: machines.VmRole
    run: identifiers.RunId
    run_directory: safepaths.SafePath
    monitor: safepaths.SafePath
    command: commands.Argv
    written_at: clock.Stamp
    witness: claims.EnvironmentKind

    def document(self) -> encoding.Document:
        return {
            "schema": SCHEMA,
            "role": str(self.role),
            "witness": str(self.witness),
            "run": str(self.run),
            "run_directory": str(self.run_directory),
            "monitor": str(self.monitor),
            "command": list(self.command),
            "written_at": self.written_at.rendered,
        }

    @classmethod
    def parse(cls, document: Mapping[str, object]) -> Self:
        try:
            command = document["command"]
            if not isinstance(command, list) or not all(isinstance(c, str) for c in command):
                raise TypeError("command")
            return cls(
                role=machines.VmRole(str(document["role"])),
                run=identifiers.RunId.parse(str(document["run"])),
                run_directory=safepaths.SafePath(_path(document["run_directory"])),
                monitor=safepaths.SafePath(_path(document["monitor"])),
                command=commands.Argv.of(*command),
                written_at=clock.Stamp(str(document["written_at"])),
                witness=claims.EnvironmentKind(str(document["witness"])),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise errors.Refusal(
                refusals.RefusalReason.LEASE_MALFORMED, subject=f"intent: {error}"
            ) from error


@dataclasses.dataclass(frozen=True, slots=True)
class MachineLease:
    intent: MachineIntent
    identity: machines.VmIdentity
    released: bool = False

    def document(self) -> encoding.Document:
        return {
            "schema": SCHEMA,
            "intent": self.intent.document(),
            "identity": dataclasses.asdict(self.identity),
            "released": self.released,
        }

    @classmethod
    def parse(cls, document: Mapping[str, object]) -> Self:
        intent = document.get("intent")
        identity = document.get("identity")
        if not isinstance(intent, dict) or not isinstance(identity, dict):
            raise errors.Refusal(
                refusals.RefusalReason.LEASE_MALFORMED, subject="lease: missing intent or identity"
            )
        try:
            fields = {name: int(identity[name]) for name in _IDENTITY_FIELDS}
        except (KeyError, TypeError, ValueError) as error:
            raise errors.Refusal(
                refusals.RefusalReason.LEASE_MALFORMED, subject=f"lease identity: {error}"
            ) from error
        return cls(
            intent=MachineIntent.parse(intent),
            identity=machines.VmIdentity(**fields),
            released=bool(document.get("released", False)),
        )

    def release(self) -> MachineLease:
        return dataclasses.replace(self, released=True)


_IDENTITY_FIELDS = tuple(field.name for field in dataclasses.fields(machines.VmIdentity))


def _path(value: object) -> Path:
    if not isinstance(value, str):
        raise TypeError("path")
    return Path(value)


def write_intent(
    ports: portset.HostPorts, intent: MachineIntent, *, root: safepaths.RuntimeRoot
) -> None:
    _write(ports, root.child(defaults.INTENT_NAME), intent.document())


def write_lease(
    ports: portset.HostPorts, lease: MachineLease, *, root: safepaths.RuntimeRoot
) -> None:
    _write(ports, root.child(defaults.LEASE_NAME), lease.document())
    _write(ports, lease.intent.run_directory.path / defaults.LEASE_NAME, lease.document())


def read_intent(ports: portset.HostPorts, *, root: safepaths.RuntimeRoot) -> MachineIntent | None:
    document = _read(ports, root.child(defaults.INTENT_NAME))
    return None if document is None else MachineIntent.parse(document)


def read_lease(ports: portset.HostPorts, *, root: safepaths.RuntimeRoot) -> MachineLease | None:
    document = _read(ports, root.child(defaults.LEASE_NAME))
    return None if document is None else MachineLease.parse(document)


def write_record(
    ports: portset.HostPorts, target: safepaths.SafePath, document: encoding.Document
) -> None:
    _write(ports, target, document)


def _write(
    ports: portset.HostPorts, target: safepaths.SafePath | Path, document: encoding.Document
) -> None:
    path = target if isinstance(target, safepaths.SafePath) else safepaths.SafePath(target)
    ports.files.write_atomic(path, encoding.canonical(document) + b"\n", mode=defaults.RECORD_MODE)


def _read(ports: portset.HostPorts, path: safepaths.SafePath) -> Mapping[str, object] | None:
    if not ports.files.exists(path):
        return None
    try:
        loaded = json.loads(ports.files.read_bytes(path, limit=defaults.DOCUMENT_LIMIT.value))
    except json.JSONDecodeError as error:
        raise errors.Refusal(
            refusals.RefusalReason.LEASE_MALFORMED, subject=f"{path.path.name}: {error.msg}"
        ) from error
    if not isinstance(loaded, dict):
        raise errors.Refusal(
            refusals.RefusalReason.LEASE_MALFORMED, subject=f"{path.path.name}: not an object"
        )
    return loaded
