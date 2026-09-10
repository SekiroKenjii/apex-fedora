"""Where a value came from, so `explain` can answer it."""

from __future__ import annotations

import enum


class Layer(enum.StrEnum):
    DEFAULT = "default"
    PROFILE = "profile"
    HOST_FILE = "host-file"
    ENVIRONMENT = "environment"
