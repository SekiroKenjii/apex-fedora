"""Deterministic identity, which is what makes golden plans reproducible."""

from __future__ import annotations

from apex.kernel import claims, identifiers
from apex.ports import ids


class SequenceIdentities(ids.IdentityPort):
    environment = claims.EnvironmentKind.SIMULATED

    def __init__(self) -> None:
        self._issued = 0

    def _next(self) -> str:
        self._issued += 1
        return f"{self._issued:032x}"

    def run_id(self) -> identifiers.RunId:
        return identifiers.RunId(self._next())

    def token(self) -> identifiers.Token:
        return identifiers.Token(self._next())
