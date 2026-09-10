from __future__ import annotations

from apex.attestation import catalogue
from apex.kernel import claims, identifiers
from apex.registry import descriptors

CHECK = catalogue.declare(
    descriptors.CheckSpec(
        id=identifiers.CheckId('installer.other-disks'),
        group='vm',
        environment=claims.EnvironmentKind.VM,
        summary=(
            'A completed offline installation onto the 48 GiB target leaves the separate 4 GiB '
            'GPT fixture disk with its EFI, NTFS and ext4 partitions identical across the full '
            'guest-visible comparison, and the.'
        ),
        accepted_proof_kinds=('.json', '.png'),
        scope_limits=(
            (
                "The stored record says only 'vm'; the v1 vocabulary has four environment kinds "
                'and does not distinguish installer vm.'
            ),
            (
                'Record\'s reason: "Fixture partitions contain sentinels, not bootable '
                'Windows/Ubuntu."'
            ),
            (
                'docs/TESTING.md: "Merely seeing the correct disk name in the installer is '
                'insufficient"; QEMU enumeration can place the other disk at /dev/vda, so.'
            ),
        ),
        sourced_from=(
            'runtime:evidence/installer.other-disks.json, environment.description and reason'
        ),
    )
)
