from __future__ import annotations

from apex.attestation import catalogue
from apex.kernel import claims, identifiers
from apex.registry import descriptors

CHECK = catalogue.declare(
    descriptors.CheckSpec(
        id=identifiers.CheckId('boot.root-failure'),
        group='vm',
        environment=claims.EnvironmentKind.VM,
        summary=(
            'A failure of the mounted-root condition in the installed required health check is '
            'treated as a failed boot and drives the same greenboot rollback path.'
        ),
        accepted_proof_kinds=('.json', '.log', '.png', '.ppm', '.txt', '.xml'),
        scope_limits=(
            (
                'The id boot.root-failure appears only in config/checks.json and in golden '
                "output; binding it to the health check's findmnt condition is my inference."
            ),
            (
                'A root-mount failure that happens before userspace belongs to boot.pre- '
                'userspace-failure, not here; docs/INITRAMFS-TESTS.md keeps those results.'
            ),
            'docs/ARCHITECTURE.md: "Configuration is not proof of recovery."',
        ),
        sourced_from=(
            'system_files/usr/lib/greenboot/check/required.d/20-apex-system.sh line `findmnt '
            '--mountpoint / >/dev/null`'
        ),
    )
)
