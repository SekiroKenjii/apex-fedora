"""Prepare, start, stop, reclaim and look at the one machine the runtime root may run.

The builder's storage is prepared from the reviewed base image, and the builder starts
from it; a disposable test machine starts from a source disk inside the runtime root, over
fresh overlays in its own run directory, with the image it boots from and what that image
is. Every action goes through the provisioning context, so the lock, the intent, the
process and the lease keep their order, and the lease carries the witness the hypervisor
adapter vouched for at launch.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path

from apex.cli import commands, commandspecs
from apex.config import builderpins, defaults
from apex.kernel import encoding, errors, identifiers, refusals, safepaths
from apex.model import machines
from apex.ports import portset
from apex.provisioning import (
    backingchain,
    builderprepare,
    builderspec,
    compacting,
    comparing,
    hotplugging,
    launching,
    leases,
    resuming,
    runrecord,
    testspec,
)
from apex.verification import installerfault
from apex.wiring import contexts

NAME = "machine"
SUMMARY = "the one machine the runtime root may run: prepare, start, stop, reclaim, status"
PREPARE, START, STOP, STATUS, RECLAIM = "prepare", "start", "stop", "status", "reclaim"
HOTPLUG = "hotplug-usb"
POWER_LOSS = "power-loss"
COMPARE = "compare"
COLLECT = "collect"
RESUME = "resume"
COMPACT = "compact"
TEST = "test"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=f"apex {NAME}", description=SUMMARY)
    actions = parser.add_subparsers(dest="action", required=True)
    actions.add_parser(
        PREPARE, help="make the builder's storage: base image, disk, key, seed, variables"
    )
    start = actions.add_parser(START, help="launch a machine from prepared storage")
    start.add_argument("--role", choices=[str(role) for role in machines.VmRole], required=True)
    start.add_argument("--disk", type=Path, help="the test machine's source disk")
    start.add_argument("--iso", type=Path, help="an image the test machine boots from")
    start.add_argument("--medium", choices=[str(medium) for medium in machines.Medium])
    start.add_argument("--extra-disk", type=Path, action="append", default=[])
    start.add_argument("--guest-ssh", action="store_true")
    start.add_argument("--serial-console", action="store_true")
    start.add_argument("--usb-bus", action="store_true", help="an emulated usb controller")
    start.add_argument("--boot-usb", type=Path, help="an image booted as emulated usb storage")
    hotplug = actions.add_parser(HOTPLUG, help="attach a usb fixture to the running test machine")
    hotplug.add_argument("--source", type=Path, required=True)
    actions.add_parser(POWER_LOSS, help="kill the running test machine outright, as a fault")
    compare = actions.add_parser(
        COMPARE, help="compare a stopped run's overlays with their sources"
    )
    compare.add_argument("--run", required=True, help="the run, by id or by its run directory")
    collect = actions.add_parser(
        COLLECT, help="judge a stopped installer fault run from its request, report and disks"
    )
    collect.add_argument("--run", required=True, help="the run, by id or by its run directory")
    resume = actions.add_parser(RESUME, help="boot a stopped run again over its own overlays")
    resume.add_argument("--run", required=True, help="the run, by id or by its run directory")
    resume.add_argument("--without-iso", action="store_true", help="leave the boot image out")
    compact = actions.add_parser(
        COMPACT, help="swap the builder's disk for a validated compressed copy"
    )
    compact.add_argument(
        "--resume", help="a kept compaction whose compared copy is swapped in, not converted again"
    )
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


def prepare(
    context: contexts.Context, ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> encoding.Document:
    reviewed = builderpins.load(context.repository)
    prepared = builderprepare.prepare(
        ports, context.settings, root, base=reviewed.source, instance=ports.identities.run_id()
    )
    return {"prepared": prepared.document()}


def start_builder(
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


def start_test(
    context: contexts.Context,
    ports: portset.HostPorts,
    root: safepaths.RuntimeRoot,
    arguments: argparse.Namespace,
) -> encoding.Document:
    if arguments.disk is None:
        raise errors.Refusal(
            refusals.RefusalReason.TOPOLOGY_INCONSISTENT,
            subject="a test machine needs a source disk",
            remedy="name it with --disk",
        )
    request = testspec.TestRequest(
        disk=arguments.disk,
        iso=arguments.iso,
        medium=None if arguments.medium is None else machines.Medium(arguments.medium),
        extra_disks=tuple(arguments.extra_disk),
        guest_ssh=arguments.guest_ssh,
        serial_console=arguments.serial_console,
        usb_bus=arguments.usb_bus,
        boot_usb=arguments.boot_usb,
    )
    prepared = testspec.prepare(
        ports, context.settings, root, request, run=ports.identities.run_id()
    )
    lease = launching.launch(
        ports,
        root=root,
        spec=prepared.spec,
        run=prepared.run,
        run_directory=prepared.run_directory,
        medium=prepared.medium,
    )
    return {"started": lease.document()}


def hotplug(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot, source: Path
) -> encoding.Document:
    return {"attached": hotplugging.attach(ports, root=root, source=source).document()}


def power_loss(ports: portset.HostPorts, root: safepaths.RuntimeRoot) -> encoding.Document:
    lease = launching.current(ports, root=root)
    if lease is None:
        raise errors.Refusal(
            refusals.RefusalReason.MACHINE_NOT_RUNNING,
            subject="no machine is running",
            remedy="a power loss is injected into a running test machine",
        )
    owned = machines.OwnedTestVm(identity=lease.identity, role=lease.intent.role)
    launching.power_loss(ports, owned, lease, root=root)
    return {
        "terminated": lease.identity.process,
        "record": str(lease.intent.run_directory.path / defaults.POWER_LOSS_RECORD),
    }


def _run_id(value: str) -> identifiers.RunId:
    """A run named by its id, or by the directory the id names, as the older tool took it."""
    return identifiers.RunId.parse(Path(value).name)


def _comparison(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot, run: str
) -> tuple[safepaths.SafePath, comparing.RunComparison]:
    run_directory = root.child(f"{defaults.RUNS_DIRECTORY}/{_run_id(run)}")
    record = runrecord.read(ports, run_directory)
    layers = record.layers(hotplugging.attached(ports, run_directory))
    disks = tuple(
        comparing.Layered(
            source=backingchain.inspect(ports, layer.source, root=root),
            overlay=backingchain.inspect(ports, layer.overlay, root=root),
        )
        for layer in layers
    )
    return run_directory, comparing.compare(
        ports, root=root, run_directory=run_directory, disks=disks
    )


def compare(ports: portset.HostPorts, root: safepaths.RuntimeRoot, run: str) -> encoding.Document:
    return _comparison(ports, root, run)[1].document()


def collect(ports: portset.HostPorts, root: safepaths.RuntimeRoot, run: str) -> encoding.Document:
    """The comparison first, since it refuses a running machine, then the fault's result."""
    run_directory, comparison = _comparison(ports, root, run)
    return installerfault.collect(
        ports, root=root, run_directory=run_directory, comparison=comparison
    ).document()


def resume(
    context: contexts.Context,
    ports: portset.HostPorts,
    root: safepaths.RuntimeRoot,
    arguments: argparse.Namespace,
) -> encoding.Document:
    prepared = resuming.resume(
        ports,
        context.settings,
        root,
        _run_id(arguments.run),
        stamp=ports.identities.token(),
        without_iso=arguments.without_iso,
    )
    lease = launching.launch(
        ports,
        root=root,
        spec=prepared.spec,
        run=prepared.run,
        run_directory=prepared.run_directory,
        medium=prepared.medium,
    )
    return {"resumed": lease.document()}


def compact(
    context: contexts.Context,
    ports: portset.HostPorts,
    root: safepaths.RuntimeRoot,
    arguments: argparse.Namespace,
) -> encoding.Document:
    if arguments.resume is not None:
        compacted = compacting.finalise(
            ports, context.settings, root, identifiers.RunId.parse(arguments.resume)
        )
    else:
        compacted = compacting.compact(ports, context.settings, root)
    return {"compacted": compacted.document()}


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


Action = Callable[
    [contexts.Context, portset.HostPorts, safepaths.RuntimeRoot, argparse.Namespace],
    encoding.Document,
]
ACTIONS: dict[str, Action] = {
    PREPARE: lambda context, ports, root, _: prepare(context, ports, root),
    START: lambda context, ports, root, arguments: (
        start_builder(context, ports, root)
        if arguments.role == str(machines.VmRole.BUILDER)
        else start_test(context, ports, root, arguments)
    ),
    HOTPLUG: lambda _, ports, root, arguments: hotplug(ports, root, arguments.source),
    POWER_LOSS: lambda _, ports, root, __: power_loss(ports, root),
    COMPARE: lambda _, ports, root, arguments: compare(ports, root, arguments.run),
    COLLECT: lambda _, ports, root, arguments: collect(ports, root, arguments.run),
    RESUME: resume,
    COMPACT: compact,
    STOP: lambda _, ports, root, __: stop(ports, root),
    RECLAIM: lambda _, ports, root, __: reclaim(ports, root),
    STATUS: lambda _, ports, root, __: status(ports, root),
}


def run(request: commandspecs.Request) -> commandspecs.Reply:
    arguments = _parser().parse_args(list(request.arguments))
    root = _root(request.context)
    ports = request.context.bundle(root)
    document = ACTIONS[str(arguments.action)](request.context, ports, root, arguments)
    return commandspecs.Reply(document=document)


def _test(*arguments: str) -> tuple[str, ...]:
    return (NAME, START, "--role", TEST, "--disk", "{{disk}}", *arguments)


RECIPES = (
    commandspecs.Recipe("builder-prepare", (), (NAME, PREPARE)),
    commandspecs.Recipe("builder-start", (), (NAME, START, "--role", "builder")),
    commandspecs.Recipe("builder-stop", (), (NAME, STOP)),
    commandspecs.Recipe("builder-status", (), (NAME, STATUS)),
    commandspecs.Recipe("builder-compact", (), (NAME, COMPACT)),
    commandspecs.Recipe(
        "builder-finalize", ("compaction_id",), (NAME, COMPACT, "--resume", "{{compaction_id}}")
    ),
    commandspecs.Recipe("test-vm", ("disk",), _test()),
    commandspecs.Recipe(
        "test-installer",
        ("disk", "iso", "other_disk"),
        _test("--iso", "{{iso}}", "--medium", "installer", "--extra-disk", "{{other_disk}}"),
    ),
    commandspecs.Recipe(
        "test-installer-diagnostic",
        ("disk", "iso", "other_disk"),
        _test(
            "--iso",
            "{{iso}}",
            "--medium",
            "installer",
            "--extra-disk",
            "{{other_disk}}",
            "--serial-console",
        ),
    ),
    commandspecs.Recipe(
        "test-live-hotplug",
        ("disk", "iso", "other_disk"),
        _test(
            "--iso",
            "{{iso}}",
            "--medium",
            "live",
            "--extra-disk",
            "{{other_disk}}",
            "--serial-console",
            "--usb-bus",
        ),
    ),
    commandspecs.Recipe(
        "test-ventoy",
        ("disk", "other_disk", "usb_image"),
        _test(
            "--extra-disk",
            "{{other_disk}}",
            "--boot-usb",
            "{{usb_image}}",
            "--usb-bus",
            "--serial-console",
        ),
    ),
    commandspecs.Recipe("test-hotplug-usb", ("source",), (NAME, HOTPLUG, "--source", "{{source}}")),
    commandspecs.Recipe("test-power-loss", (), (NAME, POWER_LOSS)),
    commandspecs.Recipe(
        "test-compare-disks", ("run_directory",), (NAME, COMPARE, "--run", "{{run_directory}}")
    ),
    commandspecs.Recipe(
        "test-resume-installed",
        ("run_directory",),
        (NAME, RESUME, "--run", "{{run_directory}}", "--without-iso"),
    ),
    commandspecs.Recipe(
        "test-installer-fault-collect",
        ("run_directory",),
        (NAME, COLLECT, "--run", "{{run_directory}}"),
    ),
)

commands.declare(commandspecs.Command(name=NAME, summary=SUMMARY, run=run, recipes=RECIPES))
