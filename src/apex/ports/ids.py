"""Run identifiers and tokens. The only source of randomness in the system."""

from __future__ import annotations

from typing import Protocol

from apex.kernel import claims, identifiers


class IdentityPort(Protocol):
    environment: claims.EnvironmentKind

    def run_id(self) -> identifiers.RunId: ...

    def token(self) -> identifiers.Token: ...
