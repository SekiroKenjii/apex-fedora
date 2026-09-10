from __future__ import annotations

from apex.attestation import catalogue
from apex.kernel import claims, identifiers
from apex.registry import descriptors

CHECK = catalogue.declare(
    descriptors.CheckSpec(
        id=identifiers.CheckId('installer.offline'),
        group='vm',
        environment=claims.EnvironmentKind.VM,
        summary=(
            'An offline UEFI installation completes with a manually created password '
            'administrator, and after the ISO is removed the installed system reaches password '
            'GDM login, Wayland, a rendered Ptyxis window.'
        ),
        accepted_proof_kinds=('.json', '.png'),
        scope_limits=(
            (
                "The stored record says only 'vm'; the v1 vocabulary has four environment kinds "
                'and does not distinguish installer vm.'
            ),
            (
                'Record\'s reason: "Does not approve physical installation, recovery or negative '
                'payload cases."'
            ),
            (
                'docs/TESTING.md: test-account and boot-argument differences "do not count as a '
                'test of an untouched first boot or the installer user workflow" (that.'
            ),
            (
                'Superseded record installer.offline-779be139...json: earlier ISO results "do '
                'not approve this changed installer", so a payload change invalidates the.'
            ),
        ),
        sourced_from='runtime:evidence/installer.offline.json, environment.description and reason',
    )
)
