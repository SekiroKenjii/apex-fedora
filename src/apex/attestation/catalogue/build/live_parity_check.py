from __future__ import annotations

from apex.attestation import catalogue
from apex.kernel import claims, identifiers
from apex.registry import descriptors

CHECK = catalogue.declare(
    descriptors.CheckSpec(
        id=identifiers.CheckId('live.parity'),
        group='build',
        environment=claims.EnvironmentKind.BUILD,
        summary=(
            "Establishes that the live derivative's installed RPM set differs from the frozen "
            'target in no kernel, kmod, akmod, NVIDIA, firmware, ALSA, PipeWire, WirePlumber, '
            'libfprint, fprintd, GNOME, Mutter.'
        ),
        accepted_proof_kinds=('.json', '.txt'),
        scope_limits=(
            (
                'guest/live-parity.py returns kernel_binary_parity: "NOT TESTED" in every '
                'result; package-name/EVR parity is not binary parity.'
            ),
            (
                'docs/LIVE.md: the file comparisons exclude the intentionally different '
                'initramfs and "do not cover the missing NVIDIA stack, full firmware contents.'
            ),
            'Non-protected package differences are reported but do not fail the check.',
        ),
        sourced_from=(
            'guest/live-parity.py, the PROTECTED tuple and compare() which fails on any '
            'protected or firmware difference'
        ),
    )
)
