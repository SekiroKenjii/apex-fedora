from __future__ import annotations

from apex.attestation import catalogue
from apex.kernel import claims, identifiers
from apex.registry import descriptors

CHECK = catalogue.declare(
    descriptors.CheckSpec(
        id=identifiers.CheckId('boot.log-review'),
        group='vm',
        environment=claims.EnvironmentKind.VM,
        summary=(
            'Kernel journals, warnings and retained serial output across the ten boots and the '
            'Ventoy boot are reviewed, and the review currently holds the release blocked on '
            'unresolved clocksource and watchdog.'
        ),
        accepted_proof_kinds=('.json', '.log'),
        scope_limits=(
            'Record\'s reason: "Desktop startup does not establish harmlessness."',
            (
                'History record: "Zero observed Oops/panic does not demonstrate fallback or '
                'timer expiry."'
            ),
            (
                'docs/BOOT-DIAGNOSTICS.md: the watchdog message text alone cannot distinguish a '
                'failed stop from a missing magic-close character, and reading sysfs.'
            ),
        ),
        sourced_from=(
            'runtime:evidence/boot.log-review.json, environment.description and reason, plus '
            'its two superseded records in evidence/history/'
        ),
    )
)
