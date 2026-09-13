"""Every build input as one rendered set, named where the generated tree keeps it.

The names are the paths under `generated/os/`; each carries the path of the handwritten
file it must equal while that file still ships, which is the gate the generator passes
before the build reads from the generated tree instead.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable

from apex.generating import imageinputs, installerinputs, liveinputs
from apex.model import release
from apex.targeting.releases import fedora44_release

DIRECTORY = "generated/os"


@dataclasses.dataclass(frozen=True, slots=True)
class Output:
    name: str
    handwritten: str
    render: Callable[[release.ReleaseProfile], str]


OUTPUTS = (
    Output("Containerfile", "Containerfile", lambda _: imageinputs.containerfile()),
    Output("image-configure.sh", "guest/image-configure.sh", imageinputs.configure),
    Output("installer-configure.sh", "guest/installer-configure.sh", installerinputs.configure),
    Output(
        "assemble-live-squashfs.sh",
        "guest/assemble-live-squashfs.sh",
        lambda _: liveinputs.assemble(),
    ),
    Output("live/Containerfile", "live/Containerfile", lambda _: liveinputs.containerfile()),
    Output("live/configure.sh", "live/configure.sh", liveinputs.configure),
)


def rendered(profile: release.ReleaseProfile = fedora44_release.PROFILE) -> dict[str, bytes]:
    return {output.name: output.render(profile).encode() for output in OUTPUTS}
