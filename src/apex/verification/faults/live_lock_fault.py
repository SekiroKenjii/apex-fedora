"""The guard run at the pre-mount breakpoint with its lock denied, which must latch."""

from __future__ import annotations

from apex.kernel import claims, identifiers
from apex.verification import faulting, faults

faults.declare(
    faulting.FaultCase(
        unit=identifiers.ProbeId("fault.live-lock"),
        environment=claims.EnvironmentKind.VM,
        summary=(
            "In the initramfs, the sentinel fixture is made writable behind a stopped udev "
            "queue and the unmodified guard is run without CAP_SYS_ADMIN; a pass is the "
            "kernel denying the lock, the latch set, and the fixture protected again after."
        ),
    )
)
