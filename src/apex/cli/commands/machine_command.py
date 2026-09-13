"""Start, stop, reclaim and look at the one machine the runtime root may run.

Only the builder starts from here so far; a disposable test machine needs its overlays and
its media, which arrive with the next slice. Every action goes through the provisioning
context, so the lock, the intent, the process and the lease keep their order, and the lease
carries the witness the hypervisor adapter vouched for at launch.
"""

from __future__ import annotations

import argparse

from apex.cli import commands, commandspecs
from apex.config import defaults
from apex.kernel import encoding, errors, refusals, safepaths
from apex.model import machines
from apex.ports import portset
from apex.provisioning import builderspec, launching, leases
from apex.wiring import contexts

NAME = "machine"
SUMMARY = "the one machine the runtime root may run: start, stop, reclaim, status"
START, STOP, STATUS, RECLAIM = "start", "stop", "status", "reclaim"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=f"apex {NAME}", description=SUMMARY)
    actions = parser.add_subparsers(dest="action", required=True)
    start = actions.add_parser(START, help="launch a machine from prepared storage")
    start.add_argument("--role", choices=[str(machines.VmRole.BUILDER)], required=True)
    actions.add_parser(STOP, help="ask the running machine to power down")
    actions.add_parser(STATUS, help="what is running, if anything")
    actions.add_parser(RECLAIM, help="what was started and left behind")
    return parser


def _root(context: contexts.Context) -> safepaths.RuntimeRoot:
    if context.root is None:
        raise errors.PreconditionUnmet(
            refusals.RefusalReason.PATH_NOT_A_DIRECTORY,
            subject=f"{context.settings.runtime_root}: create the runtime root first",
        )
    return context.root


def _lease_document(lease: leases.MachineLease | None) -> encoding.JsonValue:
    return None if lease is None else lease.document()


def start(
    context: contexts.Context, ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> encoding.Document:
    run = ports.identities.run_id()
    run_directory = root.child(f"{defaults.RUNS_DIRECTORY}/{run}")
    ports.files.make_directory(run_directory, mode=safepaths.PRIVATE_DIRECTORY_MODE)
    lease = launching.launch(
        ports,
        root=root,
        spec=builderspec.spec(context.settings, root),
        run=run,
        run_directory=run_directory,
    )
    return {"started": lease.document()}


def stop(ports: portset.HostPorts, root: safepaths.RuntimeRoot) -> encoding.Document:
    lease = launching.current(ports, root=root)
    if lease is None:
        raise errors.Refusal(
            refusals.RefusalReason.MACHINE_NOT_RUNNING,
            subject="no machine is running",
            remedy="reclaim the runtime root if one was left behind",
        )
    ending = launching.shutdown(ports, lease, root=root)
    return {"ending": str(ending), "process": lease.identity.process}


def status(ports: portset.HostPorts, root: safepaths.RuntimeRoot) -> encoding.Document:
    lease = launching.current(ports, root=root)
    return {"running": lease is not None, "lease": _lease_document(lease)}


def reclaim(ports: portset.HostPorts, root: safepaths.RuntimeRoot) -> encoding.Document:
    found = launching.reclaim(ports, root=root)
    return {
        "orphaned": found.orphaned,
        "intent": None if found.intent is None else found.intent.document(),
        "lease": _lease_document(found.lease),
    }


def run(request: commandspecs.Request) -> commandspecs.Reply:
    arguments = _parser().parse_args(list(request.arguments))
    root = _root(request.context)
    ports = request.context.bundle(root)
    if arguments.action == START:
        return commandspecs.Reply(document=start(request.context, ports, root))
    if arguments.action == STOP:
        return commandspecs.Reply(document=stop(ports, root))
    if arguments.action == RECLAIM:
        return commandspecs.Reply(document=reclaim(ports, root))
    return commandspecs.Reply(document=status(ports, root))


commands.declare(commandspecs.Command(name=NAME, summary=SUMMARY, run=run))
