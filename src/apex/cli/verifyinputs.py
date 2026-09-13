"""Everything the verify command takes from the runtime root before a recipe runs.

The lease says which machine runs and what witness its launcher vouched for; the wheel is
the one beside the store; the candidate is the frozen one; the recorder opens the store
for this run. The guest is reached as the recipe's role dictates: a builder recipe with
the builder's own account and key, a test machine recipe with the account `--user` or the
credentials file names, and over the serial socket instead of ssh when the operator asks,
which is how a live medium's rescue shell is reached as root.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

from apex.cli import builderaccess
from apex.config import defaults
from apex.kernel import errors, identifiers, refusals, safepaths
from apex.model import machines, runtimestate
from apex.ports import guestshell, portset
from apex.provisioning import launching, leases
from apex.verification import installerfault, recording, testaccess
from apex.wiring import contexts

SERIAL_USER = "root"


@dataclasses.dataclass(frozen=True, slots=True)
class Asked:
    """What the operator said on the command line, before the root fills in the rest."""

    user: str | None = None
    credentials: Path | None = None
    build: str | None = None
    serial: bool = False
    case: str | None = None
    wrong_key: Path | None = None


@dataclasses.dataclass(frozen=True, slots=True)
class Inputs:
    ports: portset.HostPorts
    guest: guestshell.GuestTarget
    wheel: safepaths.SafePath
    candidate: identifiers.Digest | None
    lease: leases.MachineLease
    recorder: recording.Recorder
    root: safepaths.RuntimeRoot
    repository: safepaths.SourceRoot
    credentials: testaccess.Credentials | None
    parent: identifiers.BuildId | None
    case: str | None = None
    wrong_key: str | None = None


def _root(context: contexts.Context) -> safepaths.RuntimeRoot:
    if context.root is None:
        raise errors.PreconditionUnmet(
            refusals.RefusalReason.PATH_NOT_A_DIRECTORY,
            subject=f"{context.settings.runtime_root}: no runtime root to verify from",
        )
    return context.root


def _running_machine(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot, role: machines.VmRole
) -> leases.MachineLease:
    lease = launching.current(ports, root=root)
    if lease is None:
        raise errors.Refusal(
            refusals.RefusalReason.MACHINE_NOT_RUNNING,
            subject="no machine is running",
            remedy=f"start the {role} machine first",
        )
    if lease.intent.role is role:
        return lease
    if role is machines.VmRole.TEST:
        raise errors.Refusal(
            refusals.RefusalReason.NOT_A_DISPOSABLE_MACHINE,
            subject=f"a {lease.intent.role} machine is running",
            remedy="this recipe mutates its guest and runs only against a test machine",
        )
    raise errors.Refusal(
        refusals.RefusalReason.MACHINE_ROLE_MISMATCH,
        subject=f"a {lease.intent.role} machine is running",
        remedy=f"this recipe runs in the isolated {role}",
    )


def wheel(root: safepaths.RuntimeRoot) -> safepaths.SafePath:
    """The agent wheel placed beside the store, which every guest recipe delivers."""
    return _present(root, defaults.AGENT_WHEEL_NAME, remedy="build the agent wheel into the root")


def _present(root: safepaths.RuntimeRoot, name: str, *, remedy: str) -> safepaths.SafePath:
    candidate = root.child(name)
    if not candidate.path.is_file():
        raise errors.PreconditionUnmet(
            refusals.RefusalReason.PATH_NOT_A_REGULAR_FILE, subject=f"{candidate}: {remedy}"
        )
    return safepaths.SafePath.regular_file(candidate.path, within=root)


def _candidate(root: safepaths.RuntimeRoot) -> identifiers.Digest:
    document = root.child(runtimestate.CANDIDATE_NAME)
    if not document.path.is_file():
        raise errors.PreconditionUnmet(
            refusals.RefusalReason.PATH_NOT_A_REGULAR_FILE,
            subject=f"{document}: select a candidate before verifying",
        )
    return runtimestate.read_candidate(document.path).digest


def required_candidate(inputs: Inputs) -> identifiers.Digest:
    if inputs.candidate is None:
        raise errors.PreconditionUnmet(
            refusals.RefusalReason.PATH_NOT_A_REGULAR_FILE,
            subject="no candidate was selected for a test machine recipe",
        )
    return inputs.candidate


def _credentials(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot, path: Path | None
) -> testaccess.Credentials | None:
    if path is None:
        return None
    return testaccess.read(ports.files, safepaths.SafePath.regular_file(path, within=root))


def _serial_ports(
    context: contexts.Context,
    ports: portset.HostPorts,
    root: safepaths.RuntimeRoot,
    lease: leases.MachineLease,
) -> portset.HostPorts:
    """The same ports with the guest shell replaced by the leased machine's serial console."""
    if not any(machines.SERIAL_CHARDEV in word for word in lease.intent.command):
        raise errors.Refusal(
            refusals.RefusalReason.SERIAL_CONSOLE_ABSENT,
            subject="the running machine was started without a serial console",
            remedy="start it with --serial-console, then verify with --serial",
        )
    console = context.serial(root.child(defaults.SERIAL_SOCKET_NAME), lease.identity.process)
    return dataclasses.replace(ports, guest=console)


def _serial_guest(
    root: safepaths.RuntimeRoot, user: str | None, credentials: Path | None
) -> guestshell.GuestTarget:
    """Over serial the account is the rescue shell's root and the key is never read."""
    if credentials is not None:
        raise errors.Refusal(
            refusals.RefusalReason.REQUEST_MALFORMED,
            subject="--serial logs into a rescue shell that asks for no password",
            remedy="leave --credentials out",
        )
    return guestshell.GuestTarget(
        user=SERIAL_USER if user is None else user,
        port=defaults.GUEST_SSH_PORT,
        key=root.child(defaults.GUEST_KEY_NAME),
        known_hosts=root.child(defaults.KNOWN_HOSTS_NAME),
    )


def _builder_guest(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot, asked: Asked
) -> guestshell.GuestTarget:
    if asked.user is not None or asked.credentials is not None or asked.serial:
        raise errors.Refusal(
            refusals.RefusalReason.REQUEST_MALFORMED,
            subject="a builder recipe takes neither --user, --credentials nor --serial",
            remedy="the builder's account and key are the runtime root's own, over ssh",
        )
    return builderaccess.leased_builder(ports, root)


def _test_guest(
    root: safepaths.RuntimeRoot, asked: Asked, credentials: testaccess.Credentials | None
) -> guestshell.GuestTarget:
    """The account and key a test machine recipe reaches its guest with over ssh."""
    key = _present(root, defaults.GUEST_KEY_NAME, remedy="place the guest key beside the store")
    if credentials is not None and credentials.key is not None:
        key = safepaths.SafePath.regular_file(credentials.key, within=root)
    return guestshell.GuestTarget(
        user=_account(asked.user, credentials),
        port=defaults.GUEST_SSH_PORT,
        key=key,
        known_hosts=root.child(defaults.KNOWN_HOSTS_NAME),
    )


def _guest(
    ports: portset.HostPorts,
    root: safepaths.RuntimeRoot,
    role: machines.VmRole,
    asked: Asked,
    credentials: testaccess.Credentials | None,
) -> guestshell.GuestTarget:
    if role is machines.VmRole.BUILDER:
        return _builder_guest(ports, root, asked)
    if asked.serial:
        return _serial_guest(root, asked.user, asked.credentials)
    return _test_guest(root, asked, credentials)


def _parent(value: str | None) -> identifiers.BuildId | None:
    return None if value is None else identifiers.BuildId.parse(value)


def _account(user: str | None, credentials: testaccess.Credentials | None) -> str:
    """The guest account: the one named, the one the credentials name, and never two."""
    if credentials is not None and user not in (None, credentials.user):
        raise errors.Refusal(
            refusals.RefusalReason.REQUEST_MALFORMED,
            subject=f"--user {user} but the credentials name {credentials.user}",
            remedy="name one account",
        )
    named = user if credentials is None else credentials.user
    if named is None:
        raise errors.Refusal(
            refusals.RefusalReason.REQUEST_MALFORMED,
            subject="no guest account",
            remedy="name it with --user or --credentials",
        )
    return named


def gather(context: contexts.Context, *, role: machines.VmRole, asked: Asked) -> Inputs:
    root = _root(context)
    ports = context.bundle(root)
    lease = _running_machine(ports, root, role)
    read = None if asked.serial else _credentials(ports, root, asked.credentials)
    guest = _guest(ports, root, role, asked, read)
    if asked.serial:
        ports = _serial_ports(context, ports, root, lease)
    return Inputs(
        ports=ports,
        guest=guest,
        wheel=wheel(root),
        candidate=_candidate(root) if role is machines.VmRole.TEST else None,
        lease=lease,
        recorder=recording.Recorder.open(
            root, filesystem=ports.files, identities=ports.identities, clock=ports.clock
        ),
        root=root,
        repository=context.repository,
        credentials=read,
        parent=_parent(asked.build),
        case=asked.case,
        wrong_key=(
            None if asked.wrong_key is None
            else installerfault.read_key(ports, root, asked.wrong_key)
        ),
    )
