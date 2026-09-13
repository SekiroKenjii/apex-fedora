"""Fedora 44, the release the image is built from.

Every value here was chosen. Nothing observed from an image and no reviewed hash belongs in
this file, and the type has no field that could hold one.
"""

from __future__ import annotations

from apex.kernel import identifiers
from apex.model import release
from apex.targeting import releases

PROFILE = releases.declare(release.ReleaseProfile(
    id=identifiers.ProfileId("fedora-44"),
    major=44,
    os_id="fedora",
    os_release_version_id="44",
    dist_tag=release.DistTag("fc44"),
    mock_root="fedora-44-x86_64",
    efi_vendor_directory="fedora",
    architecture="x86_64",
    supported=True,
))

DESKTOP = release.DesktopProfile(
    id=identifiers.ProfileId("gnome-50"),
    major=50,
    control_centre_version="50.4",
    extension_floor=50,
    extension_ceiling=50,
    shell_started_message_id="f3ea493c22934e26811cd62abe8e203a",
)
