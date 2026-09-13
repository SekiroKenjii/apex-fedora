"""Shapes that were chosen.

A release profile is code, is unit tested, and is free to change with a release. It holds no
digest by construction, so editing one can never weaken a reviewed hash.
"""

from __future__ import annotations

import dataclasses

from apex.kernel import errors, identifiers, refusals


@dataclasses.dataclass(frozen=True, slots=True)
class DistTag:
    value: str

    def applied(self, build: str, *, vendor_suffix: str = "") -> str:
        suffix = f".{vendor_suffix}" if vendor_suffix else ""
        return f"{build}.{self.value}{suffix}"


# `declared` is unused by two of the three members. It stays in the signature because
# SameAsImage compares against it, and a uniform signature is what makes the union usable.
@dataclasses.dataclass(frozen=True, slots=True)
class Exactly:
    value: str

    def satisfied_by(self, declared: str, *, observed: str) -> bool:  # noqa: ARG002
        return observed == self.value


@dataclasses.dataclass(frozen=True, slots=True)
class AtLeast:
    value: str

    def satisfied_by(self, declared: str, *, observed: str) -> bool:  # noqa: ARG002
        return _ordered(observed) >= _ordered(self.value)


@dataclasses.dataclass(frozen=True, slots=True)
class SameAsImage:
    """Whatever the frozen image reports. Never written down, always observed."""

    def satisfied_by(self, declared: str, *, observed: str) -> bool:
        return declared == observed


type VersionConstraint = Exactly | AtLeast | SameAsImage


def _ordered(value: str) -> tuple[int, ...]:
    parts = []
    for chunk in value.replace("-", ".").split("."):
        digits = "".join(character for character in chunk if character.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


@dataclasses.dataclass(frozen=True, slots=True)
class UpstreamSignal:
    """Prose this build depends on, and the release it was validated against.

    Structural fields are load bearing. Prose is corroboration only, so a rewording degrades
    a proof to not tested rather than turning a success into a refusal.
    """

    structural: str
    prose: str
    validated_against: identifiers.ProfileId


@dataclasses.dataclass(frozen=True, slots=True)
class ReleaseProfile:
    id: identifiers.ProfileId
    major: int
    os_id: str
    os_release_version_id: str
    dist_tag: DistTag
    mock_root: str
    efi_vendor_directory: str
    architecture: str
    supported: bool
    refusal: refusals.RefusalReason | None = None

    def __post_init__(self) -> None:
        if self.supported and self.refusal is not None:
            raise errors.RegistrationError(
                f"{self.id}: a supported profile cannot also declare why it is refused"
            )

    def render_nevra(
        self, *, name: str, version: str, build: str, architecture: str, vendor_suffix: str = ""
    ) -> identifiers.Nevra:
        return identifiers.Nevra(
            name=name,
            epoch=0,
            version=version,
            release=self.dist_tag.applied(build, vendor_suffix=vendor_suffix),
            architecture=architecture,
        )


@dataclasses.dataclass(frozen=True, slots=True)
class DesktopProfile:
    id: identifiers.ProfileId
    major: int
    control_centre_version: str
    extension_floor: int
    extension_ceiling: int
    shell_started_message_id: str
