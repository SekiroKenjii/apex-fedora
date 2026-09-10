from __future__ import annotations

from apex.attestation import catalogue
from apex.kernel import claims, identifiers
from apex.registry import descriptors

CHECK = catalogue.declare(
    descriptors.CheckSpec(
        id=identifiers.CheckId('live.ventoy'),
        group='vm',
        environment=claims.EnvironmentKind.VM,
        summary=(
            'The unchanged signed ISO boots through Ventoy 1.1.17 in normal mode on emulated USB '
            'media, reaches a visible Wayland application, and leaves the internal fixture disks '
            'protected.'
        ),
        accepted_proof_kinds=('.json', '.png'),
        scope_limits=(
            (
                "The stored record says only 'vm'; the v1 vocabulary has four environment kinds "
                'and does not distinguish live vm.'
            ),
            (
                'Record\'s reason: "Physical rescue, Secure Boot and unresolved boot warnings '
                'remain separate."'
            ),
            (
                'Record\'s environment.description: "no host hardware"; docs/VENTOY.md, the '
                'virtual test "does not establish rescue boot on the ASUS laptop" and.'
            ),
            (
                'docs/BACKLOG.md: Ventoy startup messages and Ubuntu live shutdown behavior '
                'must be revisited before physical rescue acceptance.'
            ),
        ),
        sourced_from='runtime:evidence/live.ventoy.json, environment.description and reason',
    )
)
