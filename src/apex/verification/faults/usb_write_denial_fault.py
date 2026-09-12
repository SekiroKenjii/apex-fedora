"""Same-byte writes to the USB fixture hot-plugged into a live guest, after udev settles."""

from __future__ import annotations

from apex.kernel import claims, identifiers
from apex.verification import faulting, faults

faults.declare(
    faulting.FaultCase(
        unit=identifiers.ProbeId("fault.usb-write-denial"),
        environment=claims.EnvironmentKind.VM,
        summary=(
            "The four nodes of the one emulated USB fixture each receive their own first sector "
            "back after udev settles; a pass is every write denied and the bytes unchanged."
        ),
    )
)
