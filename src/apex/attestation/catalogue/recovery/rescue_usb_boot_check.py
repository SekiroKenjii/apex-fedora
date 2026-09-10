from __future__ import annotations

from apex.attestation import catalogue
from apex.kernel import claims, identifiers
from apex.registry import descriptors

CHECK = catalogue.declare(
    descriptors.CheckSpec(
        id=identifiers.CheckId('rescue.usb-boot'),
        group='recovery',
        environment=claims.EnvironmentKind.PHYSICAL,
        summary=(
            'The Ubuntu rescue ISO boots on the actual M7400QC with working input and display, '
            'and the backup destination is reachable from that rescue session.'
        ),
        accepted_proof_kinds=('.json', '.log', '.png', '.txt'),
        scope_limits=(
            (
                'docs/RECOVERY.md, "Verify the rescue ISO": checksum and detached-signature '
                'verification is recorded separately from physical rescue boot, and "does.'
            ),
            (
                'docs/VENTOY.md (September 9 results): the virtual Ventoy fixture "establishes '
                'virtual rescue boot and shell access, not physical rescue acceptance or.'
            ),
            (
                "docs/VENTOY.md: Secure Boot, backup restoration and the physical USB's "
                'installed Ventoy version are kept as separate checks.'
            ),
        ),
        sourced_from=(
            'docs/RECOVERY.md, section "Before the first installation", numbered step 3 '
            '(verbatim: "Boot the Ubuntu rescue ISO on the actual M7400QC and confirm in'
        ),
    )
)
