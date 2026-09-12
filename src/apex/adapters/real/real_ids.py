"""The only module that reaches for randomness."""

from __future__ import annotations

import secrets

from apex.kernel import claims, identifiers
from apex.ports import ids


class RandomIdentities(ids.IdentityPort):
    environment = claims.EnvironmentKind.BUILD

    def run_id(self) -> identifiers.RunId:
        return identifiers.RunId(secrets.token_hex(16))

    def token(self) -> identifiers.Token:
        return identifiers.Token(secrets.token_hex(16))
