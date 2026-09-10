from __future__ import annotations

from apex.attestation import catalogue
from apex.kernel import claims, identifiers
from apex.registry import descriptors

CHECK = catalogue.declare(
    descriptors.CheckSpec(
        id=identifiers.CheckId('display.oled-hdmi'),
        group='hardware',
        environment=claims.EnvironmentKind.PHYSICAL,
        summary=(
            'Establishes that the internal OLED panel renders correctly at 175% and 200% scaling '
            'under Wayland, XWayland and Flatpak, and that HDMI output works, using real-panel '
            'screenshots.'
        ),
        accepted_proof_kinds=('.json', '.png', '.txt'),
        scope_limits=(
            (
                'KNOWN-ISSUES.md, "Supply chain and desktop": the candidate\'s clean VM review '
                'of GTK3, libadwaita and Shell surfaces was at 1280x800, and "Fractional.'
            ),
            (
                'The passing VM check `desktop.theme-surfaces` is a separate id in the vm group '
                'and does not carry over to the physical panel.'
            ),
            (
                'TESTING.md, "VM acceptance": "The virtual display uses virtio-vga without host '
                'GPU forwarding or host GL access", so no VM screenshot can attest this.'
            ),
        ),
        sourced_from=(
            'docs/TESTING.md, "Physical acceptance" bullets 4 and 5 ("NVIDIA offload, HDMI ..."'
        ),
    )
)
