from __future__ import annotations

from apex.attestation import catalogue
from apex.kernel import claims, identifiers
from apex.registry import descriptors

CHECK = catalogue.declare(
    descriptors.CheckSpec(
        id=identifiers.CheckId('installer.payload-rejection'),
        group='vm',
        environment=claims.EnvironmentKind.VM,
        summary=(
            'The production Anaconda guard rejects six ISO-level payload faults, missing '
            'signature, altered signature, wrong key, changed manifest, corrupt blob and '
            'unexpected source, before any storage change.'
        ),
        accepted_proof_kinds=('.json',),
        scope_limits=(
            (
                "The stored record says only 'vm'; the v1 vocabulary has four environment kinds "
                'and does not distinguish installer vm.'
            ),
            (
                'Proof "scope": "Six diagnostic offline VM boots of the signed installer; no '
                'physical hardware or update acceptance".'
            ),
            (
                'docs/TESTING.md: each fault must be injected before Anaconda starts; running '
                'the guard again after a normal installer startup is "only a diagnostic.'
            ),
            (
                'docs/TESTING.md: "Unit tests and the builder\'s synthetic Skopeo fixture do not '
                'satisfy this gate."'
            ),
        ),
        sourced_from=(
            'runtime:evidence/installer.payload-rejection.json environment.description (its '
            'reason field is empty) plus its proof file 6-installer-payload-rejectio'
        ),
    )
)
