"""Identifiers are well formed and never repeat within a run."""

from __future__ import annotations

from apex.kernel import identifiers
from apex.ports import ids as ids_port


def test_a_run_identifier_is_well_formed(identities: ids_port.IdentityPort) -> None:
    assert isinstance(identities.run_id(), identifiers.RunId)


def test_a_token_is_well_formed(identities: ids_port.IdentityPort) -> None:
    assert isinstance(identities.token(), identifiers.Token)


def test_successive_identifiers_differ(identities: ids_port.IdentityPort) -> None:
    issued = {str(identities.run_id()) for _ in range(20)}

    assert len(issued) == 20


def test_run_identifiers_and_tokens_share_one_sequence(identities: ids_port.IdentityPort) -> None:
    issued = {str(identities.run_id()), str(identities.token())}

    assert len(issued) == 2
