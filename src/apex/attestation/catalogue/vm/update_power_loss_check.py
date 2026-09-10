from __future__ import annotations

from apex.attestation import catalogue
from apex.kernel import claims, identifiers
from apex.registry import descriptors

CHECK = catalogue.declare(
    descriptors.CheckSpec(
        id=identifiers.CheckId('update.power-loss'),
        group='vm',
        environment=claims.EnvironmentKind.VM,
        summary=(
            'A disposable test guest killed part way through an update is resumed from the same '
            'disk and its state after that loss of guest execution is recorded.'
        ),
        accepted_proof_kinds=('.json', '.log', '.png', '.ppm', '.txt', '.xml'),
        scope_limits=(
            (
                'docs/TESTING.md: "This models loss of guest execution and RAM, not loss of the '
                'physical drive\'s write cache. Keep that distinction in results."'
            ),
            (
                'docs/TESTING.md: "The command records the injection but does not declare crash '
                'recovery successful."'
            ),
            (
                'tools/apexlib/vm.py records host_rebooted false and '
                'simulates_physical_storage_power_loss false in power-loss.json.'
            ),
        ),
        sourced_from=(
            'docs/TESTING.md "python3 tools/apex.py test-power-loss terminates only an owned '
            'disposable test VM, using a PID handle" and "just test-resume-installe'
        ),
    )
)
