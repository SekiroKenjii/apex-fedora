from __future__ import annotations

from apex.attestation import catalogue
from apex.kernel import claims, identifiers
from apex.registry import descriptors

CHECK = catalogue.declare(
    descriptors.CheckSpec(
        id=identifiers.CheckId('update.disk-full'),
        group='vm',
        environment=claims.EnvironmentKind.VM,
        summary=(
            'An update that runs out of disk space fails on a fresh fault overlay without losing '
            'user data, and rollback still works afterwards.'
        ),
        accepted_proof_kinds=('.json', '.log', '.png', '.ppm', '.txt', '.xml'),
        scope_limits=(
            (
                'docs/BACKLOG.md lists this as deferred, resumed only "when Final candidate and '
                'isolated disks are ready"; deferral "does not approve installation or.'
            ),
            (
                'No runner action exists for it in tools/update-vm.py; only provision, '
                'switch-a, forward, rollback, wrong-key, unsigned, untrusted, check-a and.'
            ),
            (
                'The pass criteria come from the BACKLOG completion-evidence column, not from a '
                'written procedure.'
            ),
        ),
        sourced_from=(
            'docs/TESTING.md required-case line "Invalid signatures, untrusted sources, full '
            'disk, interrupted download and simulated power loss."'
        ),
    )
)
