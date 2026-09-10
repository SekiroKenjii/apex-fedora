from __future__ import annotations

from apex.attestation import catalogue
from apex.kernel import claims, identifiers
from apex.registry import descriptors

CHECK = catalogue.declare(
    descriptors.CheckSpec(
        id=identifiers.CheckId('fingerprint.lock-unlock'),
        group='hardware',
        environment=claims.EnvironmentKind.PHYSICAL,
        summary=(
            'Establishes that an enrolled fingerprint unlocks the screen on the physical machine, '
            'with password login and password administration still available.'
        ),
        accepted_proof_kinds=('.json', '.log', '.png', '.txt'),
        scope_limits=(
            (
                'The source is one clause in an enumerating bullet; nothing in the docs '
                'elaborates the lock/unlock criterion further.'
            ),
            (
                'FINGERPRINT.md, "Virtual-device regression tests": "Physical ELAN behavior, '
                'GNOME Settings, GDM/PAM and suspend still need their own evidence."'
            ),
            (
                'FINGERPRINT.md: "Test GNOME Settings and the command-line client separately '
                'before involving GDM or PAM", so this check sits downstream of enroll and.'
            ),
        ),
        sourced_from=(
            'docs/TESTING.md, "Physical acceptance" bullet 3 ("... lock/unlock and reboot '
            'verification")'
        ),
    )
)
