from __future__ import annotations

from apex.attestation import catalogue
from apex.kernel import claims, identifiers
from apex.registry import descriptors

CHECK = catalogue.declare(
    descriptors.CheckSpec(
        id=identifiers.CheckId('update.rollback'),
        group='vm',
        environment=claims.EnvironmentKind.VM,
        summary=(
            'Requesting the previous deployment returns the guest, after a separate reboot with '
            'networking still restricted, to the earlier image with password login, Wayland, a '
            'rendered window and preserved user.'
        ),
        accepted_proof_kinds=('.json', '.log', '.png', '.ppm', '.txt', '.xml'),
        scope_limits=(
            'docs/UPDATES.md: "Manual rollback does not establish the two-failure GRUB fallback."',
            'docs/UPDATES.md: a successful rollback request does not prove the next boot succeeds.',
            'September 9 fixture results are not assigned to the frozen candidate.',
        ),
        sourced_from=(
            'docs/UPDATES.md step 4, "rollback requests the previous A deployment without '
            'rebooting automatically. Reboot separately and run check-a again with net'
        ),
    )
)
