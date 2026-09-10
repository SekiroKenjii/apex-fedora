from __future__ import annotations

from apex.attestation import catalogue
from apex.kernel import claims, identifiers
from apex.registry import descriptors

CHECK = catalogue.declare(
    descriptors.CheckSpec(
        id=identifiers.CheckId('sources.locked'),
        group='build',
        environment=claims.EnvironmentKind.BUILD,
        summary=(
            'Establishes that every build input, including the base image, the image-builder '
            'container, source commits and downloaded archives, is pinned by digest or SHA-256 in '
            'config/sources.lock.json so the.'
        ),
        accepted_proof_kinds=('.json', '.txt'),
        scope_limits=(
            (
                'Record reason: complete RPM repository snapshots and buildroot locks are still '
                'missing.'
            ),
            (
                'docs/BUILD.md: "The current pipeline does not claim bit-for-bit '
                'reproducibility"; package lists document what was installed but are not a '
                'repository.'
            ),
            (
                'runtime:candidate- '
                'history/4a24fbbec73d49ca9e7604cf9e965419/evidence/sources.locked.json: NVIDIA '
                'and CachyOS source locks are also incomplete.'
            ),
        ),
        sourced_from=(
            'runtime:evidence/sources.locked.json, environment.description ("Current source '
            'pins and resolved package inventory") and reason'
        ),
    )
)
