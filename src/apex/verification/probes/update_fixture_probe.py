"""Two signed images over the frozen payload, one a child of the other, built in the builder."""

from __future__ import annotations

from apex.kernel import claims, identifiers
from apex.verification import probes, probing

probes.declare(
    probing.ProbeCase(
        unit=identifiers.ProbeId("fixture.update"),
        environment=claims.EnvironmentKind.BUILD,
        summary=(
            "The payload the host imported is layered into image A with the reviewed "
            "recovery configuration and the fixture's own signing policy, B carries only its "
            "marker, both keep the parent's package inventory, both are signed with a "
            "development key made for the run, the wrong-key and unsigned twins are derived "
            "from B, and the whole bundle is packaged with every file digested."
        ),
        arguments={"work": ""},
    )
)
