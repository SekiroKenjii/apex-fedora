"""Which adapter ran is what proves the environment. A fake proves nothing."""

from __future__ import annotations

import inspect

import pytest

from apex.adapters.fakes import fake_process
from apex.adapters.real import real_process
from apex.kernel import claims, commands, errors, timing


def test_the_real_process_adapter_attests_a_build_environment() -> None:
    assert real_process.SubprocessRunner().environment is claims.EnvironmentKind.BUILD


def test_the_fake_process_adapter_attests_only_simulation() -> None:
    assert fake_process.ScriptedProcess().environment is claims.EnvironmentKind.SIMULATED


def test_a_simulated_environment_satisfies_no_requirement() -> None:
    simulated = fake_process.ScriptedProcess().environment

    for required in claims.EnvironmentKind:
        assert not simulated.satisfies(required)


def test_the_fake_refuses_an_argument_vector_the_test_did_not_declare() -> None:
    scripted = fake_process.ScriptedProcess()

    with pytest.raises(errors.PortFailure) as raised:
        scripted.run(
            commands.Argv.of("rm", "-rf", "/"),
            deadline=timing.Deadline(timing.Elapsed(1)),
            limit=commands.OutputLimit.default(),
        )

    assert "undeclared" in str(raised.value)


def test_no_real_adapter_can_reach_a_shell() -> None:
    """The runner passes a list and never sets shell, so no metacharacter is interpreted."""
    source = inspect.getsource(real_process)

    assert "shell=True" not in source
    assert "os.system" not in source
