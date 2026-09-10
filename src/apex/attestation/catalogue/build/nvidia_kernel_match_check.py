from __future__ import annotations

from apex.attestation import catalogue
from apex.kernel import claims, identifiers
from apex.registry import descriptors

CHECK = catalogue.declare(
    descriptors.CheckSpec(
        id=identifiers.CheckId('nvidia.kernel-match'),
        group='build',
        environment=claims.EnvironmentKind.BUILD,
        summary=(
            'Establishes that NVIDIA kernel modules and their matching userspace packages, built '
            "for the candidate's own kernel, are present in the candidate's package inventory."
        ),
        accepted_proof_kinds=('.txt',),
        scope_limits=(
            (
                'Record is explicitly "not a hardware test" (candidate-history description); it '
                'is a package inventory check, not GPU behaviour.'
            ),
            (
                'docs/NVIDIA.md: a successful rpm-build result leaves image integration, '
                'initramfs, Secure Boot and hardware checks NOT TESTED, and does not select a.'
            ),
            (
                'docs/NVIDIA.md: module signing and the Secure Boot trust path remain '
                'unresolved; RPM, OCI and kernel module signatures cover different boundaries.'
            ),
        ),
        sourced_from=(
            'runtime:evidence/nvidia.kernel-match.json, environment.description ("Fedora kernel '
            'control image inventory") and reason ("Matching NVIDIA kernel and u'
        ),
    )
)
