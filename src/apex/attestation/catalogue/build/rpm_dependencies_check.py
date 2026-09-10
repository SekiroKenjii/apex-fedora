from __future__ import annotations

from apex.attestation import catalogue
from apex.kernel import claims, identifiers
from apex.registry import descriptors

CHECK = catalogue.declare(
    descriptors.CheckSpec(
        id=identifiers.CheckId('rpm.dependencies'),
        group='build',
        environment=claims.EnvironmentKind.BUILD,
        summary=(
            'Establishes that the four custom RPMs rebuilt in Mock install into the image and '
            'that dnf5 check resolves every dependency in the resulting container.'
        ),
        accepted_proof_kinds=('.json', '.log', '.txt'),
        scope_limits=(
            (
                '"hardware behavior is separate" (record reason): successful dependency '
                'resolution makes no hardware claim.'
            ),
            (
                'docs/ARCHITECTURE.md: a driver package is not accepted merely because its '
                'installation succeeds.'
            ),
        ),
        sourced_from=(
            'runtime:evidence/rpm.dependencies.json, environment.description ("Four Mock '
            'rebuilds followed by image installation and dnf5 check") and reason'
        ),
    )
)
