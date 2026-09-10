"""The environment a bundle can attest is the weakest of its adapters.

A unit test may construct the whole system and run a whole pipeline. It still cannot mint a
passing result, because the bundle it holds reports simulation.
"""

from __future__ import annotations

import dataclasses

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


def fake_bundle() -> portset.HostPorts:
    return portset.HostPorts(
        processes=fake_process.ScriptedProcess(),
        files=fake_files.MemoryFiles(),
        clock=fake_clock.ManualClock(),
        identities=fake_ids.SequenceIdentities(),
    )


def test_a_real_bundle_attests_a_build_environment() -> None:
    assert real_bundle().environment is claims.EnvironmentKind.BUILD


def test_a_bundle_holding_one_fake_attests_only_simulation() -> None:
    mixed = portset.HostPorts(
        processes=fake_process.ScriptedProcess(),
        files=real_files.LocalFiles(),
        clock=real_clock.SystemClock(),
        identities=real_ids.RandomIdentities(),
    )

    assert mixed.environment is claims.EnvironmentKind.SIMULATED


def test_a_fully_fake_bundle_attests_only_simulation() -> None:
    assert fake_bundle().environment is claims.EnvironmentKind.SIMULATED


def test_a_simulated_bundle_refuses_to_authorise_a_result() -> None:
    with pytest.raises(errors.Refusal) as raised:
        fake_bundle().require_attestable()

    assert raised.value.reason is refusals.RefusalReason.SIMULATED_ENVIRONMENT


def test_a_real_bundle_authorises_a_result() -> None:
    assert real_bundle().require_attestable() is claims.EnvironmentKind.BUILD


def test_the_bundle_is_frozen() -> None:
    bundle = fake_bundle()

    with pytest.raises(dataclasses.FrozenInstanceError):
        bundle.processes = real_process.SubprocessRunner()  # type: ignore[misc]
