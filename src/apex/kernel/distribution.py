"""The name this project is installed under, and the version the installation reports.

Both sides of a request read it: the host names its version, and the guest names the version
it answers with. A checkout that is not installed reports `source`.
"""

from __future__ import annotations

import importlib.metadata

NAME = "apex-build-tools"
SOURCE = "source"


def installed_version() -> str:
    try:
        return importlib.metadata.version(NAME)
    except importlib.metadata.PackageNotFoundError:
        return SOURCE
