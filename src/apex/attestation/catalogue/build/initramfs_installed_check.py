from __future__ import annotations

from apex.attestation import catalogue
from apex.kernel import claims, identifiers
from apex.registry import descriptors

CHECK = catalogue.declare(
    descriptors.CheckSpec(
        id=identifiers.CheckId('initramfs.installed'),
        group='build',
        environment=claims.EnvironmentKind.BUILD_CONTAINER,
        summary=(
            "Establishes that the installed image keeps Fedora's initramfs for its single kernel, "
            'that the file is non-empty and hashed, and that its lsinitrd listing shows ostree '
            'support.'
        ),
        accepted_proof_kinds=('.json', '.log', '.txt'),
        scope_limits=(
            (
                'guest/image-configure.sh: the control profile does not change kernel, modules '
                'or early-boot configuration, so this establishes preservation, not a.'
            ),
            (
                'docs/BOOT-DIAGNOSTICS.md, "Mixed compression in the installed initramfs": the '
                'layout analysis "does not replace testing the installed boot path or an.'
            ),
            (
                'verify-image.py records boot: NOT TESTED and hardware: NOT TESTED alongside '
                'these static checks.'
            ),
        ),
        sourced_from='guest/image-configure.sh lines 45-48 (comment',
    )
)
