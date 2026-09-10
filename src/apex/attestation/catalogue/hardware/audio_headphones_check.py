from __future__ import annotations

from apex.attestation import catalogue
from apex.kernel import claims, identifiers
from apex.registry import descriptors

CHECK = catalogue.declare(
    descriptors.CheckSpec(
        id=identifiers.CheckId('audio.headphones'),
        group='hardware',
        environment=claims.EnvironmentKind.PHYSICAL,
        summary=(
            'Establishes that the headphone jack outputs audio and that muting behaves correctly '
            'on the candidate on real hardware, without a runtime codec workaround.'
        ),
        accepted_proof_kinds=('.json', '.log', '.txt'),
        scope_limits=(
            'The checklist item "mute" is not a separate id in config/checks.json.',
            (
                'HARDWARE-TRACE.md, "Audio baseline": the operator must "State whether ordinary '
                'audio is audible through the built-in speakers, headphones or.'
            ),
            'No record exists for this id.',
        ),
        sourced_from=(
            'docs/TESTING.md, section "Physical acceptance", bullet 2: "Low-volume left/right '
            'speakers, microphone, headphone jack, mute and post-resume audio. No'
        ),
    )
)
