from __future__ import annotations

from apex.attestation import catalogue
from apex.kernel import claims, identifiers
from apex.registry import descriptors

CHECK = catalogue.declare(
    descriptors.CheckSpec(
        id=identifiers.CheckId('backup.off-device'),
        group='recovery',
        environment=claims.EnvironmentKind.OPERATOR,
        summary=(
            'Personal data, the partition layout and EFI information are saved outside the '
            'internal disk, and the saved copy is verified as readable.'
        ),
        accepted_proof_kinds=('.json', '.log', '.txt'),
        scope_limits=(
            'docs/RECOVERY.md: ISO verification "does not prove ...',
            (
                'docs/RECOVERY.md: restoration is a separate check; a saved and readable backup '
                'does not establish that restoring from it works.'
            ),
            'docs/RECOVERY.md: "A USB holding two ISOs is still one physical device.',
        ),
        sourced_from=(
            'docs/RECOVERY.md, "Before the first installation", step 4, first sentence ("Save '
            'personal data, partition layout and EFI information outside the inter'
        ),
    )
)
