from __future__ import annotations

from apex.attestation import catalogue
from apex.kernel import claims, identifiers
from apex.registry import descriptors

CHECK = catalogue.declare(
    descriptors.CheckSpec(
        id=identifiers.CheckId('input.webcam-touchpad-fn'),
        group='hardware',
        environment=claims.EnvironmentKind.PHYSICAL,
        summary=(
            'Establishes that the webcam, touchpad and Fn keys work on the physical machine.'
        ),
        accepted_proof_kinds=('.json', '.log', '.png', '.ppm', '.txt', '.xml'),
        scope_limits=(
            'The only source is three component names inside one comma-separated bullet.',
            (
                'Nothing in the docs narrows the accepted proof kinds for this check, so the '
                'full set allowed by tools/apexlib/evidence.py is listed unchanged.'
            ),
            'No record exists for this id.',
        ),
        sourced_from=(
            'docs/TESTING.md, "Physical acceptance" bullet 5: "OLED at 175% and 200%, Wayland, '
            'XWayland, Flatpak, Wi-Fi, Bluetooth, webcam, touchpad and Fn keys."'
        ),
    )
)
