"""The generator reproduces what ships, byte for byte, and re-rendering changes nothing.

Gate G8: every generated build input equals the handwritten file it replaces for as long
as that file ships, and the frozen tree under `generated/os/` equals a fresh rendering. The
release is a parameter of the rendering, so a change of release must show where the older
files carried it by hand.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from apex.generating import osoutputs
from apex.kernel import identifiers
from apex.model import release
from apex.targeting.releases import fedora44_release

REPOSITORY = Path(__file__).resolve().parents[2]
FROZEN = REPOSITORY / osoutputs.DIRECTORY


@pytest.mark.parametrize("output", osoutputs.OUTPUTS, ids=lambda output: output.name)
def test_each_rendering_equals_the_handwritten_file_it_replaces(output: osoutputs.Output) -> None:
    handwritten = (REPOSITORY / output.handwritten).read_bytes()

    assert output.render(fedora44_release.PROFILE).encode() == handwritten


@pytest.mark.parametrize("output", osoutputs.OUTPUTS, ids=lambda output: output.name)
def test_the_frozen_tree_equals_a_fresh_rendering(output: osoutputs.Output) -> None:
    assert (FROZEN / output.name).read_bytes() == osoutputs.rendered()[output.name]


def test_the_frozen_tree_holds_nothing_the_generator_does_not_render() -> None:
    present = sorted(str(path.relative_to(FROZEN)) for path in FROZEN.rglob("*") if path.is_file())

    assert present == sorted(output.name for output in osoutputs.OUTPUTS)


def test_a_later_release_moves_every_place_the_files_carried_it_by_hand() -> None:
    later = dataclasses.replace(
        fedora44_release.PROFILE,
        id=identifiers.ProfileId("fedora-45"),
        major=45,
        os_release_version_id="45",
        dist_tag=release.DistTag("fc45"),
        efi_vendor_directory="fedoraproject",
    )

    now = osoutputs.rendered()
    then = osoutputs.rendered(later)

    image = then["image-configure.sh"].decode()
    assert 'test "$VERSION_ID" = 45\n' in image and "greenboot-0.16.4-0.fc45" in image
    assert "fc44" not in image and "= 44\n" not in image
    assert "/boot/efi/EFI/fedoraproject/shimx64.efi" in then["installer-configure.sh"].decode()
    assert "/boot/efi/EFI/fedoraproject/grubx64.efi" in then["live/configure.sh"].decode()
    assert then["Containerfile"] == now["Containerfile"]
    assert then["live/Containerfile"] == now["live/Containerfile"]
    assert then["assemble-live-squashfs.sh"] == now["assemble-live-squashfs.sh"]
