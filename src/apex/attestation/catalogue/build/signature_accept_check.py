from __future__ import annotations

from apex.attestation import catalogue
from apex.kernel import claims, identifiers
from apex.registry import descriptors

CHECK = catalogue.declare(
    descriptors.CheckSpec(
        id=identifiers.CheckId('signature.accept'),
        group='build',
        environment=claims.EnvironmentKind.BUILD,
        summary=(
            'Establishes that the detached artifact signature over a completed OCI and QCOW2 '
            'bundle verifies against a development public key that was retrieved and checked '
            'independently of the artifact directory.'
        ),
        accepted_proof_kinds=('.json',),
        scope_limits=(
            (
                'Record reason: "Detached artifact signatures only. Bootc update trust and '
                'negative update tests remain untested."'
            ),
            (
                'docs/BUILD.md: "This is development signing"; the exported public key is for '
                'out-of-band review, not automatic trust establishment, and a matching.'
            ),
            (
                'docs/BUILD.md: signed OCI update acceptance must be demonstrated separately '
                'inside a booted guest.'
            ),
        ),
        sourced_from='runtime:evidence/signature.accept.json, environment.description',
    )
)
