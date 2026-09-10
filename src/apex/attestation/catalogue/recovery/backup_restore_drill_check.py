from __future__ import annotations

from apex.attestation import catalogue
from apex.kernel import claims, identifiers
from apex.registry import descriptors

CHECK = catalogue.declare(
    descriptors.CheckSpec(
        id=identifiers.CheckId('backup.restore-drill'),
        group='recovery',
        environment=claims.EnvironmentKind.OPERATOR,
        summary=(
            'The verified backup is actually restored to a safe destination in a rehearsal, so '
            'restoration is known to work before the internal disk is touched.'
        ),
        accepted_proof_kinds=('.json', '.log', '.txt'),
        scope_limits=(
            (
                'docs/RECOVERY.md, "No working deployment": "Restoration can overwrite data, so '
                'confirm its source and destination before proceeding." The drill goes.'
            ),
            'docs/RECOVERY.md: "`bootc rollback` selects the previous deployment\'s boot entry.',
            (
                'docs/RECOVERY.md: "There is no previous Apex deployment during the first '
                'installation.'
            ),
        ),
        sourced_from=(
            'docs/RECOVERY.md, "Before the first installation", step 4, second sentence '
            '("perform a restore drill to a safe destination"). Corroborated by the oper'
        ),
    )
)
