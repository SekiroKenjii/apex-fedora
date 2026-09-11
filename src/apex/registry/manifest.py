"""Serialise the sealed registries so adding a unit stays a reviewable diff.

With every unit registered by dropping in a file, this document is where "what can this
program do, and where is that written" is answered in one place.
"""

from __future__ import annotations

import json
from typing import Any

from apex.registry import decorators

MANIFEST_VERSION = 1


def render(collector: decorators.Collector) -> dict[str, Any]:
    checks = collector.checks.seal()
    return {
        "manifest_version": MANIFEST_VERSION,
        "checks": [
            {
                "id": key,
                "group": spec.group,
                "environment": str(spec.environment),
                "summary": spec.summary,
                "module": checks.provenance(key).module,
                "qualname": checks.provenance(key).qualname,
                "line": checks.provenance(key).line,
            }
            for key, spec in checks.items()
        ],
    }


def serialise(document: dict[str, Any]) -> str:
    return json.dumps(document, indent=1, sort_keys=True) + "\n"
