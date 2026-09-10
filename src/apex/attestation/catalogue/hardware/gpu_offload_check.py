from __future__ import annotations

from apex.attestation import catalogue
from apex.kernel import claims, identifiers
from apex.registry import descriptors

CHECK = catalogue.declare(
    descriptors.CheckSpec(
        id=identifiers.CheckId('gpu.offload'),
        group='hardware',
        environment=claims.EnvironmentKind.PHYSICAL,
        summary=(
            'Establishes that a single application renders on the NVIDIA GPU through per- '
            'application PRIME offload on the real machine while AMD keeps driving the display.'
        ),
        accepted_proof_kinds=('.json', '.log', '.png', '.txt'),
        scope_limits=(
            (
                'NVIDIA.md, "Per-application offload": `apex-gpu run` "does not change GNOME\'s '
                'environment, Xorg configuration or the display GPU", and "Flatpak.'
            ),
            (
                'NVIDIA.md, "Next image-integration step": "A VM without hardware passthrough '
                'cannot pass these hardware cases", and "Then run VM boot/regression.'
            ),
            (
                'NVIDIA.md, "Build the RPM set": "A successful `rpm-build` result leaves image '
                'integration, initramfs, Secure Boot and hardware checks `NOT TESTED`."'
            ),
        ),
        sourced_from=(
            'docs/TESTING.md, "Physical acceptance" bullet 4 ("NVIDIA offload, HDMI and return '
            'to runtime suspend")'
        ),
    )
)
