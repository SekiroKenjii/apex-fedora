from __future__ import annotations

from apex.attestation import catalogue
from apex.kernel import claims, identifiers
from apex.registry import descriptors

CHECK = catalogue.declare(
    descriptors.CheckSpec(
        id=identifiers.CheckId('initramfs.live'),
        group='build',
        environment=claims.EnvironmentKind.BUILD_CONTAINER,
        summary=(
            'Establishes that the live derivative regenerates its initramfs for its single kernel '
            'with dmsquash-live, the auto-overlay and the apexprotect module, and that the apex- '
            'live-disk-guard rule appears in.'
        ),
        accepted_proof_kinds=('.json', '.txt'),
        scope_limits=(
            (
                'docs/LIVE.md: the guard\'s unit tests "do not establish kernel enforcement or '
                'live boot acceptance"; presence in the initramfs is not boot behaviour.'
            ),
            (
                'docs/LIVE.md: the live initramfs is intentionally different from the installed '
                'one, so this establishes nothing about installed-boot parity.'
            ),
            (
                'docs/LIVE.md: physical acceptance remains untested; live.direct, live.ventoy '
                'and live.disk-protection are separate checks.'
            ),
        ),
        sourced_from=(
            'live/configure.sh lines 17-21 (dracut --force --zstd --reproducible --no-hostonly '
            "--omit ostree --add 'dmsquash-live dmsquash-live-autooverlay apexpro"
        ),
    )
)
