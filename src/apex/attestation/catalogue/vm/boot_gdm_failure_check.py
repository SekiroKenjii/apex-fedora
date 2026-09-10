from __future__ import annotations

from apex.attestation import catalogue
from apex.kernel import claims, identifiers
from apex.registry import descriptors

CHECK = catalogue.declare(
    descriptors.CheckSpec(
        id=identifiers.CheckId('boot.gdm-failure'),
        group='vm',
        environment=claims.EnvironmentKind.VM,
        summary=(
            'When GDM fails on the updated deployment, the installed required health check '
            'rejects the boot and greenboot automatically returns the machine to the known-good '
            'deployment within the configured.'
        ),
        accepted_proof_kinds=('.json', '.log', '.png', '.ppm', '.txt', '.xml'),
        scope_limits=(
            (
                'docs/RECOVERY-TESTS.md: the evaluator "rejects a three-failure result even if '
                'rollback succeeds"; three failures yield FAIL and missing observations.'
            ),
            (
                'docs/RECOVERY-TESTS.md: the one-retry preset "does not prove a two-attempt '
                'bound for hangs before userspace or for a health-check process that cannot.'
            ),
            (
                'docs/RECOVERY-TESTS.md: the September 9 pass belongs to signed fixtures A and '
                'B and is "not acceptance results for the unchanged frozen candidate."'
            ),
        ),
        sourced_from=(
            'docs/RECOVERY-TESTS.md "The fault helper adds an ExecStartPre that exits 42 only '
            "when the booted digest is B. GDM itself fails, and the image's unchan"
        ),
    )
)
