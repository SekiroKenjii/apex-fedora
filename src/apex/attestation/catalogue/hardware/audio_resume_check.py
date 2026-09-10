from __future__ import annotations

from apex.attestation import catalogue
from apex.kernel import claims, identifiers
from apex.registry import descriptors

CHECK = catalogue.declare(
    descriptors.CheckSpec(
        id=identifiers.CheckId('audio.resume'),
        group='hardware',
        environment=claims.EnvironmentKind.PHYSICAL,
        summary=(
            'Establishes that audio still works at low volume after suspend and resume on the '
            'candidate, covering codec re-initialization and register-cache restore rather than a '
            'single playback attempt after.'
        ),
        accepted_proof_kinds=('.json', '.log', '.txt'),
        scope_limits=(
            (
                'AUDIO.md, "Initialization and resume": "A proposed fix must account for this '
                'order and for runtime power management, not merely make one playback.'
            ),
            (
                'KNOWN-ISSUES.md, "Audio: BLOCKED": "Speaker output and resume remain untested '
                'on Apex."'
            ),
            (
                'TESTING.md, "Physical acceptance": "No runtime codec workaround" applies to '
                'the whole audio bullet, so a post-resume hda-verb replay does not satisfy.'
            ),
        ),
        sourced_from='docs/TESTING.md, "Physical acceptance" bullet 2 ("post-resume audio")',
    )
)
