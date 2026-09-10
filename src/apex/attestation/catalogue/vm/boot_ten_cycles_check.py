from __future__ import annotations

from apex.attestation import catalogue
from apex.kernel import claims, identifiers
from apex.registry import descriptors

CHECK = catalogue.declare(
    descriptors.CheckSpec(
        id=identifiers.CheckId('boot.ten-cycles'),
        group='vm',
        environment=claims.EnvironmentKind.VM,
        summary=(
            'Ten offline boots of the frozen private QCOW2 each reach password login, a new '
            'Wayland session, Overview keyboard input and visibly rendered GTK4 pixels.'
        ),
        accepted_proof_kinds=('.json', '.png', '.xml'),
        scope_limits=(
            (
                'Record\'s reason: "Normal boots only; no claim of failed-deployment recovery or '
                'physical hardware acceptance."'
            ),
            (
                'docs/TESTING.md: a running GDM unit does not prove password login, a Wayland '
                'session or a drawn window; a window-presented log alone does not pass.'
            ),
            (
                'docs/TESTING.md: the test account and boot-argument differences are not a test '
                'of an untouched first boot or the installer user workflow.'
            ),
        ),
        sourced_from='runtime:evidence/boot.ten-cycles.json, environment.description and reason',
    )
)
