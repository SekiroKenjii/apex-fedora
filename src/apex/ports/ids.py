"""Run identifiers and tokens. The only source of randomness in the system."""

from __future__ import annotations

from abc import abstractmethod
from typing import Protocol

from apex.kernel import claims, identifiers


class IdentityPort(Protocol):
    environment: claims.EnvironmentKind

    @abstractmethod
    def run_id(self) -> identifiers.RunId: ...

    @abstractmethod
    def token(self) -> identifiers.Token: ...
