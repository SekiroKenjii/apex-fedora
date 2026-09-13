"""A completed update fixture's identical blobs shared in the builder, no file removed."""

from __future__ import annotations

from apex.kernel import claims, identifiers
from apex.verification import probes, probing

probes.declare(
    probing.ProbeCase(
        unit=identifiers.ProbeId("fixture.dedupe"),
        environment=claims.EnvironmentKind.BUILD,
        summary=(
            "In the isolated builder, a self test that identical extents share and differing "
            "ones are refused, then every content-addressed blob a completed update fixture "
            "holds twice shared through the extent port; manifests, signatures and every "
            "file left in place, the free space recorded before and after."
        ),
        arguments={"work": "", "fixture": ""},
    )
)
