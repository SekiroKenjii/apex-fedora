from __future__ import annotations

from apex.attestation import catalogue
from apex.kernel import claims, identifiers
from apex.registry import descriptors

CHECK = catalogue.declare(
    descriptors.CheckSpec(
        id=identifiers.CheckId('installation.operator-approval'),
        group='recovery',
        environment=claims.EnvironmentKind.OPERATOR,
        summary=(
            'The operator has confirmed the target partition diagram, including EFI, /boot and '
            'root, and has given a separate decision to write the internal disk.'
        ),
        accepted_proof_kinds=('.json', '.png', '.txt'),
        scope_limits=(
            (
                'docs/RECOVERY.md, opening: "Do not replace the working system while any '
                'installation gate is incomplete." Approval is one gate among several and does.'
            ),
            (
                'docs/RECOVERY.md, "Verify the rescue ISO": the decision to write the USB is a '
                'distinct operator decision from the decision to write the internal.'
            ),
            (
                'docs/BACKLOG.md: "USB rescue boot, backup restoration, audio/fingerprint '
                'acceptance and permission to write the internal disk remain mandatory before.'
            ),
        ),
        sourced_from=(
            'docs/RECOVERY.md, "Before the first installation", step 6 (verbatim: "Confirm the '
            'target partition diagram, including EFI, /boot and root, with the op'
        ),
    )
)
