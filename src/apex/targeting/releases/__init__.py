"""One module per release. Adding the next one is adding a file.

A profile declares itself by being imported, the registry is sealed once, and exactly one
declared profile is supported: the one the image is built from. Two supported
profiles would leave an upgrade plan with no current side, so that is a registration fault.
"""

from __future__ import annotations

from apex.kernel import errors, identifiers
from apex.model import release
from apex.registry import decorators, discovery, registry

_collector: registry.Registry[str, release.ReleaseProfile] = registry.Registry("release")
_sealed: registry.SealedRegistry[str, release.ReleaseProfile] | None = None


def declare(profile: release.ReleaseProfile) -> release.ReleaseProfile:
    _collector.add(str(profile.id), profile, at=decorators.caller(2))
    return profile


def sealed() -> registry.SealedRegistry[str, release.ReleaseProfile]:
    global _sealed
    if _sealed is None:
        discovery.discover([__name__])
        candidate = _collector.seal()
        supported = [name for name, profile in candidate.items() if profile.supported]
        if len(supported) != 1:
            raise errors.RegistrationError(
                f"exactly one release is supported, found {len(supported)}: "
                f"{', '.join(sorted(supported)) or 'none'}"
            )
        _sealed = candidate
    return _sealed


def registered() -> tuple[release.ReleaseProfile, ...]:
    return tuple(profile for _, profile in sorted(sealed().items(), key=lambda item: item[0]))


def lookup(name: identifiers.ProfileId) -> release.ReleaseProfile | None:
    held = sealed()
    return held.lookup(str(name)) if str(name) in held else None


def current() -> release.ReleaseProfile:
    return next(profile for profile in registered() if profile.supported)
