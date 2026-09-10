from __future__ import annotations

from apex.attestation import catalogue
from apex.kernel import claims, identifiers
from apex.registry import descriptors

CHECK = catalogue.declare(
    descriptors.CheckSpec(
        id=identifiers.CheckId('fingerprint.reboot'),
        group='hardware',
        environment=claims.EnvironmentKind.PHYSICAL,
        summary=(
            'Establishes that enrolled fingerprints still verify after a reboot of the physical '
            'machine.'
        ),
        accepted_proof_kinds=('.json', '.log', '.txt'),
        scope_limits=(
            (
                'The source is two words in an enumerating bullet ("reboot verification"); no '
                'document elaborates what persistence is being checked, so the summary.'
            ),
            (
                'TESTING.md, "Physical acceptance": biometric state must be kept "outside Git, '
                'with biometric state encrypted", and evidence.py refuses any proof that.'
            ),
            'No record exists for this id.',
        ),
        sourced_from=(
            'docs/TESTING.md, "Physical acceptance" bullet 3: "Fingerprint enroll, verify, '
            'cancel, enroll again, lock/unlock and reboot verification."'
        ),
    )
)
