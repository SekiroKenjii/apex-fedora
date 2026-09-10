from __future__ import annotations

from apex.attestation import catalogue
from apex.kernel import claims, identifiers
from apex.registry import descriptors

CHECK = catalogue.declare(
    descriptors.CheckSpec(
        id=identifiers.CheckId('boot.initramfs-failure'),
        group='vm',
        environment=claims.EnvironmentKind.VM,
        summary=(
            'A deployment whose initramfs is deliberately corrupted fails to unpack and panics '
            'while mounting root before userspace, and what happens next is observed and '
            'classified with the fault bound to the.'
        ),
        accepted_proof_kinds=('.json', '.log', '.png', '.ppm', '.txt', '.xml'),
        scope_limits=(
            (
                'docs/INITRAMFS-TESTS.md: the existing run "covers initial fault reproduction '
                'and first manual rescue only"; automatic recovery did not complete in.'
            ),
            (
                'docs/INITRAMFS-TESTS.md: OSTree retargeted the shared bootlinks after rollback '
                'so the fault moved onto A; that is "a defect in the shared-boot-path.'
            ),
            (
                'docs/INITRAMFS-TESTS.md: "Require actual unpacking or root-mount failure '
                'evidence before classifying an early-boot fault.'
            ),
        ),
        sourced_from=(
            'docs/INITRAMFS-TESTS.md, "Prepare the fault" (the 4 KiB truncated initramfs copy '
            'with an invalid header, referenced only by B\'s initrd field) and "Sep'
        ),
    )
)
