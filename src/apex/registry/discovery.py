"""Import every unit module once, in a fixed order.

A unit module holds declarations and nothing else. It receives no ports at import, so there
is nothing it could act with, and the order modules are walked in is sorted, so registration
does not depend on the filesystem's order or on who imported what first.
"""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Sequence


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
