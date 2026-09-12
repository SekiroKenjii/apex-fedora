"""Attempt same-byte writes on the live guest's unmounted virtio fixtures, and nothing else.

This is `guest/live-write-denial.py`: the live guard, the five fixture nodes by size, serial
and layout, one write each, and a stop at the first that was not denied. The report says
what happened; the host decides what it proves.
"""

from __future__ import annotations

from collections.abc import Mapping

from apex.agent import agentports, guestguard, livefixtures, units
from apex.kernel import encoding, identifiers

NOT_TESTED = "NOT TESTED"
SCOPE = "Five owned live-VM virtio fixture nodes only"
EXPECTED_NODES = 5


def run(
    ports: agentports.AgentPorts,
    *,
    arguments: Mapping[str, encoding.JsonValue],  # noqa: ARG001
) -> encoding.Document:
    # This fault takes no arguments; the shape is the unit contract and every unit keeps it.
    guestguard.require_live(ports)

    def take() -> livefixtures.Inventory:
        return livefixtures.Inventory.take(ports, matching=livefixtures.VIRTIO_NAME)

    inventory = take()
    livefixtures.require_live_fixture(inventory)
    results = livefixtures.exercise(ports, inventory, retake=take)
    return {
        "status": livefixtures.overall(results, expected=EXPECTED_NODES),
        "scope": SCOPE,
        "inventory": inventory.document(),
        "devices": results,
        "whole_disk_comparison": NOT_TESTED,
        "full_protection_acceptance": NOT_TESTED,
    }


units.declare(units.Unit(id=identifiers.ProbeId("fault.live-write-denial"), run=run))
