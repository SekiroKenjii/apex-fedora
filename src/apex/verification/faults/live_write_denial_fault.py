"""Same-byte writes to the live guest's virtio fixtures, which the guard must deny."""

from __future__ import annotations

from apex.kernel import claims, identifiers
from apex.verification import faulting, faults

faults.declare(
    faulting.FaultCase(
        unit=identifiers.ProbeId("fault.live-write-denial"),
        environment=claims.EnvironmentKind.VM,
        summary=(
            "The five owned virtio fixture nodes of a live guest each receive their own first "
            "sector back; a pass is the kernel refusing every write and the bytes unchanged."
        ),
    )
)
