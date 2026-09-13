"""Two disposable disks for installer tests, made in the isolated builder and reported."""

from __future__ import annotations

from apex.kernel import claims, identifiers
from apex.verification import probes, probing

probes.declare(
    probing.ProbeCase(
        unit=identifiers.ProbeId("fixture.installer-disks"),
        environment=claims.EnvironmentKind.BUILD,
        summary=(
            "In the isolated builder, a 4 GiB image with three foreign filesystems, each "
            "carrying a sentinel, converted to QCOW2 beside an empty 48 GiB target, both "
            "reported with their digests."
        ),
        arguments={"work": "", "output": "", "token": ""},
    )
)
