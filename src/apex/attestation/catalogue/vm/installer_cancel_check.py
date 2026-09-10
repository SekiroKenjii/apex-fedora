from __future__ import annotations

from apex.attestation import catalogue
from apex.kernel import claims, identifiers
from apex.registry import descriptors

CHECK = catalogue.declare(
    descriptors.CheckSpec(
        id=identifiers.CheckId('installer.cancel'),
        group='vm',
        environment=claims.EnvironmentKind.VM,
        summary=(
            'Quitting the installer after selecting only the target disk and a pending Standard '
            'Partition layout, before installation starts, leaves both attached virtual disks '
            'unchanged under complete comparison.'
        ),
        accepted_proof_kinds=('.json', '.png'),
        scope_limits=(
            (
                "The stored record says only 'vm'; the v1 vocabulary has four environment kinds "
                'and does not distinguish installer vm.'
            ),
            (
                "Record's reason notes a guest reset was observed and the VM was stopped before "
                'the next boot; no claim is made about the boot that would follow.'
            ),
            (
                'Comparison covers only the two attached file-backed overlays; docs/TESTING.md '
                'forbids attaching any physical device.'
            ),
            (
                'Superseded record installer.cancel-0492196b...json: earlier ISO results do not '
                'approve a changed installer payload.'
            ),
        ),
        sourced_from='runtime:evidence/installer.cancel.json, environment.description and reason',
    )
)
