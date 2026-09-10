from __future__ import annotations

from apex.attestation import catalogue
from apex.kernel import claims, identifiers
from apex.registry import descriptors

CHECK = catalogue.declare(
    descriptors.CheckSpec(
        id=identifiers.CheckId('desktop.password-wayland'),
        group='vm',
        environment=claims.EnvironmentKind.VM,
        summary=(
            'GDM password login succeeds on an independent fresh overlay and a Wayland '
            'application is visibly rendered in the resulting session.'
        ),
        accepted_proof_kinds=('.json', '.png', '.xml'),
        scope_limits=(
            (
                'Record\'s reason: "Disposable test account; not the installer user-creation '
                'workflow."'
            ),
            (
                'docs/TESTING.md: an application launched through SSH cannot replace the QMP '
                'keyboard input check.'
            ),
        ),
        sourced_from=(
            'runtime:evidence/desktop.password-wayland.json, environment.description and '
            'reason.'
        ),
    )
)
