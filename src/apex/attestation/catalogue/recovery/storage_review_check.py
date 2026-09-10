from __future__ import annotations

from apex.attestation import catalogue
from apex.kernel import claims, identifiers
from apex.registry import descriptors

CHECK = catalogue.declare(
    descriptors.CheckSpec(
        id=identifiers.CheckId('storage.review'),
        group='recovery',
        environment=claims.EnvironmentKind.OPERATOR,
        summary=(
            'Test and runtime data is held where the recovery plan requires: logs on a separate '
            'USB data partition, fingerprint state encrypted, and no persistence of the whole '
            'live root filesystem.'
        ),
        accepted_proof_kinds=('.json', '.log', '.txt'),
        scope_limits=(
            'docs/LIVE.md: "The guard is configured to make USB storage read-only.',
            (
                'docs/RECOVERY.md, "Verify the rescue ISO": "Do not store this evidence on the '
                'USB without a separate operator decision to write there." Reviewing the.'
            ),
            (
                'tools/apexlib/evidence.py rejects proof outside .txt/.log/.json/.png/.ppm/.xml '
                'with "never store biometric templates", so the encrypted fingerprint.'
            ),
        ),
        sourced_from=(
            'docs/RECOVERY.md, "Before the first installation", step 5 (verbatim: "Store logs '
            'on a separate USB data partition. Keep fingerprint state encrypted. D'
        ),
    )
)
