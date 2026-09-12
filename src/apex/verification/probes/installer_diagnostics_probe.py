"""The installer guest's logs, exported before a cancelled installation reboots it."""

from __future__ import annotations

from apex.kernel import claims, identifiers
from apex.verification import probes, probing

probes.declare(
    probing.ProbeCase(
        unit=identifiers.ProbeId("installer.diagnostics"),
        environment=claims.EnvironmentKind.INSTALLER_VM,
        summary=(
            "The preflight record, the three installer logs, SELinux, the installer units, "
            "the journal and the disks of the installer guest, bounded and bundled, framed "
            "under the host's token by the agent."
        ),
    )
)
