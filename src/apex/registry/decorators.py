"""Declaring a unit, and recording where the declaration was written.

The caller's frame supplies module and line, so provenance is a property of declaring rather
than something an author has to remember to state.
"""

from __future__ import annotations

import inspect

from apex.registry import descriptors, provenance, registry


def _caller(depth: int = 2) -> provenance.Provenance:
    frame = inspect.stack()[depth]
    module = inspect.getmodule(frame.frame)
    return provenance.Provenance(
        module=module.__name__ if module else "<unknown>",
        qualname=frame.function,
        line=frame.lineno,
    )


class Collector:
    """Holds the open registries while units are being imported."""

    def __init__(self) -> None:
        self.checks: registry.Registry[str, descriptors.CheckSpec] = registry.Registry("check")

    def check(self, spec: descriptors.CheckSpec, *, depth: int = 2) -> descriptors.CheckSpec:
        self.checks.add(str(spec.id), spec, at=_caller(depth))
        return spec
