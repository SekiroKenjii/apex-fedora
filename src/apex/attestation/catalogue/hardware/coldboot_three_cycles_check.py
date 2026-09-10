from __future__ import annotations

from apex.attestation import catalogue
from apex.kernel import claims, identifiers
from apex.registry import descriptors

CHECK = catalogue.declare(
    descriptors.CheckSpec(
        id=identifiers.CheckId('coldboot.three-cycles'),
        group='hardware',
        environment=claims.EnvironmentKind.PHYSICAL,
        summary=(
            'Establishes that the candidate completes three full cold boots on the real machine, '
            'on both battery and AC power, with the operator recording an actual power-down '
            'rather than a restart.'
        ),
        accepted_proof_kinds=('.json', '.log', '.txt'),
        scope_limits=(
            (
                'HARDWARE-TRACE.md, "Audio baseline": "Kernel uptime cannot distinguish a cold '
                'boot from a restart", so the power state is an operator statement, not.'
            ),
            (
                'HARDWARE-TRACE.md: "A clean cold-boot trial requires an agreed time and '
                'operator action."'
            ),
            (
                'TESTING.md, "Physical acceptance": the whole group is gated on "Only proceed '
                'once VM results justify a live trial", and no VM boot result substitutes.'
            ),
        ),
        sourced_from=(
            'docs/TESTING.md, section "Physical acceptance", first bullet: "Three cold boots '
            'and ten suspend/resume cycles, with battery and AC power." Cold-boot p'
        ),
    )
)
