from __future__ import annotations

from apex.attestation import catalogue
from apex.kernel import claims, identifiers
from apex.registry import descriptors

CHECK = catalogue.declare(
    descriptors.CheckSpec(
        id=identifiers.CheckId('suspend.ten-cycles'),
        group='hardware',
        environment=claims.EnvironmentKind.PHYSICAL,
        summary=(
            'Establishes that the machine completes ten suspend and resume cycles on the real '
            'hardware, on both battery and AC power.'
        ),
        accepted_proof_kinds=('.json', '.log', '.txt'),
        scope_limits=(
            (
                'The source bullet names only the cycle count and the two power sources; it '
                'does not say which subsystems must be re-checked after each resume.'
            ),
            "No record exists for this id, so nothing here is the operator's own recorded wording.",
        ),
        sourced_from=(
            'docs/TESTING.md, section "Physical acceptance", first bullet: "Three cold boots '
            'and ten suspend/resume cycles, with battery and AC power."'
        ),
    )
)
