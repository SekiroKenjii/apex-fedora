from __future__ import annotations

from apex.attestation import catalogue
from apex.kernel import claims, identifiers
from apex.registry import descriptors

CHECK = catalogue.declare(
    descriptors.CheckSpec(
        id=identifiers.CheckId('git.commit-policy'),
        group='git',
        environment=claims.EnvironmentKind.BUILD,
        summary=(
            'A commit message must be one Conventional Commit subject of at most 72 characters, '
            'and the commit-msg hook rejects unknown types, multi-line messages, bodies and co- '
            'author trailers.'
        ),
        accepted_proof_kinds=('.json', '.xml'),
        scope_limits=(
            (
                'The record explicitly states no external push was performed '
                '(runtime:evidence/git.commit-policy.json, reason; history record reason "No '
                'external.'
            ),
            (
                'CONTRIBUTING.md: hooks are local safety checks, not server-side access '
                'control; the check establishes local hook behaviour, not enforcement on a.'
            ),
            (
                'The evidence is from disposable local repositories with fixture Git identity '
                "and configuration isolated from the contributor's settings."
            ),
        ),
        sourced_from=(
            'runtime:candidate-history/4a24fbbec73d49ca9e7604cf9e965419/evidence/git.commit- '
            'policy.json, environment.description ("Local Git fixtures validate the'
        ),
    )
)
