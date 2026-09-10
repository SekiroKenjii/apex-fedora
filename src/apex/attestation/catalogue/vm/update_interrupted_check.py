from __future__ import annotations

from apex.attestation import catalogue
from apex.kernel import claims, identifiers
from apex.registry import descriptors

CHECK = catalogue.declare(
    descriptors.CheckSpec(
        id=identifiers.CheckId('update.interrupted'),
        group='vm',
        environment=claims.EnvironmentKind.VM,
        summary=(
            'An update download that is interrupted fails on a fresh fault overlay without losing '
            'user data, and rollback still works afterwards.'
        ),
        accepted_proof_kinds=('.json', '.log', '.png', '.ppm', '.txt', '.xml'),
        scope_limits=(
            (
                'docs/TESTING.md calls it an interrupted download while docs/UPDATES.md calls '
                'it an interrupted update; the two wordings are not reconciled anywhere.'
            ),
            'Deferred in docs/BACKLOG.md until the final candidate and isolated disks are ready.',
            'No runner action exists for it in tools/update-vm.py.',
        ),
        sourced_from='docs/TESTING.md required-case line "interrupted download"',
    )
)
