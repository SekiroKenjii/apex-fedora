"""The environment a bundle can attest is the weakest of its adapters.

A unit test may construct the whole system and run a whole pipeline. It still cannot mint a
passing result, because the bundle it holds reports simulation.
"""

from __future__ import annotations

import dataclasses

import pytest

from apex.adapters.fakes import fake_process
from apex.adapters.real import real_process
from apex.kernel import claims, errors, refusals
from apex.ports import portset


def test_a_real_bundle_attests_a_build_environment(ports_of_reals: portset.HostPorts) -> None:
    assert ports_of_reals.environment is claims.EnvironmentKind.BUILD


def test_a_bundle_holding_one_fake_attests_only_simulation(
    ports_of_reals: portset.HostPorts,
) -> None:
    mixed = dataclasses.replace(ports_of_reals, processes=fake_process.ScriptedProcess())

    assert mixed.environment is claims.EnvironmentKind.SIMULATED


def test_a_fully_fake_bundle_attests_only_simulation(ports_of_fakes: portset.HostPorts) -> None:
    assert ports_of_fakes.environment is claims.EnvironmentKind.SIMULATED


def test_a_simulated_bundle_refuses_to_authorise_a_result(
    ports_of_fakes: portset.HostPorts,
) -> None:
    with pytest.raises(errors.Refusal) as raised:
        ports_of_fakes.require_attestable()

    assert raised.value.reason is refusals.RefusalReason.SIMULATED_ENVIRONMENT


def test_a_real_bundle_authorises_a_result(ports_of_reals: portset.HostPorts) -> None:
    assert ports_of_reals.require_attestable() is claims.EnvironmentKind.BUILD


def test_the_bundle_is_frozen(ports_of_fakes: portset.HostPorts) -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        ports_of_fakes.processes = real_process.SubprocessRunner()  # type: ignore[misc]


def test_every_member_counts_towards_the_environment(ports_of_reals: portset.HostPorts) -> None:
    for field in dataclasses.fields(ports_of_reals):
        member = getattr(ports_of_reals, field.name)

        assert member.environment is claims.EnvironmentKind.BUILD, field.name
