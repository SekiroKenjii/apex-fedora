"""A report cannot be built without stating what it does not claim."""

from __future__ import annotations

import pytest

from apex.kernel import claims, errors


def test_the_environment_kinds_cover_what_the_evidence_records_hold() -> None:
    stored = {kind.value for kind in claims.EnvironmentKind}

    assert {"build", "vm", "physical", "operator"} <= stored


def test_a_simulated_environment_exists_and_is_distinct() -> None:
    assert claims.EnvironmentKind.SIMULATED.value == "simulated"


def test_only_a_physical_environment_satisfies_a_physical_requirement() -> None:
    assert claims.EnvironmentKind.PHYSICAL.satisfies(claims.EnvironmentKind.PHYSICAL)
    assert not claims.EnvironmentKind.VM.satisfies(claims.EnvironmentKind.PHYSICAL)


def test_a_simulated_environment_satisfies_nothing() -> None:
    for required in claims.EnvironmentKind:
        assert not claims.EnvironmentKind.SIMULATED.satisfies(required)


def test_a_scope_records_what_was_proven_and_what_was_not() -> None:
    scope = claims.ClaimScope(
        proven=frozenset({"the guest booted"}),
        not_tested=frozenset({claims.ScopeLimit.PHYSICAL_HARDWARE}),
    )

    assert claims.ScopeLimit.PHYSICAL_HARDWARE in scope.not_tested


def test_a_scope_claiming_nothing_and_limiting_nothing_is_refused() -> None:
    with pytest.raises(errors.Refusal):
        claims.ClaimScope(proven=frozenset(), not_tested=frozenset())


def test_a_claim_binds_its_environment_to_its_scope() -> None:
    claim = claims.Claim(
        statement="ten offline boots reached a desktop",
        environment=claims.EnvironmentKind.VM,
        scope=claims.ClaimScope(
            proven=frozenset({"ten boots"}),
            not_tested=frozenset({claims.ScopeLimit.PHYSICAL_HARDWARE}),
        ),
    )

    assert claim.environment is claims.EnvironmentKind.VM


@pytest.mark.parametrize(
    "witness,required,expected",
    [
        (claims.EnvironmentKind.LIVE_VM, claims.EnvironmentKind.VM, True),
        (claims.EnvironmentKind.INSTALLER_VM, claims.EnvironmentKind.VM, True),
        (claims.EnvironmentKind.VM, claims.EnvironmentKind.LIVE_VM, False),
        (claims.EnvironmentKind.LIVE_VM, claims.EnvironmentKind.INSTALLER_VM, False),
        (claims.EnvironmentKind.BUILD, claims.EnvironmentKind.VM, False),
        (claims.EnvironmentKind.SIMULATED, claims.EnvironmentKind.VM, False),
    ],
)
def test_a_machine_booted_from_a_medium_is_still_a_virtual_machine_and_not_the_reverse(
    witness: claims.EnvironmentKind, required: claims.EnvironmentKind, expected: bool
) -> None:
    assert witness.satisfies(required) is expected
