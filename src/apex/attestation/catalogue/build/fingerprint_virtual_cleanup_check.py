from __future__ import annotations

from apex.attestation import catalogue
from apex.kernel import claims, identifiers
from apex.registry import descriptors

CHECK = catalogue.declare(
    descriptors.CheckSpec(
        id=identifiers.CheckId('fingerprint.virtual-cleanup'),
        group='build',
        environment=claims.EnvironmentKind.BUILD,
        summary=(
            'Establishes that fprintd releases a claimed virtual device after an explicit stop or '
            'release and after client disconnect following a protocol error, and refuses a second '
            'claim while the first client.'
        ),
        accepted_proof_kinds=('.json', '.log', '.txt'),
        scope_limits=(
            'Record description: "no physical sensor test".',
            (
                'docs/FINGERPRINT.md: "Even a complete pass covers only the fake-device daemon '
                'contract.'
            ),
            (
                'docs/FINGERPRINT.md: "This run does not reproduce or resolve the physical ELAN '
                'failure."'
            ),
        ),
        sourced_from='runtime:evidence/fingerprint.virtual-cleanup.json, environment.description',
    )
)
