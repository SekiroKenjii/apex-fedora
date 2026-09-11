"""The required checks, declared as data, one file per group.

A check that is not in one of these files does not exist, so the readiness fold cannot report
ready by forgetting one. Adding a check is adding a table to its group's file. Every file is
validated in full when the registry seals, so a malformed entry is a fault before anything runs
and a check is blocking the moment it lands.
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from pathlib import Path

from apex.kernel import claims, errors, identifiers
from apex.registry import descriptors, provenance, registry

GROUPS = ("build", "git", "hardware", "recovery", "vm")
DIRECTORY = Path(__file__).resolve().parent
TABLE = "check"
SUFFIX = ".toml"

_sealed: registry.SealedRegistry[str, descriptors.CheckSpec] | None = None


def group_file(group: str) -> Path:
    return DIRECTORY / f"{group}{SUFFIX}"


def _strings(entry: Mapping[str, object], key: str) -> tuple[str, ...]:
    value = entry.get(key, [])
    if not isinstance(value, list):
        raise errors.RegistrationError(f"{entry.get('id', '?')}: {key} must be a list")
    return tuple(str(item) for item in value)


def parse(group: str, entry: Mapping[str, object]) -> descriptors.CheckSpec:
    """One table to one declaration. Anything missing or malformed is a registration fault."""
    try:
        return descriptors.CheckSpec(
            id=identifiers.CheckId(str(entry["id"])),
            group=group,
            environment=claims.EnvironmentKind(str(entry["environment"])),
            summary=str(entry["summary"]),
            accepted_proof_kinds=_strings(entry, "accepted_proof_kinds"),
            scope_limits=_strings(entry, "scope_limits"),
            sourced_from=str(entry.get("sourced_from", "")),
        )
    except (KeyError, ValueError, errors.Refusal) as fault:
        raise errors.RegistrationError(
            f"{group}{SUFFIX}: {entry.get('id', '?')}: {fault}"
        ) from fault


def _line_of(text: str, check: identifiers.CheckId) -> int:
    needle = f'id = "{check}"'
    for number, line in enumerate(text.splitlines(), 1):
        if line.strip() == needle:
            return number
    return 0


def _load(group: str, collector: registry.Registry[str, descriptors.CheckSpec]) -> None:
    path = group_file(group)
    text = path.read_text(encoding="utf-8")
    entries = tomllib.loads(text).get(TABLE)
    if not isinstance(entries, list) or not entries:
        raise errors.RegistrationError(f"{path.name} declares no {TABLE} table")
    for entry in entries:
        spec = parse(group, entry)
        at = provenance.Provenance(
            module=f"{__name__}.{group}", qualname=str(spec.id), line=_line_of(text, spec.id)
        )
        collector.add(str(spec.id), spec, at=at)


def sealed() -> registry.SealedRegistry[str, descriptors.CheckSpec]:
    """Read every group file once, then seal. Repeated calls return the same registry."""
    global _sealed
    if _sealed is None:
        collector: registry.Registry[str, descriptors.CheckSpec] = registry.Registry("check")
        for group in GROUPS:
            _load(group, collector)
        _sealed = collector.seal()
    return _sealed


def specification(check: identifiers.CheckId) -> descriptors.CheckSpec:
    return sealed().lookup(str(check))
