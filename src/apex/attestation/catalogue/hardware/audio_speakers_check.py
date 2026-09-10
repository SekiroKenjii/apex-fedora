from __future__ import annotations

from apex.attestation import catalogue
from apex.kernel import claims, identifiers
from apex.registry import descriptors

CHECK = catalogue.declare(
    descriptors.CheckSpec(
        id=identifiers.CheckId('audio.speakers'),
        group='hardware',
        environment=claims.EnvironmentKind.PHYSICAL,
        summary=(
            'Establishes that the built-in left and right speakers produce audible low-volume '
            'output on a clean cold boot of the candidate, from a source-level fix rather than a '
            'runtime hda-verb workaround.'
        ),
        accepted_proof_kinds=('.json', '.log', '.txt'),
        scope_limits=(
            (
                'Record\'s environment.description: "Prior user report of ALC294 speaker failure '
                'on this laptop; this candidate has not been tested on hardware".'
            ),
            (
                'HARDWARE-TRACE.md, "Audio baseline": "A visible sink, unmuted controls and a '
                'valid route do not establish speaker output."'
            ),
            (
                'AUDIO.md, "Next evidence": the September 9 snapshot showing node 0x14 unmuted, '
                'routed to DAC 0x02 with EAPD 0x2 does "not prove that the external.'
            ),
        ),
        sourced_from=(
            'runtime:evidence/audio.speakers.json, fields "reason" ("Reproduce on a clean cold '
            'boot and validate a source-level fix without runtime hda-verb workar'
        ),
    )
)
