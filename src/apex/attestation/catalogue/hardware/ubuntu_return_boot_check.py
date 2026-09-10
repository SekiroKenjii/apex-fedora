from __future__ import annotations

from apex.attestation import catalogue
from apex.kernel import claims, identifiers
from apex.registry import descriptors

CHECK = catalogue.declare(
    descriptors.CheckSpec(
        id=identifiers.CheckId('ubuntu.return-boot'),
        group='hardware',
        environment=claims.EnvironmentKind.PHYSICAL,
        summary=(
            'Establishes that the machine boots back into the existing Ubuntu installation after '
            'each physical trial, with its filesystems and boot configuration intact.'
        ),
        accepted_proof_kinds=('.json', '.log', '.png', '.txt'),
        scope_limits=(
            (
                'RECOVERY.md, "Failed update after Apex is installed": "`bootc rollback` '
                "selects the previous deployment's boot entry."
            ),
            (
                'RECOVERY.md, opening: "Do not replace the working system while any '
                'installation gate is incomplete." This check attests the return to Ubuntu '
                'after.'
            ),
            (
                'LIVE.md: "Physical acceptance remains untested", and the live disk-protection '
                'guard "is experimental and must not be trusted on the internal disk.'
            ),
        ),
        sourced_from=(
            'docs/TESTING.md, "Physical acceptance" bullet 6: "Return to Ubuntu after each '
            'trial with its filesystems and boot configuration intact."'
        ),
    )
)
