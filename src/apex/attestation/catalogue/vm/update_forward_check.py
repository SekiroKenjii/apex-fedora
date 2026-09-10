from __future__ import annotations

from apex.attestation import catalogue
from apex.kernel import claims, identifiers
from apex.registry import descriptors

CHECK = catalogue.declare(
    descriptors.CheckSpec(
        id=identifiers.CheckId('update.forward'),
        group='vm',
        environment=claims.EnvironmentKind.VM,
        summary=(
            'The installed guest stages the next signed image through the policy-enforced bootc '
            'consumer, and after a separate reboot the new deployment reaches the expected '
            'digest, password login, Wayland, a.'
        ),
        accepted_proof_kinds=('.json', '.log', '.png', '.ppm', '.txt', '.xml'),
        scope_limits=(
            (
                'docs/UPDATES.md: "A successful stage or rollback request does not prove that '
                'the next boot succeeds.'
            ),
            (
                'docs/UPDATES.md: the offline dir transport "does not test registry TLS, '
                'credentials, network delivery, remote signature discovery or production-key.'
            ),
            (
                'docs/UPDATES.md: "The frozen candidate\'s checks were not reassigned to the '
                'fixture digests, nor were fixture results assigned back to the candidate.".'
            ),
        ),
        sourced_from=(
            'docs/UPDATES.md "Run one operation at a time" steps 2 and 4 and the "September 9 '
            'results" section'
        ),
    )
)
