from __future__ import annotations

from apex.attestation import catalogue
from apex.kernel import claims, identifiers
from apex.registry import descriptors

CHECK = catalogue.declare(
    descriptors.CheckSpec(
        id=identifiers.CheckId('live.direct'),
        group='vm',
        environment=claims.EnvironmentKind.VM,
        summary=(
            'The signed live ISO boots directly on UEFI with no NIC, reaches a Wayland session '
            'with a rendered Ptyxis window, and denies writes to the attached fixture disks.'
        ),
        accepted_proof_kinds=('.json', '.png'),
        scope_limits=(
            (
                "The stored record says only 'vm'; the v1 vocabulary has four environment kinds "
                'and does not distinguish live vm.'
            ),
            'Record\'s reason: "full protection and Ventoy acceptance remain separate."',
            (
                'docs/LIVE.md: "Physical acceptance remains untested" and "A correctly signed '
                'ISO can still fail to boot"; repeat affected tests when the ISO changes.'
            ),
            (
                'Superseded records show two earlier FAILs and one BLOCKED for this same id, so '
                'the result is tied to this exact ISO.'
            ),
        ),
        sourced_from='runtime:evidence/live.direct.json, environment.description and reason',
    )
)
