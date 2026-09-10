from __future__ import annotations

from apex.attestation import catalogue
from apex.kernel import claims, identifiers
from apex.registry import descriptors

CHECK = catalogue.declare(
    descriptors.CheckSpec(
        id=identifiers.CheckId('gpu.runtime-suspend'),
        group='hardware',
        environment=claims.EnvironmentKind.PHYSICAL,
        summary=(
            'Establishes that the discrete GPU returns to runtime suspend after the offloaded '
            'application is closed, observed without repeatedly querying NVIDIA management tools '
            'during the sleep measurement.'
        ),
        accepted_proof_kinds=('.json', '.log', '.txt'),
        scope_limits=(
            'NVIDIA.md, "Per-application offload": `apex-gpu status` "reads PCI sysfs attributes.',
            (
                'NVIDIA.md, "Next image-integration step": vendor modprobe/udev/dracut/suspend '
                'configuration "presence is not approval to enable a persistence daemon.'
            ),
            (
                'TESTING.md pairs this with an idle-power concern; the sleep measurement is '
                'disturbed by the act of polling, so a polled reading is not acceptable.'
            ),
        ),
        sourced_from=(
            'docs/TESTING.md, "Physical acceptance" bullet 4 ("... return to runtime suspend. '
            'Do not continuously poll nvidia-smi during a sleep measurement.")'
        ),
    )
)
