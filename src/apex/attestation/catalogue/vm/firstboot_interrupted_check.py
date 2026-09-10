from __future__ import annotations

from apex.attestation import catalogue
from apex.kernel import claims, identifiers
from apex.registry import descriptors

CHECK = catalogue.declare(
    descriptors.CheckSpec(
        id=identifiers.CheckId('firstboot.interrupted'),
        group='vm',
        environment=claims.EnvironmentKind.VM,
        summary=(
            'A first boot that is interrupted still reaches GDM afterwards, and optional '
            'application downloads do not block it.'
        ),
        accepted_proof_kinds=('.json', '.log', '.png', '.ppm', '.txt', '.xml'),
        scope_limits=(
            (
                'The required-case line names the case and its GDM criterion but no document '
                'defines what is interrupted, at which point, or what else must hold.'
            ),
            'No evidence record, no runner and no image unit exist for this case.',
            (
                'This is the thinnest entry in the group; treat the mechanism as unspecified '
                'rather than assumed.'
            ),
        ),
        sourced_from=(
            'docs/TESTING.md, required-case list, line "Offline and interrupted firstboot. '
            'Optional app downloads must not block GDM."'
        ),
    )
)
