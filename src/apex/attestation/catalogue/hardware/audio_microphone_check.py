from __future__ import annotations

from apex.attestation import catalogue
from apex.kernel import claims, identifiers
from apex.registry import descriptors

CHECK = catalogue.declare(
    descriptors.CheckSpec(
        id=identifiers.CheckId('audio.microphone'),
        group='hardware',
        environment=claims.EnvironmentKind.PHYSICAL,
        summary=(
            'Establishes that the internal microphone captures audio on the candidate on real '
            'hardware, without a runtime codec workaround.'
        ),
        accepted_proof_kinds=('.json', '.log', '.txt'),
        scope_limits=(
            (
                'The source is one enumerating bullet; it names the microphone as a physical '
                'acceptance item but says nothing about the criterion beyond "No runtime.'
            ),
            (
                'AUDIO.md, "ASUS fixups and this board": the observed firmware pin defaults '
                'place the microphone at 0x12, which differs from the inspected ASUS.'
            ),
            (
                'TESTING.md, "Tool tests": `just hardware-snapshot` "does not enroll a finger, '
                'activate fprintd, play audio or write codec registers" and "does not.'
            ),
        ),
        sourced_from=(
            'docs/TESTING.md, section "Physical acceptance", bullet 2: "Low-volume left/right '
            'speakers, microphone, headphone jack, mute and post-resume audio. No'
        ),
    )
)
