"""Assemble the settings once, validate the whole tree, then freeze it.

There is no function that reads a configuration file at the point of use, so a value cannot
change between two reads inside one operation.
"""

from __future__ import annotations

import dataclasses
import tomllib
from collections.abc import Mapping, Sequence
from pathlib import Path

from apex.config import defaults, layers, overrides
from apex.kernel import errors, quantities, refusals, safepaths

BUILDER_FIELDS = {
    "processors": int,
    "memory_mib": int,
    "reserve_mib": int,
    "disk_gib": int,
    "minimum_free_gib": int,
    "firmware_code": str,
    "firmware_variables": str,
}


@dataclasses.dataclass(frozen=True, slots=True)
class BuilderSettings:
    processors: int
    memory: quantities.Mib
    reserve: quantities.Mib
    disk: quantities.Gib
    minimum_free: quantities.Gib
    firmware_code: Path
    firmware_variables: Path


@dataclasses.dataclass(frozen=True, slots=True)
class Settings:
    builder: BuilderSettings
    runtime_root: Path
    origins: Mapping[str, layers.Layer]

    def explain(self, field: str) -> layers.Layer:
        try:
            return self.origins[field]
        except KeyError as error:
            known = ", ".join(sorted(self.origins))
            raise errors.Refusal(
                refusals.RefusalReason.UNKNOWN_SETTING,
                subject=field,
                remedy=f"known settings: {known}",
            ) from error


def _builder_table(host_file: Path | None) -> Mapping[str, object]:
    if host_file is None or not host_file.is_file():
        return {}
    builder = tomllib.loads(host_file.read_text()).get("builder", {})
    if not isinstance(builder, dict):
        raise errors.Refusal(
            refusals.RefusalReason.UNKNOWN_SETTING, subject="builder must be a table"
        )
    for key in builder:
        if key not in BUILDER_FIELDS:
            raise errors.Refusal(
                refusals.RefusalReason.UNKNOWN_SETTING,
                subject=f"builder.{key}",
                remedy=f"known keys: {', '.join(sorted(BUILDER_FIELDS))}",
            )
    return builder


def _check_environment(environment: Mapping[str, str]) -> dict[str, str]:
    declared = {item.variable: item for item in overrides.DECLARED}
    applied: dict[str, str] = {}
    for name, value in sorted(environment.items()):
        if not name.startswith(overrides.NAMESPACE):
            continue
        if name in overrides.GUEST_VARIABLES or name in overrides.TOOLING_VARIABLES:
            continue
        if name not in declared:
            known = ", ".join(sorted(declared))
            raise errors.Refusal(
                refusals.RefusalReason.UNKNOWN_SETTING,
                subject=name,
                remedy=f"declared overrides: {known}",
            )
        applied[declared[name].field] = value
    return applied


def _pick_path(
    builder_file: Mapping[str, object], origins: dict[str, layers.Layer], key: str, fallback: str
) -> Path:
    field = f"builder.{key}"
    if key not in builder_file:
        origins[field] = layers.Layer.DEFAULT
        return Path(fallback)
    supplied = builder_file[key]
    if not isinstance(supplied, str) or not supplied:
        raise errors.Refusal(
            refusals.RefusalReason.INCONSISTENT_SETTINGS, subject=f"builder.{key} must be a path"
        )
    origins[field] = layers.Layer.HOST_FILE
    return Path(supplied).expanduser()


def load(*, host_file: Path | None, environment: Mapping[str, str]) -> Settings:
    origins: dict[str, layers.Layer] = {}
    builder_file = _builder_table(host_file)

    def pick(key: str, fallback: int) -> int:
        field = f"builder.{key.removesuffix('_mib').removesuffix('_gib')}"
        if key not in builder_file:
            origins[field] = layers.Layer.DEFAULT
            return fallback
        supplied = builder_file[key]
        if not isinstance(supplied, int) or isinstance(supplied, bool):
            raise errors.Refusal(
                refusals.RefusalReason.INCONSISTENT_SETTINGS,
                subject=f"builder.{key} must be a whole number",
            )
        origins[field] = layers.Layer.HOST_FILE
        return supplied

    def pick_path(key: str, fallback: str) -> Path:
        return _pick_path(builder_file, origins, key, fallback)

    builder = BuilderSettings(
        processors=int(pick("processors", defaults.BUILDER.processors)),
        memory=quantities.Mib(int(pick("memory_mib", defaults.BUILDER.memory.value))),
        reserve=quantities.Mib(int(pick("reserve_mib", defaults.BUILDER.reserve.value))),
        disk=quantities.Gib(int(pick("disk_gib", defaults.BUILDER.disk.value))),
        minimum_free=quantities.Gib(
            int(pick("minimum_free_gib", defaults.BUILDER.minimum_free.value))
        ),
        firmware_code=pick_path("firmware_code", defaults.BUILDER.firmware_code),
        firmware_variables=pick_path("firmware_variables", defaults.BUILDER.firmware_variables),
    )
    if builder.reserve.value >= builder.memory.value:
        raise errors.Refusal(
            refusals.RefusalReason.INCONSISTENT_SETTINGS,
            subject=(
                f"reserve {builder.reserve.value} MiB is not below "
                f"memory {builder.memory.value} MiB"
            ),
        )

    applied = _check_environment(environment)
    if "runtime_root" in applied:
        runtime_root = Path(applied["runtime_root"]).expanduser()
        origins["runtime_root"] = layers.Layer.ENVIRONMENT
    else:
        runtime_root = Path("~/.local/share/apex-fedora/runtime").expanduser()
        origins["runtime_root"] = layers.Layer.DEFAULT
    return Settings(builder=builder, runtime_root=runtime_root, origins=origins)


def runtime_root(settings: Settings, *, permitted: Sequence[Path]) -> safepaths.RuntimeRoot:
    return safepaths.RuntimeRoot.resolve(settings.runtime_root, permitted=permitted)
