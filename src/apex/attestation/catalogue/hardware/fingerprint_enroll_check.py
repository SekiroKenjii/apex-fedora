from __future__ import annotations

from apex.attestation import catalogue
from apex.kernel import claims, identifiers
from apex.registry import descriptors

CHECK = catalogue.declare(
    descriptors.CheckSpec(
        id=identifiers.CheckId('fingerprint.enroll'),
        group='hardware',
        environment=claims.EnvironmentKind.PHYSICAL,
        summary=(
            'Establishes that a finger enrolls and verifies on the physical ELAN sensor, '
            'including cancel and re-enrol, with actual Claim and Release ownership traced '
            'through the failure path.'
        ),
        accepted_proof_kinds=('.json', '.log', '.png', '.txt'),
        scope_limits=(
            (
                'Record\'s environment.description: "Prior user report that enrollment says the '
                'device is already claimed by another process; no current candidate.'
            ),
            (
                'FINGERPRINT.md, "Physical reproduction on Ubuntu, September 9": the two '
                '`enroll-stage-passed` events "are progress events, not completed enrollment.'
            ),
            (
                'FINGERPRINT.md: "An observed failure reports a protocol error during identify- '
                'for-enroll, followed by Claim denials. These are different layers ...'
            ),
        ),
        sourced_from=(
            'runtime:evidence/fingerprint.enroll.json, fields "reason" ("Trace actual '
            'Claim/Release ownership and validate enrollment and cleanup on the real senso'
        ),
    )
)
