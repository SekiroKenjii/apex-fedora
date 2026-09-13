"""Attach one USB fixture to the running test machine through its emulated controller.

The fixture is a fresh layer over a source inside the runtime root, never the source; it
is registered in the run directory before the monitor is asked, so an attempt the host did
not finish is still compared afterwards; and it goes in through the emulated controller
the machine was started with, never through a host device. One fixture per run.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from apex.config import defaults
from apex.kernel import encoding, errors, refusals, safepaths
from apex.model import machines
from apex.ports import locking, portset, qmp
from apex.provisioning import backingchain, launching, leases, runrecord

BLOCKDEV_ADD = "blockdev-add"
DEVICE_ADD = "device_add"
NODE = "apex-usb-disk"
DEVICE = "apex-usb-fixture"
INCOMPLETE = "INCOMPLETE"
ATTACHED = "ATTACHED"
NOT_TESTED = "NOT TESTED"


@dataclasses.dataclass(frozen=True, slots=True)
class HotplugReport:
    source: safepaths.SafePath
    overlay: safepaths.SafePath
    requests: tuple[qmp.QmpCommand, ...]
    responses: tuple[encoding.JsonValue, ...]
    status: str

    def document(self) -> encoding.Document:
        requests: list[encoding.JsonValue] = [
            [item.name, _json(dict(item.arguments))] for item in self.requests
        ]
        return {
            "source": str(self.source),
            "overlay": str(self.overlay),
            "requests": requests,
            "responses": list(self.responses),
            "status": self.status,
            "guest_protection": NOT_TESTED,
        }


def attach(
    ports: portset.HostPorts, *, root: safepaths.RuntimeRoot, source: Path
) -> HotplugReport:
    with ports.locks.acquire(launching.MACHINE, locking.AcquisitionPolicy.immediate()):
        lease = _test_machine_with_bus(ports, root)
        run_directory = lease.intent.run_directory
        if ports.files.exists(safepaths.SafePath(run_directory.path / defaults.HOTPLUG_RECORD)):
            raise errors.Refusal(
                refusals.RefusalReason.DUPLICATE_DEVICE,
                subject="this run already has a hot-plugged fixture",
                remedy="one fixture per run; start another run for another",
            )
        chain = backingchain.inspect(ports, source, root=root)
        overlay = backingchain.overlay(
            ports, chain, into=run_directory / defaults.HOTPLUG_OVERLAY_NAME, root=root
        )
        report = HotplugReport(
            source=chain.disk, overlay=overlay.disk, requests=_requests(overlay.disk),
            responses=(), status=INCOMPLETE,
        )
        _record(ports, run_directory, report)
        responses: list[encoding.JsonValue] = []
        try:
            with ports.monitor.connect(
                lease.intent.monitor, deadline=defaults.QMP_DEADLINE
            ) as session:
                for request in report.requests:
                    if not ports.hypervisor.running(lease.identity):
                        raise errors.Refusal(
                            refusals.RefusalReason.MACHINE_IDENTITY_CHANGED,
                            subject="the machine changed while the fixture was attached",
                        )
                    responses.append(_json(session.execute(request)))
            report = dataclasses.replace(report, responses=tuple(responses), status=ATTACHED)
        finally:
            report = dataclasses.replace(report, responses=tuple(responses))
            _record(ports, run_directory, report)
        return report


def _test_machine_with_bus(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> leases.MachineLease:
    lease = launching.current(ports, root=root)
    if lease is None:
        raise errors.Refusal(
            refusals.RefusalReason.MACHINE_NOT_RUNNING,
            subject="no machine is running",
            remedy="start a disposable test machine with its emulated usb bus first",
        )
    if lease.intent.role is not machines.VmRole.TEST:
        raise errors.Refusal(
            refusals.RefusalReason.NOT_A_DISPOSABLE_MACHINE,
            subject=f"a {lease.intent.role} machine is running",
            remedy="a fixture is attached only to a disposable test machine",
        )
    if machines.USB_CONTROLLER not in lease.intent.command:
        raise errors.Refusal(
            refusals.RefusalReason.TOPOLOGY_INCONSISTENT,
            subject="the running machine has no emulated usb bus",
            remedy="start it with --usb-bus",
        )
    return lease


def _requests(overlay: safepaths.SafePath) -> tuple[qmp.QmpCommand, ...]:
    return (
        qmp.QmpCommand(BLOCKDEV_ADD, {
            "driver": backingchain.QCOW2,
            "node-name": NODE,
            "read-only": False,
            "file": {"driver": "file", "filename": str(overlay)},
        }),
        qmp.QmpCommand(DEVICE_ADD, {
            "driver": "usb-storage",
            "id": DEVICE,
            "bus": machines.USB_ROOT_PORT,
            "drive": NODE,
            "serial": machines.USB_FIXTURE_SERIAL,
        }),
    )


def _record(
    ports: portset.HostPorts, run_directory: safepaths.SafePath, report: HotplugReport
) -> None:
    leases.write_record(
        ports, safepaths.SafePath(run_directory.path / defaults.HOTPLUG_RECORD), report.document()
    )


def _json(value: object) -> encoding.JsonValue:
    """What the monitor was sent or answered, kept only as far as it is a document."""
    if isinstance(value, dict):
        return {str(key): _json(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json(item) for item in value]
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return str(value)


def attached(
    ports: portset.HostPorts, run_directory: safepaths.SafePath
) -> runrecord.Layer | None:
    """The fixture the run hot-plugged, as source and overlay, or nothing when it never did."""
    path = safepaths.SafePath(run_directory.path / defaults.HOTPLUG_RECORD)
    if not ports.files.exists(path):
        return None
    try:
        loaded = json.loads(ports.files.read_bytes(path, limit=defaults.DOCUMENT_LIMIT.value))
        return runrecord.Layer(
            source=Path(str(loaded["source"])), overlay=Path(str(loaded["overlay"]))
        )
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise errors.Refusal(
            refusals.RefusalReason.LEASE_MALFORMED, subject=f"{path.path.name}: {error}"
        ) from error
