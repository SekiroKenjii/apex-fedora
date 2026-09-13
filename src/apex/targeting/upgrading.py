"""Planning a release upgrade, which reads everything and writes nothing.

Changing the release changes no hash and changing a pin changes no code, because a profile
has no digest field and a pin has no release field. The plan is therefore a reading: which
profile fields change, which reviewed locks name the release in use and must be looked at
again, which constraints re-observe themselves, which quirks must be matched again, and which
attestations lapse because the candidate digest will differ.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping, Sequence

from apex.kernel import encoding, identifiers
from apex.model import release

MODULE_SUFFIX = "_release.py"


@dataclasses.dataclass(frozen=True, slots=True)
class FieldChange:
    field: str
    current: str
    target: str


@dataclasses.dataclass(frozen=True, slots=True)
class UpgradePlan:
    current: identifiers.ProfileId
    target: identifiers.ProfileId
    changes: tuple[FieldChange, ...]
    pins_to_review: tuple[str, ...]
    capabilities_reobserved: tuple[str, ...]
    quirks_to_rematch: tuple[str, ...]
    attestations_to_redo: tuple[str, ...]

    def document(self) -> encoding.Document:
        return {
            "current": str(self.current),
            "target": str(self.target),
            "changes": [dataclasses.asdict(change) for change in self.changes],
            "pins_to_review": list(self.pins_to_review),
            "capabilities_reobserved": list(self.capabilities_reobserved),
            "quirks_to_rematch": list(self.quirks_to_rematch),
            "attestations_to_redo": list(self.attestations_to_redo),
            "writes": [],
        }


def _rendered(value: object) -> str:
    if isinstance(value, release.DistTag):
        return value.value
    return str(value)


def changes(
    current: release.ReleaseProfile, target: release.ReleaseProfile
) -> tuple[FieldChange, ...]:
    return tuple(
        FieldChange(
            field=field.name,
            current=_rendered(getattr(current, field.name)),
            target=_rendered(getattr(target, field.name)),
        )
        for field in dataclasses.fields(current)
        if getattr(current, field.name) != getattr(target, field.name)
    )


def markers(profile: release.ReleaseProfile) -> tuple[str, ...]:
    """The strings by which a reviewed lock can name a release: its dist tag and mock root."""
    return (profile.dist_tag.value, profile.mock_root)


def pins_to_review(
    current: release.ReleaseProfile, locks: Mapping[str, str]
) -> tuple[str, ...]:
    found = []
    for name, text in sorted(locks.items()):
        named = [marker for marker in markers(current) if marker in text]
        if named:
            found.append(f"{name}: names {', '.join(named)}")
    return tuple(found)


def reobserved(current: release.ReleaseProfile) -> tuple[str, ...]:
    return tuple(
        field.name
        for field in dataclasses.fields(current)
        if isinstance(getattr(current, field.name), release.SameAsImage)
    )


def plan(
    current: release.ReleaseProfile,
    target: release.ReleaseProfile,
    *,
    locks: Mapping[str, str],
    attestations: Sequence[str],
    quirks: Sequence[str] = (),
) -> UpgradePlan:
    return UpgradePlan(
        current=current.id,
        target=target.id,
        changes=changes(current, target),
        pins_to_review=pins_to_review(current, locks),
        capabilities_reobserved=reobserved(current),
        quirks_to_rematch=tuple(quirks),
        attestations_to_redo=tuple(sorted(attestations)),
    )


def module_name(target: identifiers.ProfileId) -> str:
    return str(target).replace("-", "").replace(".", "") + MODULE_SUFFIX


def template(target: identifiers.ProfileId, current: release.ReleaseProfile) -> str:
    """The profile module to write, every field carried over from the release in use."""
    return (
        f'"""{target}, declared and chosen field by field; nothing observed belongs here."""\n'
        "\n"
        "from __future__ import annotations\n"
        "\n"
        "from apex.kernel import identifiers\n"
        "from apex.model import release\n"
        "from apex.targeting import releases\n"
        "\n"
        "PROFILE = releases.declare(release.ReleaseProfile(\n"
        f'    id=identifiers.ProfileId("{target}"),\n'
        f"    major={current.major},\n"
        f'    os_id="{current.os_id}",\n'
        f'    os_release_version_id="{current.os_release_version_id}",\n'
        f'    dist_tag=release.DistTag("{current.dist_tag.value}"),\n'
        f'    mock_root="{current.mock_root}",\n'
        f'    efi_vendor_directory="{current.efi_vendor_directory}",\n'
        f'    architecture="{current.architecture}",\n'
        "    supported=False,\n"
        "))\n"
    )
