"""An environment is attestable only if it is on the list, not merely off the denylist."""

from __future__ import annotations

import pytest

from apex.adapters.fakes import fake_clock, fake_files, fake_ids, fake_process
from apex.adapters.real import real_clock, real_files, real_ids, real_process
from apex.kernel import claims, errors, refusals
from apex.ports import portset


def real_bundle() -> portset.HostPorts:
    return portset.HostPorts(
        processes=real_process.SubprocessRunner(),
        files=real_files.LocalFiles(),
        clock=real_clock.SystemClock(),
        identities=real_ids.RandomIdentities(),
    )


def test_simulated_is_not_attestable() -> None:
    bundle = portset.HostPorts(
        processes=fake_process.ScriptedProcess(),
        files=fake_files.MemoryFiles(),
        clock=fake_clock.ManualClock(),
        identities=fake_ids.SequenceIdentities(),
    )

    with pytest.raises(errors.Refusal) as raised:
        bundle.require_attestable()

    assert raised.value.reason is refusals.RefusalReason.SIMULATED_ENVIRONMENT


def test_the_attestable_set_is_declared_and_excludes_simulation() -> None:
    assert claims.EnvironmentKind.SIMULATED not in claims.ATTESTABLE
    assert claims.EnvironmentKind.BUILD in claims.ATTESTABLE


@pytest.mark.parametrize("kind", sorted(claims.EnvironmentKind, key=str))
def test_every_kind_is_either_attestable_or_explicitly_not(kind: claims.EnvironmentKind) -> None:
    assert (kind in claims.ATTESTABLE) is (kind is not claims.EnvironmentKind.SIMULATED)


def test_a_kind_outside_the_allowlist_is_refused_even_if_it_is_not_simulated() -> None:
    with pytest.raises(errors.Refusal):
        claims.require_attestable(None)  # type: ignore[arg-type]


def test_the_host_bundle_attests_only_a_build_environment() -> None:
    """Every real adapter here runs on the host, so nothing in this bundle can prove a VM."""
    assert real_bundle().require_attestable() is claims.EnvironmentKind.BUILD


def test_the_bundle_cannot_be_asked_to_prove_an_environment_it_does_not_hold() -> None:
    with pytest.raises(errors.Refusal) as raised:
        real_bundle().require_attestable(expected=claims.EnvironmentKind.PHYSICAL)

    assert raised.value.reason is refusals.RefusalReason.ENVIRONMENT_NOT_WITNESSED
