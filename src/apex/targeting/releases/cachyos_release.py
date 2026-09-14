"""The comparison kernel lineage, declared and deliberately not supported.

Deleting the profile would discard the recorded reason it is blocked and reintroduce a
branch the day a second lineage appears.
"""

from __future__ import annotations

from apex.kernel import identifiers, refusals
from apex.model import release
from apex.targeting import releases

PROFILE = releases.declare(
    release.ReleaseProfile(
        id=identifiers.ProfileId("cachyos"),
        major=44,
        os_id="fedora",
        os_release_version_id="44",
        dist_tag=release.DistTag("fc44"),
        mock_root="fedora-44-x86_64",
        efi_vendor_directory="fedora",
        architecture="x86_64",
        supported=False,
        refusal=refusals.RefusalReason.PROFILE_NOT_REVIEWED,
    )
)
