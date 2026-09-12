"""The installed recovery configuration, compared with the image's own assembly."""

from __future__ import annotations

from apex.kernel import claims, identifiers
from apex.verification import probes, probing

probes.declare(
    probing.ProbeCase(
        unit=identifiers.ProbeId("recovery.installed"),
        environment=claims.EnvironmentKind.VM,
        summary=(
            "The booted deployment is the expected candidate, the installed GRUB file is "
            "bootupd's assembly of the image's fragments, the retry configuration hashes to "
            "the built fixture, and SELinux enforces; the host supplies both digests."
        ),
        arguments={"expected_digest": "", "config_sha256": ""},
    )
)
