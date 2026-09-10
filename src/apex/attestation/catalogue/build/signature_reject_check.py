from __future__ import annotations

from apex.attestation import catalogue
from apex.kernel import claims, identifiers
from apex.registry import descriptors

CHECK = catalogue.declare(
    descriptors.CheckSpec(
        id=identifiers.CheckId('signature.reject'),
        group='build',
        environment=claims.EnvironmentKind.BUILD,
        summary=(
            'Establishes that artifact verification rejects a changed manifest, a changed '
            'payload, a wrong key and a bundled key offered as its own trust root, run against a '
            'completed artifact without altering.'
        ),
        accepted_proof_kinds=('.json',),
        scope_limits=(
            (
                'Record reason: "Detached artifact signatures only. Bootc update trust and '
                'negative update tests remain untested."'
            ),
            (
                'docs/TESTING.md: installer.payload-rejection is separate from detached '
                'artifact-signature and update tests.'
            ),
            (
                "docs/BUILD.md: the target's container policy still rejects all sources; do not "
                'weaken the policy to make an update test pass.'
            ),
        ),
        sourced_from='runtime:evidence/signature.reject.json, environment.description',
    )
)
