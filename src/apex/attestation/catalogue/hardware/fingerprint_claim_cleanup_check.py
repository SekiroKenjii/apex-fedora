from __future__ import annotations

from apex.attestation import catalogue
from apex.kernel import claims, identifiers
from apex.registry import descriptors

CHECK = catalogue.declare(
    descriptors.CheckSpec(
        id=identifiers.CheckId('fingerprint.claim-cleanup'),
        group='hardware',
        environment=claims.EnvironmentKind.PHYSICAL,
        summary=(
            "Establishes that the physical sensor's D-Bus claim is actually released after a "
            'protocol error or cancellation so a later Claim succeeds, tested independently '
            'through GNOME Settings and through the.'
        ),
        accepted_proof_kinds=('.json', '.log', '.txt'),
        scope_limits=(
            (
                'TESTING.md, "Physical acceptance": `just test-fingerprint` results are '
                'recorded "only as `fingerprint.virtual-cleanup`, separately from the physical.'
            ),
            (
                'HARDWARE-TRACE.md, "Capture fingerprint ownership": "`OBSERVED` means metadata '
                'was captured, not a test pass"; "Client disconnect alone does not.'
            ),
            (
                'FINGERPRINT.md, "Physical reproduction on Ubuntu, September 9": "Daemon '
                'sessions changed between the attempts, so the second successful Claim is not.'
            ),
        ),
        sourced_from=(
            'docs/TESTING.md, "Physical acceptance" bullet 3 ("Test GUI and CLI claim cleanup '
            'independently.") and the "Physical acceptance" paragraph naming "the'
        ),
    )
)
