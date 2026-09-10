"""A keyed collection that is open for registration, then sealed for reading.

Reading before the seal would make import order matter. Registering after it would let a
unit appear once a command is already running.
"""

from __future__ import annotations

import types
from collections.abc import Iterator, Mapping

from apex.kernel import errors
from apex.registry import provenance


class SealedRegistry[K, V]:
    def __init__(
        self, kind: str, entries: Mapping[K, V], origins: Mapping[K, provenance.Provenance]
    ) -> None:
        self._kind = kind
        self._entries: Mapping[K, V] = types.MappingProxyType(dict(entries))
        self._origins: Mapping[K, provenance.Provenance] = types.MappingProxyType(dict(origins))

    def __getitem__(self, key: K) -> V:
        return self.lookup(key)

    def __iter__(self) -> Iterator[K]:
        return iter(self._entries)

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, key: object) -> bool:
        return key in self._entries

    def lookup(self, key: K) -> V:
        try:
            return self._entries[key]
        except KeyError as error:
            known = ", ".join(str(item) for item in self._entries)
            raise errors.RegistrationError(
                f"no {self._kind} named {key!r}; registered: {known}"
            ) from error

    def provenance(self, key: K) -> provenance.Provenance:
        return self._origins[key]

    def values(self) -> tuple[V, ...]:
        return tuple(self._entries.values())

    def items(self) -> tuple[tuple[K, V], ...]:
        return tuple(self._entries.items())


class Registry[K, V]:
    def __init__(self, kind: str) -> None:
        self._kind = kind
        self._entries: dict[K, V] = {}
        self._origins: dict[K, provenance.Provenance] = {}
        self._sealed = False

    def add(self, key: K, value: V, *, at: provenance.Provenance) -> None:
        if self._sealed:
            raise errors.RegistrationError(
                f"{self._kind} {key!r} was registered after the registry was sealed, at {at}"
            )
        existing = self._origins.get(key)
        if existing is not None:
            raise errors.RegistrationError(
                f"duplicate {self._kind} {key!r}: registered at {existing} and again at {at}"
            )
        self._entries[key] = value
        self._origins[key] = at

    def lookup(self, key: K) -> V:
        raise errors.RegistrationError(
            f"{self._kind} registry is still open; seal it before looking {key!r} up"
        )

    def seal(self) -> SealedRegistry[K, V]:
        if self._sealed:
            raise errors.RegistrationError(f"the {self._kind} registry is already sealed")
        self._sealed = True
        ordered = dict(sorted(self._entries.items(), key=lambda item: str(item[0])))
        origins = {key: self._origins[key] for key in ordered}
        return SealedRegistry(self._kind, ordered, origins)
