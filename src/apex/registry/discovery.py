"""Import every unit module once, in a fixed order, with the world unreachable.

A unit that opens a file or runs a program while being imported would do so before every
guard in the system. Binding refusing ports during discovery makes that a defect rather than
a bypass nobody notices.
"""

from __future__ import annotations

import dataclasses
import importlib
import importlib.util
import pkgutil
from collections.abc import Sequence
from typing import Any, NoReturn

from apex.kernel import errors


def _refuse(operation: str) -> NoReturn:
    raise errors.InternalDefect(
        f"{operation} was attempted while units were being imported; "
        "registration must declare, never act"
    )


class _RefusingProcess:
    environment = None

    def run(self, *arguments: Any, **keywords: Any) -> NoReturn:
        _refuse("running a program")


class _RefusingFiles:
    environment = None

    def read_bytes(self, *arguments: Any, **keywords: Any) -> NoReturn:
        _refuse("reading a file")

    def write_atomic(self, *arguments: Any, **keywords: Any) -> NoReturn:
        _refuse("writing a file")

    def exists(self, *arguments: Any, **keywords: Any) -> NoReturn:
        _refuse("looking for a file")

    def mode_of(self, *arguments: Any, **keywords: Any) -> NoReturn:
        _refuse("reading a file mode")


class _RefusingClock:
    environment = None

    def now(self) -> NoReturn:
        _refuse("reading the clock")

    def sleep(self, *arguments: Any) -> NoReturn:
        _refuse("sleeping")

    def wait_until(self, *arguments: Any, **keywords: Any) -> NoReturn:
        _refuse("waiting")


class _RefusingIdentities:
    environment = None

    def run_id(self) -> NoReturn:
        _refuse("minting a run identifier")

    def token(self) -> NoReturn:
        _refuse("minting a token")


@dataclasses.dataclass(frozen=True, slots=True)
class RefusingPorts:
    processes: _RefusingProcess = dataclasses.field(default_factory=_RefusingProcess)
    files: _RefusingFiles = dataclasses.field(default_factory=_RefusingFiles)
    clock: _RefusingClock = dataclasses.field(default_factory=_RefusingClock)
    identities: _RefusingIdentities = dataclasses.field(default_factory=_RefusingIdentities)


def module_names(namespace: str) -> list[str]:
    try:
        package = importlib.import_module(namespace)
    except ModuleNotFoundError:
        return []
    locations = list(getattr(package, "__path__", []))
    if not locations:
        return []
    found = [
        f"{namespace}.{item.name}"
        for item in pkgutil.iter_modules(locations)
        if not item.name.startswith("_")
    ]
    return sorted(found)


def discover(namespaces: Sequence[str]) -> list[str]:
    imported: list[str] = []
    for namespace in sorted(namespaces):
        for name in module_names(namespace):
            importlib.import_module(name)
            imported.append(name)
    return sorted(imported)
