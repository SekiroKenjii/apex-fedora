"""The running builder as a guest the commands can reach: its lease, its account, its key."""

from __future__ import annotations

from apex.config import defaults
from apex.kernel import errors, refusals, safepaths
from apex.model import machines
from apex.ports import guestshell, portset
from apex.provisioning import launching


def leased_builder(ports: portset.HostPorts, root: safepaths.RuntimeRoot) -> guestshell.GuestTarget:
    lease = launching.current(ports, root=root)
    if lease is None:
        raise errors.Refusal(
            refusals.RefusalReason.MACHINE_NOT_RUNNING,
            subject="no machine is running",
            remedy="start the builder first",
        )
    if lease.intent.role is not machines.VmRole.BUILDER:
        raise errors.Refusal(
            refusals.RefusalReason.MACHINE_ROLE_MISMATCH,
            subject=f"a {lease.intent.role} machine is running",
            remedy="this runs in the isolated builder",
        )
    key = root.child(defaults.BUILDER_KEY_NAME)
    if not key.path.is_file():
        raise errors.PreconditionUnmet(
            refusals.RefusalReason.PATH_NOT_A_REGULAR_FILE,
            subject=f"{key}: prepare the builder first",
        )
    return guestshell.GuestTarget(
        user=defaults.BUILDER_USER,
        port=defaults.BUILDER_SSH_PORT,
        key=safepaths.SafePath.regular_file(key.path, within=root),
        known_hosts=root.child(defaults.KNOWN_HOSTS_NAME),
    )
