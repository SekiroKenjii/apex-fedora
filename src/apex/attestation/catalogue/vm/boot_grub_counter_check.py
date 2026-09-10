from __future__ import annotations

from apex.attestation import catalogue
from apex.kernel import claims, identifiers
from apex.registry import descriptors

CHECK = catalogue.declare(
    descriptors.CheckSpec(
        id=identifiers.CheckId('boot.grub-counter'),
        group='vm',
        environment=claims.EnvironmentKind.VM,
        summary=(
            "GRUB's boot-attempt counter persists across boots on the installed candidate and "
            'enforces the configured attempt limit, which the current record cannot yet show '
            "because the candidate's packaged."
        ),
        accepted_proof_kinds=('.json',),
        scope_limits=(
            (
                'Record\'s reason: "future recipe correction needs a new image and actual GRUB '
                'persistence/failure tests"; the stored proof is a read-only probe and a.'
            ),
            (
                'docs/UPDATES.md: the installed /boot/grub2/grub.cfg retained the old joined '
                "boot_success### END token after update and rollback, and bootupd's."
            ),
            (
                'docs/RECOVERY-TESTS.md: greenboot 0.16.4 initializes the counter only after '
                'the first failed health check, so GREENBOOT_MAX_BOOT_ATTEMPTS=2 permits.'
            ),
        ),
        sourced_from='runtime:evidence/boot.grub-counter.json, environment.description and reason',
    )
)
