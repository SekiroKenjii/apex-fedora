from __future__ import annotations

from apex.attestation import catalogue
from apex.kernel import claims, identifiers
from apex.registry import descriptors

CHECK = catalogue.declare(
    descriptors.CheckSpec(
        id=identifiers.CheckId('boot.tty-rescue'),
        group='vm',
        environment=claims.EnvironmentKind.VM,
        summary=(
            'After a fallback boot an operator can switch to a login TTY, see the password '
            'prompt, authenticate normally and run a command through password sudo.'
        ),
        accepted_proof_kinds=('.json', '.log', '.png', '.txt', '.xml'),
        scope_limits=(
            (
                'docs/RECOVERY-TESTS.md: "SSH success or an existing root rescue shell does not '
                'satisfy password TTY acceptance."'
            ),
            (
                'docs/RECOVERY-TESTS.md: prompt and result screenshots and authentication '
                'records are kept private.'
            ),
            (
                'docs/TESTING.md: the serial-console channel "uses an existing root rescue '
                'session; it does not change PAM or add a login method to the release.'
            ),
        ),
        sourced_from=(
            'docs/RECOVERY-TESTS.md "Test TTY independently: switch to a login TTY, inspect the '
            'password prompt, authenticate normally and run a command through pa'
        ),
    )
)
