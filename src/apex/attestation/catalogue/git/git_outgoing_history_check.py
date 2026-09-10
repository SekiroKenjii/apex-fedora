from __future__ import annotations

from apex.attestation import catalogue
from apex.kernel import claims, identifiers
from apex.registry import descriptors

CHECK = catalogue.declare(
    descriptors.CheckSpec(
        id=identifiers.CheckId('git.outgoing-history'),
        group='git',
        environment=claims.EnvironmentKind.BUILD,
        summary=(
            'Every commit a push would send has its subject and its full tree re-checked, so a '
            'private file deleted in a later commit, a commit body or a co-author trailer '
            'anywhere in outgoing history still.'
        ),
        accepted_proof_kinds=('.json', '.xml'),
        scope_limits=(
            (
                "No push to any external remote was performed; the record's own "
                'environment.description is "Full local history audit; no push" and the proof '
                'artifact.'
            ),
            (
                'The push path is exercised only against a temporary bare repository on disk, '
                'with no network destination (CONTRIBUTING.md.'
            ),
            (
                'The audit covers commits reachable from the current local HEAD at the time of '
                'the record (32 commits at head 1bede3f in the current proof artifact).'
            ),
        ),
        sourced_from=(
            'runtime:candidate-history/4a24fbbec73d49ca9e7604cf9e965419/evidence/git.outgoing- '
            'history.json, environment.description ("Local Git fixtures reject pri'
        ),
    )
)
