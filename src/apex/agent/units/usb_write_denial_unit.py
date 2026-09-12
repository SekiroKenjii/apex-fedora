"""Attempt same-byte writes on the emulated USB fixture the host hot-plugged, after udev settles.

This is `guest/live-usb-probe.py`: the live guard, udev settled, the four nodes that belong
to the one USB device carrying the fixture serial, one write each, and a stop at the first
that was not denied.
"""

from __future__ import annotations

from collections.abc import Mapping

from apex.agent import agentports, guestguard, livefixtures, units
from apex.config import defaults
from apex.kernel import commands, encoding, errors, identifiers

NOT_TESTED = "NOT TESTED"
SCOPE = "Emulated QEMU USB fixture after udev settle"
EXPECTED_NODES = 4
SETTLE = commands.Argv.of("udevadm", "settle", "--timeout=20")


def run(
    ports: agentports.AgentPorts,
    *,
    arguments: Mapping[str, encoding.JsonValue],  # noqa: ARG001
) -> encoding.Document:
    # This fault takes no arguments; the shape is the unit contract and every unit keeps it.
    guestguard.require_live(ports)
    settled = ports.processes.run(
        SETTLE, deadline=defaults.SETTLE_DEADLINE, limit=commands.OutputLimit.default()
    )
    if not settled.succeeded:
        raise errors.PortFailure(port="process", cause="udev did not settle")

    def take() -> livefixtures.Inventory:
        return livefixtures.Inventory.take(ports, matching=livefixtures.USB_NAME)

    inventory = take()
    livefixtures.require_usb_fixture(ports, inventory)
    results = livefixtures.exercise(ports, inventory, retake=take)
    return {
        "status": livefixtures.overall(results, expected=EXPECTED_NODES),
        "scope": SCOPE,
        "inventory": inventory.document(),
        "writes": results,
        "whole_disk_comparison": NOT_TESTED,
        "physical_usb": NOT_TESTED,
        "hotplug_race_window": NOT_TESTED,
    }


units.declare(units.Unit(id=identifiers.ProbeId("fault.usb-write-denial"), run=run))
