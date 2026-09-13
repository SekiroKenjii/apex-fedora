"""Whether the Shell's Overview is open, read over the bus after the host presses a key."""

from __future__ import annotations

from apex.kernel import claims, identifiers
from apex.verification import probes, probing

probes.declare(
    probing.ProbeCase(
        unit=identifiers.ProbeId("desktop.overview"),
        environment=claims.EnvironmentKind.VM,
        summary=(
            "The Shell's OverviewActive property, read over the account's bus until it shows "
            "the state the host expects or fifteen seconds have passed; the bus is read and "
            "never used to open or close the Overview."
        ),
        privileged=False,
    )
)
