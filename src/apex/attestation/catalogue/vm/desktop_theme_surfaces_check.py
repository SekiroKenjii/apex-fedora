from __future__ import annotations

from apex.attestation import catalogue
from apex.kernel import claims, identifiers
from apex.registry import descriptors

CHECK = catalogue.declare(
    descriptors.CheckSpec(
        id=identifiers.CheckId('desktop.theme-surfaces'),
        group='vm',
        environment=claims.EnvironmentKind.VM,
        summary=(
            'GTK3 controls, libadwaita controls and an open Quick Settings Shell surface render '
            'with visible window backgrounds at 1280x800 on a fresh QCOW2, reviewed from retained '
            'screenshots.'
        ),
        accepted_proof_kinds=('.json', '.png', '.xml'),
        scope_limits=(
            (
                'Record\'s reason: "Physical OLED, fractional scaling, XWayland, Flatpak and '
                'final design remain untested."'
            ),
            (
                'docs/TESTING.md: "Color bars alone can pass even when the surrounding theme is '
                'broken" and "The runner does not turn a screenshot capture into a.'
            ),
            (
                'Superseded FAIL record desktop.theme-surfaces-1cda1732...json shows a '
                'recovered diagnostic session after Skip "is not clean acceptance".'
            ),
        ),
        sourced_from=(
            'runtime:evidence/desktop.theme-surfaces.json, environment.description and reason'
        ),
    )
)
