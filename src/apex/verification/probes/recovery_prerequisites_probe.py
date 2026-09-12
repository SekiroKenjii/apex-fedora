"""An installed guest's recovery prerequisites: two deployments, the units, the files."""

from __future__ import annotations

from apex.kernel import claims, identifiers
from apex.verification import probes, probing

probes.declare(
    probing.ProbeCase(
        unit=identifiers.ProbeId("recovery.prerequisites"),
        environment=claims.EnvironmentKind.VM,
        summary=(
            "The deployment status, the greenboot units and their journal, the GRUB "
            "environment and the health check script of an installed guest, read once; two "
            "distinct deployments are a prerequisite and never a pass."
        ),
    )
)
