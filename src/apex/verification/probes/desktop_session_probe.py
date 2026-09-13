"""The disposable account's session on the seat, reported or waited for as the host asks."""

from __future__ import annotations

from apex.kernel import claims, identifiers
from apex.verification import probes, probing

probes.declare(
    probing.ProbeCase(
        unit=identifiers.ProbeId("desktop.session"),
        environment=claims.EnvironmentKind.VM,
        summary=(
            "Whether the named account holds a session on the seat and whether it is a "
            "Wayland one, answered at once or waited for; the host asks before typing, so a "
            "login it did not perform is never counted, and after, as the proof of acceptance."
        ),
        privileged=False,
    )
)
