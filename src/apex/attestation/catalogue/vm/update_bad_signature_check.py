from __future__ import annotations

from apex.attestation import catalogue
from apex.kernel import claims, identifiers
from apex.registry import descriptors

CHECK = catalogue.declare(
    descriptors.CheckSpec(
        id=identifiers.CheckId('update.bad-signature'),
        group='vm',
        environment=claims.EnvironmentKind.VM,
        summary=(
            'The bootc consumer rejects a wrong-key image and an unsigned image with a policy- '
            'specific error and leaves deployment state unchanged, each in its own fresh overlay.'
        ),
        accepted_proof_kinds=('.json', '.log', '.png', '.ppm', '.txt', '.xml'),
        scope_limits=(
            (
                'docs/UPDATES.md: "A connection error or missing file cannot pass. The helper '
                'refuses a second fault in the same run."'
            ),
            (
                'docs/UPDATES.md: bootc 1.16.10 prints a nonfatal unsupported-dir lookup '
                'diagnostic before both imports and rejections; "Do not use that lookup.'
            ),
            (
                'docs/TESTING.md: the eight-case installer signature fixture "does not approve '
                'the Apex installer or update path", so installer trust results cannot.'
            ),
        ),
        sourced_from=(
            'docs/UPDATES.md "Verification used by bootc" section and step 3, "Run wrong-key, '
            'unsigned and untrusted in their own overlays. Each requires a policy-'
        ),
    )
)
