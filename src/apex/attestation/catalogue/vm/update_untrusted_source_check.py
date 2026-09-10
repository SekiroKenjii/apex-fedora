from __future__ import annotations

from apex.attestation import catalogue
from apex.kernel import claims, identifiers
from apex.registry import descriptors

CHECK = catalogue.declare(
    descriptors.CheckSpec(
        id=identifiers.CheckId('update.untrusted-source'),
        group='vm',
        environment=claims.EnvironmentKind.VM,
        summary=(
            "An image offered from a source outside the policy's permitted scopes is refused by "
            'the rejecting default, with bootc deployment state unchanged.'
        ),
        accepted_proof_kinds=('.json', '.log', '.png', '.ppm', '.txt', '.xml'),
        scope_limits=(
            (
                'docs/UPDATES.md: requires a policy-specific error and unchanged deployment '
                'state; a connection error or missing file cannot pass.'
            ),
            (
                'docs/UPDATES.md: "Neither a key supplied by an untrusted payload nor a '
                'detached archive signature establishes production update trust."'
            ),
            (
                'The offline dir transport does not exercise registry TLS, credentials, network '
                'delivery or remote signature discovery.'
            ),
        ),
        sourced_from=(
            'docs/UPDATES.md "The separate untrusted-source path has no exception to the '
            'rejecting default." and step 3'
        ),
    )
)
