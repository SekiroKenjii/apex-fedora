from __future__ import annotations

from apex.attestation import catalogue
from apex.kernel import claims, identifiers
from apex.registry import descriptors

CHECK = catalogue.declare(
    descriptors.CheckSpec(
        id=identifiers.CheckId('firstboot.offline'),
        group='vm',
        environment=claims.EnvironmentKind.VM,
        summary=(
            'An untouched first boot with no network reaches GDM, and optional application '
            'downloads do not block it.'
        ),
        accepted_proof_kinds=('.json', '.log', '.png', '.ppm', '.txt', '.xml'),
        scope_limits=(
            (
                "docs/TESTING.md: the integration runner's test account and boot-argument "
                'differences "do not count as a test of an untouched first boot or the.'
            ),
            (
                'docs/ARCHITECTURE.md: offline app provisioning and the Lotus package "remain '
                'separate work", so what the optional downloads are is not yet fixed.'
            ),
            (
                'No evidence record and no runner exists; the criterion is stated only as one '
                'required-case line.'
            ),
        ),
        sourced_from=(
            'docs/TESTING.md, "Each fault case starts from a new virtual disk or overlay. '
            'Required cases include:" list, line "Offline and interrupted firstboot. O'
        ),
    )
)
