from __future__ import annotations

from apex.attestation import catalogue
from apex.kernel import claims, identifiers
from apex.registry import descriptors

CHECK = catalogue.declare(
    descriptors.CheckSpec(
        id=identifiers.CheckId('git.private-stage'),
        group='git',
        environment=claims.EnvironmentKind.BUILD,
        summary=(
            'Staged content, not the working tree, is inspected before a commit is created, so '
            'private or local-only paths, renamed local-only documents, symlinks, submodules, '
            'opaque binaries and secret material.'
        ),
        accepted_proof_kinds=('.json', '.xml'),
        scope_limits=(
            (
                'The record explicitly states no external push was performed '
                '(runtime:evidence/git.private-stage.json, reason).'
            ),
            (
                'The claim about the local-only pointer is about its current state: AGENTS.md '
                'remains unstaged and not ignored, not that it can never be staged (same.'
            ),
            (
                'CONTRIBUTING.md: hooks are local safety checks, not server-side access '
                'control, and must not be bypassed.'
            ),
        ),
        sourced_from=(
            'runtime:candidate-history/4a24fbbec73d49ca9e7604cf9e965419/evidence/git.private- '
            'stage.json, environment.description ("Local Git fixtures test staged b'
        ),
    )
)
