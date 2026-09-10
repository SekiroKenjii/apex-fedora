from __future__ import annotations

from apex.attestation import catalogue
from apex.kernel import claims, identifiers
from apex.registry import descriptors

CHECK = catalogue.declare(
    descriptors.CheckSpec(
        id=identifiers.CheckId('boot.dbus-failure'),
        group='vm',
        environment=claims.EnvironmentKind.VM,
        summary=(
            'A failure of the system D-Bus, one of the conditions in the installed required '
            'health check, is treated as a failed boot and drives the same greenboot rollback '
            'path.'
        ),
        accepted_proof_kinds=('.json', '.log', '.png', '.ppm', '.txt', '.xml'),
        scope_limits=(
            (
                'The id boot.dbus-failure appears only in config/checks.json and in golden '
                "output; binding it to the health check's busctl condition is my inference."
            ),
            (
                'docs/ARCHITECTURE.md: "Configuration is not proof of recovery." Audio, network '
                'and fingerprint failures are deliberately not reboot triggers.'
            ),
            (
                'docs/BACKLOG.md defers required-service faults until the final candidate and '
                'isolated disks are ready.'
            ),
        ),
        sourced_from=(
            'system_files/usr/lib/greenboot/check/required.d/20-apex-system.sh line `timeout 15 '
            'busctl --system list >/dev/null`'
        ),
    )
)
