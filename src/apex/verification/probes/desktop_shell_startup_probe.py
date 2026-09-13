"""The Shell's startup event on the account's bus, waited for after the login."""

from __future__ import annotations

from apex.kernel import claims, identifiers
from apex.verification import probes, probing

probes.declare(
    probing.ProbeCase(
        unit=identifiers.ProbeId("desktop.shell-startup"),
        environment=claims.EnvironmentKind.VM,
        summary=(
            "The Shell's owner on the account's bus and the journal entry that says that "
            "process finished starting, polled once a second for ninety seconds and reported "
            "as the journal wrote it."
        ),
        privileged=False,
    )
)
