from __future__ import annotations

from apex.attestation import catalogue
from apex.kernel import claims, identifiers
from apex.registry import descriptors

CHECK = catalogue.declare(
    descriptors.CheckSpec(
        id=identifiers.CheckId('boot.pre-userspace-failure'),
        group='vm',
        environment=claims.EnvironmentKind.VM,
        summary=(
            'When a boot fails before userspace starts, the saved GRUB state, the failure count '
            'and whether a manual power cycle is required are established.'
        ),
        accepted_proof_kinds=('.json', '.log', '.png', '.ppm', '.txt', '.xml'),
        scope_limits=(
            (
                'docs/INITRAMFS-TESTS.md: saved grubenv after the failures held boot_success=0, '
                'the expected B digest and fallback=1 but no boot_counter, and "The.'
            ),
            'docs/RECOVERY.md: greenboot\'s "userspace checks cannot recover every kernel hang."',
            (
                'docs/BOOT-DIAGNOSTICS.md: the watchdog settings observed "do not prove an '
                'early-panic reset path or its timing."'
            ),
        ),
        sourced_from=(
            'docs/BACKLOG.md deferred row "Pre-userspace failure policy and rescue menu | '
            'Isolated fixture is available | Saved GRUB state, failure count and expli'
        ),
    )
)
