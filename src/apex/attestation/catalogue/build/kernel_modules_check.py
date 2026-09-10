from __future__ import annotations

from apex.attestation import catalogue
from apex.kernel import claims, identifiers
from apex.registry import descriptors

CHECK = catalogue.declare(
    descriptors.CheckSpec(
        id=identifiers.CheckId('kernel.modules'),
        group='build',
        environment=claims.EnvironmentKind.BUILD_CONTAINER,
        summary=(
            'Establishes that the image carries exactly one installed kernel with a vmlinuz, and '
            'that amdgpu, snd_hda_intel, nvme, usb_storage, virtio_blk and dm_crypt are either '
            'built into that kernel or resolve.'
        ),
        accepted_proof_kinds=('.json', '.log', '.txt'),
        scope_limits=(
            (
                'verify-image.py docstring: "Static image checks, separate from boot and '
                'hardware acceptance"; its own output records boot: NOT TESTED and hardware.'
            ),
            (
                'docs/ARCHITECTURE.md: vermagic, firmware, module loading, HDMI and runtime '
                'suspension require separate checks, so a matching vermagic is not a claim.'
            ),
            (
                'docs/ARCHITECTURE.md: later optimisation must keep storage, encryption, USB, '
                'VM and rescue support that may not appear in lsmod.'
            ),
        ),
        sourced_from=(
            'guest/verify-image.py, main(): the single-kernel assertion, the module tuple '
            "('amdgpu', 'snd_hda_intel', 'nvme', 'usb_storage', 'virtio_blk', 'dm_cryp"
        ),
    )
)
