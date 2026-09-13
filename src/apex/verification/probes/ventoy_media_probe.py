"""File-backed Ventoy media prepared in the builder from reviewed inputs, and reported."""

from __future__ import annotations

from apex.kernel import claims, identifiers
from apex.verification import probes, probing

probes.declare(
    probing.ProbeCase(
        unit=identifiers.ProbeId("fixture.ventoy"),
        environment=claims.EnvironmentKind.BUILD,
        summary=(
            "In the isolated builder, the reviewed Ventoy archive installed onto a sparse "
            "image attached as a loop device, the two ISOs copied onto it and hashed again, "
            "the medium converted to QCOW2 and reported with its digest; no physical medium."
        ),
        arguments={"work": ""},
    )
)
