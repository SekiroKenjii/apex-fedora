from __future__ import annotations

from apex.attestation import catalogue
from apex.kernel import claims, identifiers
from apex.registry import descriptors

CHECK = catalogue.declare(
    descriptors.CheckSpec(
        id=identifiers.CheckId('live.disk-protection'),
        group='vm',
        environment=claims.EnvironmentKind.VM,
        summary=(
            "The live image's initramfs guard sets every discovered internal disk read-only and "
            'latches any failure, covering fixed devices, USB hotplug after udev settle, the '
            'early pre-mount latch and a.'
        ),
        accepted_proof_kinds=('.json', '.png'),
        scope_limits=(
            (
                "The stored record says only 'vm'; the v1 vocabulary has four environment kinds "
                'and does not distinguish live vm.'
            ),
            'Record\'s reason: "Physical and Ventoy checks remain separate."',
            (
                'Record\'s environment.description: "no host devices; one VM at a time"; '
                'docs/TESTING.md forbids attaching a physical block device.'
            ),
            (
                'docs/LIVE.md: results are bound to this ISO, "Repeat affected tests when the '
                'ISO changes; retain the empty optical drive."'
            ),
        ),
        sourced_from=(
            'runtime:evidence/live.disk-protection.json, environment.description and reason'
        ),
    )
)
