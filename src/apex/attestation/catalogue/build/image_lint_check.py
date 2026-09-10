from __future__ import annotations

from apex.attestation import catalogue
from apex.kernel import claims, identifiers
from apex.registry import descriptors

CHECK = catalogue.declare(
    descriptors.CheckSpec(
        id=identifiers.CheckId('image.lint'),
        group='build',
        environment=claims.EnvironmentKind.BUILD,
        summary=(
            'Establishes that the built bootc container passes bootc container lint with fatal '
            'warnings in the isolated Fedora builder, where 13 checks passed and one upstream '
            'check was skipped rather than passed.'
        ),
        accepted_proof_kinds=('.json', '.log'),
        scope_limits=(
            'The upstream skip is explicitly not counted as a passed check (record reason).',
            'Lint of the container only; it does not establish that the image boots.',
        ),
        sourced_from='runtime:evidence/image.lint.json, environment.description',
    )
)
